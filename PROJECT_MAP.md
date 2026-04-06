# Project Map

Mapa practico del codebase actual y de sus responsabilidades reales.

## Punto de entrada

### `app.py`

Responsabilidad actual:

- Entry point principal.
- Configura Streamlit, branding y tabs.
- Hidrata datos locales y remotos al inicio.
- Maneja sidebar, uploads, procesamiento y notificaciones.
- Orquesta visualizaciones y exportes.

Observaciones:

- Es el archivo mas cargado del proyecto.
- Todavia conserva logica legacy duplicada aunque parte de la "source of truth" ya vive en modulos compartidos.

## Persistencia y estado

### `local_store.py`

Responsabilidad:

- Define datasets soportados.
- Guarda y relee historial local en `.local/store` por defecto.
- Mergea y deduplica filas nuevas con historial previo.
- Mantiene ventana activa de 6 semanas.
- Construye modelos de carga derivados.
- Mantiene registro y correccion de nombres de atletas.

Es uno de los modulos mas importantes del sistema.

Observacion:

- Si existe historial viejo en `data/store`, se migra automaticamente al nuevo store local.

### `modules/page_state.py`

Responsabilidad:

- Bootstrap de `st.session_state` para las paginas secundarias.
- Carga estado reciente desde `local_store.py`.

## Parsing e ingestion

### `modules/data_loader.py`

Responsabilidad:

- Lee exports `.xlsx` de TeamBuildr para `RPE` y `Wellness`.
- Lee CSVs de `Completion`, `Rep/Load`, `Raw Workouts` y `Maxes`.
- Lee `.xlsx` de plataforma de fuerza para `CMJ`, `SJ`, `DJ` e `IMTP`.
- Normaliza columnas y tipos.

Es el parser vivo mas importante del proyecto.

## Calculo y analisis

### `modules/load_monitoring.py`

Responsabilidad:

- Calculo de `ACWR`.
- Calculo de `Monotonia`.
- Calculo de `Strain`.

### `modules/jump_analysis.py`

Responsabilidad:

- Normalizacion de `jump_df`.
- Recalcula `EUR`, `DRI`, z-scores y `NM_Profile`.
- Consolida registros individuales por atleta y fecha.

## Reportes

### `modules/report_generator.py`

Responsabilidad:

- Construye resumen ejecutivo.
- Construye hojas para Excel.
- Genera interpretacion por audiencia.
- Intenta generar PDF visual y tiene fallback.

Observaciones:

- Es el segundo archivo mas pesado del repo.
- Ya no conserva las redefiniciones mas peligrosas que estaban pisando funciones en tiempo de import.
- Mezcla logica de negocio, presentacion y exportacion.

## Charts reutilizables

### `charts/load_charts.py`

Responsabilidad:

- `ACWR`
- `Monotonia/Strain`
- `Wellness`
- `Volumen por tag`
- tendencia de maximos

### `charts/dashboard_charts.py`

Responsabilidad:

- radar neuromuscular
- cuadrantes
- tendencia de CMJ
- completion

## Paginas secundarias

### `pages/01_load_monitoring.py`

- Vista simplificada de monitoreo de carga.

### `pages/02_jump_evaluation.py`

- Vista simplificada de evaluaciones individuales.

### `pages/03_athlete_profile.py`

- Vista simplificada de perfil de atleta.

### `pages/04_team_dashboard.py`

- Vista simplificada del dashboard grupal.

### `pages/05_reports.py`

- Vista simplificada de exportacion de reportes.

Observacion general sobre `pages/`:

- Hoy no reemplazan al dashboard principal.
- Funcionan mas como accesos secundarios apoyados en el mismo estado local.

## Configuracion y soporte

### `.streamlit/config.toml`

- Tema visual de Streamlit.

### `.streamlit/secrets.example.toml`

- Plantilla para Supabase.

Observacion:

- El ejemplo actual ya esta sanitizado y sirve solo como plantilla.

## Datos y assets

### `.local/store/`

Responsabilidad:

- Historial local persistido de datasets.

Observacion:

- `data/store/` queda como ruta legacy de migracion automatica.

Archivos tipicos:

- `rpe_history.csv`
- `wellness_history.csv`
- `completion_history.csv`
- `rep_load_history.csv`
- `raw_workouts_history.csv`
- `maxes_history.csv`
- `evaluations_history.csv`
- `athletes.csv`

### `assets/brand/`

Responsabilidad:

- Logos y assets visuales.

Estado actual:

- Ya contiene archivos PNG de marca.

## SQL y soporte externo

### `supabase_evaluations_schema.sql`

- Esquema para persistencia de evaluaciones.

### `supabase_dataset_store_schema.sql`

- Esquema para persistencia generica de datasets TeamBuildr.

## Documentacion auxiliar del repo

### `.github/workflows/smoke-check.yml`

- Smoke check minimo del repo.
- Instala dependencias y compila el codebase Python activo.

### `INVENTARIO_FUNCIONAL.md`

- Inventario funcional previo.

Observacion:

- Tiene partes que ya no reflejan exactamente el estado real actual del sistema.

### `BACKLOG_PRIORIZADO.md`

- Backlog y prioridades.

Observacion:

- Util como hoja de ruta, pero no reemplaza inspeccion tecnica del codigo real.

## Lectura rapida de responsabilidades

- UI y flujo principal: `app.py`
- Persistencia local y ventana operativa: `local_store.py`
- Parsing: `modules/data_loader.py`
- Calculo carga: `modules/load_monitoring.py`
- Calculo evaluaciones: `modules/jump_analysis.py`
- Estado para paginas: `modules/page_state.py`
- Reportes: `modules/report_generator.py`
- Charts reutilizables vivos: `charts/load_charts.py`, `charts/dashboard_charts.py`
- Validacion automatizada minima: `.github/workflows/smoke-check.yml`
