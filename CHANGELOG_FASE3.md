# Changelog Fase 3

## 1. Problema inicial

Al entrar en Fase 3, la persistencia remota y el sync con Supabase tenian una duplicacion tecnica clara:

- configuracion de Supabase repetida o dispersa
- checks de habilitacion remota repartidos
- request helper remoto reutilizado de forma acoplada
- serializacion de datasets y evaluaciones duplicada
- operaciones concretas de carga y guardado remoto repartidas entre archivos
- definiciones legacy que seguian presentes aunque el runtime ya empezaba a usar una capa compartida

En la practica, esto generaba estos riesgos:

- posibilidad de drift entre la app principal y el gestor de historial
- mayor dificultad para cambiar o probar la capa remota sin tocar varias zonas
- riesgo de corregir una funcion vieja que ya no gobernaba el runtime
- mas costo de mantenimiento para cualquier ajuste de persistencia remota

## 2. Cambios realizados en Fase 3

### 3A: base remota compartida

Se centralizo en `modules/remote_store.py` la base comun del flujo remoto:

- `REMOTE_DATASET_KEYS`
- resolucion de secretos y variables de entorno
- configuracion de tablas remotas
- checks `supabase_dataset_store_enabled()` y `supabase_evaluations_enabled()`
- helper `_supabase_request(...)`

Ademas:

- `app.py` dejo de redefinir esa base como fuente principal
- `modules/history_manager.py` paso a depender de la misma capa compartida

Duplicacion eliminada realmente en 3A:

- ya no hay dos fuentes activas distintas para la configuracion base de Supabase
- ya no hay dos criterios activos distintos para decidir si el modo remoto esta habilitado
- ya no hay dos helpers activos distintos para construir requests REST a Supabase

### 3B: operaciones remotas concretas compartidas

Se movieron a `modules/remote_store.py` las operaciones remotas concretas que seguian repartidas:

- `dataset_df_to_remote_records(...)`
- `jump_df_to_db_records(...)`
- `save_remote_dataset(...)`
- `load_remote_dataset(...)`
- `save_remote_evaluations(...)`
- `load_remote_evaluations_frame(...)`
- `load_remote_evaluations(...)`

Ademas:

- `app.py` paso a usar estas implementaciones compartidas por alias
- `modules/history_manager.py` paso a usar la misma capa compartida para carga remota
- se agrego cobertura puntual en `tests/test_phase3_remote_store.py`

Duplicacion eliminada realmente en 3B:

- ya no quedan dos implementaciones activas distintas para serializar datasets remotos
- ya no quedan dos implementaciones activas distintas para serializar evaluaciones remotas
- ya no quedan dos caminos activos distintos para cargar datasets remotos
- ya no quedan dos caminos activos distintos para cargar evaluaciones remotas
- ya no quedan dos caminos activos distintos para hacer upsert remoto en los flujos cubiertos

### 3C: poda legacy segura

Se hizo una limpieza controlada de definiciones viejas:

- se elimino de `modules/history_manager.py` el bloque legacy remoto que ya no se usaba en runtime
- se marco en `app.py` que las definiciones legacy remotas de ese bloque quedan temporariamente solo como referencia, pero que el runtime usa `modules.remote_store`

Duplicacion eliminada o aclarada en 3C:

- en `modules/history_manager.py` se elimino duplicacion muerta
- en `app.py` se dejo explicitamente marcada la duplicacion legacy que todavia no conviene borrar sin una pasada mas amplia

## 3. Validaciones hechas

### Validacion de 3A

Se ejecuto:

```powershell
.\.venv\Scripts\python.exe -m py_compile app.py modules\remote_store.py modules\history_manager.py tests\test_phase3_remote_store.py
.\.venv\Scripts\python.exe -m unittest tests.test_phase3_remote_store tests.test_phase2_history tests.test_phase1_reporting
```

Resultado:

- compilacion correcta
- `8 tests OK`

### Validacion de 3B

Se ejecuto:

```powershell
.\.venv\Scripts\python.exe -m py_compile modules\remote_store.py modules\history_manager.py tests\test_phase3_remote_store.py app.py
.\.venv\Scripts\python.exe -m unittest tests.test_phase3_remote_store tests.test_phase2_history tests.test_phase1_reporting
```

Resultado:

- compilacion correcta
- `12 tests OK`

### Validacion de 3C

Se ejecuto:

```powershell
.\.venv\Scripts\python.exe -m py_compile app.py modules\history_manager.py modules\remote_store.py
.\.venv\Scripts\python.exe -m unittest tests.test_phase3_remote_store tests.test_phase2_history tests.test_phase1_reporting
```

Resultado:

- compilacion correcta
- `12 tests OK`

## 4. Riesgo tecnico y operativo que bajo

### Riesgo tecnico

- bajo el riesgo de drift entre implementaciones remotas equivalentes
- bajo el riesgo de tener contratos distintos de serializacion segun la pantalla o el modulo
- bajo el riesgo de tocar una copia vieja pensando que era la ruta activa
- bajo el costo de prueba y mantenimiento de la capa remota

### Riesgo operativo

- bajo el riesgo de que una sincronizacion remota se comporte distinto entre `app.py` y el gestor de historial
- bajo el riesgo de introducir regresiones silenciosas en guardado/carga remota por cambios en un solo lugar
- bajo el riesgo de soporte confuso al tener varias implementaciones aparentemente validas para el mismo flujo

## 5. Archivos tocados en Fase 3

- `app.py`
- `modules/history_manager.py`
- `modules/remote_store.py`
- `tests/test_phase3_remote_store.py`
- `CHANGELOG_FASE3.md`

## 6. Deuda pendiente

- `app.py` todavia conserva definiciones legacy remotas marcadas, no eliminadas
- `replace_remote_history(...)` sigue viviendo en `modules/history_manager.py`
- `rename_evaluation_athlete_remote(...)` sigue viviendo en `app.py`
- la app principal sigue concentrando demasiado contexto operativo
- no hay todavia pruebas end-to-end de UI para los flujos remotos

## 7. Riesgos que siguen existiendo

- algunas operaciones remotas siguen siendo destructivas a nivel dataset completo, aunque ahora la base compartida es mas clara
- una parte del flujo remoto activo sigue repartida entre `app.py`, `modules/history_manager.py` y `modules/remote_store.py`
- la deuda legacy en `app.py` sigue pudiendo confundir si no se completa la poda en una siguiente pasada controlada
- la disponibilidad real de Supabase sigue dependiendo de credenciales, conectividad y permisos del entorno

## 8. Siguiente paso recomendado

Hacer un paso 3D igual de controlado:

- mover solo las operaciones remotas activas que todavia quedan fuera de `modules.remote_store`
- priorizar `rename_evaluation_athlete_remote(...)` y la parte mas aislable de `replace_remote_history(...)`
- completar luego la eliminacion segura del bloque legacy remoto de `app.py`

El objetivo de ese siguiente paso no deberia ser redisenar la arquitectura, sino terminar de dejar una unica capa remota compartida y mas facil de validar.
