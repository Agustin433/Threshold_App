# config.py — Threshold S&C Configuration

# ── Colores del sistema ───────────────────────────────────────────────
COLORS = {
    "primary":    "#00C853",   # verde Threshold
    "warning":    "#FFD600",   # amarillo alerta
    "danger":     "#FF1744",   # rojo riesgo
    "neutral":    "#78909C",   # gris neutro
    "background": "#0D0D0D",   # fondo oscuro
    "surface":    "#1A1A2E",   # superficie card
    "text":       "#E8EAED",
}

# ── Umbrales ACWR (Gabbett 2016) ─────────────────────────────────────
ACWR_ZONES = {
    "subcarga":     (0.0,  0.80),
    "optimo":       (0.80, 1.30),
    "precaucion":   (1.30, 1.50),
    "alto_riesgo":  (1.50, 9.99),
}

# ── Umbrales CMJ desvío vs baseline ──────────────────────────────────
CMJ_ALERT_THRESHOLD = 5.0        # % desvío para alerta (McMahon et al.)
CMJ_WARNING_THRESHOLD = 3.0      # % desvío para warning

# ── Umbrales EUR (Balsalobre-Fernández) ──────────────────────────────
# EUR = (CMJ - SJ) / SJ × 100
EUR_REFERENCE = {
    "bajo":         (0,   10),   # predominio fuerza concéntrica pura
    "moderado":     (10,  20),   # uso moderado del CEA
    "alto":         (20,  30),   # buen uso del CEA/SSC
    "muy_alto":     (30, 100),   # dominancia reactiva
}

# ── Umbrales DRI/RSI ──────────────────────────────────────────────────
# DRI = jump_height_m / contact_time_s
DRI_REFERENCE = {
    "bajo":        (0.0,  0.9),
    "moderado":    (0.9,  1.5),
    "bueno":       (1.5,  2.0),
    "excelente":   (2.0,  9.9),
}

# ── Monotonía (Foster 2001) ───────────────────────────────────────────
MONOTONY_HIGH = 2.0    # > 2.0 = riesgo de sobreentrenamiento

# ── Columnas esperadas por reporte Teambuildr ─────────────────────────
TB_RPE_COLUMNS = ["Date", "Athlete", "Duration", "RPE", "WorkoutName"]
TB_WELLNESS_COLUMNS = ["Date", "Athlete", "Q1", "Q2", "Q3"]
TB_REPLOAD_COLUMNS = ["Date", "Athlete", "Exercise", "Sets", "Reps", "Load"]
TB_RAW_COLUMNS = ["Date", "Athlete", "Exercise", "Set", "Reps", "Load",
                  "ExternalID", "Tags"]

# ── Columnas de evaluación de saltos ─────────────────────────────────
JUMP_EVAL_COLUMNS = ["Date", "Athlete", "CMJ_cm", "SJ_cm",
                     "DJ_cm", "DJ_tc_ms", "IMTP_N"]