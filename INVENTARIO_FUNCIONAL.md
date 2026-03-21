# Inventario Funcional Actual

## Estado general

- La app real hoy vive casi toda en `app.py`.
- La navegación principal funcional está armada como tabs dentro de `app.py`: `Overview`, `Load Monitoring`, `Evaluaciones`, `Perfil Atleta`, `Team Dashboard` y `Reporte`.
- Los archivos subidos no se guardan en base de datos ni en disco. Se leen en memoria, se procesan y se guardan en `st.session_state` mientras dura la sesión.
- Hay una segunda navegación en `pages/`, pero hoy esas páginas son placeholders y no contienen la lógica real.

## Qué tiene hoy

- Carga manual de archivos desde sidebar.
- Procesamiento de datos Teambuildr.
- Procesamiento de evaluaciones físicas históricas.
- Procesamiento manual de tests de plataforma de fuerza: `CMJ`, `SJ`, `DJ`, `IMTP`.
- Cálculo de `sRPE`.
- Cálculo de `ACWR` clásico y `ACWR EWMA`.
- Cálculo de `Monotonía` y `Strain`.
- Cálculo de `Wellness_Score`.
- Cálculo de `EUR`.
- Cálculo de `DRI`.
- Cálculo de `Z-scores`.
- Cálculo de `NM_Profile`.
- Gráficos individuales y grupales.
- Exportación de reportes en Excel.
- Descarga de plantilla CSV para evaluaciones.

## Qué pasa cuando subís archivos

### 1. `RPE + Tiempo (questionnaire-report.xlsx / csv)`

- La app lee el archivo como bloques por atleta y filas por fecha.
- Toma la primera métrica como `RPE`.
- Toma la segunda métrica como `Duration_min`.
- Calcula `sRPE = RPE x Duration_min`.
- Guarda un DataFrame con `Date`, `Athlete`, `RPE`, `Duration_min` y `sRPE`.
- Después precalcula por atleta:
- `ACWR_Classic`
- `ACWR_EWMA`
- `Aguda_7d`
- `Cronica_28d`
- `EWMA_Aguda`
- `EWMA_Cronica`
- `Zona`
- `Monotonía`
- `Strain`

### 2. `Wellness 3Q (questionnaire-report_wellness.xlsx / csv)`

- La app lee el archivo con la misma lógica de bloques por atleta.
- Toma tres valores por fila:
- `Sueno_hs`
- `Estres`
- `Dolor`
- Calcula `Wellness_Score` como suma de esas tres variables.
- Guarda un DataFrame con `Date`, `Athlete`, `Sueno_hs`, `Estres`, `Dolor` y `Wellness_Score`.

### 3. `Completion Report (.csv)`

- La app espera columnas `Dates`, `Assigned` y `Completed`.
- Convierte `Dates` a fecha.
- Convierte `Assigned` y `Completed` a número.
- Calcula `Pct = Completed / Assigned x 100`.
- Guarda un DataFrame con la adherencia por fecha.

### 4. `Rep/Load Report (.csv)`

- La app espera columnas compatibles con:
- `Date`
- `Rep Count (Assigned)`
- `Rep Count (Completed)`
- `Load (Completed)`
- Renombra internamente a:
- `Reps_Assigned`
- `Reps_Completed`
- `Load_kg`
- Convierte esos valores a numéricos.
- Usa estos datos para métricas simples de volumen y para exportación.

### 5. `Raw Data Report - Workouts (.csv)`

- La app convierte `Assigned Date` a fecha.
- Convierte `Result` y `Reps` a numéricos.
- Calcula `Volume_Load = Result x Reps`.
- Mapea `Tags` a categorías internas como `Push H`, `Push V`, `Dom. Rodilla`, `Dom. Cadera`, `Plyo/Saltos`, etc.
- Usa ese archivo para el gráfico de `Volumen por Patrón de Movimiento`.

### 6. `Raw Data Report - Maxes (.csv)`

- La app convierte `Added Date` a fecha.
- Convierte `Max Value` a numérico.
- Arma `Athlete = First Name + Last Name`.
- Guarda el dataset.
- Hoy ese dataset entra al checklist y al reporte Excel.
- Hoy no tiene visualización conectada en la UI principal.

### 7. `Archivo del test` de plataforma de fuerza (`CMJ`, `SJ`, `DJ`, `IMTP`)

- La app lee el `.xlsx` transpuesto de la plataforma.
- Busca métricas por nombre exacto.
- Según el test, toma el mejor valor o el promedio de las repeticiones.
- Además guarda internamente las repeticiones por métrica.

`CMJ` extrae:

- `CMJ_cm`
- `CMJ_RSI`
- `CMJ_conc_ms`
- `CMJ_brake_ms`
- `CMJ_contraction_ms`
- `CMJ_peak_force_N`
- `CMJ_peak_power_W`
- `CMJ_asym_pct`
- `CMJ_brake_asym_pct`
- `BW_kg`
- `CMJ_flight_ms`

`SJ` extrae:

- `SJ_cm`
- `SJ_RSI`
- `SJ_conc_ms`
- `SJ_peak_force_N`
- `SJ_peak_power_W`
- `SJ_asym_pct`
- `BW_kg`
- `SJ_flight_ms`

`DJ` extrae:

- `DJ_cm`
- `DJ_tc_ms`
- `DRI`
- `DJ_asym_pct`
- `DJ_peak_force_N`
- `DJ_flight_ms`
- `DJ_force_L_N`
- `DJ_force_R_N`

`IMTP` extrae:

- `IMTP_N`
- `IMTP_avg_N`
- `RFD_50`
- `RFD_100`
- `RFD_150`
- `RFD_250`
- `IMTP_asym_pct`
- `IMTP_pretension`
- `IMTP_time_max_s`
- `IMTP_force_L_N`
- `IMTP_force_R_N`

Después, al presionar `PROCESAR TODO`, la app arma `jump_df` y calcula:

- `EUR`
- `DRI`
- `Z-scores`
- `NM_Profile`

### 8. `Planilla de evaluaciones (CSV o Excel DATOS)`

- La app acepta un CSV estándar o un Excel en formato `DATOS`.
- Normaliza nombres de columnas como `Jugador`, `Athlete`, `Fecha`, `Date`.
- Convierte `FECHA` a fecha.
- Convierte las columnas numéricas esperadas a valores numéricos.
- Calcula `Z-scores`.
- Guarda el resultado en `eval_df`.

Las columnas esperadas del módulo son:

- `JUGADOR`
- `FECHA`
- `CMJ_PF_N`
- `CMJ_RSI`
- `CMJ_cm`
- `SJ_PF_N`
- `SJ_asim_pct`
- `SJ_cm`
- `DJ_tc_ms`
- `DJ_cm`
- `DJ_RSI`
- `EUR`
- `IMTP_N`
- `IMTP_RFD100`
- `IMTP_RFD250`
- `Sprint_10m`
- `Sprint_20m`

## Qué muestra hoy cada módulo

### Overview

- Estado de carga de datasets: `RPE/sRPE`, `Wellness`, `Completion`, `Rep/Load`, `Raw Workouts`, `Maxes`, `Saltos/Eval`.
- Tabla rápida de última sesión por atleta con:
- `sRPE`
- `ACWR EWMA`
- `Zona`
- `Monotonía`
- `Strain`
- Gráfico de completion.
- Métricas resumidas de tonaje total y reps promedio si hay `Rep/Load`.

### Load Monitoring

- Selector de atleta.
- KPIs de:
- `sRPE última sesión`
- `RPE última sesión`
- `ACWR EWMA`
- `Monotonía`
- `Strain`
- Alertas por zona de ACWR.
- Alerta de monotonía alta.
- Gráfico combinado de `ACWR + sRPE diario`.
- Gráfico semanal de `Monotonía & Strain`.
- Gráfico histórico de wellness.
- Tabla de sesiones detalladas.
- Gráfico de `Volumen por Patrón de Movimiento` usando `Raw Workouts`.

### Evaluaciones

- Si no hay datos, muestra:
- mensaje para subir la planilla
- descarga de plantilla CSV
- tabla del formato esperado

- Si hay datos, muestra tres submódulos:

- `INDIVIDUAL`
- KPI cards con valor actual, delta vs anterior, mejor histórico y semáforo
- radar individual
- historial de saltos `CMJ / SJ / DJ`
- historial `DJ / RSI`
- historial `EUR`
- tabla histórica completa

- `GRUPAL`
- cuadrante grupal de clasificación
- gráfico `DJ vs RSI`
- heatmap de `Z-scores`
- mensaje de sprint deshabilitado

- `COMPARATIVA`
- barras grupales `SJ / CMJ / DJ`
- ranking grupal de última evaluación
- descarga de la tabla a Excel

### Perfil Atleta

- Lista unificada de atletas desde `jump_df`, `rpe_df` y `wellness_df`.
- Radar neuromuscular si hay datos de saltos en `jump_df`.
- Estado actual de `ACWR`.
- Promedio de `Wellness_Score` de los últimos 3 días.
- Tabla con KPIs de la evaluación más reciente.
- `NM_Profile`.
- Cuadrantes grupales si hay más de un atleta con datos de saltos.

### Team Dashboard

- Tabla grupal de carga con:
- `sRPE última sesión`
- `ACWR EWMA`
- `Zona`
- `Monotonía`
- `Strain`
- Cuadrante `CMJ x IMTP`.
- Cuadrante `DRI x SJ`.
- Heatmap grupal de `Z-scores`.
- Gráfico grupal de completion.

### Reporte

- Exporta un Excel.
- Permite incluir o excluir:
- `ACWR + sRPE`
- `Monotonía + Strain`
- `Wellness`
- `Evaluaciones de saltos`
- `Máximos`
- `Volumen por sesión`
- `Completion`
- Permite filtrar por atleta en parte del reporte.
- Muestra checklist de qué datasets faltan para un reporte completo.

## Cosas que se muestran pero hoy no funcionan bien o no están completas

### 1. Las páginas de `pages/` están visibles pero vacías

- `pages/01_load_monitoring.py`
- `pages/02_jump_evaluation.py`
- `pages/03_athlete_profile.py`
- `pages/04_team_dashboard.py`
- `pages/05_reports.py`
- Hoy sólo muestran un título y una línea de texto.
- No contienen la lógica real del producto.

### 2. El selector `Método ACWR` aparece pero no cambia nada

- La UI muestra `EWMA (recomendado)` y `Clásico 7:28`.
- El valor seleccionado no modifica los cálculos ni la visualización principal.
- El módulo sigue mostrando y usando `ACWR EWMA`.

### 3. El selector de `Evaluación` en el módulo individual aparece pero no se usa

- La UI deja elegir una fecha.
- Esa fecha no altera las KPI cards ni los gráficos.
- Los componentes siguen usando el último registro o todo el historial.

### 4. El gráfico de sprints está anunciado pero deshabilitado

- Existe una función para tendencia de sprints.
- En la UI se muestra el mensaje de que está temporalmente deshabilitado.
- Hoy no hay gráfico de sprints activo.

### 5. `Maxes` se puede subir pero no tiene dashboard visual conectado

- El archivo se procesa.
- El estado aparece como cargado.
- Puede entrar al reporte Excel.
- Existe una función `chart_maxes_trend`.
- Hoy no está conectada en ninguna tab.

### 6. La app promete PDF en algunos lugares, pero hoy sólo exporta Excel

- `pages/05_reports.py` dice `Descargá reportes en PDF`.
- `modules/report_generator.py` existe como stub para PDF.
- Hoy el producto real sólo genera Excel.

### 7. La data de evaluaciones está partida en dos mundos

- `eval_df` alimenta el módulo `Evaluaciones`.
- `jump_df` alimenta `Perfil Atleta`, `Team Dashboard` y la parte de saltos del `Reporte`.
- Si subís solo la planilla histórica de evaluaciones:
- funciona el tab `Evaluaciones`
- no se llenan automáticamente `Perfil Atleta`
- no se llena `Team Dashboard`
- no entra a `Reporte` como dataset de saltos

### 8. Los tests de plataforma de fuerza pisan `eval_df` en vez de integrarse de verdad

- La UI dice que se integran automáticamente al módulo analítico.
- Hoy, si cargás planilla histórica y además cargás tests manuales de plataforma, el código termina reemplazando `eval_df` por la versión derivada desde `jump_df`.
- No hay merge real entre historia previa y tests nuevos.

### 9. Hay inconsistencia de unidad en `EUR`

- La planilla histórica y la plantilla hablan de `EUR (CMJ/SJ ratio)`.
- Los datos de ejemplo usan `EUR` cercano a `1.0`.
- Los tests de plataforma calculan `EUR = (CMJ - SJ) / SJ x 100`.
- Eso genera mezcla entre `ratio` y `porcentaje`.
- Hoy eso puede distorsionar comparaciones, gráficos y z-scores.

### 10. El filtro por atleta del reporte es parcial

- Sí filtra:
- `ACWR`
- `Monotonía`
- `Wellness`
- `Evaluaciones_Saltos`

- No filtra:
- `Maximos_Ejercicios`
- `Volumen_Sesion`
- `Completion_Rate`

### 11. El gráfico de volumen por tags es sensible al formato del CSV

- La UI usa la columna `Name` para listar atletas.
- El parser de `Raw Workouts` no normaliza esa columna a una estructura estándar.
- Si el export cambia de nombre de columna, este gráfico puede romperse.

### 12. Los parsers son estrictos y dependen mucho del formato exacto

- `RPE/Wellness` depende del orden de las columnas dentro del questionnaire export.
- `Completion` depende de `Dates`, `Assigned`, `Completed`.
- `Rep/Load` depende de nombres exactos del export.
- `Raw Workouts` depende de columnas muy específicas.
- `Maxes` depende de `First Name`, `Last Name`, `Added Date`, `Max Value`.

## Funciones construidas pero hoy no conectadas

- `chart_maxes_trend`
- `chart_cmj_trend`
- `parse_jump_eval`
- `modules/report_generator.generate_report`
- `modules/strength_analysis.analyze_imtp`
- `modules/strength_analysis.calculate_e1rm`
- `charts/dashboard_charts.create_team_comparison`
- `charts/load_charts.plot_acwr_trend`
- `charts/load_charts.plot_srpe_trend`
- parte de `modules/*` y `charts/*` quedó como base de una modularización futura, pero la app actual no la usa

## Lo que falta para que el producto quede más sólido

- Unificar `eval_df` y `jump_df` en una sola fuente de verdad.
- Integrar tests nuevos con historia previa sin sobrescribir.
- Definir una única unidad oficial para `EUR` y migrar todo a eso.
- Hacer que el selector de `Método ACWR` realmente cambie KPI, zona y gráfico principal.
- Hacer que el selector de `Evaluación` realmente cargue la fecha elegida.
- Activar el módulo de sprints o esconderlo hasta que esté listo.
- Conectar visualmente el dataset de `Maxes`.
- Decidir si el producto final va a usar tabs internas, multipage o ambos, y eliminar la navegación duplicada.
- Reemplazar parsers rígidos por los loaders más robustos de `modules/data_loader.py` o consolidar en una sola implementación.
- Agregar persistencia real de sesión si se quiere conservar cargas entre usos.
- Implementar reportes PDF sólo si realmente son parte del roadmap.

## Prioridades recomendadas

- Prioridad alta: unificar evaluaciones, corregir `EUR`, arreglar `method_sel`, arreglar `fecha_sel`.
- Prioridad media: conectar `Maxes`, activar o remover sprints, robustecer parsers.
- Prioridad baja: limpiar módulos muertos, ordenar arquitectura `app.py` vs `pages/`.
