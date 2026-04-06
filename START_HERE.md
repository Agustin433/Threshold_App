# Start Here

Guia unica para entender el proyecto, levantarlo localmente y decidir por donde empezar a trabajar.

No reemplaza por completo a `PROJECT_MAP.md`, `RUNBOOK.md` o `BACKLOG_PRIORIZADO.md`, pero los concentra en un punto de entrada mas practico.

## 1. Que es este repo hoy

Threshold S&C es una app en Streamlit para:

- cargar exports de TeamBuildr
- procesar `RPE`, `Wellness`, `Completion`, `Rep/Load`, `Raw Workouts` y `Maxes`
- consolidar evaluaciones de fuerza y salto (`CMJ`, `SJ`, `DJ`, `IMTP`)
- calcular metricas de carga y perfil neuromuscular
- persistir historial local en `.local/store`
- exportar Excel y una version de PDF con fallback

## 2. Mapa rapido del codebase

### Nucleo

- `app.py`: entrypoint principal, UI, sidebar, tabs, carga, sync y orquestacion general
- `local_store.py`: persistencia local, merge, deduplicacion, ventana operativa y atletas

### Modulos de negocio

- `modules/data_loader.py`: parsers de archivos TeamBuildr y evaluaciones
- `modules/load_monitoring.py`: `ACWR`, `Monotonia`, `Strain`
- `modules/jump_analysis.py`: `EUR`, `DRI`, z-scores y `NM_Profile`
- `modules/report_generator.py`: exportes, resumenes y PDF
- `modules/page_state.py`: bootstrap de estado para `pages/`

### Visualizacion

- `charts/load_charts.py`
- `charts/dashboard_charts.py`

### Vistas secundarias

- `pages/01_load_monitoring.py`
- `pages/02_jump_evaluation.py`
- `pages/03_athlete_profile.py`
- `pages/04_team_dashboard.py`
- `pages/05_reports.py`

## 3. Estado tecnico real

- La app corre desde `app.py`.
- `app.py` sigue siendo el archivo mas pesado del repo, con unas 4000 lineas.
- `modules/report_generator.py` tambien es grande, con mas de 2000 lineas.
- El proyecto ya tiene modularizacion util, pero todavia convive con logica legacy.
- Las `pages/` existen y funcionan, pero hoy son complementarias al dashboard principal.
- El smoke check actual compila el repo, pero no prueba un flujo funcional punta a punta.

## 4. Como levantar la app

Crear entorno virtual si hace falta:

```powershell
python -m venv .venv
```

Activarlo:

```powershell
.\.venv\Scripts\Activate.ps1
```

Instalar dependencias:

```powershell
pip install -r requirements.txt
```

Correr la app:

```powershell
python -m streamlit run app.py
```

Headless:

```powershell
python -m streamlit run app.py --server.headless true
```

Smoke test automatizado:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

## 5. Donde mirar primero si algo falla

- No arranca: `app.py`, `.streamlit/config.toml`, `requirements.txt`
- Falla la carga: `modules/data_loader.py`, `local_store.py`, `app.py`
- Falla el estado entre paginas: `modules/page_state.py`, `local_store.py`, `pages/`
- Falla el calculo de carga: `modules/load_monitoring.py`, `local_store.py`
- Falla el reporte: `modules/report_generator.py`

## 6. Regla practica para empezar a trabajar

No conviene arrancar por un refactor grande de `app.py`.

Primero hay que estabilizar la operacion real:

1. asegurar que los uploads aceptan exactamente los formatos correctos
2. mejorar mensajes de validacion y error
3. armar una prueba funcional repetible con datos reales o fixtures confiables
4. recien despues separar responsabilidades y limpiar deuda tecnica

## 7. Hoja de ruta recomendada

### Fase 0: baseline operativa

Objetivo: que el sistema sea predecible al cargar, procesar y exportar.

- Corregir la promesa de formato en uploads de `RPE` y `Wellness`
- Mostrar errores de validacion mas precisos por archivo
- Armar un smoke test funcional con archivos de ejemplo reales
- Confirmar que `.local/store` y la migracion desde `data/store` funcionan bien

Resultado esperado:

- cualquier persona puede levantar la app
- cargar archivos validos
- entender por que un archivo fallo
- repetir una validacion minima sin inspeccion manual profunda

### Fase 1: mejoras de producto con impacto rapido

Objetivo: mejorar el valor diario sin tocar arquitectura profunda.

- Agregar `% completed` individual con selector de atleta y opcion `Todos`
- Mejorar UX de carga de evaluaciones
- Pulir estructura final del Excel exportado
- Cerrar branding real en header, sidebar, portada y favicon

Resultado esperado:

- mejor lectura individual
- menos friccion operativa
- entregables mas presentables

### Fase 2: continuidad y escalado

Objetivo: que el sistema sea mas util entre sesiones, equipos o dispositivos.

- Extender persistencia remota a datasets ademas de evaluaciones
- Mejorar PDF ejecutivo real
- Equiparar mas las `pages/` con el dashboard principal
- Empezar gestion de historial desde UI

### Fase 3: mantenimiento y refactor

Objetivo: bajar deuda tecnica sin romper flujos ya estabilizados.

- Reducir `app.py` a orquestacion y UI
- Separar responsabilidades en `modules/report_generator.py`
- Mover logica repetida a helpers o modulos dedicados
- Dejar contratos de datos mas explicitos entre parser, store y vistas

## 8. Orden concreto para empezar esta semana

1. Validar contrato real de uploads en `app.py` y `modules/data_loader.py`
2. Mejorar mensajes de error de carga
3. Preparar un set de archivos de prueba y hacer smoke test funcional
4. Resolver `% completed` individual
5. Recien ahi abrir la limpieza fuerte de `app.py`

## 9. Cuando abrir los otros docs

- Leer `PROJECT_MAP.md` si vas a tocar arquitectura o repartir trabajo por archivos
- Leer `RUNBOOK.md` si necesitas levantar la app o diagnosticar fallos
- Leer `BACKLOG_PRIORIZADO.md` si vas a planificar entregas o priorizar mejoras

## 10. Decision recomendada

Si hubiera que elegir un unico documento para arrancar a trabajar, este deberia ser ese documento.

Y si hubiera que elegir un primer frente tecnico, hoy conviene empezar por estabilidad de ingestion y validacion, no por refactor grande.
