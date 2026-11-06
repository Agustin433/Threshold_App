# Changelog

Resumen acumulado del trabajo de estabilizacion y consolidacion hecho hasta este checkpoint.

## 2026-11-06 - PR D: ajustes post PR C (radar y textos)

1. Radar: eje "CMJ (vuelo)" (CMJ_ft_cm -> CMJ_ft_Z), misma escalera de
   referencia y una toma por atleta, sin restriccion de era (misma
   plataforma). Reemplaza al CMJ por impulso cuando este no tiene referencia
   (era Involution con < 8 atletas). El perfil compuesto lo usa con el mismo
   criterio, rotulado "CMJ (vuelo)".
2. Menos de 3 ejes con z/percentil: no se dibuja radar. Dashboard: aviso;
   PDF profe: tabla Variable / Valor / Comparacion / Referencia.
3. PDF profe: cada z con intervalo por la incertidumbre del SD de la
   cohorte, SE(SD) ~ SD/sqrt(2(n-1)): "+1.0 (0.8 a 1.3), n=9" (tabla del
   perfil, lectura principal, variable dominante/rezagada). Un decimal: con
   n ~ 10 el segundo decimal es ruido. No incluye la incertidumbre de la media
   ni el error tipico de la medicion.
4. Foco IMTP: "con el protocolo actual" solo si la ultima IMTP es de la era
   vigente (involution_straps); si no, "Tu ultima medicion de IMTP es con el
   protocolo anterior; en la proxima evaluacion tomamos una nueva referencia"
   (Giffon, valkyria_straps 22/05/2026).
5. "Lo que mas se destaca": maximo 2 variables de pruebas distintas (CMJ,
   SJ, DJ, IMTP); DJ RSI, DJ, DRI y tiempo de contacto son la misma prueba.
6. Grafico de fuerza estimada: eje Y "kg" (el rotulo largo vertical pisaba el
   titulo); la ventana va en el titulo. PDF atleta/cliente: encabezado mas
   bajo, graficos mas bajos con leyenda en un renglon, tabla de bienestar en
   pares y diccionario compacto: Giffon pasa de 3 a 2 paginas.

Tests: `tests/test_post_reference_adjustments.py`.

## 2026-11-05 - PR C: referencia de z-scores, radar y eras de medicion

1. Radar y cuadrantes nunca usan la serie propia (INTRA_INDIVIDUAL): esa
   comparacion vive en "Lo que lograste" y en la tabla de cambios.
2. `modules/reference_engine.py`: una toma por atleta (la ultima valida de
   los ultimos 12 meses, por metrica, fuente y era). `cohort_size` cuenta
   atletas; SD entre atletas (ddof=1). Las tomas historicas se puntuan contra
   la referencia de su propia era.
3. `modules/measurement_eras.py`: columna `device` (valkyria_sin_straps
   < 29/01/2026, valkyria_straps 29/01-30/09/2026, involution_straps
   >= 01/10/2026). IMTP y derivados de la velocidad integrada solo se
   comparan dentro de la misma era; alturas por tiempo de vuelo, DJ y fuerzas
   medidas si entre eras. Tabla de cambios profe: "no comparable: cambio de
   software/protocolo". Formulario: dispositivo obligatorio (default
   involution_straps).
4. Grupo de demanda desde Deporte (mapa unico en `athlete_profile.py`):
   intermitentes de equipo, raqueta/combate, resistencia, fuerza-potencia,
   poblacion general. Deportes compuestos: el primero reconocido.
5. Escalera: literatura (deporte + nivel + sexo + instrumento + era) ->
   Deporte+Nivel+Sexo (>= 8) -> Grupo+Sexo (>= 8) -> Sexo (>= 8) ->
   percentil con 5-7 atletas (radar 0-100, nunca mezclado con z) -> < 5 sin
   radar ("todavia no hay grupo de comparacion"). Nunca se mezclan sexos ni
   eras; sin sexo no hay grupo.
6. IMTP en radar/cuadrantes: relativa (N/kg); la absoluta queda descriptiva.
7. Sexo obligatorio al cargar una evaluacion (se guarda en el perfil);
   deporte y nivel opcionales.
8. Literatura: McMahon et al. 2022 (Sensors 22(22):8669,
   doi:10.3390/s22228669), mRSI de rugby: forwards 0.44 +/- 0.08 (n=66),
   backs 0.49 +/- 0.08 (n=55), solo como contexto mientras el nivel no
   coincida. Cada referencia declara `normalizacion`, `eras` y `nivel_uso`
   ("z" o "contexto"); `validate_reference_tables()` lo exige.
9. PDF profe: debajo del radar "Referencia: <escalon>, era <device>, N
   atletas, tomas de <min> a <max>"; lista de atletas en un anexo.
10. PDF atleta/cliente (pendientes de PR B): sin radar; "Tu fuerza" solo con
    grafico de fuerza estimada; sin "Seguir de cerca"; sin ACWR en tabla ni
    diccionario; tablas que no se parten entre paginas.
11. Cita corregida: Comfort et al. 2019, Strength Cond J 41(2):57-79 (no
    J Strength Cond Res).

Consecuencia con los datos reales: la era involution_straps tiene < 8
atletas, asi que SJ, CMJ (impulso) e IMTP salen del radar de quienes ya
midieron con Involution; DJ, DJ RSI y tiempo de contacto se mantienen.

Tests: `tests/test_reference_eras.py`.

## 2026-11-05 - PR B: reportes de atleta y cliente muestran lo que hay

Diagnostico con los PDF reales del 04/11/2026: el PDF atleta no tenia
seccion de comparacion (no era la ventana de 6 semanas: `jump_df` se carga
completo); Giffon tenia IMTP pero sin z ("imtp_reference_missing") y el
texto pedia "Completar IMTP"; portada y seccion de bienestar usaban ventanas
distintas (17.3 vs 13.7); la frase de carga del cliente decia "mas exigente"
con -4.1% semanal.

1. "Lo que lograste" (primera seccion, PDF atleta/cliente y dashboard):
   `compute_evaluation_changes` es el motor unico (tambien de la tabla de
   cambios del PDF profe) sobre todo el historial. Solo mejoras que superan
   max(TE, SWC); CMJ/SJ por tiempo de vuelo si el impulso no es comparable.
   Cambio de altura > +20% entre dos tomas: no se muestra al atleta; el PDF
   profe lo marca "cambio inusualmente grande: verificar tecnica/protocolo"
   (Holgado CMJ 37.5 -> 51.5 cm). Suma mejores marcas nuevas (maxes, solo
   levantamientos principales con registro previo) y sesiones completadas.
   Sin mejoras: "Tu referencia actual: ...".
2. PDF atleta/cliente sin "Sin patron definido", confianza, asimetria IMTP,
   tiempo al pico ni frases meta; el foco aparece una vez.
3. Secciones sin datos evaluables (carga sin sRPE, bienestar < 3 dias) no
   ocupan lugar: pasan a "Proximos pasos" (maximo 2, en positivo).
4. Coherencia: frase de carga con el signo del cambio semanal y referente
   explicito ("las ultimas semanas vienen mas exigentes que tu promedio");
   frase de bienestar segun la clasificacion; un unico valor de bienestar
   (ultima semana completa) con su rango; foco sin metricas que el atleta no
   tiene; sin confianza en atleta/cliente.
5. Portada: "Datos hasta DD/MM/AAAA".
6. Diccionario: solo terminos presentes, junto a "Proximos pasos".
7. Textos de faltante y proximos pasos en `modules/report_messages.py`.
8. Grafico "Fuerza estimada" (Epley, 1-10 reps, levantamientos principales
   con barra en `modules/strength_estimates.py`, mejor valor por dia).
9. `chart_maxes_trend` duplicado eliminado de app.py.

Ajustes de revision (mismo PR):
- IMTP absoluta y relativa > +25% entre dos tomas: solo PDF profe con
  "cambio inusualmente grande: verificar familiarizacion/protocolo"
  (Tomas 2565 -> 3638 N, primer IMTP). En "Lo que lograste", IMTP en una
  linea (N con N/kg entre parentesis).
- "N sesiones completadas" solo con >= 1 por semana en la ventana.
- Fuerza estimada: envolvente movil de 14 dias por ejercicio; sin datos en
  las ultimas 6 semanas el ejercicio no se muestra (y si no queda ninguno,
  tampoco el grafico).
- Carga atleta/cliente: "Mas alta / Similar / Mas baja que tu promedio";
  "Precaucion" por ACWR solo en el PDF profe (Impellizzeri et al. 2020).
- "Seguir de cerca" y "Lo que mas se destaca": maximo 2, por mayor z.
- Secciones del PDF: titulo + primer bloque juntos, el resto fluye.
- PDFs de muestra fuera del repo (datos de salud).

Tests: `tests/test_individual_report.py`.

## 2026-11-04 - PR A2: dependientes de v y serie por tiempo de vuelo

1. Si la altura CMJ/SJ de una toma esta marcada (regla 6b), tambien salen de
   radar, z, cohorte y comparaciones las variables de la misma velocidad
   integrada: velocidad de despegue, impulso relativo, potencia pico, RSI-mod,
   momentum, EUR, duraciones de frenado/concentrica (limite v = 0), RFD de
   esas fases y rigidez de aterrizaje. Se conservan fuerzas medidas, asimetrias,
   tiempo de vuelo y de contraccion, e IMTP.
2. Serie `CMJ_ft_cm` / `SJ_ft_cm` (h = g*t^2/8) para toda toma con vuelo. Solo
   vuelo-vs-vuelo, misma fuente, umbral max(TE, SWC), rotulada "por tiempo de
   vuelo"; no entra a radar, z ni cohorte, no se guarda.
   `compare_flight_time_height` queda para "Lo que lograste".
3. Tabla de cambios: la fila por impulso no se compara contra una toma mas
   vieja si en el medio hay una marcada ("no comparable: altura por impulso
   inconsistente"); el PDF profe agrega debajo la fila por tiempo de vuelo.

Tests: `tests/test_validity_coherence.py`.

## 2026-11-04 - PR A: validez y coherencia de numeros

1. Altura CMJ/SJ por impulso vs tiempo de vuelo (`evaluation_rules`, regla 6b):
   h_vuelo = 9.81 * t^2 / 8. Si |informada - h_vuelo| > max(3 cm, 8% de
   h_vuelo) en una toma de plataforma, la altura queda fuera de radar,
   z-score, cohorte, EUR, momentum y comparaciones. Rotulo: "altura por
   impulso inconsistente con tiempo de vuelo (probable error de peso en la
   fase de pesaje)". La altura por vuelo se muestra solo en el PDF profe,
   rotulada. No se modifica Supabase. Con los datos reales marca 31 alturas
   en 20 tomas (ninguna de oct-2026). Ref: Street et al. 2001; Moir 2008.
2. Umbral de cambio = max(TE, SWC) en todas las variables: el TE del
   instrumento entra siempre, tambien con 3+ mediciones (antes el SJ quedaba
   en 0.6 cm "Hopkins 0.2·SD").
3. Una sola fuente de z en el PDF profe: el perfil compuesto y el radar ya no
   re-preparan el historial del atleta sin cohorte (el z de literatura pisaba
   el de cohorte: CMJ 1.25 vs 1.29, DRI 0.46 vs 0.72 en el mismo PDF).
4. Adherencia: completion_df solo trae totales del periodo sin fecha y el raw
   de TeamBuildr solo series completadas (sin denominador), asi que no hay
   adherencia por ventana: el tile/fila se omite en vez de decir "Todavia no
   registrado".

Tests: `tests/test_validity_coherence.py`.

## 2026-11-04 - Fecha de evaluacion elegida a proposito

9. El selector "Fecha de evaluacion" arranca vacio y es obligatorio. Una fecha
   de mas de 90 dias, de otro anio o futura no entra a la cola sin marcar
   "Confirmo la fecha". Motivo: el archivo de Involution no trae fecha, y con
   "hoy" por defecto entraron IMTP con el anio corrido.

Tests: `tests/test_evaluation_date_rule.py` (regla pura y formulario real con AppTest).

## 2026-11-04 - Tomas duplicadas con fecha distinta y TE sin pares identicos

8. Toma duplicada: al agregar una evaluacion a la cola (y otra vez en
   "Procesar todo"), si el mismo atleta y fuente ya tiene en el historial o en
   la cola una toma en OTRA fecha con >= 3 metricas identicas y >= 50% de las
   comparables, se bloquea: "posible toma duplicada con fecha distinta
   (DD/MM/AAAA)". No cuentan los valores fijos del protocolo (duracion del
   tiron, altura de caida, peso). Calibrado con los datos reales: duplicados
   16/16 contra un maximo de 2/8 en tomas reales (0 falsos positivos en 43).
5. Umbral de cambio: una toma identica a la anterior se descarta antes de
   calcular la SD de Hopkins y el TE intraindividual (TE = 0 no es fisiologico).

Fecha del IMTP de Involution: el parser no lee ninguna fecha del archivo; la
fecha es la del selector "Fecha de evaluacion" de cada carga. Los IMTP con el
anio corrido (Giffon, Lopez Munoz, Anadon) vienen de ahi, no del parseo.

Tests: `tests/test_duplicate_takes.py`.

## 2026-11-04 - Peso de plataforma invalido y peso de una evaluacion cercana

Dos reglas mas en `modules/evaluation_rules.py`, aplicadas en `_prepare_jump_df`:

6. Peso de plataforma invalido: si Involution calculo un CMJ/SJ sin peso valido
   (0, vacio o impulso relativo negativo), se descartan altura por
   impulso-momento, velocidad de despegue, potencia, impulso, RSI, rigidez,
   fases y momentum de esa toma. Fuerzas, tiempo de vuelo, asimetrias, DJ e
   IMTP se conservan. Aviso rojo con el dato descartado y su altura por tiempo
   de vuelo (solo referencia, otro metodo). Tambien avisa al cargar el archivo.
   Solo aplica a tomas de plataforma con cinematica: una carga manual con solo
   la altura no se toca. Casos reales: Gray y Palazzo 07/05, Florencia Romano
   16/05, Lorenzo 28/09.
7. Peso de una evaluacion cercana: sin peso valido, la fuerza relativa del IMTP
   y el momentum usan el peso medido del mismo atleta a <= 14 dias, rotulado
   ("Peso tomado de la evaluacion del dd/mm/aaaa"). Va en `BW_kg_imputed`, que
   nunca se guarda en Supabase, y no rescata lo descartado por la regla 6.

Tests: `tests/test_platform_body_weight.py`.

## 2026-11-01 - Reglas de validez de evaluaciones (toda la app)

Una funcion por regla en `modules/evaluation_rules.py`, aplicada en
`_prepare_jump_df` y en el resumen force-time; dashboard (Overview, Decision,
Analisis Plataforma, Profile, Team), pagina Jump Evaluation, Excel y los tres
PDF la consumen sin parches por pantalla.

1. Calidad IMTP: (Force@50 - pretension) < 50 N o RFD 0-50 < 1000 N/s marca la toma
   "curva sin subida tras el inicio". El exceso de pretension sobre BW es solo
   informativo (PDF profesional). RFD y
   Force@50-250 se anulan en el frame preparado (no se muestran ni entran en
   DSI, z-scores, deltas ni comparaciones); el crudo queda en Supabase.
2. Fuerza relativa IMTP bruta (PF/masa) y neta ((PF-BW)/masa), rotuladas.
3. Peso fuera de 30-200 kg (incluido 0) = vacio: bloquea relativas, se valida
   en la carga y se guarda NULL. Migracion `20261101120000_evaluations_bw_kg_range.sql`.
4. Evaluacion > 12 semanas: "Evaluacion desactualizada (hace N semanas)" y la
   confianza del perfil baja un nivel.
5. Umbral de cambio: < 3 mediciones = max(SWC fijo, TE del instrumento);
   >= 3 = max(0.2*SD Hopkins, TE intraindividual). La fuente se rotula.

Tests: `tests/test_evaluation_rules.py` con los casos reales (Habib, Anadon,
Santiago Gray, Ignacio De La Vega), verificados en dashboard (AppTest), PDF y Excel.

## 2026-04-07 - Consolidacion documental

Se actualizaron o crearon los documentos principales del proyecto para reflejar el estado actual:

- `README.md`
- `RUNBOOK.md`
- `PROJECT_STATUS_CHECKPOINT.md`
- `SMOKE_TEST_CHECKLIST.md`
- `CHANGELOG.md`

Objetivo:

- dejar una fuente clara de verdad sobre operacion, validacion, estado actual, bugs corregidos y proximo paso recomendado

## 2026-04-07 - Fase 3 y bugfix de historial local

### Fase 3A

- se centralizo la base compartida de persistencia remota en `modules/remote_store.py`
- se unificaron configuracion, checks de habilitacion y request helper

### Fase 3B

- se movieron a `modules/remote_store.py` las operaciones remotas concretas mas duplicadas
- `app.py` y `modules/history_manager.py` pasaron a usar la capa compartida

### Fase 3C

- se elimino duplicacion legacy muerta en `modules/history_manager.py`
- se marco explicitamente el legacy remoto que todavia queda en `app.py`

### Bugfix puntual

- se corrigio `Vaciar dataset local` para que un dataset vaciado no se repueble inmediatamente desde `data/store`
- se mejoro el feedback de exito y backup para que sobreviva al rerun

Impacto:

- menos duplicacion activa en persistencia remota
- menos riesgo de drift entre rutas remotas
- historial local mas confiable

## 2026-04-06 / 2026-04-07 - Fase 1 y Fase 2

### Fase 1

- entorno local reproducible con `.venv`
- comando real y estable para correr la app
- eliminacion de la dependencia de `PYTHONPATH` manual

### Fase 2

- backups y confirmaciones previas para acciones destructivas del historial
- estabilidad de exportaciones visuales con `plotly==6.6.0` y `kaleido==1.2.0`
- mensajes claros cuando Supabase no esta configurado y la app queda en modo local

Impacto:

- la app corre de forma mucho mas confiable
- bajo el riesgo operativo de perdida de historial
- bajo el riesgo de confundir persistencia local con sincronizacion remota

## Validaciones registradas

- compilaciones puntuales con `py_compile`
- `tests.test_phase1_reporting`
- `tests.test_phase2_history`
- `tests.test_phase3_remote_store`
- arranque real de Streamlit
- verificacion de exportacion visual

## Deuda pendiente principal

- seguir consolidando la capa remota
- bajar el peso de `app.py`
- bajar el peso de `modules/report_generator.py`
- sumar restauracion guiada de backups desde la UI
- agregar pruebas end-to-end de UI

## Proximo paso recomendado

Continuar con una fase de consolidacion controlada, no de nuevas features:

- cerrar la deuda remota restante en `app.py` y `modules/history_manager.py`
- o, si se prioriza operacion, sumar restauracion guiada de backups en historial

Para mayor detalle por bloque:

- `CHANGELOG_FASE1_FASE2.md`
- `CHANGELOG_FASE3.md`
