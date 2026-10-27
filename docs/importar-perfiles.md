# Importar perfiles desde el Google Form

Página **Importar perfiles** (`pages/03_importar_perfiles.py`). Lee las respuestas
del formulario "THRESHOLD S&C — Perfil de Cliente" y crea o actualiza
`athlete_profile_df` sin tipeo manual.

## Privacidad (no negociable)

- La planilla tiene teléfonos, contactos de emergencia y datos de salud de
  terceros. **Nunca** "Publicar en la web" ni compartir por link público.
- La app lee **solo** las columnas del perfil (`FORM_COLUMNS` en
  `modules/profile_form_import.py`):
  - **Google Sheets:** pide primero la fila de encabezados y después únicamente
    los rangos de esas columnas. El resto no se descarga.
  - **CSV:** usa `usecols`. El archivo subido sí pasa entero por la memoria del
    navegador y del servidor (así funciona cualquier upload), pero las otras
    columnas no se parsean ni se guardan.
- Email y años de entrenamiento se pueden leer, pero no se guardan: no existen
  en el esquema del perfil.

## Configurar la service account (una vez)

1. En Google Cloud: crear un proyecto (o usar uno existente), habilitar la
   **Google Sheets API** y crear una **service account**. No necesita roles.
2. Crear una clave JSON para esa service account.
3. Abrir la planilla de respuestas → Compartir → agregar el `client_email` de la
   service account como **Lector**. Nadie más que el equipo.
4. Cargar en los secrets de Streamlit Cloud (ver `.streamlit/secrets.example.toml`):
   - `[gcp_service_account]` con el contenido del JSON;
   - `PROFILE_FORM_SPREADSHEET_ID`: el ID que aparece en la URL de la planilla,
     entre `/d/` y `/edit`;
   - opcional: `PROFILE_FORM_WORKSHEET`, si la pestaña no se llama
     "Respuestas de formulario 1".

Sin estos secrets, la página acepta el archivo exportado a mano
(Archivo → Descargar → **.xlsx** o .csv), con el mismo validador. Del .xlsx se
leen solo las celdas de las columnas permitidas.

## Qué hace con cada respuesta

| Grupo | Cuándo |
|---|---|
| **Listos** | Autorizado, datos válidos, nombre idéntico al de TeamBuildr, sin perfil previo distinto. |
| **Requieren confirmación** | Nombre sin match exacto (con candidatos: otro orden, nombre completo vs. corto, sin tildes), perfil existente con cambios (diff campo por campo), practica deporte (hay que elegir el nivel competitivo) o una opción mapeada por palabra clave. |
| **Rechazados** | Sin autorización, fecha imposible/futura, edad fuera de 10–90, altura fuera de 120–220 cm, peso fuera de 30–200 kg, modalidad no reconocida, o respuesta duplicada más vieja. |
| **Sin cambios** | Ya tiene un perfil idéntico: no se reimporta. |

- El nombre que se guarda es **siempre** el de TeamBuildr. Nunca se crea un
  atleta en silencio.
- Una altura de 1.75 o 1,75 se convierte a 175 cm, con aviso.
- Si alguien respondió dos veces, vale la respuesta más reciente, con aviso.
- `Fecha_actualizacion` = marca temporal de la respuesta.
- El resultado dice cuántos perfiles **confirmó Supabase**. Si Supabase falla o no
  está configurado, se muestra como error, nunca como "guardado".

## Mapeo de las opciones del formulario (planilla real, oct/2026)

| Pregunta | Respuesta | Perfil |
|---|---|---|
| Objetivo principal | Salud y longevidad | Salud general y calidad de vida |
| | Rendimiento deportivo | Rendimiento deportivo específico |
| | Composición corporal / estética | Recomposición corporal |
| | Recuperación / regreso de una lesión | Rehabilitación y retorno deportivo (RTP) |
| | Combinación rendimiento deportivo + composición corporal/estetico | Rendimiento deportivo específico + secundario Recomposición corporal |
| | texto libre ("Otro") | Otro + texto en `Objetivo_otro_texto` |
| Modalidad | Presencial / Online | Contexto Gimnasio / Online |
| Tratamiento o rehabilitación | Sí | Es_RTP = true |
| | No o vacío (pregunta opcional) | Es_RTP = false |
| | otro texto (ej. "Terminé hace poco") | Es_RTP = false, se muestra para confirmar |
| Sexo biológico | Masculino / Femenino | M / F |

**Nivel.** El formulario pregunta experiencia ("Principiante / Intermedio /
Avanzado"), pero el Nivel de la app es **nivel competitivo**: define la clase
(población general vs. deportista), la cohorte y las referencias publicadas de
z-score. La experiencia **nunca** define el Nivel:
- si no practica deporte → **Población general**, automático;
- si practica deporte → la UI pide elegir Recreativo / Competitivo / Alto
  rendimiento, con Recreativo preseleccionado y la experiencia del formulario
  como pista.

## Agregar una opción nueva del formulario

Si el formulario cambia el texto de una opción de objetivo, nivel o modalidad,
agregala a `_OBJETIVO_EXACT` (o `_OBJETIVO_COMBOS`) o a `_MODALIDAD_EXACT` en
`modules/profile_form_import.py`. Mientras no esté, la app no adivina:
- si el texto se parece a una opción conocida, la propone y pide confirmación;
- si no se parece a nada, rechaza la respuesta (modalidad) o guarda el texto en
  `Objetivo_otro_texto` (objetivo).
