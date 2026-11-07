"""Textos de faltante y proximos pasos de los reportes, en un solo lugar.

Regla de uso:
- PDF profe: muestra todos los avisos de faltante (es su trabajo auditar el dato).
- PDF atleta/cliente y dashboard del atleta: una seccion sin datos evaluables
  no ocupa lugar ni dice lo que falta; se convierte, como mucho, en un item de
  "Proximos pasos" (maximo 2), escrito en positivo y accionable.
"""

from __future__ import annotations

# ── Faltantes (PDF profe y tablas tecnicas) ──────────────────────────────
MISSING_GENERIC = "Faltan datos"
MISSING_NOT_REGISTERED = "Todavía no registrado"
MISSING_PENDING_EVALUATION = "Pendiente de evaluación"
MISSING_DATA_NOT_AVAILABLE = "Dato todavía no disponible"
MISSING_REFERENCE = "Falta completar esta referencia"
MISSING_LOAD_NOT_EVALUABLE = "No evaluable"

# ── Proximos pasos (atleta / cliente) ────────────────────────────────────
NEXT_STEP_RPE = "rpe"
NEXT_STEP_WELLNESS = "wellness"
NEXT_STEP_FIRST_COMPARISON = "first_comparison"
NEXT_STEP_REEVALUATE = "reevaluate"
# Avisos de IMTP que antes ocupaban el "Foco del proximo bloque" (PR H).
NEXT_STEP_IMTP_REPEAT = "imtp_repeat"
NEXT_STEP_IMTP_PREVIOUS_PROTOCOL = "imtp_previous_protocol"

NEXT_STEPS_MAX = 2

NEXT_STEP_TEXT: dict[str, dict[str, str]] = {
    NEXT_STEP_FIRST_COMPARISON: {
        "atleta": "Repetí la evaluación en las próximas semanas: con una segunda medición ya podemos mostrarte cuánto mejoraste.",
        "cliente": "Repetí la evaluación en las próximas semanas: con una segunda medición ya podemos mostrarte tu progreso.",
    },
    NEXT_STEP_REEVALUATE: {
        "atleta": "Coordiná una nueva evaluación: con tu medición actual vamos a ver cuánto cambiaste desde la última.",
        "cliente": "Coordiná una nueva evaluación: con tu medición actual vamos a ver tu progreso desde la última.",
    },
    NEXT_STEP_IMTP_REPEAT: {
        "atleta": "Repetí el IMTP en la próxima evaluación: así tenés una referencia propia de fuerza máxima con el protocolo actual.",
        "cliente": "Repetí la medición de fuerza máxima en la próxima evaluación: así tenés una referencia propia para comparar.",
    },
    NEXT_STEP_IMTP_PREVIOUS_PROTOCOL: {
        "atleta": "Tu última medición de IMTP es con el protocolo anterior: en la próxima evaluación tomamos una nueva referencia.",
        "cliente": "Tu última medición de fuerza máxima es con el protocolo anterior: en la próxima evaluación tomamos una nueva referencia.",
    },
    NEXT_STEP_RPE: {
        "atleta": "Registrá tu RPE al terminar cada sesión: con 3 por semana ya podemos leer tu carga.",
        "cliente": "Registrá cómo te sentiste al terminar cada sesión: con 3 por semana ya podemos leer cómo venís con la carga.",
    },
    NEXT_STEP_WELLNESS: {
        "atleta": "Completá el cuestionario de bienestar al menos 3 días por semana: así podemos leer cómo venís recuperando.",
        "cliente": "Completá el cuestionario de bienestar al menos 3 días por semana: así podemos ver cómo venís recuperando.",
    },
}

# Orden de prioridad: primero lo que destraba una comparacion, despues el
# registro diario.
NEXT_STEP_PRIORITY = (
    NEXT_STEP_FIRST_COMPARISON,
    NEXT_STEP_REEVALUATE,
    NEXT_STEP_IMTP_PREVIOUS_PROTOCOL,
    NEXT_STEP_IMTP_REPEAT,
    NEXT_STEP_RPE,
    NEXT_STEP_WELLNESS,
)


def next_step_lines(keys: list[str] | tuple[str, ...], audience: str) -> list[str]:
    """Hasta NEXT_STEPS_MAX textos, en orden de prioridad y sin repetir."""
    audience_key = "cliente" if str(audience).strip().lower() == "cliente" else "atleta"
    wanted = set(keys)
    ordered = [key for key in NEXT_STEP_PRIORITY if key in wanted]
    return [NEXT_STEP_TEXT[key][audience_key] for key in ordered][:NEXT_STEPS_MAX]


# ── Frases que no van en el PDF atleta/cliente ───────────────────────────
# Quedan en el PDF profe. Se usan en los tests como lista negra.
ATHLETE_FORBIDDEN_PHRASES = (
    "sin patrón definido",
    "sin patron definido",
    "confianza de lectura",
    "asimetría",
    "asimetria",
    "tiempo al pico",
    "el radar acompaña la lectura",
    "el gráfico acompaña la lectura",
    "el foco no cambia la etiqueta",
    "no evaluable",
    "todavía no registrado",
    "dato todavía no disponible",
)
