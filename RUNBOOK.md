# Runbook

Guia operativa para correr la app, validar lo basico y ubicar rapido los puntos de falla mas probables.

## 1. Requisitos previos

- Windows + PowerShell
- Python 3.13 validado en esta maquina
- acceso a la raiz del repo

## 2. Preparacion del entorno

Crear el entorno virtual:

```powershell
py -3.13 -m venv .venv
```

Instalar dependencias:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

La app ya no requiere `PYTHONPATH` manual para funcionar.

## 3. Comando exacto para correr la app

Comando recomendado y verificado:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Version headless util para checks rapidos:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.headless true
```

## 4. Persistencia local

La persistencia local vive por defecto en:

```text
.local/store
```

Si queres usar otra carpeta:

```powershell
$env:THRESHOLD_STORE_DIR = "C:\ruta\privada\threshold-store"
```

Notas importantes:

- `data/store` queda como ruta legacy
- si existe historial legacy, la app puede migrarlo a `.local/store`
- el flujo `Vaciar dataset local` ya fue corregido para que el dataset quede realmente vacio sin repoblarse inmediatamente

## 5. Configuracion opcional de Supabase

Crear el archivo de secretos:

```powershell
Copy-Item .streamlit\secrets.example.toml .streamlit\secrets.toml
```

Completar:

- `SUPABASE_URL`
- `SUPABASE_KEY`
- `SUPABASE_EVALUATIONS_TABLE`
- `SUPABASE_DATASETS_TABLE`

Si Supabase no esta configurado:

- la app sigue funcionando localmente
- los dashboards siguen funcionando
- la gestion de historial local sigue funcionando
- lo que no esta disponible es la sincronizacion remota

## 5b. Login obligatorio (OIDC con Google)

La app no muestra ni carga datos sin login. Falla cerrada: si falta la
seccion `[auth]` o `ALLOWED_EMAILS` en `.streamlit/secrets.toml`, no entra
nadie. Motivo: la app usa la `service_role` key de Supabase, que ignora RLS,
asi que el login es la unica barrera entre los datos de los atletas y
cualquiera que tenga la URL.

Configurar una vez en Google Cloud Console (https://console.cloud.google.com):

1. Crear (o elegir) un proyecto.
2. `APIs & Services -> OAuth consent screen`: tipo External, completar nombre
   de la app y email de soporte. En modo Testing, agregar en "Test users" los
   mismos emails que vayan en `ALLOWED_EMAILS`.
3. `APIs & Services -> Credentials -> Create credentials -> OAuth client ID`,
   tipo "Web application".
4. En "Authorized redirect URIs" agregar, tal cual:
   - `http://localhost:8501/oauth2callback` (uso local)
   - `https://<url-de-la-app-publicada>/oauth2callback` (si esta publicada)
5. Copiar `client_id` y `client_secret` a la seccion `[auth]` de
   `.streamlit/secrets.toml` (ver `secrets.example.toml`).
6. Generar `cookie_secret`:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

7. Completar `ALLOWED_EMAILS` con los emails que pueden entrar.

Si la app esta publicada (por ejemplo Streamlit Community Cloud), el mismo
contenido va en la configuracion de secrets de la plataforma, con
`redirect_uri` apuntando a la URL publicada.

Solo para desarrollo en tu propia maquina se puede apagar el login con
`THRESHOLD_AUTH_DISABLED = true` en `secrets.toml`. Nunca en una app publicada.

## 6. Que deberias ver si arranca bien

- Streamlit abre `app.py`
- aparece el sidebar con branding y carga de archivos
- si no hay datos, la app sigue usable en estado vacio
- si hay datos en `.local/store`, la app los hidrata al inicio
- la pagina `pages/06_history_manager.py` permite revisar historial local

## 7. Flujos validados en este bloque

Validados manual o funcionalmente durante esta etapa:

- arranque local de la app
- carga y procesamiento local
- visualizacion del dashboard principal
- gestion de historial local con backup
- exportacion Excel
- exportacion visual basada en Plotly/Kaleido

Validados con cobertura automatica puntual:

- helpers de reporting
- backups y reemplazo de historial
- capa remota compartida
- fix de vaciado local sin repoblacion legacy inmediata

Para una pasada operativa completa, usar `SMOKE_TEST_CHECKLIST.md`.

## 8. Smoke test rapido recomendado

1. Correr `.\.venv\Scripts\python.exe -m streamlit run app.py`.
2. Confirmar que la UI abre.
3. Cargar al menos un archivo de ejemplo.
4. Procesar datos.
5. Confirmar que aparecen tablas y metricas.
6. Entrar a `Gestion de Historial`.
7. Probar descarga CSV.
8. Si hace falta, probar `Vaciar dataset local` sobre un dataset de prueba y verificar que queda en 0 filas.
9. Probar exportacion Excel.
10. Si el entorno lo permite, probar exportacion visual/PDF.

## 9. Fallos comunes

### `ModuleNotFoundError: No module named 'streamlit'`

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### `ModuleNotFoundError: No module named 'PIL'`

```powershell
.\.venv\Scripts\python.exe -m pip install Pillow
```

### `ModuleNotFoundError: No module named 'reportlab'`

Impacto:

- el PDF visual puede fallar

### `ModuleNotFoundError: No module named 'kaleido'`

Impacto:

- la exportacion de imagenes de Plotly puede fallar

### `pyo3_runtime.PanicException` o `ModuleNotFoundError: No module named '_cffi_backend'` al correr los tests

Pasa al instalar `requirements.txt` en un entorno Linux/CI limpio: `pypdf`
depende de `cryptography`, que a su vez depende de la extension nativa
`cffi`. Si `cffi` no quedo instalado correctamente, la coleccion de tests
de PDF (`tests/test_athlete_pdf_report.py`, `tests/test_client_pdf_report.py`,
`tests/test_professional_pdf_report.py`) se corta entera al importar.

No es un bug de la app, es una dependencia nativa que a veces no se instala
sola. Solucion:

```bash
pip install --force-reinstall cffi
```

Despues de eso, `pip install -r requirements.txt` y los tests corren normal.
En Windows con el flujo de `RUNBOOK.md` (venv + pip install de este mismo
archivo) esto no suele aparecer; es mas frecuente en un entorno Linux/CI
recien creado.

### La app arranca pero no aparecen datos

Revisar:

- `.local/store`
- el parser correspondiente
- si los datos quedan dentro de la ventana operativa

### La sincronizacion con Supabase no funciona

Revisar:

- `.streamlit/secrets.toml`
- conectividad
- tablas configuradas

### `Vaciar dataset local` no deja el dataset en 0 filas

El flujo ya fue corregido. Si volviera a aparecer:

- revisar `local_store.py`
- revisar si hay escritura externa sobre `.local/store`
- revisar que el dataset probado sea realmente el seleccionado en `Gestion de Historial`

## 10. Archivos clave para diagnostico

- `app.py`
- `local_store.py`
- `modules/data_loader.py`
- `modules/history_manager.py`
- `modules/remote_store.py`
- `modules/report_generator.py`
- `pages/06_history_manager.py`

## 11. Deuda tecnica vigente

- `app.py` sigue siendo pesado
- `modules/report_generator.py` sigue concentrando demasiadas responsabilidades
- todavia no hay restauracion guiada de backups desde UI
- faltan pruebas end-to-end de UI
