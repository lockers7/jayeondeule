#!/usr/bin/env python3
"""
Import test script for agri_ai_core restructuring
Tests critical imports at each phase
"""
import sys
import traceback

def test_phase_0():
    """Test current imports before restructuring"""
    print("=== Phase 0: Testing current structure ===")
    try:
        from agri_ai_core.startup import initialize_app, shutdown_app
        print("✓ startup module")

        from agri_ai_core.database.postgres.connection import db_session
        print("✓ postgres connection")

        from agri_ai_core.database.chromadb.client import heartbeat
        print("✓ chromadb client")

        from agri_ai_core.shared_modules.config.settings import settings
        print("✓ settings")

        from agri_ai_core.log_utils.log_handlers import setup_logger
        print("✓ logger")

        print("\n✓✓✓ Phase 0: All imports successful\n")
        return True
    except Exception as e:
        print(f"\n✗✗✗ Phase 0: Import failed: {e}")
        traceback.print_exc()
        return False


def test_phase_3():
    """Test config.py after merge"""
    print("=== Phase 3: Testing config.py ===")
    try:
        from agri_ai_core.config import settings, SENSOR_MAPPING, get_relay_name
        print(f"✓ config.py merged: model={settings.model.name}")
        print(f"✓ SENSOR_MAPPING has {len(SENSOR_MAPPING)} sensors")
        relay_name = get_relay_name("relay_1_flag")
        print(f"✓ get_relay_name working: {relay_name}")
        print("\n✓✓✓ Phase 3: config.py working\n")
        return True
    except Exception as e:
        print(f"\n✗✗✗ Phase 3: config.py failed: {e}")
        traceback.print_exc()
        return False


def test_phase_4():
    """Test logs.py after merge"""
    print("=== Phase 4: Testing logs.py ===")
    try:
        from agri_ai_core.src.logs import setup_logger
        logger = setup_logger(__name__)
        logger.info("Test log message")
        print("✓ logs.py working")
        print("\n✓✓✓ Phase 4: logs.py working\n")
        return True
    except Exception as e:
        print(f"\n✗✗✗ Phase 4: logs.py failed: {e}")
        traceback.print_exc()
        return False


def test_phase_5():
    """Test PostgreSQL module"""
    print("=== Phase 5: Testing PostgreSQL module ===")
    try:
        from agri_ai_core.src.postgresql import db_session
        print("✓ postgresql.db_session")

        from agri_ai_core.src.postgresql.reader import read_units_data
        print("✓ postgresql.reader")

        print("\n✓✓✓ Phase 5: PostgreSQL module working\n")
        return True
    except Exception as e:
        print(f"\n✗✗✗ Phase 5: PostgreSQL failed: {e}")
        traceback.print_exc()
        return False


def test_phase_6():
    """Test ChromaDB module"""
    print("=== Phase 6: Testing ChromaDB module ===")
    try:
        from agri_ai_core.src.chroma import heartbeat, get_collection
        print("✓ chroma.heartbeat")

        status = heartbeat()
        print(f"✓ ChromaDB status: {status}")

        print("\n✓✓✓ Phase 6: ChromaDB module working\n")
        return True
    except Exception as e:
        print(f"\n✗✗✗ Phase 6: ChromaDB failed: {e}")
        traceback.print_exc()
        return False


def test_phase_final():
    """Test all final imports"""
    print("=== Final: Testing all imports ===")
    try:
        from agri_ai_core.config import settings
        from agri_ai_core.src.logs import setup_logger
        from agri_ai_core.src.postgresql import db_session
        from agri_ai_core.src.chroma import heartbeat
        from agri_ai_core.src.ai.llm import get_llm_response
        from agri_ai_core.src.control import setup_scheduler

        print("✓ All critical imports successful")
        print("\n✓✓✓✓✓ FINAL: All modules working\n")
        return True
    except Exception as e:
        print(f"\n✗✗✗ FINAL: Import failed: {e}")
        traceback.print_exc()
        return False


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "0"

    if phase == "0":
        success = test_phase_0()
    elif phase == "3":
        success = test_phase_3()
    elif phase == "4":
        success = test_phase_4()
    elif phase == "5":
        success = test_phase_5()
    elif phase == "6":
        success = test_phase_6()
    elif phase == "final":
        success = test_phase_final()
    else:
        print(f"Usage: python test_imports.py [0|3|4|5|6|final]")
        success = False

    sys.exit(0 if success else 1)
