"""Reloj unico de la app: "ahora" y "hoy" en hora de Argentina.

El servidor (Streamlit Cloud) corre en UTC. datetime.now()/Timestamp.now()
devolvian la hora UTC: el PDF decia "Generado el 18:37" cuando eran las
15:37, y despues de las 21:00 locales "hoy" ya era mañana (semana actual,
dias desde la ultima evaluacion, edad, alertas).

Todo "ahora"/"hoy" de la app sale de aca. Devuelve valores SIN zona horaria
(naive), en hora local, igual que el resto de las fechas de la app.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timezone

import pandas as pd

APP_TIMEZONE = "America/Argentina/Buenos_Aires"


_frozen_utc: datetime | None = None


def _utc_now() -> datetime:
    """Unico punto que lee el reloj del sistema."""
    if _frozen_utc is not None:
        return _frozen_utc
    return datetime.now(timezone.utc)


@contextmanager
def frozen_app_now(local_moment: object) -> Iterator[None]:
    """Congela app_now() en `local_moment`, hora de Argentina (para tests).

    Un valor sin zona horaria se interpreta como hora local argentina.
    """
    global _frozen_utc
    moment = pd.Timestamp(local_moment)
    if moment.tzinfo is None:
        moment = moment.tz_localize(APP_TIMEZONE)
    previous = _frozen_utc
    _frozen_utc = moment.tz_convert("UTC").to_pydatetime()
    try:
        yield
    finally:
        _frozen_utc = previous


def app_now() -> pd.Timestamp:
    """Fecha y hora actual en Argentina, sin zona horaria."""
    return pd.Timestamp(_utc_now()).tz_convert(APP_TIMEZONE).tz_localize(None)


def app_today() -> pd.Timestamp:
    """Hoy en Argentina, a las 00:00 (Timestamp sin zona horaria)."""
    return app_now().normalize()


def app_today_date() -> date:
    """Hoy en Argentina como datetime.date."""
    return app_now().date()
