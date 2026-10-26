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

## Versionar el esquema real

Hoy las tablas `evaluations` y `dataset_rows` se crearon corriendo a mano los
scripts de la raíz (`supabase_*_schema.sql`) en el SQL editor. No hay historial de
migraciones en la base. Para tener una línea base fiel a producción:

```bash
npm i -g supabase            # o: brew install supabase/tap/supabase
supabase login
supabase link --project-ref qeeajsquggrolobiqffa
supabase db pull             # genera supabase/migrations/<ts>_remote_schema.sql
```

`db pull` necesita Docker corriendo. Revisar el archivo generado, commitearlo y
desde ahí todo cambio de esquema va como migración nueva (`supabase migration new <nombre>`).

Ojo con dos cosas:

- La primera vez, `db pull` ofrece marcar la migración base como ya aplicada en la
  base remota (escribe en `supabase_migrations.schema_migrations`). Es correcto
  aceptarlo, pero es una escritura en producción: hacerlo a conciencia.
- Hacer el `db pull` **antes** de aplicar `20261026120000_heartbeat.sql`. Si la
  base generada por el pull queda con un timestamp más nuevo que el heartbeat,
  renombrar el archivo del heartbeat a un timestamp posterior antes de
  `supabase db push`, para que el orden de migraciones sea coherente.
