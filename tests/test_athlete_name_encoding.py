"""Encoding de exports de TeamBuildr y normalizacion unica de nombres.

Bug de oct/2026: parse_questionnaire_raw_csv probaba ("utf-8", "replace")
primero, que nunca falla, asi que el fallback a latin-1 no corria y los
exports en Windows-1252 guardaban "Gaston Casta�O".

El fixture questionnaire_raw_cp1252.csv tiene el formato exacto del export
de TeamBuildr (mismo encabezado) codificado en cp1252, con los nombres de
los casos reales y un apostrofo tipografico (0x92, que solo existe en cp1252).
"""

from __future__ import annotations

import io
import unittest
from pathlib import Path

import pandas as pd

from local_store import normalize_athlete_name as normalize_from_local_store
from modules.athlete_names import (
    REPLACEMENT_CHAR,
    AthleteNameEncodingError,
    normalize_athlete_name,
    normalize_athlete_series,
)
from modules.data_loader import (
    _read_binary_content,
    _read_csv_with_fallback,
    parse_questionnaire_raw_csv,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "questionnaire_raw_cp1252.csv"

EXPECTED_ATHLETES = {
    "Gaston Castaño",
    "Lourdes Castaño",
    "Tomás Camandona",
    "Agustin Lopez Muñoz",
    "Julián Peñalva",
    "Sofía Gambandé",
    "Martín Viña",
    "Martina D’Andrea",
}


class _Named(io.BytesIO):
    def __init__(self, data: bytes, name: str = "questionnaire.csv"):
        super().__init__(data)
        self.name = name


def _fixture_text() -> str:
    return FIXTURE.read_bytes().decode("cp1252")


class QuestionnaireEncodingTest(unittest.TestCase):
    def test_fixture_is_really_cp1252(self):
        raw = FIXTURE.read_bytes()
        with self.assertRaises(UnicodeDecodeError):
            raw.decode("utf-8")
        # Asi se rompia: utf-8 con errors="replace" "funciona" y deja U+FFFD.
        self.assertIn(REPLACEMENT_CHAR, raw.decode("utf-8", errors="replace"))

    def test_cp1252_export_keeps_ene_and_accents(self):
        rpe_df, wellness_df = parse_questionnaire_raw_csv(_Named(FIXTURE.read_bytes()))
        self.assertEqual(set(rpe_df["Athlete"]), EXPECTED_ATHLETES)
        self.assertEqual(set(wellness_df["Athlete"]), EXPECTED_ATHLETES)
        for frame in (rpe_df, wellness_df):
            self.assertFalse(frame["Athlete"].str.contains(REPLACEMENT_CHAR).any())
        castano = rpe_df[rpe_df["Athlete"] == "Gaston Castaño"].iloc[0]
        self.assertAlmostEqual(float(castano["sRPE"]), 420.0)

    def test_utf8_and_utf8_bom_exports_read_the_same(self):
        text = _fixture_text()
        for encoded in (text.encode("utf-8"), text.encode("utf-8-sig")):
            rpe_df, _ = parse_questionnaire_raw_csv(_Named(encoded))
            self.assertEqual(set(rpe_df["Athlete"]), EXPECTED_ATHLETES)

    def test_bytes_undefined_in_cp1252_fall_back_to_latin1(self):
        # 0x81 no existe en cp1252: tiene que caer a latin-1, no romper.
        data = FIXTURE.read_bytes().replace(b"Camandona", b"Camand\x81na")
        rpe_df, _ = parse_questionnaire_raw_csv(_Named(data))
        self.assertIn("Tomás Camand\x81na", set(rpe_df["Athlete"]))
        self.assertIn("Gaston Castaño", set(rpe_df["Athlete"]))

    def test_export_already_containing_fffd_is_rejected(self):
        broken = _fixture_text().replace("Castaño", "Casta�o").encode("utf-8")
        with self.assertRaises(AthleteNameEncodingError) as ctx:
            parse_questionnaire_raw_csv(_Named(broken))
        message = str(ctx.exception)
        self.assertIn("Casta�o", message)
        self.assertIn("no se guardo", message)

    def test_read_binary_content_does_not_replace(self):
        self.assertEqual(_read_binary_content(io.StringIO("Castaño")), "Castaño".encode("utf-8"))
        with self.assertRaises(UnicodeEncodeError):
            _read_binary_content(io.StringIO("Casta\ud800o"))


class CsvFallbackTest(unittest.TestCase):
    def test_utf8_bom_does_not_leak_into_first_column(self):
        data = "Athlete,Date\nGaston Castaño,2026-10-20\n".encode("utf-8-sig")
        df = _read_csv_with_fallback(_Named(data, "x.csv"))
        self.assertEqual(list(df.columns), ["Athlete", "Date"])

    def test_cp1252_csv_is_decoded_strictly(self):
        data = "Athlete,Date\nMartina D’Andrea,2026-10-20\n".encode("cp1252")
        df = _read_csv_with_fallback(_Named(data, "x.csv"))
        self.assertEqual(df.iloc[0]["Athlete"], "Martina D’Andrea")


class NormalizeAthleteNameTest(unittest.TestCase):
    def test_single_source_of_truth(self):
        self.assertIs(normalize_from_local_store, normalize_athlete_name)

    def test_casing_rules(self):
        cases = {
            "GASTON CASTAÑO": "Gaston Castaño",
            "gaston castaño": "Gaston Castaño",
            "de la vega": "De La Vega",
            "De La Vega": "De La Vega",
            "McDonald": "McDonald",
            "d'andrea": "D'Andrea",
            "D'ANDREA": "D'Andrea",
            "jean-pierre lópez": "Jean-Pierre López",
            "gASTON": "Gaston",
            "  Agustín   Lopez  Muñoz ": "Agustín Lopez Muñoz",
            "﻿Ana Lopez": "Ana Lopez",
            "Atleta 1": "Atleta 1",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_athlete_name(raw), expected)

    def test_unicode_is_composed(self):
        # n + tilde combinada; .title() la convertia en "CastañO".
        self.assertEqual(normalize_athlete_name("Castaño"), "Castaño")

    def test_missing_values(self):
        for value in (None, float("nan"), pd.NA, "", "   "):
            self.assertEqual(normalize_athlete_name(value), "")

    def test_existing_stored_names_do_not_change(self):
        # Todo lo guardado hasta hoy salio de .title(): la nueva normalizacion
        # tiene que devolver exactamente lo mismo para no cambiar claves.
        raw_names = [
            "gaston castaño", "AGUSTIN LOPEZ MUÑOZ", "de la vega", "maría josé", "o'neil",
            "ana-laura pérez", "celina amarillo", "anadón",
        ]
        for raw in raw_names:
            stored = " ".join(raw.split()).title()
            with self.subTest(stored=stored):
                self.assertEqual(normalize_athlete_name(stored), stored)

    def test_idempotent(self):
        for raw in ("McDonald", "d'andrea", "GASTON CASTAÑO", "Castaño"):
            once = normalize_athlete_name(raw)
            self.assertEqual(normalize_athlete_name(once), once)

    def test_series_rejects_fffd_only_when_asked(self):
        series = pd.Series(["Gaston Casta�o", "Ana Lopez", None])
        with self.assertRaises(AthleteNameEncodingError):
            normalize_athlete_series(series, source_label="Test")
        relaxed = normalize_athlete_series(series, reject_replacement_char=False)
        self.assertEqual(relaxed.iloc[1], "Ana Lopez")
        self.assertTrue(pd.isna(relaxed.iloc[2]))


if __name__ == "__main__":
    unittest.main()
