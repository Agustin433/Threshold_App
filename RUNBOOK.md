# Runbook

Runbook operativo para levantar la app localmente y resolver los fallos mas probables.

## 1. Requisitos previos

- Python 3.13 recomendado y validado en esta maquina.
- PowerShell en Windows.
- Acceso al directorio del proyecto.

## 2. Preparacion del entorno

Crear el entorno virtual del proyecto:

```powershell
py -3.13 -m venv .venv
```

Instalar dependencias declaradas sin depender de activacion manual:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Activacion opcional en PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

La persistencia local se guarda por defecto en `.local/store`.

Si queres usar otra carpeta:

```powershell
$env:THRESHOLD_STORE_DIR = "C:\ruta\privada\threshold-store"
```

## 3. Configuracion opcional de Supabase

Copiar el ejemplo:

```powershell
Copy-Item .streamlit\secrets.example.toml .streamlit\secrets.toml
```

Editar `.streamlit\secrets.toml` si se quiere persistencia remota.

Claves usadas por la app:

- `SUPABASE_URL`
- `SUPABASE_KEY`
- `SUPABASE_EVALUATIONS_TABLE`
- `SUPABASE_DATASETS_TABLE`

Si no configuras Supabase, la app sigue funcionando en modo local.

## 4. Comando exacto para correr la app

Comando recomendado y verificado desde la raiz del proyecto:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Version headless util para pruebas:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.headless true
```

Si activaste el entorno antes, tambien funciona:

```powershell
python -m streamlit run app.py
```

## 5. Que deberias ver si arranca bien

- Streamlit levanta la app principal con tabs.
- Sidebar con branding y zona de carga de archivos.
- Sin datos cargados, la app muestra estado vacio pero usable.
- Si existen datos en `.local/store`, la app hidrata estado local al inicio.
- Si solo existe historial viejo en `data/store`, la app lo migra automaticamente.

## 6. Primeros archivos a revisar si algo falla

### Si no arranca la app

Revisar en este orden:

- `app.py`
- `.streamlit/config.toml`
- `requirements.txt`
- `README.md`

### Si falla la carga de archivos

Revisar:

- `modules/data_loader.py`
- `local_store.py`
- el archivo subido

### Si falla el estado entre paginas

Revisar:

- `modules/page_state.py`
- `local_store.py`
- `pages/*.py`

### Si fallan los calculos de carga

Revisar:

- `modules/load_monitoring.py`
- `local_store.py`
- `app.py`

### Si fallan las evaluaciones

Revisar:

- `modules/data_loader.py`
- `modules/jump_analysis.py`
- `app.py`

### Si falla el reporte

Revisar:

- `modules/report_generator.py`
- `requirements.txt`
- si estan instalados `reportlab` y `kaleido`

## 7. Fallos comunes y como resolverlos

### Error: `ModuleNotFoundError: No module named 'streamlit'`

Solucion:

```powershell
pip install -r requirements.txt
```

### Error: `ModuleNotFoundError: No module named 'PIL'`

Solucion:

```powershell
pip install Pillow
```

### Error: `ModuleNotFoundError: No module named 'reportlab'`

Impacto:

- El PDF visual no funciona completo.

Solucion:

```powershell
pip install reportlab
```

### Error: `ModuleNotFoundError: No module named 'kaleido'`

Impacto:

- La exportacion de graficos a imagen no funciona.

Solucion:

```powershell
pip install kaleido
```

### Fallo al sincronizar con Supabase

Revisar:

- `.streamlit/secrets.toml`
- conectividad
- tablas creadas segun:
  - `supabase_evaluations_schema.sql`
  - `supabase_dataset_store_schema.sql`

### Los datos no aparecen aunque la app corre

Revisar:

- `.local/store`
- si el parser produjo filas validas
- si el dataset cae dentro de la ventana activa de 6 semanas

### El reporte sale raro o incompleto

Revisar:

- si hay suficientes datos cargados
- `modules/report_generator.py`
- si faltan dependencias opcionales

## 8. Smoke test minimo recomendado

1. Correr `streamlit run app.py`.
2. Verificar que abre la UI principal.
3. Cargar un archivo de ejemplo por tipo.
4. Presionar `PROCESAR TODO`.
5. Verificar tabs principales.
6. Descargar Excel.
7. Probar PDF.
8. Si usas Supabase, probar sincronizacion manual.
9. Revisar `pages/06_history_manager.py` para confirmar filtros, descarga y push/pull de historial.

Si queres una validacion automatizada del repo, usar tambien el workflow `.github/workflows/smoke-check.yml`.

Smoke test automatizado local:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

## 9. Observaciones operativas

- La persistencia local usa CSV en `.local/store`.
- `data/store` queda como ruta legacy de migracion.
- La app principal es la experiencia mas completa; `pages/` son vistas secundarias.
- `pages/06_history_manager.py` es la vista recomendada para auditar o recortar historial sin tocar los CSV a mano.
- `app.py` es grande y mezcla UI con orquestacion y parte del acceso a datos.
- Si algo falla, casi siempre el primer triangulo de revision es:
  - `app.py`
  - `modules/data_loader.py`
  - `local_store.py`
