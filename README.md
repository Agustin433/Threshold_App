# Threshold S&C App

Aplicacion Streamlit para seguimiento de carga, wellness, evaluaciones de saltos y reportes operativos de Threshold S&C.

## Que hace hoy la app

- carga exports manuales de TeamBuildr desde el sidebar principal
- procesa `RPE + Tiempo`, `Wellness`, `Completion`, `Rep/Load`, `Raw Workouts` y `Maxes`
- consolida evaluaciones de plataforma de fuerza para `CMJ`, `SJ`, `DJ` e `IMTP`
- calcula `sRPE`, `ACWR`, `Monotonia`, `Strain`, `EUR`, `DRI`, z-scores y `NM_Profile`
- guarda historial local en `.local/store`
- permite gestion de historial local con filtros, descarga, borrado y vaciado con backup previo
- permite sincronizacion remota con Supabase si esta configurado
- exporta Excel y tiene una ruta de exportacion visual/PDF

## Estado actual

La app ya corre de forma reproducible en esta maquina y los flujos principales probados estan OK.

Flujos principales validados en este bloque:

- arranque local de la app
- carga y procesamiento local de datasets
- navegacion del dashboard principal y paginas secundarias
- gestion de historial local con backup
- exportacion Excel
- exportacion visual basada en Plotly/Kaleido

La sincronizacion con Supabase sigue siendo opcional y depende de credenciales validas.

## Como correrla

Desde la raiz del repo:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

No hace falta usar `PYTHONPATH` manual.

## Configuracion opcional

Para persistencia remota con Supabase:

```powershell
Copy-Item .streamlit\secrets.example.toml .streamlit\secrets.toml
```

Claves esperadas:

- `SUPABASE_URL`
- `SUPABASE_KEY`
- `SUPABASE_EVALUATIONS_TABLE`
- `SUPABASE_DATASETS_TABLE`

Si no configuras Supabase, la app sigue funcionando en modo local.

## Documentacion util

- `RUNBOOK.md`: guia operativa para levantar y revisar la app
- `PROJECT_STATUS_CHECKPOINT.md`: estado consolidado del proyecto
- `SMOKE_TEST_CHECKLIST.md`: checklist manual de validacion
- `CHANGELOG.md`: resumen acumulado de cambios
- `PROJECT_MAP.md`: mapa del codebase

## Bugs corregidos recientemente

- entorno de ejecucion no reproducible
- acciones destructivas de historial sin backup previo
- incompatibilidad operativa entre `plotly` y `kaleido`
- confusion de UI cuando Supabase no estaba configurado
- duplicacion activa en la capa de persistencia remota
- bug de `Vaciar dataset local` que podia repoblar el dataset desde la ruta legacy

## Deuda tecnica pendiente

- `app.py` sigue concentrando demasiada logica
- `modules/report_generator.py` sigue siendo grande y acoplado
- todavia quedan definiciones legacy remotas marcadas en `app.py`
- faltan pruebas end-to-end de UI
- la restauracion de backups de historial sigue siendo manual

## Proximo paso recomendado

La mejor continuacion hoy es una fase de consolidacion controlada de la capa remota:

- mover las operaciones remotas activas que todavia quedan fuera de `modules.remote_store`
- priorizar `rename_evaluation_athlete_remote(...)`
- evaluar la parte mas aislable de `replace_remote_history(...)`
- despues completar la poda segura del bloque legacy remoto de `app.py`

Si se prioriza operacion antes que arquitectura, la otra opcion fuerte es sumar restauracion guiada de backups desde la UI de historial.
