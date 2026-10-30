"""Escalas del cuestionario de wellness (TeamBuildr): una sola fuente.

Estres y dolor se responden en 0-10 en el cuestionario de TeamBuildr (Question
ID 103227 y 103498); el sueno en horas. El score de wellness (data_loader)
invierte estres y dolor sobre esa misma escala 0-10.

Antes el PDF inferia la escala del maximo de los datos ("/5" si ningun valor
pasaba de 5, "/10" si no): el mismo atleta podia salir con "Dolor 2.3/5" en un
reporte y "7.0/10" en otro. Dashboard, PDF y Excel leen la escala de aca.
"""

from __future__ import annotations

WELLNESS_RESPONSE_MAX = 10.0
WELLNESS_RESPONSE_SCALE = f"/{WELLNESS_RESPONSE_MAX:.0f}"
WELLNESS_RESPONSE_RANGE = f"0-{WELLNESS_RESPONSE_MAX:.0f}"

STRESS_LABEL = f"Estrés ({WELLNESS_RESPONSE_RANGE})"
PAIN_LABEL = f"Dolor ({WELLNESS_RESPONSE_RANGE})"
SLEEP_LABEL = "Sueño (h)"

# Encabezados del Excel: el dato crudo no cambia, solo el rotulo con su escala.
WELLNESS_EXPORT_HEADERS = {
    "Sueno_hs": SLEEP_LABEL,
    "Estres": STRESS_LABEL,
    "Dolor": PAIN_LABEL,
    "Sueno_mean": "Sueño medio (h)",
    "Estres_mean": f"Estrés medio ({WELLNESS_RESPONSE_RANGE})",
    "Dolor_mean": f"Dolor medio ({WELLNESS_RESPONSE_RANGE})",
}
