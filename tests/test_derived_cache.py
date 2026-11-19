"""El cache de calculos derivados nunca muestra datos viejos.

`modules.derived_cache` memoiza en `session_state` resumenes, alertas e
insights que antes se recalculaban en cada rerun. Estos tests fijan el
contrato: misma entrada -> se reutiliza; dataset nuevo, reemplazado o
borrado -> se recalcula.
"""

from __future__ import annotations

import importlib
import os
import re
import shutil
import unittest
import uuid
from collections import OrderedDict
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

import modules.derived_cache as derived_cache
from modules.app_clock import app_today

APP_PY = Path(__file__).resolve().parent.parent / "app.py"
TMP_ROOT = Path(__file__).resolve().parent / ".tmp_derived_cache"
TODAY = app_today()


class _FakeState(dict):
    pass


def _rpe(athletes: list[str], value: float = 400.0) -> pd.DataFrame:
    # Lunes de esta semana hasta hoy, para que cuenten como "semana actual".
    monday = TODAY - pd.Timedelta(days=TODAY.dayofweek)
    days = pd.date_range(monday - pd.Timedelta(days=27), TODAY, freq="D")
    return pd.DataFrame(
        [
            {"Athlete": athlete, "Date": day.strftime("%Y-%m-%d"), "RPE": 6, "Duration_min": 60, "sRPE": value}
            for athlete in athletes
            for day in days
        ]
    )


class CachedCallUnitTest(unittest.TestCase):
    def setUp(self):
        self.state = _FakeState()
        patcher = patch.object(derived_cache, "_session_state", return_value=self.state)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.calls = 0

    def _fn(self, frame: pd.DataFrame, label: str = "x") -> dict[str, object]:
        self.calls += 1
        return {"total": float(frame["sRPE"].sum()), "label": label}

    def test_same_content_is_reused(self):
        frame = _rpe(["Ana Lopez"])
        first = derived_cache.cached_call("fn", self._fn, frame)
        second = derived_cache.cached_call("fn", self._fn, frame.copy(deep=True))
        self.assertEqual(first, second)
        self.assertEqual(self.calls, 1)

    def test_changed_value_same_shape_recomputes(self):
        frame = _rpe(["Ana Lopez"])
        derived_cache.cached_call("fn", self._fn, frame)
        changed = frame.copy()
        changed.loc[changed.index[0], "sRPE"] = 9999.0
        result = derived_cache.cached_call("fn", self._fn, changed)
        self.assertEqual(self.calls, 2)
        self.assertEqual(result["total"], float(changed["sRPE"].sum()))

    def test_in_place_mutation_recomputes(self):
        frame = _rpe(["Ana Lopez"])
        derived_cache.cached_call("fn", self._fn, frame)
        frame.loc[frame.index[-1], "Athlete"] = "Otro Atleta"
        derived_cache.cached_call("fn", self._fn, frame)
        self.assertEqual(self.calls, 2)

    def test_scalar_arguments_are_part_of_the_signature(self):
        frame = _rpe(["Ana Lopez"])
        derived_cache.cached_call("fn", self._fn, frame, label="a")
        result = derived_cache.cached_call("fn", self._fn, frame, label="b")
        self.assertEqual(result["label"], "b")
        self.assertEqual(self.calls, 2)

    def test_caller_mutation_does_not_poison_the_cache(self):
        frame = _rpe(["Ana Lopez"])
        first = derived_cache.cached_call("fn", self._fn, frame)
        first["total"] = -1
        second = derived_cache.cached_call("fn", self._fn, frame)
        self.assertEqual(second["total"], float(frame["sRPE"].sum()))

    def test_unsignable_argument_bypasses_the_cache(self):
        opaque = object()
        derived_cache.cached_call("fn", lambda value: id(value), opaque)
        derived_cache.cached_call("fn", lambda value: id(value), opaque)
        self.assertEqual(self.state[derived_cache.DERIVED_CACHE_STATS_KEY].get("bypass"), 2)
        self.assertFalse(self.state.get(derived_cache.DERIVED_CACHE_KEY))

    def test_invalidate_clears_entries(self):
        frame = _rpe(["Ana Lopez"])
        derived_cache.cached_call("fn", self._fn, frame)
        derived_cache.invalidate_derived_cache()
        self.assertEqual(self.state[derived_cache.DERIVED_CACHE_KEY], OrderedDict())
        derived_cache.cached_call("fn", self._fn, frame)
        self.assertEqual(self.calls, 2)

    def test_store_change_invalidates(self):
        frame = _rpe(["Ana Lopez"])
        with patch.object(derived_cache, "_store_version", return_value=(("rpe", 1, 10),)):
            derived_cache.cached_call("fn", self._fn, frame)
            derived_cache.cached_call("fn", self._fn, frame)
        with patch.object(derived_cache, "_store_version", return_value=(("rpe", 2, 10),)):
            derived_cache.cached_call("fn", self._fn, frame)
        self.assertEqual(self.calls, 2)

    def test_outside_streamlit_calls_directly(self):
        with patch.object(derived_cache, "_session_state", return_value=None):
            frame = _rpe(["Ana Lopez"])
            derived_cache.cached_call("fn", self._fn, frame)
            derived_cache.cached_call("fn", self._fn, frame)
        self.assertEqual(self.calls, 2)


def _active_athletes_in_overview(at: AppTest) -> int | None:
    """Atletas activos segun la "Lectura integrada" (generate_module_insights)."""
    pattern = re.compile(r"Semana actual con (\d+) atleta\(s\) activos")
    for element in at.markdown:
        match = pattern.search(str(element.value))
        if match:
            return int(match.group(1))
    return None


class OverviewShowsFreshDataTest(unittest.TestCase):
    def setUp(self):
        self.original = os.environ.get("THRESHOLD_STORE_DIR")
        self.tmp = TMP_ROOT / uuid.uuid4().hex[:8]
        self.store = self.tmp / "store"
        self.store.mkdir(parents=True)
        os.environ["THRESHOLD_STORE_DIR"] = str(self.store)
        import local_store

        self.local_store = importlib.reload(local_store)

    def tearDown(self):
        if self.original is None:
            os.environ.pop("THRESHOLD_STORE_DIR", None)
        else:
            os.environ["THRESHOLD_STORE_DIR"] = self.original
        shutil.rmtree(self.tmp, ignore_errors=True)
        if TMP_ROOT.exists() and not any(TMP_ROOT.iterdir()):
            TMP_ROOT.rmdir()

    def _run(self, at: AppTest) -> AppTest:
        at.run()
        self.assertFalse(at.exception, at.exception)
        return at

    def test_loading_replacing_and_deleting_a_dataset_invalidates_the_cache(self):
        _rpe(["Ana Lopez", "Bruno Diaz"]).to_csv(self.store / "rpe_history.csv", index=False)
        at = AppTest.from_file(str(APP_PY), default_timeout=180)
        self._run(at)
        self.assertEqual(_active_athletes_in_overview(at), 2)

        # Rerun sin cambios: el calculo se reutiliza (el cache esta activo).
        self._run(at)
        stats = at.session_state[derived_cache.DERIVED_CACHE_STATS_KEY]
        self.assertGreater(stats.get("hit", 0), 0)
        self.assertEqual(_active_athletes_in_overview(at), 2)

        # Cargar un dataset nuevo (mismo camino que un upload: se guarda en el store).
        self.local_store.save_dataset("rpe_df", _rpe(["Carla Perez"]))
        self._run(at)
        self.assertEqual(_active_athletes_in_overview(at), 3)

        # Reemplazar el historial por uno distinto.
        self.local_store.overwrite_dataset("rpe_df", _rpe(["Diego Romero"]))
        self._run(at)
        self.assertEqual(_active_athletes_in_overview(at), 1)

        # Borrar: sin sRPE no queda ningun atleta activo en la semana.
        self.local_store.overwrite_dataset("rpe_df", None)
        self._run(at)
        self.assertIn(_active_athletes_in_overview(at), (None, 0))


if __name__ == "__main__":
    unittest.main()
