"""Importador de perfiles desde el Google Form "Perfil de Cliente".

El CSV de ejemplo tiene los encabezados reales del formulario MAS columnas de
telefono, contacto de emergencia, salud y medicacion: ninguna puede llegar a un
DataFrame ni al payload que se guarda.
"""

from __future__ import annotations

import csv
import io
import os
import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from modules.profile_form_import import (
    FORM_COLUMNS,
    build_import_plan,
    final_profile,
    match_form_headers,
    name_candidates,
    profile_diff,
    read_form_csv,
    read_form_sheet,
)

TODAY = pd.Timestamp("2026-10-27")

SENSITIVE_HEADERS = [
    "Teléfono",
    "Contacto de emergencia (nombre y teléfono)",
    "¿Tenés alguna condición de salud que debamos conocer?",
    "Lesiones previas",
    "¿Tomás alguna medicación?",
    "Disponibilidad horaria",
]
SENSITIVE_VALUES = ["+54 9 381 555-0000", "Mamá 381-555-1111", "Asma", "LCA 2023", "Salbutamol", "Lunes 18hs"]

HEADERS = [
    FORM_COLUMNS["timestamp"],
    FORM_COLUMNS["nombre"],
    SENSITIVE_HEADERS[0],
    FORM_COLUMNS["nacimiento"],
    FORM_COLUMNS["altura"],
    FORM_COLUMNS["peso"],
    FORM_COLUMNS["sexo"],
    FORM_COLUMNS["email"],
    SENSITIVE_HEADERS[1],
    FORM_COLUMNS["objetivo"],
    FORM_COLUMNS["objetivo_texto"],
    FORM_COLUMNS["deporte"],
    FORM_COLUMNS["anios_fuerza"],
    FORM_COLUMNS["nivel"],
    SENSITIVE_HEADERS[2],
    SENSITIVE_HEADERS[3],
    SENSITIVE_HEADERS[4],
    FORM_COLUMNS["rtp"],
    FORM_COLUMNS["modalidad"],
    SENSITIVE_HEADERS[5],
    FORM_COLUMNS["autorizacion"],
]

TEAMBUILDR_NAMES = [
    "Ana Lopez",
    "Celina Amarillo",
    "Agustin Lopez Muñoz",
    "Bruno Rey",
    "Gaston Castaño",
]


def _row(ts, name, birth, height, weight, *, sexo="Femenino", objetivo="Fuerza máxima", nivel="Recreativo",
         rtp="No", modalidad="Presencial", autorizacion="Sí, autorizo", deporte="Sí, fútbol", texto=""):
    values = {
        FORM_COLUMNS["timestamp"]: ts,
        FORM_COLUMNS["nombre"]: name,
        FORM_COLUMNS["nacimiento"]: birth,
        FORM_COLUMNS["altura"]: height,
        FORM_COLUMNS["peso"]: weight,
        FORM_COLUMNS["sexo"]: sexo,
        FORM_COLUMNS["email"]: "atleta@example.com",
        FORM_COLUMNS["objetivo"]: objetivo,
        FORM_COLUMNS["objetivo_texto"]: texto,
        FORM_COLUMNS["deporte"]: deporte,
        FORM_COLUMNS["anios_fuerza"]: "2",
        FORM_COLUMNS["nivel"]: nivel,
        FORM_COLUMNS["rtp"]: rtp,
        FORM_COLUMNS["modalidad"]: modalidad,
        FORM_COLUMNS["autorizacion"]: autorizacion,
    }
    values.update(dict(zip(SENSITIVE_HEADERS, SENSITIVE_VALUES)))
    return [values[header] for header in HEADERS]


ROWS = [
    # fila 2: valida, match exacto con TeamBuildr
    _row("20/10/2026 10:00:00", "ana lopez", "15/03/1998", "168", "61,5"),
    # fila 3: fecha imposible
    _row("20/10/2026 10:05:00", "Bruno Rey", "31/02/1990", "180", "80", sexo="Masculino"),
    # fila 4: altura en metros
    _row("20/10/2026 10:10:00", "Gaston Castaño", "02/07/1995", "1,79", "78", sexo="Masculino", rtp="Sí",
         objetivo="Rehabilitación y retorno deportivo (RTP)"),
    # fila 5: sin autorizacion
    _row("20/10/2026 10:15:00", "Ana Lopez", "15/03/1998", "168", "61", autorizacion="No autorizo"),
    # fila 6: nombre invertido
    _row("20/10/2026 10:20:00", "Amarillo Celina", "10/10/2000", "165", "58", modalidad="Online",
         objetivo="Quiero correr una maratón", texto="Terminar los 42k en abril"),
    # filas 7 y 8: misma persona dos veces (vale la mas reciente)
    _row("21/10/2026 09:00:00", "Agustin Lopez Muñoz", "01/01/1990", "175", "70", sexo="Masculino"),
    _row("22/10/2026 09:00:00", "Agustin Lopez Muñoz", "01/01/1990", "175", "72", sexo="Masculino"),
]

EXISTING_PROFILES = pd.DataFrame(
    [
        {
            "Athlete": "Agustin Lopez Muñoz", "Fecha_nacimiento": "1990-01-01", "Sexo": "M", "Altura_cm": 175,
            "Peso_kg": 70, "Contexto": "Gimnasio", "Deporte": "Fútbol", "Nivel": "Recreativo",
            "Objetivo_primario": "Fuerza máxima", "Objetivos_secundarios": "", "Objetivo_otro_texto": None,
            "Es_RTP": False, "Fecha_actualizacion": "2026-09-01",
        }
    ]
)


def _csv_bytes(rows=ROWS, encoding="utf-8-sig") -> io.BytesIO:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(HEADERS)
    writer.writerows(rows)
    data = io.BytesIO(buffer.getvalue().encode(encoding))
    data.name = "respuestas.csv"
    return data


def _plan(rows=ROWS, existing=EXISTING_PROFILES):
    return build_import_plan(read_form_csv(_csv_bytes(rows)), TEAMBUILDR_NAMES, existing, today=TODAY)


def _item(plan, row_number):
    return next(item for item in plan.items if item.row_number == row_number)


class ReadOnlyAllowedColumnsTest(unittest.TestCase):
    def test_csv_reader_never_loads_sensitive_columns(self):
        frame = read_form_csv(_csv_bytes())
        self.assertEqual(set(frame.columns), set(FORM_COLUMNS))
        dumped = frame.to_csv()
        for value in SENSITIVE_VALUES:
            self.assertNotIn(value, dumped)

    def test_payload_has_only_profile_columns_and_no_sensitive_data(self):
        plan = _plan()
        payloads = [final_profile(item) for item in plan.items if item.athlete and not item.errors]
        self.assertTrue(payloads)
        for payload in payloads:
            self.assertNotIn("Email", payload)
            text = repr(payload)
            for value in SENSITIVE_VALUES + ["atleta@example.com"]:
                self.assertNotIn(value, text)

    def test_sheets_reader_requests_only_allowed_column_ranges(self):
        requested: list[str] = []
        header = HEADERS
        data_columns = list(zip(*ROWS))

        def fake_get_json(url: str, token: str) -> dict:
            requested.append(url)
            if "batchGet" not in url:
                return {"values": [header]}
            ranges = [part.split("=", 1)[1] for part in url.split("?", 1)[1].split("&") if part.startswith("ranges=")]
            value_ranges = []
            for encoded in ranges:
                from urllib.parse import unquote_plus

                letter = unquote_plus(encoded).split("!")[1].split("2:")[0]
                index = ord(letter) - 65
                value_ranges.append({"values": [list(data_columns[index])]})
            return {"valueRanges": value_ranges}

        frame = read_form_sheet("sheet-id", "Respuestas de formulario 1", "token", get_json=fake_get_json)
        self.assertEqual(set(frame.columns), set(FORM_COLUMNS))
        self.assertEqual(len(frame), len(ROWS))
        sensitive_letters = {chr(65 + HEADERS.index(h)) for h in SENSITIVE_HEADERS}
        from urllib.parse import unquote_plus

        batch = unquote_plus(requested[1])
        for letter in sensitive_letters:
            self.assertNotIn(f"!{letter}2:{letter}", batch)

    def test_missing_required_column_fails_loud(self):
        with self.assertRaises(ValueError) as ctx:
            match_form_headers([h for h in HEADERS if h != FORM_COLUMNS["nacimiento"]])
        self.assertIn("Fecha de nacimiento", str(ctx.exception))


class ValidationTest(unittest.TestCase):
    def setUp(self):
        self.plan = _plan()

    def test_valid_response_is_ready_with_teambuildr_name(self):
        item = _item(self.plan, 2)
        self.assertEqual(item.status, "listo")
        profile = final_profile(item)
        self.assertEqual(profile["Athlete"], "Ana Lopez")
        self.assertEqual(profile["Fecha_nacimiento"], "1998-03-15")
        self.assertEqual(profile["Peso_kg"], 61.5)
        self.assertEqual(profile["Sexo"], "F")
        self.assertEqual(profile["Contexto"], "Gimnasio")
        self.assertEqual(profile["Deporte"], "Fútbol")
        self.assertEqual(profile["Fecha_actualizacion"], pd.Timestamp("2026-10-20 10:00:00"))
        self.assertIs(profile["Es_RTP"], False)

    def test_impossible_date_is_rejected_with_value(self):
        item = _item(self.plan, 3)
        self.assertEqual(item.status, "rechazado")
        self.assertIn("31/02/1990", " ".join(item.errors))

    def test_future_and_out_of_range_ages_are_rejected(self):
        rows = [
            _row("20/10/2026 10:00:00", "Ana Lopez", "01/01/2030", "168", "61"),
            _row("20/10/2026 10:00:00", "Bruno Rey", "01/01/2020", "168", "61"),
            _row("20/10/2026 10:00:00", "Celina Amarillo", "01/01/1920", "168", "61"),
        ]
        plan = _plan(rows, None)
        self.assertIn("futura", " ".join(plan.items[0].errors))
        self.assertIn("6 años", " ".join(plan.items[1].errors))
        self.assertIn("106 años", " ".join(plan.items[2].errors))

    def test_height_in_meters_is_converted_with_warning(self):
        item = _item(self.plan, 4)
        self.assertEqual(item.profile["Altura_cm"], 179.0)
        self.assertTrue(any("metros" in warning for warning in item.warnings))
        self.assertIs(item.profile["Es_RTP"], True)
        self.assertEqual(item.profile["Objetivo_primario"], "Rehabilitación y retorno deportivo (RTP)")

    def test_out_of_range_weight_and_height_are_rejected(self):
        rows = [_row("20/10/2026 10:00:00", "Ana Lopez", "15/03/1998", "250", "20")]
        errors = " ".join(_plan(rows, None).items[0].errors)
        self.assertIn("altura fuera de rango", errors)
        self.assertIn("peso fuera de rango", errors)

    def test_without_authorization_is_excluded(self):
        item = _item(self.plan, 5)
        self.assertEqual(item.status, "rechazado")
        self.assertTrue(item.errors[0].startswith("sin autorización"))
        self.assertEqual(item.profile, {})

    def test_inverted_name_requires_confirmation_with_candidate(self):
        item = _item(self.plan, 6)
        self.assertEqual(item.status, "requiere_confirmacion")
        self.assertIsNone(item.athlete)
        self.assertEqual(item.candidates[0], ("Celina Amarillo", "mismas palabras en otro orden"))
        self.assertEqual(item.profile["Contexto"], "Online")
        self.assertEqual(item.profile["Objetivo_primario"], "Otro")
        self.assertEqual(item.profile["Objetivo_otro_texto"], "Quiero correr una maratón | Terminar los 42k en abril")
        with self.assertRaises(ValueError):
            final_profile(item)
        item.athlete = "Celina Amarillo"
        self.assertEqual(final_profile(item)["Athlete"], "Celina Amarillo")

    def test_duplicate_response_keeps_latest_and_warns(self):
        older, latest = _item(self.plan, 7), _item(self.plan, 8)
        self.assertEqual(older.status, "rechazado")
        self.assertIn("duplicada", " ".join(older.errors))
        self.assertTrue(any("respondió 2 veces" in w for w in latest.warnings))
        self.assertTrue(self.plan.warnings)

    def test_existing_profile_shows_diff_and_needs_confirmation(self):
        latest = _item(self.plan, 8)
        self.assertEqual(latest.status, "requiere_confirmacion")
        self.assertEqual(latest.diff, [("Peso_kg", 70, 72.0)])

    def test_identical_existing_profile_is_not_reimported(self):
        rows = [_row("21/10/2026 09:00:00", "Agustin Lopez Muñoz", "01/01/1990", "175", "70", sexo="Masculino")]
        item = _plan(rows).items[0]
        self.assertEqual(item.status, "sin_cambios")

    def test_keyword_mapping_requires_confirmation(self):
        rows = [_row("20/10/2026 10:00:00", "Ana Lopez", "15/03/1998", "168", "61", nivel="Competitivo regional")]
        item = _plan(rows, None).items[0]
        self.assertEqual(item.status, "requiere_confirmacion")
        self.assertEqual(item.profile["Nivel"], "Competitivo")
        self.assertIn("palabra clave", " ".join(item.confirmations))

    def test_unknown_level_and_modality_are_rejected(self):
        rows = [_row("20/10/2026 10:00:00", "Ana Lopez", "15/03/1998", "168", "61", nivel="???", modalidad="Híbrido")]
        errors = " ".join(_plan(rows, None).items[0].errors)
        self.assertIn("nivel no reconocido", errors)
        self.assertIn("modalidad no reconocida", errors)


class NameResolutionTest(unittest.TestCase):
    def test_candidates_cover_inverted_short_and_accents(self):
        names = ["Celina Amarillo", "Agustin Lopez Muñoz", "Lucia Anadon", "Otro Atleta"]
        self.assertEqual(name_candidates("Amarillo Celina", names), [("Celina Amarillo", "mismas palabras en otro orden")])
        self.assertEqual(
            name_candidates("Agustín Alejandro Lopez Muñoz", names),
            [("Agustin Lopez Muñoz", "nombre completo vs. nombre corto")],
        )
        self.assertEqual(name_candidates("Lucía Anadón", names), [("Lucia Anadon", "mismo nombre sin tildes/mayúsculas")])
        self.assertEqual(name_candidates("Nadie Conocido", names), [])

    def test_profile_diff_ignores_equivalent_values(self):
        old = {"Peso_kg": "70.0", "Es_RTP": "False", "Deporte": None}
        new = {"Peso_kg": 70, "Es_RTP": False, "Deporte": ""}
        self.assertEqual([change for change in profile_diff(old, new) if change[0] in old], [])


APP_PAGE = Path(__file__).resolve().parent.parent / "pages" / "03_importar_perfiles.py"


@contextmanager
def isolated_store():
    original = os.environ.get("THRESHOLD_STORE_DIR")
    tmp_root = Path(__file__).resolve().parent / f".tmp_profile_import_{uuid.uuid4().hex[:8]}"
    (tmp_root / "store").mkdir(parents=True)
    os.environ["THRESHOLD_STORE_DIR"] = str(tmp_root / "store")
    try:
        yield tmp_root / "store"
    finally:
        if original is None:
            os.environ.pop("THRESHOLD_STORE_DIR", None)
        else:
            os.environ["THRESHOLD_STORE_DIR"] = original
        shutil.rmtree(tmp_root, ignore_errors=True)


class ImportPageTest(unittest.TestCase):
    def test_page_blocks_without_teambuildr_names(self):
        import importlib

        import local_store
        from streamlit.testing.v1 import AppTest

        with isolated_store():
            importlib.reload(local_store)
            try:
                at = AppTest.from_file(str(APP_PAGE), default_timeout=60)
                at.run()
                self.assertFalse(at.exception, at.exception)
                self.assertTrue(any("No hay nombres de TeamBuildr" in e.value for e in at.error))
            finally:
                importlib.reload(local_store)

    def test_import_flow_without_supabase_never_says_saved(self):
        import importlib

        import local_store
        from streamlit.testing.v1 import AppTest

        env_backup = {k: os.environ.pop(k, None) for k in ("SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_SERVICE_ROLE_KEY")}
        try:
            with isolated_store() as store:
                pd.DataFrame(
                    {"Athlete": TEAMBUILDR_NAMES, "Date": ["2026-10-20"] * len(TEAMBUILDR_NAMES), "sRPE": [300] * len(TEAMBUILDR_NAMES)}
                ).to_csv(store / "rpe_history.csv", index=False)
                importlib.reload(local_store)
                try:
                    at = AppTest.from_file(str(APP_PAGE), default_timeout=60)
                    at.session_state["profile_import_plan"] = _plan(existing=None)
                    at.session_state["profile_import_existing"] = {}
                    at.run()
                    self.assertFalse(at.exception, at.exception)
                    metrics = {m.label: m.value for m in at.metric}
                    self.assertEqual(metrics["Listos"], "3")
                    self.assertEqual(metrics["Rechazados"], "3")
                    self.assertEqual(metrics["Requieren confirmación"], "1")

                    self.assertTrue(at.checkbox(key="pf_confirm_6").disabled)  # sin atleta elegido
                    at.selectbox(key="pf_athlete_6").set_value("Celina Amarillo")
                    at.run()
                    at.checkbox(key="pf_confirm_6").check()
                    at.run()
                    import_button = next(b for b in at.button if b.label.startswith("Importar confirmados"))
                    self.assertEqual(import_button.label, "Importar confirmados (4)")
                    import_button.click()
                    at.run()
                    self.assertFalse(at.exception, at.exception)
                    errors = " ".join(e.value for e in at.error)
                    self.assertIn("SOLO en esta instancia", errors)
                    self.assertFalse(any("guardados en Supabase" in s.value for s in at.success))

                    saved = pd.read_csv(store / "athlete_profiles.csv")
                    self.assertEqual(
                        sorted(saved["Athlete"]),
                        ["Agustin Lopez Muñoz", "Ana Lopez", "Celina Amarillo", "Gaston Castaño"],
                    )
                    agustin = saved[saved["Athlete"] == "Agustin Lopez Muñoz"].iloc[0]
                    self.assertEqual(float(agustin["Peso_kg"]), 72.0)  # la respuesta mas reciente
                    self.assertNotIn("Amarillo Celina", set(saved["Athlete"]))
                finally:
                    importlib.reload(local_store)
        finally:
            for key, value in env_backup.items():
                if value is not None:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
