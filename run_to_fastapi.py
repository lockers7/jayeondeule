from pathlib import Path
import sys

def _ensure_repo_on_path() -> None:
    repo_root = Path(__file__).resolve().parent
    pkg_root = repo_root / "agri_ai_core"
    legacy_src = repo_root / "agri_ai_core" / "src"

    for path in (repo_root, pkg_root, legacy_src):
        str_path = str(path)
        if str_path not in sys.path:
            sys.path.insert(0, str_path)


_ensure_repo_on_path()

from agri_ai_core.run_api import main  # noqa: E402  (import after sys.path tweak)

if __name__ == "__main__":
    main()
