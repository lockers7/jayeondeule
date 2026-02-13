#!/usr/bin/env python3
"""
Complete test suite for restructured agri_ai_core
"""
import sys
import traceback

def test_all():
    """Run all tests"""
    print("="*70)
    print("COMPLETE TEST SUITE - Restructured agri_ai_core")
    print("="*70)

    all_passed = True

    # Test 1: Config
    print("\n[Test 1] Config Module...")
    try:
        from agri_ai_core.config import settings, SENSOR_MAPPING, get_relay_name
        assert settings.model.name == "qwen3:14b"
        assert len(SENSOR_MAPPING) == 8
        print("  ✓ config.py working")
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        all_passed = False

    # Test 2: Logs
    print("\n[Test 2] Logs Module...")
    try:
        from agri_ai_core.src.logs import setup_logger
        logger = setup_logger(__name__)
        logger.info("Test log")
        print("  ✓ logs.py working")
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        all_passed = False

    # Test 3: PostgreSQL
    print("\n[Test 3] PostgreSQL Module...")
    try:
        from agri_ai_core.src.postgresql import db_session
        print("  ✓ postgresql module working")
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        all_passed = False

    # Test 4: ChromaDB
    print("\n[Test 4] ChromaDB Module...")
    try:
        from agri_ai_core.src.chroma import heartbeat
        status = heartbeat()
        print(f"  ✓ chroma module working: {status}")
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        all_passed = False

    # Test 5: Utils
    print("\n[Test 5] Utils Module...")
    try:
        from agri_ai_core.src.utils import clean_sensor_value
        print("  ✓ utils module working")
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        all_passed = False

    # Test 6: Control
    print("\n[Test 6] Control Module...")
    try:
        from agri_ai_core.src.control import setup_scheduler
        print("  ✓ control module working")
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        all_passed = False

    # Test 7: AI - LLM
    print("\n[Test 7] AI - LLM Module...")
    try:
        from agri_ai_core.src.ai import get_llm_response, query_llm_unified
        print("  ✓ AI LLM module working")
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        all_passed = False

    # Test 8: AI - RAG
    print("\n[Test 8] AI - RAG Module...")
    try:
        from agri_ai_core.src.ai.rag import embed_text
        print("  ✓ AI RAG module working")
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        all_passed = False

    # Test 9: AI - Learning
    print("\n[Test 9] AI - Learning Module...")
    try:
        from agri_ai_core.src.ai.learning import verify_chroma_connection
        print("  ✓ AI Learning module working")
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        all_passed = False

    # Test 10: UI
    print("\n[Test 10] UI Module...")
    try:
        from agri_ai_core.src.ui.main import main
        print("  ✓ UI module working")
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        all_passed = False

    # Test 11: Entry Points
    print("\n[Test 11] Entry Points...")
    try:
        from agri_ai_core.startup import initialize_app, shutdown_app
        from agri_ai_core.run_scheduler import main as scheduler_main
        from agri_ai_core import settings, setup_logger, db_session
        print("  ✓ Entry points working")
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        all_passed = False

    # Test 12: Import Performance
    print("\n[Test 12] Import Performance...")
    try:
        import time
        start = time.time()
        from agri_ai_core.src.ai import query_llm_unified
        elapsed = time.time() - start
        print(f"  ✓ AI import time: {elapsed:.3f}s")
    except Exception as e:
        print(f"  ✗ FAILED: {e}")
        all_passed = False

    # Summary
    print("\n" + "="*70)
    if all_passed:
        print("✓✓✓ ALL TESTS PASSED ✓✓✓")
        print("="*70)
        return 0
    else:
        print("✗✗✗ SOME TESTS FAILED ✗✗✗")
        print("="*70)
        return 1


if __name__ == "__main__":
    sys.exit(test_all())
