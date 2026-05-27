"""Runtime marker for long local LLM calls.

The Ollama watchdog runs outside Python.  It must be able to tell the
difference between a hung runner and a runner that is busy with a legitimate
farm-control request.  This module writes a small marker file while a local
LLM call is in progress.  The watchdog treats a live, non-expired marker as a
"busy, do not deep-check" signal.
"""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:
    import fcntl
except Exception:  # pragma: no cover - Linux 운영환경에서는 항상 존재
    fcntl = None


DEFAULT_MARKER = "/tmp/agri_ai_core_llm_busy"
DEFAULT_LOCK = "/tmp/agri_ai_core_llm_call.lock"


class LlmCallLockTimeout(TimeoutError):
    """Raised when another process holds the local LLM call slot too long."""



def _marker_path() -> Path:
    return Path(os.getenv("AGRI_LLM_BUSY_FILE", DEFAULT_MARKER))


def _lock_path() -> Path:
    return Path(os.getenv("AGRI_LLM_CALL_LOCK_FILE", DEFAULT_LOCK))


def _is_call_lock_enabled() -> bool:
    return str(os.getenv("AGRI_LLM_CALL_LOCK_ENABLED", "1")).strip().lower() not in {
        "0", "false", "no", "off"
    }


def _open_call_lock_fd(path: Path) -> tuple[int, bool]:
    """Open the cross-process LLM lock with shared permissions.

    The lock is shared by root-owned core control and user-owned agent
    services. Force a permissive create mode before the file exists, and fall
    back to read-only locking if an older file was created without write
    permission for this process.
    """
    previous_umask = os.umask(0)
    try:
        # 이미 존재하는 파일은 O_CREAT 없이 O_RDWR 로 먼저 연다.
        # /tmp(sticky, world-writable)에서 커널 fs.protected_regular(=2) 는
        # "교차 소유 파일의 O_CREAT open" 을 root 에게도 EACCES 로 차단한다.
        # O_CREAT 없는 O_RDWR 는 이 제약을 받지 않으므로 쓰기 가능한 fd 를 얻는다.
        try:
            fd = os.open(str(path), os.O_RDWR)
            return fd, True
        except FileNotFoundError:
            pass
        except PermissionError:
            pass
        # 파일이 없거나 위 시도가 막힌 경우에만 생성(O_CREAT)을 시도한다.
        try:
            fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o666)
            return fd, True
        except PermissionError:
            try:
                os.chmod(str(path), 0o666)
            except Exception:
                pass
            try:
                fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o666)
                return fd, True
            except PermissionError:
                fd = os.open(str(path), os.O_RDONLY)
                return fd, False
    finally:
        os.umask(previous_umask)


@contextmanager
def llm_activity(label: str, timeout_sec: int | float | None = None) -> Iterator[None]:
    """Mark this process as actively using the local LLM.

    The marker is intentionally best-effort.  LLM calls must proceed even when
    the marker cannot be written.
    """
    path = _marker_path()
    pid = os.getpid()
    now = int(time.time())
    ttl = int(timeout_sec or 0)
    expires_at = now + max(ttl + 60, 120)
    previous = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            previous = path.read_text(encoding="utf-8", errors="ignore")
        path.write_text(f"{pid} {expires_at} {label}\n", encoding="utf-8")
    except Exception:
        previous = None

    try:
        yield
    finally:
        try:
            current = path.read_text(encoding="utf-8", errors="ignore").split()
            if current and current[0] == str(pid):
                if previous:
                    path.write_text(previous, encoding="utf-8")
                else:
                    path.unlink(missing_ok=True)
        except Exception:
            pass


def is_llm_busy(labels=None, exclude_pid=None) -> bool:
    """Return True if a live, non-expired local-LLM busy marker is held.

    Lower-priority LLM users (the monitor agent) call this to *yield* to the
    higher-priority farm-control LLM call: while control holds the marker the
    agent waits instead of competing for the single Ollama slot. This avoids
    the slot-handoff error and gives farm control the slot first.

    labels      : if given, only report busy when the marker label is in this set
                  (e.g. {"ai_control"} to yield only to farm control).
    exclude_pid : ignore a marker owned by this pid (skip self).
    """
    path = _marker_path()
    try:
        parts = path.read_text(encoding="utf-8", errors="ignore").split()
    except Exception:
        return False
    if len(parts) < 2:
        return False
    try:
        pid = int(parts[0])
        expires_at = int(parts[1])
    except (ValueError, TypeError):
        return False
    marker_label = parts[2] if len(parts) > 2 else ""
    if exclude_pid is not None and pid == exclude_pid:
        return False
    if int(time.time()) > expires_at:
        return False
    if labels is not None and marker_label not in labels:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False          # 마커 소유 프로세스가 이미 종료됨 → busy 아님
    except PermissionError:
        pass                  # 다른 소유자(root) 프로세스지만 살아있음 → busy
    except Exception:
        return False
    return True


@contextmanager
def llm_call_lock(
    label: str,
    wait_sec: int | float | None = None,
    poll_interval: float = 0.25,
) -> Iterator[None]:
    """Serialize scheduled local LLM calls across Python processes.

    Ollama can return 503 or stall when multiple heavy 16k-context farm-control
    calls overlap. This lock does not shorten prompts or change model options;
    it only waits for the current local LLM call to finish before starting the
    next scheduled control/agent call.
    """
    if not _is_call_lock_enabled() or fcntl is None:
        yield
        return

    path = _lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    timeout = float(wait_sec if wait_sec is not None else os.getenv("AGRI_LLM_CALL_LOCK_WAIT_SEC", "60"))
    timeout = max(timeout, 0.0)
    deadline = time.monotonic() + timeout
    fd, writable = _open_call_lock_fd(path)
    if writable:
        try:
            os.fchmod(fd, 0o666)
        except Exception:
            pass
    acquired = False

    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    try:
                        holder = path.read_text(encoding="utf-8", errors="ignore").strip()
                    except Exception:
                        holder = ""
                    detail = f" holder={holder}" if holder else ""
                    raise LlmCallLockTimeout(
                        f"local LLM call slot wait timeout ({timeout:.1f}s) label={label}{detail}"
                    )
                remaining = max(0.0, deadline - time.monotonic())
                time.sleep(min(max(poll_interval, 0.05), remaining))

        # 여기 도달 시점에 flock(상호배제)은 이미 획득됨. 아래 메타데이터 기록은
        # 정보성(best-effort) 이다. 교차 소유(root 제어 vs user agent) fd 등 일부
        # 환경에서 ftruncate/write 가 [Errno 22] 로 실패할 수 있으나, 그 경우에도
        # 상호배제(flock)는 유효하므로 LLM 호출을 막지 않고 그대로 진행한다.
        try:
            now = int(time.time())
            meta = f"{os.getpid()} {now} {label}\n"
            os.ftruncate(fd, 0)
            os.write(fd, meta.encode("utf-8", errors="replace"))
            os.fsync(fd)
        except OSError:
            pass
        yield
    finally:
        if acquired:
            try:
                os.ftruncate(fd, 0)
                os.fsync(fd)
            except Exception:
                pass
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except Exception:
                pass
        try:
            os.close(fd)
        except Exception:
            pass
