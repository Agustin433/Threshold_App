# Backlog Priorizado - Threshold S&C

> Nota: este backlog sigue siendo util como roadmap, pero `PROJECT_MAP.md` y `RUNBOOK.md` describen mejor el estado operativo actual.

## Estado actual

- La app principal funciona desde `app.py`.
- La persistencia local guarda historial en `.local/store` y migra automaticamente desde `data/store` si hace falta.
- La ventana operativa visible carga las ultimas 6 semanas.
- Las evaluaciones trabajan con carga individual consolidada en `jump_df`.
- La app exporta Excel y un PDF ejecutivo basico.
- Las paginas secundarias ya muestran datos reales.

## Como leer este backlog

- `P0`: afecta estabilidad, claridad operativa o ingreso de datos.
- `P1`: mejora funcional importante del producto.
- `P2`: mejora valiosa, pero no bloqueante.
- `P3`: evolucion futura o capa premium.

## Backlog actual

| ID | Prioridad | Tiene hoy | Falta | Impacto | Archivos afectados |
|---|---|---|---|---|---|
| BL-01 | P0 | La app procesa y guarda datasets principales. | Corregir la promesa de formato en uploads de `RPE` y `Wellness`: hoy la UI acepta `.csv`, pero ese flujo esta pensado principalmente para `.xlsx`. | Alto: evita errores al cargar. | `app.py`, `modules/data_loader.py` |
| BL-02 | P0 | Los errores de carga mejoraron. | Mostrar validaciones mas precisas por archivo: columnas faltantes, formato esperado y motivo exacto de fallo. | Alto: reduce friccion operativa. | `app.py`, `modules/data_loader.py` |
| BL-03 | P0 | La UI ya esta preparada para branding real. | Integrar los assets oficiales reales en `assets/brand` y cerrar header, sidebar, portada y favicon con esos archivos. | Medio-alto: cierra identidad visual real. | `app.py`, `assets/brand/README.md`, `assets/brand/*` |
| BL-04 | P0 | La app compila y los flujos principales estan armados. | Hacer smoke test funcional real con archivos operativos para validar punta a punta uploads, graficos, reportes y persistencia. | Muy alto: separa "compila" de "esta estable". | `app.py`, `pages/*`, `modules/*` |
| BL-05 | P1 | Las evaluaciones individuales ya se consolidan y persisten. | Mejorar UX de carga de evaluaciones para ver mejor los tests pendientes antes de procesar todo. | Medio-alto: agiliza uso diario. | `app.py`, `modules/jump_analysis.py` |
| BL-06 | P1 | El reporte Excel ya sale con resumen e interpretacion. | Pulir estructura final del Excel: orden, nombres de hojas, formato y criterio de presentacion para terceros. | Medio-alto: mejora entregables. | `modules/report_generator.py`, `pages/05_reports.py` |
| BL-07 | P1 | Existe completion grupal y grafico de `% completed` global. | Hacer el `% completed` tambien individual, con selector de atleta y opcion `Todos`. Para eso primero hay que confirmar y preservar `Athlete` en el parser de completion si el export lo trae. | Alto: mejora mucho la lectura individual de adherencia y alinea completion con el resto de modulos. | `modules/data_loader.py`, `local_store.py`, `charts/load_charts.py`, `app.py`, `pages/04_team_dashboard.py`, `pages/05_reports.py` |
| BL-08 | P1 | Solo evaluaciones tienen opcion de persistencia remota. | Extender persistencia remota a `RPE`, `Wellness`, `Completion`, `Rep/Load`, `Raw` y `Maxes` si se quiere continuidad entre equipos/dispositivos. | Alto: clave para crecimiento multi-equipo. | `app.py`, `local_store.py` |
| BL-09 | P1 | Ya existe un PDF ejecutivo. | Llevar el PDF a un reporte visual real con mejor composicion y, mas adelante, graficos incrustados. | Alto: objetivo fuerte de producto. | `modules/report_generator.py`, `app.py` |
| BL-10 | P2 | Las paginas de `pages/` ya muestran datos reales. | Equipararlas mas al dashboard principal en profundidad visual y analitica. | Medio: mejora consistencia. | `pages/01_load_monitoring.py`, `pages/02_jump_evaluation.py`, `pages/03_athlete_profile.py`, `pages/04_team_dashboard.py`, `pages/05_reports.py` |
| BL-11 | P2 | La app esta bastante modularizada. | Limpiar codigo legacy remanente en `app.py` para dejarlo como orquestador y UI. | Medio: reduce deuda tecnica. | `app.py` |
| BL-12 | P2 | Los datos se guardan y vuelven a cargar. | Agregar gestion de historial desde UI: editar, borrar, auditar y revisar registros guardados. | Alto para operacion diaria. | `local_store.py`, `app.py` |
| BL-13 | P2 | La estetica general esta mejor encaminada. | Unificar mas tablas, charts, spacing y contenedores en todos los modulos para un look export-ready consistente. | Medio-alto. | `app.py`, `charts/load_charts.py`, `charts/dashboard_charts.py` |
| BL-14 | P3 | La app ya sirve como herramienta operativa local. | Agregar autenticacion, perfiles o separacion por equipos/clientes. | Medio-alto a futuro. | Arquitectura futura |

## Orden recomendado

1. BL-01
2. BL-02
3. BL-03
4. BL-04
5. BL-07
6. BL-05
7. BL-06
8. BL-08
9. BL-09
10. BL-10
11. BL-11
12. BL-12
13. BL-13

## Lectura rapida

- Lo mas urgente hoy es asegurar uploads, validaciones, branding real y estabilidad operativa.
- El `% completed` individual con opcion `Todos` entra como `P1` alto.
- No lo pongo en `P0` porque no rompe la app actual, pero si lo pondria antes que varias mejoras cosmeticas o de exportacion fina.
- Si el export de completion ya trae atleta, es una mejora directa y muy valiosa.
- Si no lo trae, primero hay que ajustar el tipo de reporte o cambiar el parser para capturarlo correctamente.
