#!/usr/bin/env python3
"""Lightweight import smoke tests for current agri_ai_core layout."""

import importlib
import sys
import traceback


MODULES = [
    "agri_ai_core",
    "agri_ai_core.config",
    "agri_ai_core.startup",
    "agri_ai_core.run_scheduler",
    "agri_ai_core.main.main",
    "agri_ai_core.src.logs",
    "agri_ai_core.src.postgresql",
    "agri_ai_core.src.chroma",
    "agri_ai_core.src.ai",
    "agri_ai_core.src.ui_reflex.main",
    "agri_ai_core.src.ui_reflex.state",
]


def run_import_smoke() -> bool:
    print("=== Import Smoke Test ===")
    ok = True

    for mod_name in MODULES:
        try:
            importlib.import_module(mod_name)
            print(f"✓ {mod_name}")
        except Exception as exc:
            ok = False
            print(f"✗ {mod_name}: {type(exc).__name__}: {exc}")
            traceback.print_exc()

    try:
        import agri_ai_core

        _ = agri_ai_core.db_session
        _ = agri_ai_core.run_reflex
        _ = agri_ai_core.run_streamlit
        print("✓ agri_ai_core lazy exports")
    except Exception as exc:
        ok = False
        print(f"✗ agri_ai_core lazy exports: {type(exc).__name__}: {exc}")
        traceback.print_exc()

    return ok


if __name__ == "__main__":
    success = run_import_smoke()
    sys.exit(0 if success else 1)
