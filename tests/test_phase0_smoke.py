from __future__ import annotations

import importlib
import os
import tempfile
import unittest
import zipfile
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

import pandas as pd

from charts.load_charts import chart_volume_by_tag
from modules import data_loader
from modules.jump_analysis import _records_to_jump_df


class NamedBytesIO(BytesIO):
    def __init__(self, data: bytes, name: str):
        super().__init__(data)
        self.name = name


def _column_letter(index: int) -> str:
    result = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _build_minimal_xlsx(rows: list[list[object]]) -> bytes:
    shared_strings: list[str] = []
    shared_lookup: dict[str, int] = {}

    def shared_index(value: str) -> int:
        if value not in shared_lookup:
            shared_lookup[value] = len(shared_strings)
            shared_strings.append(value)
        return shared_lookup[value]

    sheet_rows: list[str] = []
    for row_number, row in enumerate(rows, start=1):
        cells: list[str] = []
        for column_number, value in enumerate(row, start=1):
            cell_ref = f"{_column_letter(column_number)}{row_number}"
            if value in (None, ""):
                cells.append(f'<c r="{cell_ref}"/>')
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{cell_ref}"><v>{value}</v></c>')
            else:
                idx = shared_index(str(value))
                cells.append(f'<c r="{cell_ref}" t="s"><v>{idx}</v></c>')
        sheet_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')

    shared_strings_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">'
        + "".join(f"<si><t>{escape(text)}</t></si>" for text in shared_strings)
        + "</sst>"
    )
    worksheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(sheet_rows)}</sheetData>"
        "</worksheet>"
    )

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as workbook:
        workbook.writestr("xl/sharedStrings.xml", shared_strings_xml)
        workbook.writestr("xl/worksheets/sheet1.xml", worksheet_xml)
    return buffer.getvalue()


def _questionnaire_bytes(mode: str) -> bytes:
    if mode == "rpe":
        rows = [
            ["Name", "RPE", "Time"],
            ["Juan Perez", ""],
            ["Apr 02, 2026", "7", "60"],
            ["Maria Gomez", ""],
            ["Apr 03, 2026", "5", "45"],
        ]
    else:
        rows = [
            ["Name", "Sleep", "Stress", "Soreness"],
            ["Juan Perez", ""],
            ["Apr 02, 2026", "4", "3", "2"],
            ["Maria Gomez", ""],
            ["Apr 03, 2026", "5", "2", "1"],
        ]
    return _build_minimal_xlsx(rows)


def _forceplate_bytes() -> bytes:
    rows = [
        ["Metric", "Rep 1", "Rep 2"],
        ["Height Jump (cm)", 38.2, 39.1],
        ["RSI", 1.45, 1.61],
        ["Concentric Time (ms)", 505, 490],
        ["Propulsive Max Force (N)", 1810, 1840],
        ["Propulsive Relative Impulse (N*s/Kg)", 2.21, 2.35],
        ["Landing Max Force (N)", 3120, 3205],
        ["Landing Asymmetry Max Force (%)", 4.2, 3.8],
        ["Stabilization Time (ms)", 1180, 1125],
    ]
    return _build_minimal_xlsx(rows)


def _csv_bytes(text: str) -> bytes:
    return text.strip().encode("utf-8")


def _chart_theme() -> dict:
    return {
        "colors": {
            "navy": "#0D3C5E",
            "steel": "#134263",
            "blue": "#6E8C9F",
            "green": "#6F8F78",
            "yellow": "#C4A464",
            "orange": "#B56B73",
            "gray": "#7A8690",
            "muted": "#7A8690",
        },
        "layout": {},
        "grid": "rgba(0,0,0,0.1)",
        "grid_soft": "rgba(0,0,0,0.06)",
        "legend": {},
    }


@contextmanager
def isolated_store():
    original_store = os.environ.get("THRESHOLD_STORE_DIR")
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            store_dir = Path(tmp_dir) / "store"
            os.environ["THRESHOLD_STORE_DIR"] = str(store_dir)
            import local_store as local_store_module

            local_store_module = importlib.reload(local_store_module)
            local_store_module.LEGACY_STORE_DIR = Path(tmp_dir) / "legacy-default"
            yield local_store_module, Path(tmp_dir)
    finally:
        if original_store is None:
            os.environ.pop("THRESHOLD_STORE_DIR", None)
        else:
            os.environ["THRESHOLD_STORE_DIR"] = original_store
        import local_store as local_store_module

        importlib.reload(local_store_module)


class Phase0SmokeTest(unittest.TestCase):
    def test_jump_records_compute_eur_as_ratio(self):
        jump_df = _records_to_jump_df(
            [
                {"Athlete": "Ana Lopez", "Date": pd.Timestamp("2026-04-03"), "CMJ_cm": 35},
                {"Athlete": "Ana Lopez", "Date": pd.Timestamp("2026-04-03"), "SJ_cm": 30},
            ]
        )

        self.assertEqual(len(jump_df), 1)
        self.assertAlmostEqual(float(jump_df.loc[0, "EUR"]), 1.167, places=3)
        self.assertNotIn(16.7, jump_df["EUR"].tolist())

    def test_jump_history_read_normalizes_legacy_eur_percentages(self):
        with isolated_store() as (local_store, _):
            local_store._ensure_store_dir()
            pd.DataFrame(
                [
                    {
                        "Athlete": "Ana Lopez",
                        "Date": "2026-04-03",
                        "EUR": 16.7,
                        "DRI": 1.6,
                        "IMTP_N": 1820,
                    }
                ]
            ).to_csv(local_store.STORE_DIR / "evaluations_history.csv", index=False)

            loaded = local_store.read_full_dataset("jump_df")
            recent_state = local_store.load_recent_state()
            recent_jump_df = recent_state["jump_df"]

            self.assertEqual(len(loaded), 1)
            self.assertAlmostEqual(float(loaded.loc[0, "EUR"]), 1.167, places=3)
            self.assertEqual(loaded.loc[0, "NM_Profile"], "Reactivo")
            self.assertNotIn(16.7, loaded["EUR"].tolist())
            self.assertIsNotNone(recent_jump_df)
            self.assertAlmostEqual(float(recent_jump_df.loc[0, "EUR"]), 1.167, places=3)

    def test_parsers_accept_valid_exports(self):
        rpe_df = data_loader.parse_xlsx_questionnaire(
            _questionnaire_bytes("rpe"),
            mode="rpe",
            filename="questionnaire-report.xlsx",
        )
        wellness_df = data_loader.parse_xlsx_questionnaire(
            _questionnaire_bytes("wellness"),
            mode="wellness",
            filename="questionnaire-report_wellness.xlsx",
        )
        completion_df = data_loader.parse_completion_report(
            NamedBytesIO(
                _csv_bytes(
                    """
                    Date,Assigned,Completed,Athlete
                    2026-04-02,10,9,Juan Perez
                    2026-04-03,8,8,Maria Gomez
                    """
                ),
                "completion.csv",
            )
        )
        rep_load_df = data_loader.parse_rep_load_report(
            NamedBytesIO(
                _csv_bytes(
                    """
                    Date,Rep Count (Completed),Load (Completed),Exercise Name,Athlete
                    2026-04-02,5,80,Back Squat,Juan Perez
                    2026-04-03,3,95,Trap Bar Deadlift,Maria Gomez
                    """
                ),
                "rep_load.csv",
            )
        )
        raw_df = data_loader.parse_raw_workouts(
            NamedBytesIO(
                _csv_bytes(
                    """
                    Assigned Date,Result,Reps,Tags,Athlete
                    2026-04-02,80,5,Dominante de Rodilla,Juan Perez
                    2026-04-03,65,6,Empuje Horizontal,Maria Gomez
                    """
                ),
                "raw_workouts.csv",
            )
        )
        maxes_df = data_loader.parse_maxes_health(
            NamedBytesIO(
                _csv_bytes(
                    """
                    Added Date,Max Value,Exercise Name,Athlete
                    2026-04-02,110,Back Squat,Juan Perez
                    2026-04-03,95,Bench Press,Maria Gomez
                    """
                ),
                "maxes.csv",
            )
        )
        forceplate_record = data_loader.parse_forceplate_file(
            _forceplate_bytes(),
            "CMJ",
            filename="cmj.xlsx",
        )

        self.assertEqual(len(rpe_df), 2)
        self.assertIn("sRPE", rpe_df.columns)
        self.assertEqual(len(wellness_df), 2)
        self.assertIn("Wellness_Score", wellness_df.columns)
        self.assertTrue(completion_df["Pct"].notna().all())
        self.assertIn("Load_kg", rep_load_df.columns)
        self.assertIn("Volume_Load", raw_df.columns)
        self.assertIn("Volume_Load_legacy", raw_df.columns)
        self.assertIn("Volume_Load_kg", raw_df.columns)
        self.assertIn("Contacts", raw_df.columns)
        self.assertIn("Exposures", raw_df.columns)
        self.assertIn("stimulus_category", raw_df.columns)
        self.assertIn("Max Value", maxes_df.columns)
        self.assertIn("CMJ_cm", forceplate_record)
        self.assertIn("CMJ_propulsive_PF_N", forceplate_record)
        self.assertIn("CMJ_rel_impulse", forceplate_record)
        self.assertIn("CMJ_landing_force_N", forceplate_record)
        self.assertIn("CMJ_landing_asym_pct", forceplate_record)
        self.assertIn("CMJ_stabilization_ms", forceplate_record)

    def test_raw_workouts_split_external_load_by_stimulus(self):
        raw_df = data_loader.parse_raw_workouts(
            NamedBytesIO(
                _csv_bytes(
                    """
                    Assigned Date,Result,Reps,Sets,Duration (s),Tags,Athlete,Exercise
                    2026-04-02,80,5,4,,Dominante de Rodilla,Juan Perez,Back Squat
                    2026-04-03,60,3,3,,DLO,Juan Perez,Hang Clean
                    2026-04-04,,24,6,,Jump_Plyo,Juan Perez,Pogo
                    2026-04-05,,12,4,,Catch_Landing,Juan Perez,Drop Catch
                    2026-04-06,1500,1,3,30,Iso_Overcoming,Juan Perez,Mid Thigh Pull Hold
                    2026-04-07,,12,4,,Core,Juan Perez,Dead Bug
                    2026-04-08,,10,2,,Stretch MMII,Juan Perez,Hip Mobility
                    2026-04-09,0,6,3,,Empuje Horizontal,Juan Perez,Bench Press
                    2026-04-10,40,0,3,,Empuje Vertical,Juan Perez,Push Press
                    2026-04-11,20,8,3,,ju,Juan Perez,Dirty Tag
                    2026-04-12,15,10,3,,UnknownTag,Juan Perez,Unknown Drill
                    """
                ),
                "raw_workouts.csv",
            )
        )

        strength_row = raw_df[raw_df["Tags"] == "Dominante de Rodilla"].iloc[0]
        dlo_row = raw_df[raw_df["Tags"] == "DLO"].iloc[0]
        plyo_row = raw_df[raw_df["Tags"] == "Jump_Plyo"].iloc[0]
        iso_row = raw_df[raw_df["Tags"] == "Iso_Overcoming"].iloc[0]
        core_row = raw_df[raw_df["Tags"] == "Core"].iloc[0]
        mobility_row = raw_df[raw_df["Tags"] == "Stretch MMII"].iloc[0]
        invalid_row = raw_df[raw_df["Tags"] == "ju"].iloc[0]
        untagged_row = raw_df[raw_df["Tags"] == "UnknownTag"].iloc[0]

        self.assertEqual(strength_row["stimulus_category"], "strength_loaded")
        self.assertEqual(strength_row["Category"], "Dominante de Rodilla")
        self.assertAlmostEqual(float(strength_row["Volume_Load_kg"]), 400.0, places=3)
        self.assertTrue(pd.isna(raw_df[raw_df["Tags"] == "Empuje Horizontal"].iloc[0]["Volume_Load_kg"]))
        self.assertEqual(dlo_row["stimulus_category"], "olympic_derivatives")
        self.assertEqual(float(dlo_row["Exposures"]), 3.0)
        self.assertEqual(plyo_row["stimulus_category"], "plyo_jump")
        self.assertEqual(float(plyo_row["Contacts"]), 24.0)
        self.assertEqual(iso_row["stimulus_category"], "iso")
        self.assertEqual(float(iso_row["Exposures"]), 30.0)
        self.assertEqual(core_row["stimulus_category"], "core_stability")
        self.assertEqual(float(core_row["Exposures"]), 4.0)
        self.assertEqual(mobility_row["stimulus_category"], "mobility_prehab")
        self.assertEqual(float(mobility_row["Exposures"]), 2.0)
        self.assertTrue(bool(invalid_row["is_invalid"]))
        self.assertTrue(bool(untagged_row["is_untagged"]))

        quality_df = data_loader.summarize_raw_workouts_quality(raw_df)
        issues = set(quality_df["Detalle"].tolist())
        self.assertIn('Tag invalido ("ju")', issues)
        self.assertIn("Filas sin tag clasificado", issues)
        self.assertIn("Result = 0 en strength_loaded", issues)
        self.assertIn("Reps = 0", issues)

    def test_volume_panel_uses_new_external_load_columns(self):
        raw_df = data_loader.parse_raw_workouts(
            NamedBytesIO(
                _csv_bytes(
                    """
                    Assigned Date,Result,Reps,Sets,Tags,Athlete,Exercise
                    2026-04-02,80,5,4,Dominante de Rodilla,Juan Perez,Back Squat
                    2026-04-03,,20,5,Jump_Plyo,Juan Perez,Pogo
                    2026-04-04,60,3,3,DLO,Juan Perez,Hang Clean
                    """
                ),
                "raw_workouts.csv",
            )
        )

        figure = chart_volume_by_tag(raw_df, "Juan Perez", theme=_chart_theme())
        trace_names = {trace.name for trace in figure.data}
        annotation_texts = [annotation.text for annotation in figure.layout.annotations]

        self.assertIn("Dominante de Rodilla", trace_names)
        self.assertIn("Jump_Plyo", trace_names)
        self.assertIn("DLO", trace_names)
        self.assertTrue(any("Fuerza con carga" in text for text in annotation_texts))
        self.assertTrue(any("Pliometria y aterrizajes" in text for text in annotation_texts))

    def test_invalid_extensions_raise_clear_errors(self):
        with self.assertRaisesRegex(ValueError, r"Completion Report: formato no soportado"):
            data_loader.parse_completion_report(
                NamedBytesIO(_csv_bytes("Date,Assigned,Completed\n2026-04-02,10,9\n"), "completion.xlsx")
            )

        with self.assertRaisesRegex(ValueError, r"RPE \+ Tiempo: formato no soportado"):
            data_loader.parse_xlsx_questionnaire(
                _questionnaire_bytes("rpe"),
                mode="rpe",
                filename="questionnaire-report.csv",
            )

    def test_store_pipeline_and_recent_state_smoke(self):
        with isolated_store() as (local_store, _tmp_root):
            rpe_df = data_loader.parse_xlsx_questionnaire(
                _questionnaire_bytes("rpe"),
                mode="rpe",
                filename="questionnaire-report.xlsx",
            )
            wellness_df = data_loader.parse_xlsx_questionnaire(
                _questionnaire_bytes("wellness"),
                mode="wellness",
                filename="questionnaire-report_wellness.xlsx",
            )
            completion_df = data_loader.parse_completion_report(
                NamedBytesIO(
                    _csv_bytes(
                        """
                        Date,Assigned,Completed,Athlete
                        2026-04-02,10,9,Juan Perez
                        2026-04-03,8,8,Maria Gomez
                        """
                    ),
                    "completion.csv",
                )
            )
            rep_load_df = data_loader.parse_rep_load_report(
                NamedBytesIO(
                    _csv_bytes(
                        """
                        Date,Rep Count (Completed),Load (Completed),Exercise Name,Athlete
                        2026-04-02,5,80,Back Squat,Juan Perez
                        2026-04-03,3,95,Trap Bar Deadlift,Maria Gomez
                        """
                    ),
                    "rep_load.csv",
                )
            )
            raw_df = data_loader.parse_raw_workouts(
                NamedBytesIO(
                    _csv_bytes(
                        """
                        Assigned Date,Result,Reps,Tags,Athlete
                        2026-04-02,80,5,Dominante de Rodilla,Juan Perez
                        2026-04-03,65,6,Empuje Horizontal,Maria Gomez
                        """
                    ),
                    "raw_workouts.csv",
                )
            )
            maxes_df = data_loader.parse_maxes_health(
                NamedBytesIO(
                    _csv_bytes(
                        """
                        Added Date,Max Value,Exercise Name,Athlete
                        2026-04-02,110,Back Squat,Juan Perez
                        2026-04-03,95,Bench Press,Maria Gomez
                        """
                    ),
                    "maxes.csv",
                )
            )
            jump_record = data_loader.parse_forceplate_file(
                _forceplate_bytes(),
                "CMJ",
                filename="cmj.xlsx",
            )
            jump_record["Athlete"] = "Juan Perez"
            jump_record["Date"] = pd.Timestamp("2026-04-03")
            jump_df = _records_to_jump_df([jump_record])

            local_store.save_dataset("rpe_df", rpe_df)
            local_store.save_dataset("wellness_df", wellness_df)
            local_store.save_dataset("completion_df", completion_df)
            local_store.save_dataset("rep_load_df", rep_load_df)
            local_store.save_dataset("raw_df", raw_df)
            local_store.save_dataset("maxes_df", maxes_df)
            local_store.save_dataset("jump_df", jump_df)

            state = local_store.load_recent_state()
            summaries = local_store.build_dataset_summaries(state)
            datasets = {row["Dataset"] for row in summaries}

            self.assertTrue({"RPE + Tiempo", "Wellness", "Completion", "Rep/Load", "Raw Workouts", "Maxes", "Evaluaciones"}.issubset(datasets))
            self.assertEqual(sorted(local_store.load_athlete_registry()), ["Juan Perez", "Maria Gomez"])

    def test_legacy_store_migration_copies_existing_files(self):
        with isolated_store() as (local_store, tmp_root):
            legacy_dir = tmp_root / "legacy-store"
            legacy_dir.mkdir(parents=True, exist_ok=True)

            pd.DataFrame(
                {
                    "Date": ["2026-04-02"],
                    "Athlete": ["Juan Perez"],
                    "RPE": [7],
                    "Duration_min": [60],
                    "sRPE": [420],
                }
            ).to_csv(legacy_dir / "rpe_history.csv", index=False)
            pd.DataFrame({"Athlete": ["Juan Perez"]}).to_csv(legacy_dir / "athletes.csv", index=False)

            local_store.LEGACY_STORE_DIR = legacy_dir
            local_store._ensure_store_dir()

            self.assertTrue((local_store.STORE_DIR / "rpe_history.csv").exists())
            self.assertEqual(local_store.load_athlete_registry(), ["Juan Perez"])


if __name__ == "__main__":
    unittest.main()
