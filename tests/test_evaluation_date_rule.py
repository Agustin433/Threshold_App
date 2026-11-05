"""Regla 9: la fecha de evaluacion se elige a proposito.

El archivo de Involution no trae fecha. Con el selector en "hoy" por defecto
entraron tomas con el anio corrido (IMTP de Giffon, Lopez Munoz y Anadon en
2025 en vez de 2026). Ahora el selector arranca vacio y una fecha de mas de
90 dias, de otro anio o futura pide confirmacion antes de entrar a la cola.
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from modules.evaluation_rules import EVAL_DATE_CONFIRM_DAYS, evaluation_date_check
from tests.test_manual_profile_form import APP_PY, isolated_store

TODAY = date(2026, 11, 4)


class EvaluationDateRuleTest(unittest.TestCase):
    def test_empty_date_is_missing(self):
        self.assertTrue(evaluation_date_check(None, TODAY)["missing"])

    def test_recent_date_this_year_needs_nothing(self):
        result = evaluation_date_check(date(2026, 10, 30), TODAY)
        self.assertFalse(result["missing"])
        self.assertFalse(result["needs_confirmation"])

    def test_real_shifted_year_needs_confirmation(self):
        result = evaluation_date_check(date(2025, 5, 22), TODAY)
        self.assertTrue(result["needs_confirmation"])
        self.assertIn("22/05/2025", result["reason"])
        self.assertIn("es de 2025, no de 2026", result["reason"])

    def test_older_than_90_days_same_year(self):
        old = TODAY - timedelta(days=EVAL_DATE_CONFIRM_DAYS + 1)
        result = evaluation_date_check(old, TODAY)
        self.assertTrue(result["needs_confirmation"])
        self.assertIn("91 días", result["reason"])
        exactly_90 = TODAY - timedelta(days=EVAL_DATE_CONFIRM_DAYS)
        self.assertFalse(evaluation_date_check(exactly_90, TODAY)["needs_confirmation"])

    def test_future_date_needs_confirmation(self):
        result = evaluation_date_check(TODAY + timedelta(days=1), TODAY)
        self.assertTrue(result["needs_confirmation"])
        self.assertIn("futura", result["reason"])


class EvaluationDateFormTest(unittest.TestCase):
    """app.py real con AppTest: carga manual de un CMJ."""

    def _app(self):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(str(APP_PY), default_timeout=120)
        at.run()
        self.assertFalse(at.exception, at.exception)
        return at

    def _submit(self, at, *, eval_date, confirm: bool = False):
        at.radio(key="eval_entry_mode").set_value("Manual")
        at.run()
        at.selectbox(key="eval_athlete_select").set_value("Escribir nuevo...")
        at.text_input(key="eval_athlete_text").input("Ana Lopez")
        # PR C: sexo obligatorio si el atleta no tiene perfil con sexo.
        at.selectbox(key="eval_sexo_choice").set_value("Femenino")
        if eval_date is not None:
            at.date_input(key="eval_date").set_value(eval_date)
        confirm_box = next(box for box in at.checkbox if str(box.key).startswith("eval_date_confirm_"))
        confirm_box.set_value(confirm)
        at.number_input(key="eval_manual_CMJ_cm").set_value(40.0)
        next(button for button in at.button if button.label == "Agregar evaluacion").click()
        at.run()
        self.assertFalse(at.exception, at.exception)
        return at

    @staticmethod
    def _queue(at) -> list:
        return list(at.session_state["eval_records"]) if "eval_records" in at.session_state else []

    @staticmethod
    def _messages(at) -> str:
        # Los avisos de la carga se encolan en upload_feedback y se muestran
        # al comienzo del siguiente rerun (_flush_notices).
        pending = at.session_state["upload_feedback"] if "upload_feedback" in at.session_state else []
        shown = [str(item.value) for kind in (at.warning, at.success, at.error) for item in kind]
        return " ".join([str(item.get("message", "")) for item in pending] + shown)

    def test_date_picker_starts_empty(self):
        with isolated_store():
            self.assertIsNone(self._app().date_input(key="eval_date").value)

    def test_empty_date_is_not_queued(self):
        with isolated_store():
            at = self._submit(self._app(), eval_date=None)
            self.assertEqual(self._queue(at), [])
            self.assertIn("elegí la fecha de evaluación", self._messages(at))

    def test_other_year_without_confirmation_is_not_queued(self):
        with isolated_store():
            at = self._submit(self._app(), eval_date=date(2025, 5, 22))
            self.assertEqual(self._queue(at), [])
            self.assertIn("No se agregó a la cola", self._messages(at))

    def test_other_year_with_confirmation_is_queued(self):
        with isolated_store():
            at = self._submit(self._app(), eval_date=date(2025, 5, 22), confirm=True)
            queue = self._queue(at)
            self.assertEqual(len(queue), 1)
            self.assertEqual(str(queue[0]["Date"].date()), "2025-05-22")


if __name__ == "__main__":
    unittest.main()
