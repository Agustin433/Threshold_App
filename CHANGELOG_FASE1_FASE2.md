# Changelog Fase 1 y Fase 2

## 1. Contexto inicial

Al comenzar este ciclo, el proyecto tenia tres problemas operativos principales:

- la app no corria de forma limpia y reproducible en esta maquina
- habia acciones destructivas sobre historial sin resguardo previo
- las exportaciones visuales dependian de una ventana de versiones riesgosa entre `plotly` y `kaleido`
- cuando Supabase no estaba configurado, la UI no dejaba del todo claro que seguia funcionando solo en modo local

En la practica, eso se traducia en:

- necesidad de usar `PYTHONPATH` manual apuntando a `site-packages` del usuario
- `.venv` roto o no confiable para correr la app
- riesgo de borrar o sobrescribir historial sin backup
- riesgo de romper exportaciones estaticas al reinstalar dependencias
- confusion sobre si los datos estaban realmente sincronizados o solo guardados localmente

## 2. Cambios realizados

### Fase 1: entorno reproducible

Se resolvio el arranque limpio del proyecto:

- reconstruccion del `.venv` local del repo con Python 3.13
- instalacion de dependencias dentro del entorno del proyecto
- eliminacion de la necesidad de usar `PYTHONPATH` manual
- estandarizacion del comando real de arranque
- alineacion de documentacion minima de ejecucion

Problema resuelto:

- la app ya no depende del `site-packages` del usuario para arrancar
- el comando estandar para correrla es reproducible desde el repo

### Fase 2: cierre de criticos operativos

#### 2.1 Historial destructivo protegido

Se agrego proteccion minima y segura antes de acciones destructivas:

- backup automatico previo a borrar filas filtradas
- backup automatico previo a vaciar dataset local
- backup automatico previo a sobrescribir remoto con local
- backup automatico previo a reemplazar local desde remoto
- confirmacion explicita en UI para acciones destructivas
- mensaje visible de recuperacion con archivo y ruta del backup

Problema resuelto:

- ya no se ejecutan acciones destructivas sobre historial sin snapshot previo y sin confirmacion visible

#### 2.2 Exportaciones visuales estables

Se estabilizo la exportacion estatica de imagenes:

- fijacion de versiones compatibles de `plotly` y `kaleido`
- eliminacion del parametro deprecado `engine="kaleido"` en la exportacion de PNG
- prueba automatizada del helper de exportacion
- verificacion manual de exportacion real de bytes PNG

Problema resuelto:

- se evita reinstalar combinaciones incompatibles de `plotly` y `kaleido`
- la ruta de exportacion queda alineada con la API compatible actual de Plotly/Kaleido

#### 2.3 Claridad operativa de Supabase

Se mejoro la comunicacion de estado cuando Supabase no esta configurado:

- mensaje visible en sidebar para datasets TeamBuildr
- mensaje visible en sidebar para historial de evaluaciones
- mensaje claro en la pagina de gestion de historial
- explicacion de que sigue funcionando localmente y que no sincroniza

Problema resuelto:

- baja la confusion entre "guardado local" y "sincronizacion remota"

## 3. Validaciones hechas

### Entorno y arranque

- verificacion de `Python 3.13.3`
- creacion del `.venv` local del repo
- instalacion de dependencias con `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`
- arranque real de Streamlit con:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.headless true --server.port 8514
```

Resultado:

- la app levanto correctamente y publico URL local

### Compilacion

Se validaron compilaciones puntuales con `py_compile` sobre los archivos tocados.

### Historial

Se ejecuto:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_phase2_history
```

Resultado:

- `3 tests OK`

Incluye validacion de creacion de backup con nombre esperable y CSV recuperable.

### Exportaciones visuales

Se ejecuto:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_phase1_reporting
```

Resultado:

- `3 tests OK`

Ademas se verifico una exportacion real de PNG via `export_plotly_figure_png(...)`.

Resultado:

- exportacion correcta
- salida de `23706` bytes en la prueba manual

## 4. Riesgos operativos que bajaron

- bajo el riesgo de que la app no arranque por depender del entorno global del usuario
- bajo el riesgo de usar un comando de inicio incorrecto o incompleto
- bajo el riesgo de perder historial por vaciado o reemplazo sin backup previo
- bajo el riesgo de reinstalar una combinacion incompatible de `plotly` y `kaleido`
- bajo el riesgo de interpretar que los datos estaban en Supabase cuando en realidad solo estaban en local

## 5. Riesgos que siguen existiendo

- el restore de backups de historial sigue siendo manual; no hay boton de restauracion
- las operaciones remotas siguen siendo destructivas a nivel dataset completo
- la exportacion estatica sigue dependiendo de contar con Chrome o Chromium disponible
- en entornos muy restringidos, `kaleido` puede fallar por permisos del directorio temporal aunque las versiones sean correctas
- `app.py` y `modules/report_generator.py` siguen siendo archivos grandes con deuda tecnica
- el estado de Supabase es mas claro, pero no existe todavia una vista unica de salud/configuracion de persistencia

## 6. Archivos tocados en Fase 1 y Fase 2

### Fase 1

- `README.md`
- `RUNBOOK.md`
- `START_HERE.md`

### Fase 2

- `app.py`
- `requirements.txt`
- `modules/history_manager.py`
- `modules/report_generator.py`
- `pages/06_history_manager.py`
- `tests/test_phase1_reporting.py`
- `tests/test_phase2_history.py`

## 7. Proximo paso recomendado

Entrar en Fase 3 empezando por ordenar la capa de persistencia:

- centralizar en un servicio comun las operaciones locales y remotas de datasets/evaluaciones
- evitar que `app.py` y `pages/06_history_manager.py` repitan decisiones de estado o sincronizacion
- como mejora inmediata de alto valor, sumar restauracion guiada de backups de historial desde UI
