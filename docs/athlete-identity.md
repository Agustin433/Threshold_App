# Identidad de atletas — diseño propuesto

> Estado: **propuesta, sin implementar**. Nada de esto está aplicado. La
> migración de abajo **no** está en `supabase/migrations/` a propósito: entra ahí
> recién cuando se apruebe el diseño.

## 1. El problema

Hoy la identidad de un atleta es su nombre normalizado (`normalize_athlete_name`).
Ese string es clave en todos lados: `dedupe_cols` de cada dataset, `row_key` de
`dataset_rows`, PK de `evaluations` y cruce entre perfiles y cargas.

El nombre no sirve como clave. De 30 perfiles, solo 14 se cruzan con sus cargas.
Hay tres tipos de error, cada uno con un ejemplo real:

| Tipo | Perfil | Cargas (TeamBuildr) |
|---|---|---|
| Orden invertido | Amarillo Celina | Celina Amarillo |
| Nombre de más / de menos | Agustín Alejandro Lopez Muñoz | Agustin Lopez Muñoz |
| Tildes | Anadón | Anadon |

A eso se suma el bug de encoding (`Gaston Casta�O`, corregido en el PR de
encoding). Si mañana aparece otra variante de escritura, la app crea en silencio
un atleta nuevo, con un historial vacío y un ACWR sin crónico. Nadie lo nota hasta
que un reporte sale mal.

**Principio del diseño:** la app nunca crea un atleta en silencio. Un nombre que no
reconoce es una pregunta para el usuario, no una fila nueva.

## 2. Modelo

```
athletes                       athlete_aliases
─────────────                  ───────────────────────────────
id  uuid PK      ◄──────────── athlete_id  uuid FK
canonical_name   text          alias_key   text   UNIQUE  (clave de matching)
created_at                     alias_text  text   (como vino escrito)
archived_at      (nullable)    source      text   (questionnaire_raw, raw_workouts, perfil, manual…)
notes                          created_at / created_by
                               confirmed   bool   (true = lo confirmó una persona)

athlete_external_ids
──────────────────────────────
athlete_id    uuid FK
system        text   ('teambuildr')
external_id   text   (User ID del export)
PK (system, external_id)
```

- **`athletes`**: una fila por persona real. `canonical_name` es solo para
  mostrar, nunca se usa como clave. Para renombrar a alguien se cambia una sola
  fila y no se mueve ningún dato.
- **`athlete_aliases`**: todas las formas en que ese atleta apareció escrito.
  `alias_key` es único: un mismo alias no puede apuntar a dos atletas.
- **`athlete_external_ids`**: el export de cuestionarios de TeamBuildr trae
  `User ID`, y hoy ningún parser lo lee. Un ID del sistema de origen es una clave
  mucho mejor que cualquier normalización de nombres. Cuando un archivo traiga ID,
  se resuelve por ID primero. **A verificar:** qué otros exports de TeamBuildr
  (Raw Workouts, Completion, Maxes) traen `User ID`.

### `alias_key`: qué se compara

Se calcula **en Python**, en una sola función (`athlete_alias_key`, en
`modules/athlete_names.py`), nunca duplicada en SQL:

1. `normalize_athlete_name` (NFC, espacios, mayúsculas).
2. `casefold()`.
3. Sin tildes ni diacríticos: NFKD y descartar los caracteres combinantes
   (`Anadón` → `anadon`, `Muñoz` → `munoz`).
4. Sin puntuación salvo espacios (`D'Andrea` → `dandrea`, `Jean-Pierre` → `jeanpierre`).

**El orden de las palabras se conserva.** `Celina Amarillo` y `Amarillo Celina`
tienen claves distintas. Ordenar las palabras alfabéticamente las uniría solas,
pero también uniría a "Martín Lucas" con "Lucas Martín", que en un plantel
pueden ser dos personas distintas. El orden invertido se resuelve como
**sugerencia** (ver 3b), no como match automático.

## 3. Resolución de un nombre al cargar un archivo

Para cada nombre distinto del archivo, en este orden:

**a. Match automático (sin preguntar):**
1. Si el archivo trae `User ID` y está en `athlete_external_ids` → ese atleta.
2. `alias_key` exacto en `athlete_aliases` → ese atleta.

**b. Sugerencias (requieren confirmación):** se ordenan por confianza.
| Regla | Ejemplo | Confianza |
|---|---|---|
| Mismas palabras, otro orden | Amarillo Celina ↔ Celina Amarillo | alta |
| Palabras del archivo ⊂ palabras de un atleta (falta un nombre) | Agustin Lopez Muñoz ⊂ Agustín Alejandro Lopez Muñoz | media |
| Similitud ≥ 0.88 (SequenceMatcher sobre `alias_key`) | Gaston Castano ↔ Gaston Castaño | media |
| Mismo apellido y misma inicial del nombre | M. Viña ↔ Martín Viña | baja |

**c. Desconocido:** sin match automático, con o sin sugerencias.

### Qué hace la app con un nombre desconocido

La carga **no se guarda parcialmente en silencio**. Antes de guardar aparece un
paso "Resolver atletas" con una fila por cada nombre desconocido:

```
"Celina Amarillo" (12 filas, Questionnaire Raw CSV)
  ( ) Es Amarillo Celina          ← sugerencia, mismas palabras en otro orden
  ( ) Es otro atleta: [selector]
  ( ) Es un atleta nuevo → nombre canónico: [Celina Amarillo]
  ( ) Descartar estas filas
```

- **Confirmar un match** crea el alias (`confirmed = true`, `source` = tipo de
  archivo). La próxima vez ese nombre entra solo.
- **Atleta nuevo** es una acción explícita, nunca un default. Si hay una sugerencia
  de confianza alta, crear uno nuevo pide una segunda confirmación ("Ya existe
  Amarillo Celina con las mismas palabras. ¿Crear igual?").
- **Descartar** no guarda esas filas y lo informa ("12 filas de 'X' descartadas").
- **Mientras haya nombres sin resolver, el botón de guardar queda bloqueado** para
  ese archivo. Encaja con el criterio del PR "fallar fuerte": nada se guarda a
  medias sin que se vea.
- Si el archivo trae `User ID` nuevo y se confirma el match, también se guarda en
  `athlete_external_ids`.

**Carga manual de perfiles y evaluaciones:** el campo de atleta pasa a ser un
selector de atletas existentes, con la opción "Nuevo atleta…". El texto libre es
el origen de "Amarillo Celina" vs "Celina Amarillo".

## 4. Migración propuesta (no aplicar todavía)

```sql
-- supabase/migrations/<ts>_athlete_identity.sql  (PROPUESTA)

create table public.athletes (
    id uuid primary key default gen_random_uuid(),
    canonical_name text not null,
    notes text,
    created_at timestamptz not null default now(),
    archived_at timestamptz
);

create table public.athlete_aliases (
    alias_key text primary key,                 -- athlete_alias_key(), calculada en Python
    athlete_id uuid not null references public.athletes (id) on delete restrict,
    alias_text text not null,                   -- como vino escrito
    source text not null,                       -- questionnaire_raw, raw_workouts, perfil, manual, seed
    confirmed boolean not null default false,
    created_at timestamptz not null default now(),
    created_by text
);
create index idx_athlete_aliases_athlete on public.athlete_aliases (athlete_id);

create table public.athlete_external_ids (
    system text not null,                       -- 'teambuildr'
    external_id text not null,
    athlete_id uuid not null references public.athletes (id) on delete restrict,
    created_at timestamptz not null default now(),
    primary key (system, external_id)
);
create index idx_athlete_external_ids_athlete on public.athlete_external_ids (athlete_id);

-- Referencia al atleta en los datos (nullable hasta completar el backfill).
alter table public.dataset_rows add column if not exists athlete_id uuid references public.athletes (id);
alter table public.evaluations  add column if not exists athlete_id uuid references public.athletes (id);
create index if not exists idx_dataset_rows_athlete_id on public.dataset_rows (dataset_key, athlete_id);
create index if not exists idx_evaluations_athlete_id on public.evaluations (athlete_id, date);

-- Seguridad: igual que el resto (docs/supabase-grants.md, plantilla A).
alter table public.athletes enable row level security;
alter table public.athlete_aliases enable row level security;
alter table public.athlete_external_ids enable row level security;
revoke all on table public.athletes, public.athlete_aliases, public.athlete_external_ids from anon, authenticated;
grant select, insert, update, delete
    on table public.athletes, public.athlete_aliases, public.athlete_external_ids
    to service_role;
```

`on delete restrict`: no se puede borrar un atleta que tenga alias o datos. Para
dar de baja a alguien se usa `archived_at`, no `delete`.

## 5. Plan por fases

Cada fase es un PR y deja la app funcionando.

**Fase 0 — Tablas y semilla.**
- Migración de arriba.
- `scripts/seed_athletes.py`: un atleta por cada `alias_key` distinto que exista
  hoy (cargas, evaluaciones, perfiles), con `source = 'seed'` y `confirmed = false`.
- **Sesión de unificación asistida:** una pantalla de mantenimiento (o el reporte
  del script) lista los pares sugeridos según 3b. Vos confirmás cuáles son la misma
  persona y se fusionan: el alias pasa al atleta que queda y el otro se archiva. Acá
  se resuelven los 16 perfiles que hoy no cruzan.
- La app sigue leyendo por nombre. Nada cambia para el usuario.

**Fase 1 — Resolución al cargar.**
- El paso "Resolver atletas" de la sección 3 en todos los parsers y en la carga
  manual.
- Se escribe `athlete_id` en cada fila nueva, además del nombre.
- Los parsers empiezan a leer `User ID` cuando viene.

**Fase 2 — Backfill y lecturas por id.**
- `athlete_id` para todas las filas históricas, vía los alias.
- Los cruces (perfil ↔ cargas ↔ evaluaciones, cohortes, reportes) pasan a hacerse
  por `athlete_id`.
- Las filas que no se puedan resolver quedan listadas, no se adivinan.

**Fase 3 — `athlete_id` como clave.**
- `dedupe_cols` y `row_key` usan `athlete_id` en lugar de `Athlete`. La PK de
  `evaluations` pasa a ser `(athlete_id, date, source)`.
- `athlete_id` queda `not null`. El nombre pasa a ser solo visual.
- Esta fase cambia todos los `row_key`. Necesita un script de recálculo con el
  mismo chequeo que `scripts/repair_fffd_names.sql` (recalcular el `row_key` viejo,
  verificar que coincide con el guardado y recién después reescribirlo).

## 6. Riesgos y decisiones a tomar

- **Fusionar mal es peor que no fusionar.** Dos personas mezcladas contaminan ACWR,
  z-scores y reportes, y separarlas después es manual. Por eso nada se fusiona solo
  por similitud: siempre lo confirma una persona.
- **Homónimos:** dos atletas con el mismo nombre no pueden compartir `alias_key`.
  Hace falta un segundo dato al crear el segundo atleta (el `User ID` de TeamBuildr,
  o un sufijo visible en `canonical_name`, como "Juan Pérez (sub-17)").
- **Costo de UI:** el paso "Resolver atletas" agrega fricción en la primera carga
  de cada nombre nuevo. Después de la fase 0 deberían quedar muy pocos.
- **A decidir:** si el seed usa `confirmed = false` y la app pide confirmar cada
  alias semilla la primera vez que aparece (más seguro, más clicks), o si se confía
  en el seed (menos fricción, hereda los errores de hoy). Recomiendo lo primero solo
  para los alias que tengan alguna sugerencia de conflicto.
- **No hacer:** ordenar palabras dentro de `alias_key`, fusionar por similitud
  sin confirmación, o permitir texto libre en el campo atleta.
