# Requirements Overview

Este documento explica las dependencias reales del proyecto, para que se usan y que falta declarar hoy.

## Dependencias declaradas en `requirements.txt`

### `streamlit`

- Framework principal de UI.
- Se usa en `app.py` y en todas las vistas de `pages/`.

### `pandas`

- Base del modelo de datos.
- Se usa para parsing, normalizacion, calculos, merge y exportes.

### `numpy`

- Soporte numerico para metricas derivadas y z-scores.

### `plotly`

- Visualizaciones interactivas.
- Se usa en `charts/` y en partes legacy todavia presentes en `app.py`.

### `openpyxl`

- Exportacion Excel.
- Tambien soporta lectura tabular en algunos casos.

## Dependencias de runtime que el codigo tambien necesita

### `Pillow`

- Se usa para cargar logos e iconos.
- Referencia principal en `app.py`.
- Sin `Pillow`, la app cae en un fallback para el icono, pero pierde parte del branding esperado.

### `reportlab`

- Se usa para la ruta "premium" de PDF visual.
- Referencia principal en `modules/report_generator.py`.
- Si no esta instalada, el generador cae en un PDF manual de fallback.

### `kaleido`

- Se usa para exportar graficos de Plotly a PNG antes de incrustarlos en PDF.
- Referencia principal en `modules/report_generator.py`.
- Sin `kaleido`, la exportacion visual del PDF queda limitada.

## Dependencias estandar de Python relevantes

El proyecto tambien usa bastante biblioteca estandar:

- `base64`
- `hashlib`
- `json`
- `os`
- `pathlib`
- `re`
- `urllib`
- `warnings`
- `xml.etree.ElementTree`
- `zipfile`
- `textwrap`
- `unicodedata`
- `io`
- `datetime`
- `difflib`
- `itertools`

## Estado real del entorno vs estado del repo

La auditoria se hizo principalmente a nivel de codigo y estructura.

Eso significa:

- `requirements.txt` ahora refleja el runtime realmente usado por la app principal.
- `scipy` se elimino porque no aparece referenciada en el codebase actual.
- Las exportaciones PDF/PNG mas completas siguen dependiendo de `reportlab` y `kaleido`.
- En un entorno limpio, `pip install -r requirements.txt` deberia dejar cubierto el flujo principal.

## Comando recomendado de instalacion hoy

```powershell
pip install -r requirements.txt
```

## Recomendacion

Conviene seguir distinguiendo explicitamente:

- dependencias core
- dependencias opcionales de exportacion
- dependencias solo de desarrollo
