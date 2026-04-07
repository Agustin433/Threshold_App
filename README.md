# Threshold S&C App

Aplicacion Streamlit para seguimiento de carga, wellness, evaluaciones de saltos y generacion de reportes para Threshold S&C.

## Que hace hoy

- Carga manual de exports de TeamBuildr desde el sidebar principal.
- Procesa `RPE + Tiempo`, `Wellness`, `Completion`, `Rep/Load`, `Raw Workouts` y `Maxes`.
- Consolida evaluaciones individuales de plataforma de fuerza para `CMJ`, `SJ`, `DJ` e `IMTP`.
- Calcula `sRPE`, `ACWR`, `Monotonia`, `Strain`, `EUR`, `DRI`, z-scores y `NM_Profile`.
- Guarda historial local en `.local/store`.
- Puede sincronizar datasets y evaluaciones con Supabase si se configura.
- Exporta Excel y tiene una ruta de PDF visual con fallback.

## Estado actual del proyecto

- El punto de entrada real es `app.py`.
- `app.py` concentra gran parte de la UI y todavia conserva bastante logica legacy.
- Hay modulos compartidos reales en `modules/` y `charts/` que ya son la base mas sana del proyecto.
- Las paginas de `pages/` existen y muestran datos reales, pero son vistas simplificadas respecto del dashboard principal.
- La app funciona como herramienta local operativa, pero todavia no esta del todo limpia para mantenimiento o despliegue prolijo sin ajustes.

## Flujo general

1. `app.py` arranca Streamlit y configura branding, estado y tabs.
2. El usuario sube archivos desde el sidebar.
3. Los parsers de `modules/data_loader.py` convierten archivos a DataFrames normalizados.
4. `local_store.py` mergea y persiste datasets en `.local/store` por defecto.
5. `modules/load_monitoring.py` y `modules/jump_analysis.py` calculan metricas derivadas.
6. `charts/` renderiza visualizaciones reutilizables.
7. `modules/report_generator.py` arma resumenes y exportaciones.

## Estructura importante

- `app.py`: entrypoint principal, sidebar, tabs, sync y orquestacion general.
- `local_store.py`: persistencia local CSV, merge, deduplicacion, ventana operativa y registro de atletas.
- `modules/data_loader.py`: parsers de TeamBuildr y plataforma de fuerza.
- `modules/jump_analysis.py`: normalizacion y metricas de evaluaciones.
- `modules/load_monitoring.py`: ACWR, Monotonia y Strain.
- `modules/page_state.py`: bootstrap de estado para `pages/`.
- `modules/report_generator.py`: resumenes, hojas Excel y PDF.
- `charts/`: charts reutilizables.
- `pages/`: vistas secundarias simplificadas.
- `.streamlit/`: tema y ejemplo de secretos.
- `.local/store/`: historial local persistido por defecto.
- `data/store/`: ruta legacy que se migra automaticamente si existe.

## Dependencias

Dependencias declaradas hoy en `requirements.txt`:

- `streamlit`
- `pandas`
- `numpy`
- `plotly`
- `openpyxl`
- `Pillow`
- `reportlab`
- `kaleido`

Esas tres ultimas cubren branding con imagenes y exportacion de reportes visuales.

## Como correrla

Ver `RUNBOOK.md` para los pasos exactos.

Comando principal:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

## Validacion minima

- Hay un smoke check automatizado en `.github/workflows/smoke-check.yml`.
- Ese flujo instala dependencias y compila `app.py`, `local_store.py`, `modules/`, `charts/` y `pages/`.
- Sirve como validacion rapida para compartir el repo o revisar cambios antes de desplegar.

## Configuracion opcional

Para sincronizacion con Supabase, crear `.streamlit/secrets.toml` a partir de `.streamlit/secrets.example.toml`.

Claves esperadas:

- `SUPABASE_URL`
- `SUPABASE_KEY`
- `SUPABASE_EVALUATIONS_TABLE`
- `SUPABASE_DATASETS_TABLE`

Para cambiar la carpeta de persistencia local, definir `THRESHOLD_STORE_DIR`.

## Limitaciones conocidas

- `app.py` y `modules/report_generator.py` son grandes y tienen deuda tecnica.
- Aunque ya se podaron stubs y redefiniciones claras, todavia convive codigo legacy con la version modular.
- Aunque `requirements.txt` ya cubre el runtime principal, el modulo de reportes sigue teniendo deuda tecnica.
- El store local ya no apunta por defecto a una carpeta versionada del repo; usa `.local/store` y migra desde `data/store` si encuentra historial legacy.
- El README original era minimo; este archivo refleja mejor el estado real actual.

## Archivos recomendados para seguir leyendo

- `PROJECT_MAP.md`
- `RUNBOOK.md`
- `REQUIREMENTS_OVERVIEW.md`
- `BACKLOG_PRIORIZADO.md`
