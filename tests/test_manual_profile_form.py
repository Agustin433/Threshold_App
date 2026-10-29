"""Carga manual del perfil de atleta: fecha de nacimiento, rangos y contexto Online."""

from __future__ import annotations

import importlib
import os
import shutil
import unittest
import uuid
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from modules.athlete_profile import (
    BIRTH_DATE_MIN,
    CONTEXTO_OPTIONS,
    get_comparison_cohort,
    validate_profile_fields,
)

APP_PY = Path(__file__).resolve().parent.parent / "app.py"
TMP_ROOT = Path(__file__).resolve().parent / ".tmp_manual_profile"

BASE_PROFILE = {
    "Athlete": "Ana Lopez",
    "Contexto": "Gimnasio",
    "Nivel": "Recreativo",
    "Objetivo_primario": "Fuerza máxima",
    "Sexo": "F",
}


def _errors(**fields) -> list[str]:
    return validate_profile_fields({**BASE_PROFILE, **fields}, today=date(2026, 10, 29))


class ProfileValidationTest(unittest.TestCase):
    def test_birth_date_bounds(self):
        self.assertEqual(_errors(Fecha_nacimiento="1981-05-10"), [])
        self.assertEqual(_errors(Fecha_nacimiento=None), [])
        future = _errors(Fecha_nacimiento="2026-10-30")
        self.assertEqual(len(future), 1)
        self.assertIn("futura", future[0])
        self.assertIn("30/10/2026", future[0])
        self.assertIn("anterior a 01/01/1940", _errors(Fecha_nacimiento="1939-12-31")[0])

    def test_height_zero_or_range(self):
        for ok in (None, 0, 0.0, 120, 175.5, 220):
            self.assertEqual(_errors(Altura_cm=ok), [], ok)
        for bad in (119.5, 221, 1.75):
            errors = _errors(Altura_cm=bad)
            self.assertEqual(len(errors), 1, bad)
            self.assertIn(f"{bad:g} cm", errors[0])

    def test_weight_zero_or_range(self):
        for ok in (None, 0, 30, 82.5, 200):
            self.assertEqual(_errors(Peso_kg=ok), [], ok)
        for bad in (29, 201, 250):
            errors = _errors(Peso_kg=bad)
            self.assertEqual(len(errors), 1, bad)
            self.assertIn(f"{bad:g} kg", errors[0])

    def test_online_is_a_context_option(self):
        self.assertEqual(CONTEXTO_OPTIONS, ("Club", "Gimnasio", "Online"))
        self.assertEqual(_errors(Contexto="Online"), [])


class OnlineCohortTest(unittest.TestCase):
    def test_online_athlete_is_compared_by_class_and_sex(self):
        # La cohorte de z-scores agrupa por clase (Nivel) y sexo, no por
        # Contexto: un atleta Online compara con los de su clase y sexo.
        athletes = [f"Atleta {i}" for i in range(10)]
        profiles = pd.DataFrame(
            {
                "Athlete": athletes,
                "Contexto": ["Online"] * 3 + ["Gimnasio"] * 4 + ["Club"] * 3,
                "Nivel": ["Recreativo"] * 10,
                "Sexo": ["F"] * 10,
            }
        )
        jumps = pd.DataFrame({"Athlete": athletes, "Date": ["2026-10-01"] * 10, "CMJ_cm": range(30, 40)})
        cohort = get_comparison_cohort("Atleta 0", jumps, profiles, min_cohort_size=8)
        self.assertEqual(cohort["cohort_level"], "clase_sexo")
        self.assertEqual(cohort["cohort_size"], 10)


@contextmanager
def isolated_store():
    original = os.environ.get("THRESHOLD_STORE_DIR")
    env_backup = {key: os.environ.pop(key, None) for key in ("SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_SERVICE_ROLE_KEY")}
    tmp = TMP_ROOT / uuid.uuid4().hex[:8]
    (tmp / "store").mkdir(parents=True)
    os.environ["THRESHOLD_STORE_DIR"] = str(tmp / "store")
    import local_store

    importlib.reload(local_store)
    try:
        yield tmp / "store"
    finally:
        if original is None:
            os.environ.pop("THRESHOLD_STORE_DIR", None)
        else:
            os.environ["THRESHOLD_STORE_DIR"] = original
        for key, value in env_backup.items():
            if value is not None:
                os.environ[key] = value
        importlib.reload(local_store)
        shutil.rmtree(tmp, ignore_errors=True)
        if TMP_ROOT.exists() and not any(TMP_ROOT.iterdir()):
            TMP_ROOT.rmdir()


class ManualProfileFormTest(unittest.TestCase):
    """Corre app.py real con AppTest sobre un store aislado y sin Supabase."""

    def _app(self):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(APP_PY), default_timeout=120)
        at.run()
        self.assertFalse(at.exception, at.exception)
        return at

    def _fill_and_submit(self, at, *, birth: date | None, height: float = 0.0, contexto: str = "Gimnasio"):
        at.selectbox(key="profile_athlete_select_0").set_value("Escribir nuevo...")
        at.text_input(key="profile_athlete_text_0").input("Ana Lopez")
        if birth is not None:
            at.date_input(key="profile_birth_0").set_value(birth)
        at.number_input(key="profile_height_0").set_value(height)
        at.radio(key="profile_contexto_0").set_value(contexto)
        at.radio(key="profile_sexo_0").set_value(at.radio(key="profile_sexo_0").options[1])
        next(button for button in at.button if button.label == "Guardar perfil").click()
        at.run()
        self.assertFalse(at.exception, at.exception)
        return at

    @staticmethod
    def _saved(store: Path) -> pd.DataFrame:
        path = store / "athlete_profiles.csv"
        return pd.read_csv(path) if path.exists() else pd.DataFrame()

    def test_birth_date_widget_allows_adults_and_blocks_future(self):
        with isolated_store():
            at = self._app()
            widget = at.date_input(key="profile_birth_0")
            self.assertEqual(widget.min, BIRTH_DATE_MIN)
            self.assertEqual(widget.max, date.today())
            self.assertLessEqual(widget.min, date(1981, 5, 10))
            self.assertGreater(date.today() + timedelta(days=1), widget.max)

    def test_accepts_1981_and_saves(self):
        with isolated_store() as store:
            at = self._fill_and_submit(self._app(), birth=date(1981, 5, 10), height=175.0, contexto="Online")
            saved = self._saved(store)
            self.assertEqual(list(saved["Athlete"]), ["Ana Lopez"])
            self.assertEqual(saved.iloc[0]["Fecha_nacimiento"], "1981-05-10")
            self.assertEqual(saved.iloc[0]["Contexto"], "Online")
            self.assertEqual(float(saved.iloc[0]["Altura_cm"]), 175.0)

    def test_tomorrow_is_never_stored(self):
        # En el navegador el calendario no deja elegir despues de max_value.
        # Si igual llega (AppTest lo permite), Streamlit descarta el valor
        # fuera de rango: el perfil se guarda SIN fecha, nunca con la futura.
        # La validacion de validate_profile_fields es la segunda barrera
        # (test_birth_date_bounds).
        tomorrow = date.today() + timedelta(days=1)
        with isolated_store() as store:
            self._fill_and_submit(self._app(), birth=tomorrow)
            saved = self._saved(store)
            self.assertEqual(len(saved), 1)
            self.assertTrue(pd.isna(saved.iloc[0]["Fecha_nacimiento"]))
            self.assertNotIn(tomorrow.isoformat(), saved.to_csv())

    def test_out_of_range_height_shows_error_with_value(self):
        with isolated_store() as store:
            at = self._fill_and_submit(self._app(), birth=date(1981, 5, 10), height=250.0)
            errors = " ".join(element.value for element in at.error)
            self.assertIn("Altura fuera de rango: 250 cm", errors)
            self.assertTrue(self._saved(store).empty)


class DecisionPanelContextFilterTest(unittest.TestCase):
    def test_decision_filter_offers_every_profile_context(self):
        source = APP_PY.read_text(encoding="utf-8")
        self.assertIn('["Todos", *CONTEXTO_OPTIONS]', source)
        self.assertNotIn('["Todos", "Club", "Gimnasio"]', source)


if __name__ == "__main__":
    unittest.main()
