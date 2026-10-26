-- Threshold S&C
-- Tabla minima para el keepalive (.github/workflows/supabase-keepalive.yml).
-- El workflow hace GET /rest/v1/heartbeat?limit=1 con la anon key cada 3 dias
-- para que el proyecto (plan free) no se pause por inactividad.
-- No guarda datos de atletas: es la unica tabla legible por anon y por eso
-- solo contiene una fila fija sin informacion.

create table if not exists public.heartbeat (
    id smallint primary key default 1 check (id = 1),
    note text not null default 'keepalive',
    created_at timestamptz not null default now()
);

comment on table public.heartbeat is
'Fila unica y publica para el keepalive de GitHub Actions. Sin datos sensibles.';

-- RLS primero, despues la policy, despues los grants: anon nunca ve la tabla
-- sin RLS activo.
alter table public.heartbeat enable row level security;

drop policy if exists heartbeat_public_read on public.heartbeat;
create policy heartbeat_public_read
    on public.heartbeat
    for select
    to anon, authenticated
    using (true);

-- Grants explicitos (desde el 30/10 las tablas nuevas en public no los
-- reciben automaticamente). anon y authenticated: solo lectura.
-- Sin insert/update/delete para ellos: la fila no se toca desde la API publica.
revoke all on table public.heartbeat from anon, authenticated;
grant select on table public.heartbeat to anon, authenticated;
grant select, insert, update, delete on table public.heartbeat to service_role;

insert into public.heartbeat (id) values (1)
on conflict (id) do nothing;
