# Project Status Checkpoint

## 1. Estado inicial

Cuando arranco este bloque, el proyecto tenia una mezcla de problemas operativos y de consolidacion:

- entorno local no reproducible
- dependencia de `PYTHONPATH` manual en esta maquina
- acciones destructivas de historial sin backup previo
- exportaciones visuales sensibles a la version de `plotly` y `kaleido`
- poca claridad cuando Supabase no estaba configurado
- duplicacion activa en la capa remota
- definiciones legacy remotas conviviendo con la capa modular
- bug en `Vaciar dataset local` por repoblacion desde la ruta legacy

## 2. Estado actual

Hoy la app:

- corre de forma reproducible con `.venv`
- arranca con un comando unico y real
- funciona correctamente en modo local
- tiene gestion de historial con backup antes de acciones destructivas
- tiene la capa remota bastante mas consolidada
- mantiene exportaciones visuales en una combinacion de dependencias estable

Los flujos principales probados quedaron OK.

## 3. Fases realizadas

### Fase 1

- reconstruccion del entorno Python
- comando real de arranque
- documentacion minima de ejecucion alineada

### Fase 2

- backups y confirmaciones para historial destructivo
- estabilidad de `plotly` + `kaleido`
- claridad operativa cuando Supabase no esta configurado

### Fase 3A

- base compartida de persistencia remota en `modules/remote_store.py`

### Fase 3B

- centralizacion de operaciones remotas concretas en la misma capa

### Fase 3C

- poda legacy segura en `modules/history_manager.py`
- marcado explicito de legacy remoto en `app.py`

### Bugfix posterior

- correccion del flujo `Vaciar dataset local` para que no se repueble de inmediato desde `data/store`
- feedback de exito y backup visible tras rerun

## 4. Cambios principales

- entorno local reproducible
- startup limpio
- proteccion de historial con backup
- exportaciones visuales estabilizadas
- UI mas clara para modo local vs remoto
- menor duplicacion remota
- correccion del vaciado local de datasets
- documentacion de estado y operacion mucho mas clara

## 5. Validaciones manuales y automaticas

### Manuales

- arranque real de Streamlit
- chequeo de modo local
- revision del flujo de historial
- analisis de punta a punta del bug de vaciado local

### Automaticas

- `py_compile` sobre archivos tocados
- `tests.test_phase1_reporting`
- `tests.test_phase2_history`
- `tests.test_phase3_remote_store`

Resultados relevantes:

- historial y reporting: `3 tests OK`
- remoto + historial + reporting: `12 tests OK`
- bugfix de vaciado local: `4 tests OK` en `tests.test_phase2_history`

## 6. Bugs corregidos

- entorno no reproducible
- acciones destructivas sin snapshot previo
- incompatibilidad operativa conocida entre `plotly` y `kaleido`
- confusion de UI sobre estado de Supabase
- duplicacion activa en persistencia remota
- `Vaciar dataset local` sin efecto real por repoblacion legacy inmediata

## 7. Riesgos que bajaron

- menor riesgo de no poder correr la app en esta maquina
- menor riesgo de perder historial por error operativo
- menor riesgo de drift entre implementaciones remotas
- menor riesgo de romper exportes visuales por reinstalar versiones incompatibles
- menor riesgo de soporte confuso por coexistencia de varias rutas remotas
- menor riesgo de que vaciar un dataset local no tenga efecto real

## 8. Deuda tecnica pendiente

- `app.py` sigue siendo grande
- `modules/report_generator.py` sigue muy concentrado
- todavia quedan definiciones legacy remotas marcadas en `app.py`
- `replace_remote_history(...)` sigue en `modules/history_manager.py`
- `rename_evaluation_athlete_remote(...)` sigue en `app.py`
- no hay restauracion guiada de backups desde UI
- faltan pruebas end-to-end de UI

## 9. Siguiente paso recomendado

Hay dos caminos razonables:

- consolidacion tecnica: avanzar con un Fase 3D chico para terminar de mover operaciones remotas activas a `modules.remote_store`
- consolidacion operativa: sumar restauracion guiada de backups en `Gestion de Historial`

Si la prioridad es mantenimiento, recomiendo primero la consolidacion tecnica.
Si la prioridad es operacion diaria, recomiendo primero la restauracion guiada de backups.
