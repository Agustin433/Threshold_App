"""Confirms whether editing athlete_profile_df invalidates the report preview
cache signature (current_report_state_version / build_report_preview_signature).

Context: `_current_report_state_snapshot()` (app.py) does not yet include
`athlete_profile_df`, and `REPORT_DATASET_KEYS` (modules/page_state.py) --
which drives `current_report_state_version()`'s file-mtime tracking -- does
not list "athlete_profile_df" either. This test proves whether editing a
profile actually changes the cache signature today, before deciding whether
`REPORT_DATASET_KEYS` needs the new key added as part of Block 4.
"""

from __future__ import annotations

import importlib
import os
import shutil
import time
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

TEST_TMP_ROOT = Path(__file__).resolve().parent / ".tmp_report_cache"


@contextmanager
def isolated_store():
    original_store = os.environ.get("THRESHOLD_STORE_DIR")
    tmp_root = None
    try:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        tmp_root = TEST_TMP_ROOT / f"report_cache_{uuid.uuid4().hex[:8]}"
        store_dir = tmp_root / "store"
        store_dir.mkdir(parents=True, exist_ok=True)
        os.environ["THRESHOLD_STORE_DIR"] = str(store_dir)

        import local_store as local_store_module
        import modules.page_state as page_state_module

        local_store_module = importlib.reload(local_store_module)
        page_state_module = importlib.reload(page_state_module)
        yield local_store_module, page_state_module
    finally:
        if original_store is None:
            os.environ.pop("THRESHOLD_STORE_DIR", None)
        else:
            os.environ["THRESHOLD_STORE_DIR"] = original_store
        if tmp_root is not None:
            shutil.rmtree(tmp_root, ignore_errors=True)
        if TEST_TMP_ROOT.exists() and not any(TEST_TMP_ROOT.iterdir()):
            TEST_TMP_ROOT.rmdir()

        import local_store as local_store_module
        import modules.page_state as page_state_module

        importlib.reload(local_store_module)
        importlib.reload(page_state_module)


class ReportStateCacheInvalidationTest(unittest.TestCase):
    def test_editing_objetivo_primario_changes_current_report_state_version(self):
        with isolated_store() as (local_store, page_state):
            local_store.upsert_athlete_profile(
                {
                    "Athlete": "Ana Lopez",
                    "Contexto": "Club",
                    "Nivel": "Competitivo",
                    "Objetivo_primario": "Fuerza máxima",
                    "Es_RTP": False,
                }
            )
            version_before = page_state.current_report_state_version()

            time.sleep(0.05)
            local_store.upsert_athlete_profile(
                {
                    "Athlete": "Ana Lopez",
                    "Contexto": "Club",
                    "Nivel": "Competitivo",
                    "Objetivo_primario": "Hipertrofia",
                    "Es_RTP": False,
                }
            )
            version_after = page_state.current_report_state_version()

            self.assertNotEqual(
                version_before,
                version_after,
                "current_report_state_version() no cambio tras editar Objetivo_primario "
                "-- confirma que REPORT_DATASET_KEYS no vigila athlete_profiles.csv.",
            )

    def test_toggling_es_rtp_changes_build_report_preview_signature(self):
        with isolated_store() as (local_store, page_state):
            local_store.upsert_athlete_profile(
                {
                    "Athlete": "Ana Lopez",
                    "Contexto": "Club",
                    "Nivel": "Competitivo",
                    "Objetivo_primario": "Fuerza máxima",
                    "Es_RTP": False,
                }
            )
            signature_before = page_state.build_report_preview_signature(
                report_audience="profe",
                report_athlete="Ana Lopez",
                effective_report_athlete="Ana Lopez",
                report_options={"include_technical_annex": False},
                date_window="01/01/2026 - 31/01/2026",
            )

            time.sleep(0.05)
            local_store.upsert_athlete_profile(
                {
                    "Athlete": "Ana Lopez",
                    "Contexto": "Club",
                    "Nivel": "Competitivo",
                    "Objetivo_primario": "Fuerza máxima",
                    "Es_RTP": True,
                }
            )
            signature_after = page_state.build_report_preview_signature(
                report_audience="profe",
                report_athlete="Ana Lopez",
                effective_report_athlete="Ana Lopez",
                report_options={"include_technical_annex": False},
                date_window="01/01/2026 - 31/01/2026",
            )

            self.assertNotEqual(
                signature_before,
                signature_after,
                "build_report_preview_signature() no cambio tras togglear Es_RTP -- "
                "el preview de reporte cacheado no se invalidaria con este edit.",
            )


if __name__ == "__main__":
    unittest.main()
