-- Threshold S&C
-- Tabla unica para persistir evaluaciones individuales de plataforma de fuerza.
-- La app recalcula EUR, z-scores y NM_Profile al cargar, por eso no se guardan aca.

create table if not exists public.evaluations (
    athlete text not null,
    date date not null,
    bw_kg double precision,
    cmj_asym_pct double precision,
    cmj_brake_asym_pct double precision,
    cmj_brake_ms double precision,
    cmj_cm double precision,
    cmj_conc_ms double precision,
    cmj_contraction_ms double precision,
    cmj_flight_ms double precision,
    cmj_peak_force_n double precision,
    cmj_peak_power_w double precision,
    cmj_rsi double precision,
    dj_asym_pct double precision,
    dj_cm double precision,
    dj_drop_height_cm double precision,
    dj_flight_ms double precision,
    dj_force_l_n double precision,
    dj_force_r_n double precision,
    dj_peak_force_n double precision,
    dj_tc_ms double precision,
    dri double precision,
    iso_ham_asym_pct double precision,
    iso_ham_avg_n double precision,
    iso_ham_force_l_n double precision,
    iso_ham_force_r_n double precision,
    iso_ham_force_50_n double precision,
    iso_ham_force_100_n double precision,
    iso_ham_force_150_n double precision,
    iso_ham_force_200_n double precision,
    iso_ham_force_250_n double precision,
    iso_ham_n double precision,
    iso_ham_pretension double precision,
    iso_ham_rfd_50_n_s double precision,
    iso_ham_rfd_100_n_s double precision,
    iso_ham_rfd_150_n_s double precision,
    iso_ham_rfd_250_n_s double precision,
    iso_ham_time_max_s double precision,
    iso_ham_time_pull_s double precision,
    imtp_asym_pct double precision,
    imtp_avg_n double precision,
    imtp_force_l_n double precision,
    imtp_force_r_n double precision,
    imtp_force_50_n double precision,
    imtp_force_100_n double precision,
    imtp_force_150_n double precision,
    imtp_force_200_n double precision,
    imtp_force_250_n double precision,
    imtp_n double precision,
    imtp_pretension double precision,
    imtp_rfd_50_n_s double precision,
    imtp_rfd_100_n_s double precision,
    imtp_rfd_150_n_s double precision,
    imtp_rfd_250_n_s double precision,
    imtp_time_max_s double precision,
    imtp_time_pull_s double precision,
    rfd_50 double precision,
    rfd_100 double precision,
    rfd_150 double precision,
    rfd_250 double precision,
    sj_asym_pct double precision,
    sj_cm double precision,
    sj_conc_ms double precision,
    sj_flight_ms double precision,
    sj_peak_force_n double precision,
    sj_peak_power_w double precision,
    sj_rsi double precision,
    source text not null default 'platform',
    device text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    -- source forma parte de la clave: una medicion de plataforma y una de
    -- MyJump2/alfombra del mismo atleta y fecha son filas distintas.
    primary key (athlete, date, source)
);

alter table if exists public.evaluations add column if not exists iso_ham_n double precision;
alter table if exists public.evaluations add column if not exists iso_ham_avg_n double precision;
alter table if exists public.evaluations add column if not exists iso_ham_force_l_n double precision;
alter table if exists public.evaluations add column if not exists iso_ham_force_r_n double precision;
alter table if exists public.evaluations add column if not exists iso_ham_asym_pct double precision;
alter table if exists public.evaluations add column if not exists iso_ham_pretension double precision;
alter table if exists public.evaluations add column if not exists iso_ham_time_max_s double precision;
alter table if exists public.evaluations add column if not exists iso_ham_time_pull_s double precision;
alter table if exists public.evaluations add column if not exists iso_ham_force_50_n double precision;
alter table if exists public.evaluations add column if not exists iso_ham_force_100_n double precision;
alter table if exists public.evaluations add column if not exists iso_ham_force_150_n double precision;
alter table if exists public.evaluations add column if not exists iso_ham_force_200_n double precision;
alter table if exists public.evaluations add column if not exists iso_ham_force_250_n double precision;
alter table if exists public.evaluations add column if not exists iso_ham_rfd_50_n_s double precision;
alter table if exists public.evaluations add column if not exists iso_ham_rfd_100_n_s double precision;
alter table if exists public.evaluations add column if not exists iso_ham_rfd_150_n_s double precision;
alter table if exists public.evaluations add column if not exists iso_ham_rfd_250_n_s double precision;
alter table if exists public.evaluations add column if not exists dj_drop_height_cm double precision;

-- ── Migracion a evaluaciones particionadas por fuente de medicion ──────────
-- Ejecutar en orden sobre una base existente. Es idempotente.
-- Todo el historial previo a esta columna vino de la plataforma de fuerza,
-- por eso el backfill a 'platform' es correcto y no una suposicion.
alter table if exists public.evaluations add column if not exists source text;
alter table if exists public.evaluations add column if not exists device text;
update public.evaluations set source = 'platform' where source is null;
alter table if exists public.evaluations alter column source set default 'platform';
alter table if exists public.evaluations alter column source set not null;

-- Reemplazo de la PK. Solo corre si la clave todavia no incluye source, asi
-- que repetir el script no falla ni pierde datos.
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

    if pk_name is not null and pk_cols is distinct from 'athlete,date,source' then
        execute format('alter table public.evaluations drop constraint %I', pk_name);
        execute 'alter table public.evaluations add primary key (athlete, date, source)';
    end if;
end
$$;

create or replace function public.set_evaluations_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trg_evaluations_updated_at on public.evaluations;

create trigger trg_evaluations_updated_at
before update on public.evaluations
for each row
execute function public.set_evaluations_updated_at();

-- Metricas de CMJ recuperadas del export real de plataforma que antes se
-- leian y se descartaban en el parseo (RFD propulsivo/frenado, rigidez de
-- aterrizaje, velocidad de despegue, eficiencia vuelo/contacto, fuerza L/R
-- por fase). Ver auditoria de evaluaciones.
alter table if exists public.evaluations add column if not exists cmj_propulsive_rfd_n_s double precision;
alter table if exists public.evaluations add column if not exists cmj_braking_rfd_n_s double precision;
alter table if exists public.evaluations add column if not exists cmj_landing_stiffness_n_m double precision;
alter table if exists public.evaluations add column if not exists cmj_takeoff_velocity_m_s double precision;
alter table if exists public.evaluations add column if not exists cmj_efficiency_tvtc double precision;
alter table if exists public.evaluations add column if not exists cmj_propulsive_pf_l_n double precision;
alter table if exists public.evaluations add column if not exists cmj_propulsive_pf_r_n double precision;
alter table if exists public.evaluations add column if not exists cmj_braking_pf_l_n double precision;
alter table if exists public.evaluations add column if not exists cmj_braking_pf_r_n double precision;
alter table if exists public.evaluations add column if not exists cmj_landing_force_l_n double precision;
alter table if exists public.evaluations add column if not exists cmj_landing_force_r_n double precision;

-- Metricas de SJ recuperadas del mismo export real (carlos_falivene_SJ):
-- el SJ tambien tiene fase de aterrizaje y se descartaba igual que CMJ.
alter table if exists public.evaluations add column if not exists sj_landing_force_n double precision;
alter table if exists public.evaluations add column if not exists sj_landing_asym_pct double precision;
alter table if exists public.evaluations add column if not exists sj_stabilization_ms double precision;
alter table if exists public.evaluations add column if not exists sj_rel_impulse double precision;
alter table if exists public.evaluations add column if not exists sj_takeoff_velocity_m_s double precision;

comment on table public.evaluations is
'Fuente unica de verdad para evaluaciones individuales de saltos, IMTP e isometricos complementarios.';

comment on column public.evaluations.imtp_rfd_50_n_s is
'Campo canonico IMTP RFD 50 N/s. Los antiguos rfd_50/rfd_100/rfd_150/rfd_250 se conservan solo como alias legacy de lectura.';

-- Row Level Security: sin politicas para anon/authenticated, esta tabla
-- queda inaccesible via PostgREST para esas keys. La app debe usar
-- SUPABASE_SERVICE_ROLE_KEY (bypassa RLS por diseno en Postgres/Supabase),
-- nunca la anon key, para leer o escribir evaluaciones de atletas.
alter table public.evaluations enable row level security;
