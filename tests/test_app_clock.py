"""Reloj de la app en hora de Argentina.

El servidor corre en UTC: a las 22:00 de Argentina en UTC ya es la 01:00 del
dia siguiente. "Hoy" y "Generado el" tienen que ser los de Argentina.
"""

from __future__ import annotations

import re
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from modules import app_clock
from modules.app_clock import APP_TIMEZONE, app_now, app_today, app_today_date, frozen_app_now

REPO_ROOT = Path(__file__).resolve().parent.parent

# 22:00 del 28/10 en Argentina = 01:00 del 29/10 en UTC.
LOCAL_22H = datetime(2026, 10, 28, 22, 0)


class AppClockTest(unittest.TestCase):
    def test_at_22h_local_today_is_still_today(self):
        with frozen_app_now(LOCAL_22H):
            self.assertEqual(app_clock._utc_now(), datetime(2026, 10, 29, 1, 0, tzinfo=timezone.utc))
            self.assertEqual(app_now(), pd.Timestamp("2026-10-28 22:00"))
            self.assertEqual(app_today(), pd.Timestamp("2026-10-28"))
            self.assertEqual(app_today_date(), date(2026, 10, 28))
            self.assertIsNone(app_now().tzinfo)

    def test_afternoon_hour_is_local_not_utc(self):
        # El PDF decia 18:37 (UTC) cuando eran las 15:37 en Argentina.
        with frozen_app_now(pd.Timestamp("2026-10-28 18:37", tz="UTC")):
            self.assertEqual(app_now().strftime("%H:%M"), "15:37")

    def test_freeze_is_restored(self):
        with frozen_app_now(LOCAL_22H):
            pass
        self.assertIsNone(app_clock._frozen_utc)
        real = pd.Timestamp.now(tz=APP_TIMEZONE).tz_localize(None)
        self.assertLess(abs((app_now() - real).total_seconds()), 5)

    def test_report_generated_at_uses_local_time(self):
        from modules import report_generator

        with frozen_app_now(LOCAL_22H):
            metadata = report_generator._build_report_metadata_df({}, "Ana Lopez", "cliente", [])
        generated = metadata.loc[metadata["Campo"] == "Generado", "Valor"].iloc[0]
        self.assertEqual(generated, "28/10/2026 22:00")

    def test_current_week_and_alerts_use_local_today(self):
        import local_store
        from modules import alerts

        # Domingo 01/11 22:00 local = lunes 02/11 en UTC. La semana actual
        # tiene que seguir siendo la del lunes 26/10, no la siguiente.
        with frozen_app_now(datetime(2026, 11, 1, 22, 0)):
            self.assertEqual(local_store._resolve_today(), pd.Timestamp("2026-11-01"))
            self.assertEqual(local_store._current_week_start(), pd.Timestamp("2026-10-26"))
            self.assertEqual(alerts._coerce_reference_date(), pd.Timestamp("2026-11-01"))

    def test_no_raw_clock_calls_outside_app_clock(self):
        # Tambien utcnow (deprecado en pandas, se rompe en pandas 4) y las
        # formas con texto: Timestamp("now"/"today"), to_datetime("now"/"today").
        pattern = re.compile(
            r"datetime\.now\(|Timestamp\.now\(|Timestamp\.today\(|date\.today\(|datetime\.today\("
            r"|utcnow\(|utcfromtimestamp\("
            r"|Timestamp\(\s*[\"'](?:now|today)[\"']|to_datetime\(\s*[\"'](?:now|today)[\"']"
        )
        offenders = []
        for folder in ("modules", "charts", "pages", "scripts"):
            for path in (REPO_ROOT / folder).glob("*.py"):
                if path.name == "app_clock.py":
                    continue
                for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    if pattern.search(line) and not line.lstrip().startswith("#"):
                        offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}")
        for path in (REPO_ROOT / "app.py", REPO_ROOT / "local_store.py"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line) and not line.lstrip().startswith("#"):
                    offenders.append(f"{path.name}:{number}")
        self.assertEqual(offenders, [], "Usar modules.app_clock (app_now/app_today) en lugar del reloj del sistema")


if __name__ == "__main__":
    unittest.main()
