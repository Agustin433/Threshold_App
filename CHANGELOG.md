# Changelog

Resumen acumulado del trabajo de estabilizacion y consolidacion hecho hasta este checkpoint.

## 2026-04-07 - Consolidacion documental

Se actualizaron o crearon los documentos principales del proyecto para reflejar el estado actual:

- `README.md`
- `RUNBOOK.md`
- `PROJECT_STATUS_CHECKPOINT.md`
- `SMOKE_TEST_CHECKLIST.md`
- `CHANGELOG.md`

Objetivo:

- dejar una fuente clara de verdad sobre operacion, validacion, estado actual, bugs corregidos y proximo paso recomendado

## 2026-04-07 - Fase 3 y bugfix de historial local

### Fase 3A

- se centralizo la base compartida de persistencia remota en `modules/remote_store.py`
- se unificaron configuracion, checks de habilitacion y request helper

### Fase 3B

- se movieron a `modules/remote_store.py` las operaciones remotas concretas mas duplicadas
- `app.py` y `modules/history_manager.py` pasaron a usar la capa compartida

### Fase 3C

- se elimino duplicacion legacy muerta en `modules/history_manager.py`
- se marco explicitamente el legacy remoto que todavia queda en `app.py`

### Bugfix puntual

- se corrigio `Vaciar dataset local` para que un dataset vaciado no se repueble inmediatamente desde `data/store`
- se mejoro el feedback de exito y backup para que sobreviva al rerun

Impacto:

- menos duplicacion activa en persistencia remota
- menos riesgo de drift entre rutas remotas
- historial local mas confiable

## 2026-04-06 / 2026-04-07 - Fase 1 y Fase 2

### Fase 1

- entorno local reproducible con `.venv`
- comando real y estable para correr la app
- eliminacion de la dependencia de `PYTHONPATH` manual

### Fase 2

- backups y confirmaciones previas para acciones destructivas del historial
- estabilidad de exportaciones visuales con `plotly==6.6.0` y `kaleido==1.2.0`
- mensajes claros cuando Supabase no esta configurado y la app queda en modo local

Impacto:

- la app corre de forma mucho mas confiable
- bajo el riesgo operativo de perdida de historial
- bajo el riesgo de confundir persistencia local con sincronizacion remota

## Validaciones registradas

- compilaciones puntuales con `py_compile`
- `tests.test_phase1_reporting`
- `tests.test_phase2_history`
- `tests.test_phase3_remote_store`
- arranque real de Streamlit
- verificacion de exportacion visual

## Deuda pendiente principal

- seguir consolidando la capa remota
- bajar el peso de `app.py`
- bajar el peso de `modules/report_generator.py`
- sumar restauracion guiada de backups desde la UI
- agregar pruebas end-to-end de UI

## Proximo paso recomendado

Continuar con una fase de consolidacion controlada, no de nuevas features:

- cerrar la deuda remota restante en `app.py` y `modules/history_manager.py`
- o, si se prioriza operacion, sumar restauracion guiada de backups en historial

Para mayor detalle por bloque:

- `CHANGELOG_FASE1_FASE2.md`
- `CHANGELOG_FASE3.md`
