-- Threshold S&C
-- Alinea el historial de migraciones con lo que se aplico a mano en
-- produccion desde el SQL Editor el 26/10/2026. Hasta ese dia, produccion
-- estaba desfasada del repo: el script supabase_evaluations_schema.sql
-- describia columnas que la base no tenia, y el guardado fallaba.
--
-- Todo es idempotente: en produccion no cambia nada (marcar como aplicada con
-- `supabase migration repair --status applied 20261026150000`); en una base
-- nueva completa el esquema. Sin `if exists` en los alter table a proposito:
-- si la tabla no existe, la migracion tiene que fallar, no saltearse.

-- ── Fuente de medicion (plataforma vs. MyJump2/alfombra) ───────────────
alter table public.evaluations add column if not exists source text;
alter table public.evaluations add column if not exists device text;
-- Todo el historial previo a la columna vino de la plataforma de fuerza.
update public.evaluations set source = 'platform' where source is null;
alter table public.evaluations alter column source set default 'platform';
alter table public.evaluations alter column source set not null;

-- PK (athlete, date, source): solo se reemplaza si la clave actual no es esa,
-- asi que repetirla no falla ni pierde datos.
do $$
declare
    pk_name text;
    pk_cols text;
begin
    select con.conname,
           string_agg(att.attname, ',' order by att.attname)
      into pk_name, pk_cols
      from pg_constraint con
      join pg_attribute att
        on att.attrelid = con.conrelid
       and att.attnum = any(con.conkey)
     where con.conrelid = 'public.evaluations'::regclass
       and con.contype = 'p'
     group by con.conname;

    if pk_name is null then
        execute 'alter table public.evaluations add primary key (athlete, date, source)';
    elsif pk_cols is distinct from 'athlete,date,source' then
        execute format('alter table public.evaluations drop constraint %I', pk_name);
        execute 'alter table public.evaluations add primary key (athlete, date, source)';
    end if;
end
$$;

-- ── Grants: solo service_role (la app es server-side) ───────────────────
-- anon y authenticated quedan sin privilegios ademas de bloqueados por RLS.
revoke all on table public.evaluations, public.dataset_rows from anon, authenticated;
grant select, insert, update, delete on table public.evaluations, public.dataset_rows to service_role;

-- ── Funciones de trigger con search_path fijo ───────────────────────────
-- Aviso "function_search_path_mutable" del advisor de Supabase. now() vive en
-- pg_catalog, que siempre se resuelve, asi que el cuerpo no cambia.
alter function public.set_evaluations_updated_at() set search_path = '';
alter function public.set_dataset_rows_updated_at() set search_path = '';

-- ── Metricas de CMJ y SJ recuperadas del export real de plataforma ──────
-- (ea7ab01, d5dfb62). Estaban en el script de la raiz pero no en produccion.
alter table public.evaluations add column if not exists cmj_braking_pf_l_n double precision;
alter table public.evaluations add column if not exists cmj_braking_pf_r_n double precision;
alter table public.evaluations add column if not exists cmj_braking_rfd_n_s double precision;
alter table public.evaluations add column if not exists cmj_efficiency_tvtc double precision;
alter table public.evaluations add column if not exists cmj_landing_force_l_n double precision;
alter table public.evaluations add column if not exists cmj_landing_force_r_n double precision;
alter table public.evaluations add column if not exists cmj_landing_stiffness_n_m double precision;
alter table public.evaluations add column if not exists cmj_propulsive_pf_l_n double precision;
alter table public.evaluations add column if not exists cmj_propulsive_pf_r_n double precision;
alter table public.evaluations add column if not exists cmj_propulsive_rfd_n_s double precision;
alter table public.evaluations add column if not exists cmj_takeoff_velocity_m_s double precision;
alter table public.evaluations add column if not exists sj_landing_asym_pct double precision;
alter table public.evaluations add column if not exists sj_landing_force_n double precision;
alter table public.evaluations add column if not exists sj_rel_impulse double precision;
alter table public.evaluations add column if not exists sj_stabilization_ms double precision;
alter table public.evaluations add column if not exists sj_takeoff_velocity_m_s double precision;
