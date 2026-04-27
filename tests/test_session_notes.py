from __future__ import annotations

import importlib
import os
import unittest
from io import BytesIO
from pathlib import Path

import pandas as pd

from modules.data_loader import (
    classify_session_note_reason,
    extract_replacement_exercise,
    parse_session_notes_pdf,
)
from modules.report_generator import build_report_sheets

try:
    from reportlab.pdfgen import canvas
except Exception:  # pragma: no cover - optional dependency guard for lean envs
    canvas = None


def _session_notes_pdf(lines: list[str]) -> BytesIO:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    y = 800
    for line in lines:
        pdf.drawString(48, y, line)
        y -= 16
        if y < 48:
            pdf.showPage()
            y = 800
    pdf.save()
    buffer.seek(0)
    buffer.name = "teambuildr_optouts.pdf"
    return buffer


def _sample_notes_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Date": pd.Timestamp("2026-04-24"),
                "Athlete": "Ana Lopez",
                "Date_Assigned": pd.Timestamp("2026-04-23"),
                "Assigned_Exercise": "Back Squat",
                "Opt_Out_Type": "Injury / Pain",
                "Reason_Category": "injury_or_pain",
                "Replacement_Exercise": "Trap Bar Deadlift",
                "Explanation_Text": "Trap Bar Deadlift completed instead due to knee pain.",
                "Source": "teambuildr_optouts.pdf",
                "Source_Page": 1,
                "Raw_Text": "Ana Lopez | Back Squat | Injury / Pain",
            }
        ]
    )


class SessionNotesTest(unittest.TestCase):
    @unittest.skipIf(canvas is None, "reportlab is not installed")
    def test_parse_session_notes_pdf_extracts_real_rows_and_ignores_empty_blocks(self):
        pdf = _session_notes_pdf(
            [
                "Athlete",
                "Date Recorded",
                "Assigned Exercise",
                "Date Assigned",
                "Opt-Out Type",
                "Explanation",
                "Ana Lopez",
                "Apr 24, 2026",
                "Back Squat",
                "Apr 23, 2026",
                "Injury / Pain",
                "Trap Bar Deadlift completed instead due to knee pain.",
                "Bruno Rey",
                "Apr 24, 2026",
                "Bench Press",
                "Apr 23, 2026",
                "No Exercises Completed Yet",
                "No Exercises Completed Yet",
                "Carla Diaz",
                "Apr 25, 2026",
                "Box Jump",
                "Apr 24, 2026",
                "Lack of Equipment",
                "No boxes available.",
            ]
        )

        parsed = parse_session_notes_pdf(pdf)

        self.assertEqual(parsed["Athlete"].tolist(), ["Carla Diaz", "Ana Lopez"])
        self.assertNotIn("Bruno Rey", parsed["Athlete"].tolist())
        ana = parsed[parsed["Athlete"] == "Ana Lopez"].iloc[0]
        carla = parsed[parsed["Athlete"] == "Carla Diaz"].iloc[0]
        self.assertEqual(ana["Reason_Category"], "injury_or_pain")
        self.assertEqual(ana["Replacement_Exercise"], "Trap Bar Deadlift")
        self.assertEqual(carla["Reason_Category"], "lack_of_equipment")
        self.assertEqual(int(ana["Source_Page"]), 1)
        self.assertIn("knee pain", ana["Raw_Text"])

    def test_minimal_reason_taxonomy_and_replacement_extraction_are_conservative(self):
        self.assertEqual(
            classify_session_note_reason("Modified Load", "Reduced weight for today"),
            "modified_load",
        )
        self.assertEqual(
            classify_session_note_reason("", "No rack available"),
            "lack_of_equipment",
        )
        self.assertEqual(
            extract_replacement_exercise("Trap Bar Deadlift completed instead due to knee pain."),
            "Trap Bar Deadlift",
        )
        self.assertTrue(pd.isna(extract_replacement_exercise("Felt off today, skipped.")))

    def test_session_notes_dataset_persists_in_local_store(self):
        old_store_dir = os.environ.get("THRESHOLD_STORE_DIR")
        workspace_root = Path(__file__).resolve().parents[1]
        store_dir = workspace_root / ".test_session_notes_store"
        loaded = pd.DataFrame()
        try:
            store_dir.mkdir(exist_ok=True)
            os.environ["THRESHOLD_STORE_DIR"] = str(store_dir)
            import local_store

            local_store = importlib.reload(local_store)
            local_store.save_dataset("session_notes_df", _sample_notes_df())
            loaded = local_store.read_full_dataset("session_notes_df")
        finally:
            if old_store_dir is None:
                os.environ.pop("THRESHOLD_STORE_DIR", None)
            else:
                os.environ["THRESHOLD_STORE_DIR"] = old_store_dir
            import local_store

            importlib.reload(local_store)
            for filename in ["session_notes_history.csv", "athletes.csv"]:
                path = store_dir / filename
                if path.exists():
                    path.unlink()
            if store_dir.exists() and not any(store_dir.iterdir()):
                store_dir.rmdir()

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded.loc[0, "Athlete"], "Ana Lopez")
        self.assertEqual(loaded.loc[0, "Reason_Category"], "injury_or_pain")

    def test_report_sheets_include_curated_context_and_opt_in_annex(self):
        state = {
            "rpe_df": None,
            "wellness_df": None,
            "completion_df": None,
            "rep_load_df": None,
            "raw_df": None,
            "session_notes_df": _sample_notes_df(),
            "maxes_df": None,
            "jump_df": None,
            "acwr_dict": {},
            "mono_dict": {},
        }

        athlete_sheets = build_report_sheets(
            state,
            report_athlete="Ana Lopez",
            report_audience="atleta",
            include_technical_annex=True,
        )
        profe_sheets = build_report_sheets(
            state,
            report_athlete="Ana Lopez",
            report_audience="profe",
            include_technical_annex=True,
        )

        self.assertIn("Contexto_Operativo", athlete_sheets)
        self.assertNotIn("Session_Notes", athlete_sheets)
        self.assertIn("Contexto_Operativo", profe_sheets)
        self.assertIn("Session_Notes", profe_sheets)
        self.assertEqual(
            athlete_sheets["Contexto_Operativo"].loc[0, "Categoria"],
            "injury_or_pain",
        )


if __name__ == "__main__":
    unittest.main()
