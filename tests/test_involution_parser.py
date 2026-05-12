from __future__ import annotations

import unittest
from io import BytesIO

from openpyxl import Workbook

from modules.evaluation_registry import (
    get_evaluation_spec,
    get_storage_mapping,
    list_evaluation_specs,
)
from modules.involution_parser import parse_involution_summary_excel


def _build_involution_workbook(
    rows: list[tuple[object, object]],
    *,
    sheet_name: str = "Custom Export",
    include_noise_sheet: bool = False,
) -> bytes:
    workbook = Workbook()
    if include_noise_sheet:
        noise = workbook.active
        noise.title = "Metadata"
        noise.append(["Random", "Value"])
        noise.append(["Nothing", "Useful"])
        worksheet = workbook.create_sheet(title=sheet_name)
    else:
        worksheet = workbook.active
        worksheet.title = sheet_name

    worksheet.append(["References", "Rep 1"])
    for label, value in rows:
        worksheet.append([label, value])

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _valid_imtp_rows(asymmetry_label: str = "Asimmetry (%)") -> list[tuple[object, object]]:
    return [
        ("Time Max Force (s)", 2.63),
        ("Time Pull (s)", 3.00),
        ("RFD at 50 (N/s)", 1260),
        ("RFD at 100 (N/s)", 2558),
        ("RFD at 150 (N/s)", 3411),
        ("RFD at 250 (N/s)", 4493),
        ("Force At 50 (N)", 1172),
        ("Force At 100 (N)", 1364),
        ("Force At 150 (N)", 1620),
        ("Force At 200 (N)", 1957),
        ("Force At 250 (N)", 2232),
        ("Force Max (N)", 3385),
        ("Force Avg (N)", 2993),
        ("Force Left Max (N)", 1731),
        ("Force Right Max (N)", 1653),
        (asymmetry_label, 4.5),
        ("Pre-tension (N)", 1109),
    ]


class InvolutionParserTest(unittest.TestCase):
    def test_parser_reads_valid_imtp_workbook(self):
        workbook_bytes = _build_involution_workbook(_valid_imtp_rows())

        result = parse_involution_summary_excel(
            BytesIO(workbook_bytes),
            test_id="imtp",
            athlete_name="Carlos Falivene",
            test_date="2026-05-10",
        )

        self.assertEqual(result["test_id"], "imtp")
        self.assertEqual(result["athlete_name"], "Carlos Falivene")
        self.assertEqual(result["test_date"], "2026-05-10")
        self.assertEqual(result["rep_column"], "Rep 1")
        self.assertEqual(result["source_format"], "involution_summary")
        self.assertEqual(result["metrics"]["force_max_n"], 3385)
        self.assertEqual(result["metrics"]["force_avg_n"], 2993)
        self.assertEqual(result["metrics"]["force_left_max_n"], 1731)
        self.assertEqual(result["metrics"]["force_right_max_n"], 1653)
        self.assertEqual(result["metrics"]["asymmetry_pct"], 4.5)
        self.assertEqual(result["metrics"]["time_to_peak_s"], 2.63)
        self.assertEqual(result["metrics"]["time_pull_s"], 3)

    def test_parser_finds_sheet_by_content_not_sheet_name(self):
        workbook_bytes = _build_involution_workbook(
            _valid_imtp_rows(),
            sheet_name="Not Sheet One",
            include_noise_sheet=True,
        )

        result = parse_involution_summary_excel(workbook_bytes, test_id="imtp")

        self.assertEqual(result["rep_column"], "Rep 1")
        self.assertEqual(result["metrics"]["force_250_n"], 2232)

    def test_parser_tolerates_missing_metrics_and_returns_none(self):
        partial_rows = [
            ("Time Max Force (s)", 2.63),
            ("Force Max (N)", 3385),
            ("Force Left Max (N)", 1731),
            ("Force Right Max (N)", 1653),
            ("Asimmetry (%)", "not a number"),
        ]
        workbook_bytes = _build_involution_workbook(partial_rows)

        result = parse_involution_summary_excel(workbook_bytes, test_id="imtp")

        self.assertIsNone(result["metrics"]["time_pull_s"])
        self.assertIsNone(result["metrics"]["force_avg_n"])
        self.assertIsNone(result["metrics"]["asymmetry_pct"])
        self.assertIn("time_pull_s", result["missing_metrics"])
        self.assertIn("force_avg_n", result["missing_metrics"])
        self.assertIn("asymmetry_pct", result["missing_metrics"])

    def test_parser_tolerates_asimmetry_and_asymmetry_labels(self):
        for label in ("Asimmetry (%)", "Asymmetry (%)"):
            with self.subTest(label=label):
                workbook_bytes = _build_involution_workbook(_valid_imtp_rows(asymmetry_label=label))
                result = parse_involution_summary_excel(workbook_bytes, test_id="imtp")
                self.assertEqual(result["metrics"]["asymmetry_pct"], 4.5)

    def test_parser_does_not_invent_rfd_200(self):
        workbook_bytes = _build_involution_workbook(_valid_imtp_rows())

        result = parse_involution_summary_excel(workbook_bytes, test_id="imtp")

        self.assertNotIn("rfd_200_n_s", result["metrics"])
        self.assertNotIn("rfd_200_n_s", result["missing_metrics"])

    def test_parser_returns_expected_normalized_field_names(self):
        workbook_bytes = _build_involution_workbook(_valid_imtp_rows())

        result = parse_involution_summary_excel(workbook_bytes, test_id="imtp")

        expected_fields = {
            "force_max_n",
            "force_avg_n",
            "force_left_max_n",
            "force_right_max_n",
            "asymmetry_pct",
            "pre_tension_n",
            "time_to_peak_s",
            "time_pull_s",
            "force_50_n",
            "force_100_n",
            "force_150_n",
            "force_200_n",
            "force_250_n",
            "rfd_50_n_s",
            "rfd_100_n_s",
            "rfd_150_n_s",
            "rfd_250_n_s",
        }

        self.assertEqual(set(result["metrics"]), expected_fields)

    def test_registry_returns_imtp_spec(self):
        spec = get_evaluation_spec("imtp")

        self.assertIsNotNone(spec)
        self.assertEqual(spec["id"], "imtp")
        self.assertEqual(spec["display_name"], "IMTP")
        self.assertEqual(spec["primary_metric"], "force_max_n")
        self.assertEqual(spec["interpretation_model"], "imtp_force_time")
        self.assertEqual(spec["report_levels"], ["athlete", "professional"])
        self.assertEqual(len(list_evaluation_specs()), 1)

    def test_registry_exposes_correct_imtp_storage_mapping(self):
        mapping = get_storage_mapping("imtp")
        spec = get_evaluation_spec("imtp")

        self.assertEqual(mapping["force_max_n"], "IMTP_N")
        self.assertEqual(mapping["time_pull_s"], "IMTP_time_pull_s")
        self.assertEqual(mapping["force_200_n"], "IMTP_force_200_N")
        self.assertEqual(mapping["rfd_250_n_s"], "IMTP_rfd_250_N_s")
        self.assertEqual(
            spec["legacy_storage_aliases"],
            {
                "RFD_50": "IMTP_rfd_50_N_s",
                "RFD_100": "IMTP_rfd_100_N_s",
                "RFD_150": "IMTP_rfd_150_N_s",
                "RFD_250": "IMTP_rfd_250_N_s",
            },
        )


if __name__ == "__main__":
    unittest.main()
