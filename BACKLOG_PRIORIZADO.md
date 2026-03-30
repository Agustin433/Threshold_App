# Backlog Priorizado - Threshold S&C

## Estado Base Actual

- La app principal funciona desde `app.py`.
- La persistencia local ya existe y guarda historial en `data/store`.
- La ventana activa visible ya está limitada a las últimas 6 semanas.
- Las evaluaciones ya trabajan con carga individual consolidada en `jump_df`.
- La app ya exporta Excel, pero todavía no exporta reportes visuales.
- La app ya usa nombres persistidos de atletas, pero todavía necesita más limpieza estructural.

## Cómo Leer Este Backlog

- `P0`: deuda o riesgo que conviene resolver primero porque afecta estabilidad, mantenimiento o consistencia de datos.
- `P1`: mejora estructural importante para que la app crezca bien.
- `P2`: mejora funcional valiosa, pero no bloqueante.
- `P3`: evolución futura o capa premium.

## Backlog Prioritario

| ID | Prioridad | Tiene hoy | Falta | Impacto | Archivos afectados |
|---|---|---|---|---|---|
| BL-01 | P0 | La app procesa y muestra datos correctamente en la mayoría de los flujos. | Eliminar funciones duplicadas en `app.py` para parsers, `EUR`, `NM_Profile`, `Raw Workouts`, `Maxes` y algunos charts. | Baja riesgo de inconsistencias y facilita mantener la app. | `app.py` |
| BL-02 | P0 | `jump_df` es la fuente activa de evaluaciones. | Dejar documentado y limpio que `jump_df` es la única fuente de verdad, removiendo restos legacy del modelo viejo. | Evita volver a partir evaluaciones en dos lógicas distintas. | `app.py`, `INVENTARIO_FUNCIONAL.md` |
| BL-03 | P0 | La app ya tolera varios CSV con fallback de encoding. | Unificar toda la validación de uploads y devolver errores claros por archivo, columna faltante y formato esperado. | Reduce errores al subir archivos y mejora soporte operativo. | `app.py` |
| BL-04 | P0 | Los datos de TeamBuildr se guardan localmente. | Mostrar en UI qué fecha máxima tiene cada dataset y qué ventana de datos quedó activa tras procesar. | Hace más transparente qué está viendo realmente el usuario. | `app.py`, `pages/01_load_monitoring.py`, `pages/04_team_dashboard.py`, `pages/05_reports.py` |
| BL-05 | P0 | La app ya usa lista persistida de atletas para evaluaciones. | Permitir revisar y corregir nombres duplicados o mal escritos desde una UI simple de mantenimiento. | Evita padrón sucio y errores por variantes de nombres. | `app.py`, `local_store.py` |
| BL-06 | P0 | Existe sistema visual nuevo y carga de branding preparada. | Conectar los assets oficiales reales en `assets/brand` y verificar header, sidebar, favicon y portada con esos archivos. | Cierra el branding de forma correcta y definitiva. | `app.py`, `assets/brand/README.md`, `assets/brand/*` |
| BL-07 | P1 | La persistencia local ya está separada en `local_store.py`. | Extraer parsers de archivos a un módulo propio para que `app.py` deje de concentrar carga, validación y lógica. | Mejora muchísimo mantenibilidad y pruebas. | `app.py`, `modules/` o nueva carpeta `services/` |
| BL-08 | P1 | `app.py` contiene lógica de negocio, charts y render. | Separar cálculos de carga, evaluaciones y reportes en módulos dedicados. | Permite crecer sin romper otras áreas. | `app.py`, `local_store.py`, `modules/` o nueva carpeta `services/` |
| BL-09 | P1 | Los charts están funcionales en `app.py`. | Extraer charts a módulos reutilizables y dejar `app.py` solo como orquestador de pantalla. | Facilita reutilizar vistas en tabs, `pages` y futura exportación. | `app.py`, `charts/` |
| BL-10 | P1 | Las páginas de `pages/` ya no son placeholders. | Unificar las vistas secundarias con las funciones de render del dashboard principal para evitar duplicación. | Reduce deuda y mantiene consistencia visual y funcional. | `app.py`, `pages/01_load_monitoring.py`, `pages/02_jump_evaluation.py`, `pages/03_athlete_profile.py`, `pages/04_team_dashboard.py`, `pages/05_reports.py` |
| BL-11 | P1 | Hay exportación Excel con datasets útiles. | Diseñar una estructura de bloques exportables reales: portada, resumen, tablas, gráficos y focos de intervención. | Es la base para PDF o reporte visual profesional. | `app.py`, nueva capa `reports/` o `export/` |
| BL-12 | P1 | Solo evaluaciones tienen opción de Supabase. | Decidir si TeamBuildr también va a persistirse remoto y, si sí, replicar el patrón de `save/load` para RPE, wellness, completion, rep/load, raw y maxes. | Permite continuidad entre equipos o dispositivos. | `app.py`, `local_store.py`, esquema SQL futuro |
| BL-13 | P1 | La UI muestra estados generales de datasets. | Agregar una tabla de auditoría de historial por dataset: registros, atletas, fecha mínima, fecha máxima y última actualización. | Ayuda mucho a control operativo y revisión de carga. | `app.py`, `local_store.py` |
| BL-14 | P1 | La app muestra datos y exporta Excel. | Agregar interpretación automática breve por módulo: carga, wellness, evaluación y próximos focos. | Aumenta valor profesional del reporte sin cambiar el dato base. | `app.py` |
| BL-15 | P2 | Overview, Load, Perfil, Team y Reporte ya existen. | Crear una vista de “historial completo / últimas 6 semanas” con selector global o por módulo. | Da flexibilidad sin perder foco operativo. | `app.py`, `local_store.py`, `pages/*` |
| BL-16 | P2 | El perfil del atleta integra carga, wellness y evaluación. | Enriquecer el perfil con tendencias cruzadas entre ACWR, wellness y salto más reciente. | Mejora lectura individual de fatiga y rendimiento. | `app.py` |
| BL-17 | P2 | El reporte exporta hojas de datos. | Agregar una hoja resumen ejecutiva con KPIs clave por atleta o equipo. | Hace el Excel más presentable y útil para compartir. | `app.py` |
| BL-18 | P2 | Se pueden cargar evaluaciones manualmente una por una. | Permitir carga múltiple o batch de varios archivos de plataforma en una sola operación. | Ahorra mucho tiempo operativo cuando hay varios atletas. | `app.py` |
| BL-19 | P2 | Existe padrón persistido de atletas. | Permitir alta manual de atleta nuevo sin depender primero de una carga de archivo. | Ordena mejor el flujo inicial de uso. | `app.py`, `local_store.py` |
| BL-20 | P2 | La estética general ya está bastante mejor orientada. | Llevar el layout a modo realmente “export-ready”: bloques con tamaños, paddings y jerarquía estables para PDF. | Prepara la transición a reportes visuales. | `app.py`, `.streamlit/config.toml` |
| BL-21 | P3 | La app funciona como herramienta local operativa. | Agregar autenticación, perfiles de usuario o acceso por clientes/equipos. | Abre camino a una versión más profesional o comercial. | Arquitectura futura |
| BL-22 | P3 | La app exporta datos. | Generar reportes PDF con identidad visual Threshold y secciones cerradas por módulo. | Es la evolución natural del producto actual. | Nueva capa de exportación |
| BL-23 | P3 | Hay visualización de datos históricos recientes. | Agregar comparativas entre microciclos, mesociclos o bloques de entrenamiento. | Mejora análisis longitudinal avanzado. | `app.py`, `local_store.py` |

## Orden Recomendado de Ejecución

1. BL-01
2. BL-03
3. BL-04
4. BL-05
5. BL-06
6. BL-07
7. BL-08
8. BL-09
9. BL-10
10. BL-11
11. BL-12

## Siguiente Sprint Recomendado

### Sprint 1 - Estabilidad y claridad operativa

| Prioridad | Item | Objetivo concreto |
|---|---|---|
| P0 | BL-01 | Limpiar duplicados peligrosos en `app.py`. |
| P0 | BL-03 | Mejorar validación y mensajes de error de uploads. |
| P0 | BL-04 | Mostrar fecha y ventana activa de cada dataset en UI. |
| P0 | BL-05 | Crear control básico de nombres duplicados o inconsistentes. |
| P0 | BL-06 | Conectar assets oficiales reales de marca. |

### Sprint 2 - Modularización real

| Prioridad | Item | Objetivo concreto |
|---|---|---|
| P1 | BL-07 | Extraer parsers. |
| P1 | BL-08 | Extraer lógica de negocio. |
| P1 | BL-09 | Extraer charts. |
| P1 | BL-10 | Unificar `pages` con el dashboard principal. |

### Sprint 3 - Producto exportable

| Prioridad | Item | Objetivo concreto |
|---|---|---|
| P1 | BL-11 | Diseñar bloques exportables reales. |
| P1 | BL-14 | Agregar interpretación breve por módulo. |
| P2 | BL-17 | Crear hoja ejecutiva en Excel. |
| P2 | BL-20 | Ajustar layout export-ready. |
| P3 | BL-22 | Pasar a PDF visual. |

## Definición de Terminado por Etapa

### Etapa 1 - Limpieza crítica

- `app.py` deja de tener lógica duplicada peligrosa.
- Los errores de carga indican exactamente qué archivo falló y por qué.
- La UI muestra claramente qué datos están activos y de qué período.

### Etapa 2 - Arquitectura

- `app.py` queda como capa de composición y UI.
- Parsers, cálculos y charts viven en módulos separados.
- `pages/` reutiliza la misma lógica que el dashboard principal.

### Etapa 3 - Reporte profesional

- La app exporta bloques claros y consistentes.
- La lectura visual funciona tanto en pantalla como en documento.
- El sistema queda listo para un generador PDF posterior.
