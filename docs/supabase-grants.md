# Grants para tablas nuevas en Supabase

Desde el 30/10/2026, las tablas nuevas en el schema `public` **no reciben grants
automáticos** para la Data API (PostgREST, supabase-js, supabase-py, y el REST
directo que usa esta app en `modules/remote_store.py`). Sin grant, la API responde
`42501 permission denied` aunque la key sea válida. Las tablas que ya existían
conservan sus grants.

Regla: cada `create table` en `public` va con sus grants **en la misma migración**,
en este orden: tabla → RLS → policies → grants.

## Cómo accede la app hoy

| Rol | Quién lo usa | Qué necesita |
|---|---|---|
| `service_role` | Streamlit (server-side, `SUPABASE_SERVICE_ROLE_KEY`) | CRUD. Bypassa RLS. |
| `anon` | Solo el keepalive de GitHub Actions (`SUPABASE_ANON_KEY`) | `select` en `heartbeat`. Nada más. |
| `authenticated` | Nadie todavía (no se usa Supabase Auth) | Nada, salvo que la tabla lo requiera. |

## Plantilla A — tabla privada (datos de atletas, lo normal)

```sql
create table if not exists public.mi_tabla (
    id bigint generated always as identity primary key,
    -- ...
    created_at timestamptz not null default now()
);

alter table public.mi_tabla enable row level security;
-- Sin policies para anon/authenticated: quedan bloqueados por RLS.

grant select, insert, update, delete on table public.mi_tabla to service_role;
-- Si la tabla usa identity/serial y se inserta via API:
-- grant usage, select on sequence public.mi_tabla_id_seq to service_role;
```

## Plantilla B — tabla pública de solo lectura

Usar solo si el contenido puede verlo cualquiera que tenga la anon key (que es
pública por diseño: puede terminar en un navegador o en un log).

```sql
create table if not exists public.mi_tabla_publica ( ... );

alter table public.mi_tabla_publica enable row level security;

create policy mi_tabla_publica_read
    on public.mi_tabla_publica
    for select
    to anon, authenticated
    using (true);

revoke all on table public.mi_tabla_publica from anon, authenticated;
grant select on table public.mi_tabla_publica to anon, authenticated;
grant select, insert, update, delete on table public.mi_tabla_publica to service_role;
```

## Plantilla C — tabla por usuario (si algún día se usa Supabase Auth)

```sql
alter table public.mi_tabla enable row level security;

create policy mi_tabla_own_rows
    on public.mi_tabla
    for all
    to authenticated
    using (owner_id = (select auth.uid()))
    with check (owner_id = (select auth.uid()));

grant select, insert, update, delete on table public.mi_tabla to authenticated;
grant select, insert, update, delete on table public.mi_tabla to service_role;
```

## Checklist antes de mergear una migración

- [ ] `enable row level security` está en la misma migración que el `create table`.
- [ ] Ningún `grant ... to anon` sin una policy explícita y revisada.
- [ ] Nunca `grant ... to anon` en tablas con datos de atletas.
- [ ] `service_role` tiene los grants que la app usa (select/insert/update/delete).
- [ ] Probado en local (`supabase db reset` o un Postgres local) antes de aplicarlo en remoto.

## Verificar grants en la base

```sql
select grantee, privilege_type
from information_schema.role_table_grants
where table_schema = 'public' and table_name = 'mi_tabla'
order by grantee, privilege_type;

select relname, relrowsecurity
from pg_class
where relnamespace = 'public'::regnamespace and relkind = 'r';
```

## Fuente de verdad: `supabase/migrations/`

**Todo cambio de esquema va como un archivo nuevo en `supabase/migrations/`.**
Nada se aplica a mano desde el SQL Editor sin su archivo commiteado. El 26/10
producción estaba desfasada del repo justamente por eso: había cambios pegados a
mano y otros que estaban en un script pero nunca se aplicaron, y el guardado de
evaluaciones falló sin que nadie se enterara.

- Una base nueva creada **solo** con `supabase/migrations/` queda igual a producción.
  Lo verifica el workflow `Migrations Check` (aplica todo dos veces sobre un
  Postgres vacío y compara con las columnas que guarda la app) y el test
  `tests/test_evaluation_db_contract.py`, que lee **solo** migraciones.
- `supabase_evaluations_schema.sql` y `supabase_dataset_store_schema.sql` (raíz)
  son **referencia histórica**. No se ejecutan ni se editan: describían lo que
  "debería" haber, no lo que había.
- Archivos: `YYYYMMDDHHMMSS_descripcion.sql`, idempotentes (`if not exists`,
  `create or replace`, bloques `do $$` que chequean antes de cambiar).

```bash
supabase migration new evaluations_nueva_columna   # crea el archivo vacío
# editar, probar en local (supabase db reset), commitear, PR
supabase db push                                   # recién después del merge
```

### Linkear la CLI por primera vez (historial de migraciones)

Las migraciones de abajo ya están reflejadas en producción, pero se aplicaron a
mano, fuera del historial de la CLI (`supabase_migrations.schema_migrations`).
Antes del primer `db push` hay que marcarlas como aplicadas, o la CLI intentará
correrlas:

```bash
npm i -g supabase            # o: brew install supabase/tap/supabase
supabase login
supabase link --project-ref qeeajsquggrolobiqffa
supabase migration list      # muestra Local vs Remote
supabase migration repair --status applied \
  20260501000000 20261026120000 20261026140000 20261026140100 20261026150000
supabase migration list      # ahora todas deben figurar en Remote
```

`migration repair` escribe en el historial de producción (no toca tablas), así que
hacelo a conciencia. **Marcá solo las versiones que de verdad estén aplicadas.**
Si una no lo está (por ejemplo, si nunca se creó `heartbeat`), sacala del
`repair` y dejá que `supabase db push` la aplique. Para chequear:

```sql
-- 20261026120000: ¿existe heartbeat?
select to_regclass('public.heartbeat');
-- 20261026140100: ¿existe dj_rsi?
select column_name from information_schema.columns
where table_schema = 'public' and table_name = 'evaluations' and column_name = 'dj_rsi';
```

No uses `supabase db pull` para crear una línea base: la base ya está en
`20260501000000_baseline_evaluations_dataset_rows.sql`. Un pull generaría una
segunda línea base duplicada. Sí sirve `supabase db diff --linked` para detectar
desfase entre producción y las migraciones (necesita Docker).
