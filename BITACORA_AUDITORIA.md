# Bitácora de la auditoría — Threshold S&C (sep–oct 2026)

Este documento resume qué se cambió en la app, por qué se cambió, qué decidiste vos y qué queda pendiente. Cada bloque cita su commit en `main`.

---

## 1. Punto de partida

Se pidió una auditoría completa de la app: bugs, pendientes, cálculos, estética, reruns y exportaciones (sobre todo el PDF). Se trabajó por fases y cada una se mergeó directo a `main`.

---

## 2. Fase 0–4: estabilidad, datos y PDF

| Qué | Por qué | Commit |
|---|---|---|
| El DRI histórico ya no se borra en cada recálculo. La altura de caída del DJ queda en 30 cm por defecto y 40 cm para Christian Heredia y Agustín Esterman. | Si faltaba la altura de caída, el DRI quedaba en NaN y se perdía. La excepción de 40 cm la confirmaste vos. | `6b309f8` |
| PDF: tildes con WinAnsiEncoding, errores con log en vez de fallar en silencio y mojibake reparado en las 4 audiencias. | Los PDF salían con caracteres rotos o vacíos sin ningún aviso. | `9ca27eb` |
| Supabase: upsert antes de delete, RLS, service-role, y perfil y notas sincronizados en remoto. | Evita perder datos si una escritura falla a mitad de camino. | `03ae82e` |
| Fix del KeyError en Team Dashboard cuando no había evaluaciones. | Error en vivo en producción. | `3ec630a` |
| Se eliminaron 8 funciones duplicadas que no se usaban en `report_generator.py`. | Las copias muertas ya divergían del código vivo. | `a67e574` |
| Importador del formulario de admisión (Google Forms) a Perfil de Atleta. | 31 atletas cargados; altura en metros corregida a cm. | `4fcedc6` |
| `_json_safe_value` serializaba los booleanos como 0/1. | En Python, `bool` es subclase de `int`. | `aa29f2f` |
| Selector de atleta unificado en Load. | Había selectores duplicados. | `8321fde` |
| La escritura a Supabase ahora va en lotes de 500. | El Raw Workouts completo desaparecía después de un redeploy. Confirmaste: "ya funciona". | `c1d970a` |

---

## 3. Evaluaciones de plataforma de fuerza

- **Repeticiones fallidas (mistrigger):** una rep fallida (vuelo menor a 100 ms o salto menor a 3 cm) podía quedar como la "mejor" en CMJ, SJ o DJ. Ahora se descarta antes de agregar las reps (`2a37a8d`).
- **Métricas que se perdían:** se recuperaron 11 métricas de CMJ (RFD propulsivo y de frenado, rigidez de aterrizaje, velocidad de despegue, eficiencia, fuerza izquierda/derecha por fase) y 5 de SJ (aterrizaje, asimetría, estabilización, impulso relativo y velocidad de despegue). El parser las leía y las descartaba (`ea7ab01`, `d5dfb62`). Las columnas SQL nuevas están en `supabase_evaluations_schema.sql`.
- **Fuentes de archivo:**
  - **Valkyria Trainer** (sistema viejo, sin soporte): los exports son genuinos y se verificaron contra archivos reales (SERGIO, Carlos Falivene, Carlos Palazzo).
  - **Involution Trainer** (sistema nuevo): necesita suscripción paga. Decidiste pagar un mes para bajar los Excel.
  - Los xlsx transcritos por IA a partir de capturas (Paulina Brito, Mariano Burgos) se descartaron: no son confiables.

---

## 4. Auditoría del reporte profesional (Mariano Díaz Romero)

### 4.1 Diagnóstico
- **"1 sesión" en el PDF:** no era un error de cálculo, era la etiqueta. El número contaba días con sRPE en una sola semana, no sesiones entrenadas. Se renombró a "Sesiones con sRPE (semana)" (`e9d73d1`).
- **Hallazgos críticos de tu auditoría:**
  1. El reporte emitía una zona ACWR "Óptimo" con cobertura roja.
  2. La monotonía de 0.41 era un artefacto aritmético.
  3. El wellness no se solapaba con la semana de carga.
  4. El ACWR no era verificable.
  5. Había texto plantilla que contradecía los datos.
  6. El sueño quedaba escondido en el puntaje compuesto.
  7. Había inferencias hechas desde datos faltantes.
  8. "Contenido entrenado" mezclaba unidades no comparables.
  9. El semáforo salía negro en el PDF.

### 4.2 Primera tanda de arreglos (`d4585c3`)
- La fila "Semana analizada" pasó a la tarjeta de Wellness. El wellness score no se clasifica con menos de 5 días de registro.
- La monotonía y el strain no se muestran con menos de 4 sesiones con sRPE en la semana.
- "Wellness" pasó a llamarse "Wellness/sRPE". Ese porcentaje es sobre días con sRPE, no sobre la ventana completa.
- En "Exposición del bloque", un estímulo con dosis desconocida ya no gana el puesto de "menor exposición".
- Sin evaluación de referencia, el reporte ya no dice "Mantener el perfil actual".
- Se quitó el emoji del semáforo: la fuente del PDF no lo soporta y salía como un cuadrado negro.
- **Error propio corregido después:** el filtro de cobertura de esta tanda (sRPE en menos del 70% de los días) usaba días calendario como base. Un atleta que entrena 3 veces por semana y reporta todo nunca supera ~43%, así que bloqueaba a casi cualquiera. Se reemplazó en la sección 5.

---

## 5. Modelo de carga: "no reportó" ≠ "no entrenó"

**Problema de fondo:** cualquier día sin sRPE contaba como carga 0. En el gimnasio los atletas entrenan pero no siempre reportan, así que las métricas medían los huecos de registro, no la carga. En una simulación con ~25% de cumplimiento, el modelo viejo dio 1.52 "Alto riesgo". En el PDF real de Mariano el mismo problema dio 0.98 "Óptimo".

**Supuesto confirmado:** lo asignado está en el Completion Report, así que el Raw Workouts trae solo lo realizado. Por eso sirve como registro de sesiones entrenadas.

| Qué | Commit |
|---|---|
| **ACWR diario (`calc_acwr`).** Cada día se clasifica como *registrado* (tiene sRPE), *sin_registro* (entrenó según Raw Workouts pero sin sRPE) o *descanso* (0 real). Las sesiones faltantes se completan con la mediana de las sesiones reportadas por el propio atleta en los 28 días previos; ese valor solo entra al cálculo del ACWR, y `sRPE_diario` sigue siendo solo lo reportado. El ACWR no se muestra si más del 30% de las sesiones de 28 días o más del 34% de las de 7 días no tienen sRPE, si hay menos de 28 días de historia (antes arrancaba en 1.0 "Óptimo" por construcción) o si no hay carga crónica (antes daba 0, "Subcarga"). La monotonía y el strain no se calculan en semanas con sesiones sin sRPE. El dashboard y el PDF usan el último día entrenado y muestran el motivo cuando no hay ACWR. Los nombres se cruzan sin importar tildes ni mayúsculas. | `f41649d` |
| **Cobertura de sRPE:** ahora es sesiones con sRPE ÷ sesiones realizadas. Sin Raw Workouts del atleta se mantiene la base de días calendario, aclarada en el texto. La portada del PDF muestra, por ejemplo, "sRPE 33% de sesiones (6/18)". | `352137e` |
| **ACWR semanal (1:4) y variación semanal.** El resumen semanal suma sesiones realizadas, sesiones sin sRPE y la carga del modelo. Las semanas entrenadas sin ningún sRPE ya no se borran; antes se borraban y la carga crónica pasaba a usar otras semanas. La variación solo se calcula entre semanas consecutivas y comparables. El gráfico apila la carga reportada y la estimada. El "−54.8%" de Mariano era exactamente este caso. | `d082cef` |
| **Panel Decision.** Riesgo, variación, wellness+carga y ranking usan `compare_weekly_load` y marcan "No comparable" cuando corresponde. En el ranking, "Sesiones" pasó a contar las sesiones realizadas, no las reportadas. | `b60df16` |

**Umbrales elegidos (decisión propia, no de la literatura):**
- 30% de sesiones sin sRPE en la ventana crónica de 28 días.
- 34% en la ventana aguda de 7 días.
- 34% en la semana, para monotonía y variación.
- Mediana individual de 28 días para completar las sesiones faltantes.
- 28 días mínimos de historia.

Se pueden calibrar con datos reales si bloquean demasiado.

**Lectura de fondo:** arreglar el cálculo no hace que el ACWR prediga lesiones (Impellizzeri et al. 2020; Lolli et al. 2019). Lo que se logró es que el número deje de mentir. El cuello de botella ahora es la adherencia al RPE en el piso del gimnasio, no el código.

---

## 5b. Contenido entrenado (decisiones del entrenador, oct/2026)

| Decisión | Implementación |
|---|---|
| **Volumen de fuerza: series + tonelaje.** Las series son la métrica comparable entre patrones. El tonelaje (kg×rep) queda como dato secundario, nunca para comparar patrones. | `add_strength_detail_columns` en `data_loader`. El Raw Workouts trae una fila por serie (la clave de deduplicación incluye `Set Number`); si una fila trae `Sets` agregado, se usa ese valor. Se cuentan también las series con peso corporal. |
| **Desglose por patrón completo:** dominante de cadera/rodilla, empuje H/V, tracción H/V, saltos con carga, accesorios MMII/MMSS, cuello y sin patrón. | El patrón sale primero del tag (el patrón principal gana sobre el de postura: "Stance_Split\|Dominante de Rodilla" cuenta como rodilla). Si no hay tag de patrón, se infiere del nombre con palabras clave conservadoras; si tampoco, queda "Sin patrón" y no se asigna a ninguna región. El PDF suma la línea "tren inferior N series · tren superior M series". |
| **Copenhagen → prehab, y también aductores y Nordic** ("isquio preventivo en general"). | `EXERCISE_CATEGORY_OVERRIDES` clasifica por nombre del ejercicio, por encima del tag. Para revertir un caso basta con sacar su palabra clave de la lista. |
| **Isométricos separados de Core / anti-rotación.** | El PDF y el gráfico de Load ahora tienen filas separadas. Antes un Pallof contaba como "isométrico". |
| **Ranking entre estímulos solo por sesiones.** | Las dosis vienen en unidades no comparables y ya no se usan para desempatar. Si hay empate en el mínimo, no se nombra un "menor" o se nombran todos los empatados. |

**Supuesto a confirmar con un archivo real:** que el Raw Workouts sigue trayendo una fila por serie.

---

## 6. Referencias citadas

Son de memoria: verificar DOI/PMID antes de citarlas.

- Foster C et al. 2001. J Strength Cond Res 15(1):109–115. sRPE, monotonía y strain.
- Williams S et al. 2017. Br J Sports Med 51:209–210. EWMA para ACWR.
- Lolli L et al. 2019. Br J Sports Med 53:921–922. Acoplamiento matemático en el ACWR.
- Impellizzeri FM et al. 2020. Int J Sports Physiol Perform 15(6):907–913. Problemas conceptuales del ACWR.
- Benson LC et al. 2021. J Sports Sci Med 20(2):188–196. Métodos para completar datos de carga faltantes. Es la cita con más dudas.

---

## 7. Pendiente

### Puntos de la auditoría que necesitan tu criterio
1. ~~Contenido entrenado~~ y ~~clasificación de ejercicios~~: hechos (ver 5b).
2. **Wellness por ítems:** la dirección de las escalas es ambigua y el sueño queda escondido en el puntaje compuesto. *Es el bloque que sigue.*

### Pendientes menores
- Zonas de referencia para monotonía y strain, y definición de DSI/DRI dentro del reporte.
- Texto repetido: "Faltan datos para generar una interpretación confiable" aparece igual en dos recuadros.
- El rep 3 de Carlos Palazzo (CMJ) tiene fases de tiempo anómalas que el filtro de reps fallidas no detecta.
- Al llegar los Excel de Involution, repetir la verificación del mapeo de métricas.
- Centralizar la paleta de colores (diferido).
- `_build_professional_training_context` y `_append_training_section` son código muerto en `report_generator.py`.
