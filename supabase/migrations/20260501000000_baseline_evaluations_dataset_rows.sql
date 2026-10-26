-- Threshold S&C
-- Migracion base: public.evaluations y public.dataset_rows.
--
-- Estas tablas se crearon a mano desde el SQL Editor antes de que existiera
-- supabase/migrations/. Este archivo reconstruye su CREATE TABLE para que una
-- base nueva creada SOLO con supabase/migrations/ quede igual a produccion.
-- En produccion no se ejecuta: se marca como aplicada con
--   supabase migration repair --status applied 20260501000000
-- (ver docs/supabase-grants.md). Todo es idempotente igual.
--
-- Las columnas agregadas despues (source/device, metricas recuperadas de CMJ
-- y SJ, etc.) viven en las migraciones posteriores, no aca.

-- ── evaluations ─────────────────────────────────────────────────────────
-- Una fila por atleta + fecha + fuente de medicion. La app recalcula EUR,
-- z-scores y NM_Profile al cargar, por eso no se guardan aca.
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
    cmj_landing_asym_pct double precision,
    cmj_landing_force_n double precision,
    cmj_peak_force_n double precision,
    cmj_peak_power_w double precision,
    cmj_propulsive_pf_n double precision,
    cmj_rel_impulse double precision,
    cmj_rsi double precision,
    cmj_stabilization_ms double precision,
    dj_asym_pct double precision,
    dj_cm double precision,
    dj_drop_height_cm double precision,
    dj_flight_ms double precision,
    dj_force_l_n double precision,
    dj_force_r_n double precision,
    dj_peak_force_n double precision,
    dj_rsi double precision,
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

comment on table public.evaluations is
'Fuente unica de verdad para evaluaciones individuales de saltos, IMTP e isometricos complementarios.';

-- ── dataset_rows ────────────────────────────────────────────────────────
-- Persistencia generica de datasets TeamBuildr (payload JSONB).
create table if not exists public.dataset_rows (
    dataset_key text not null,
    row_key text not null,
    event_date date,
    athlete text,
    payload jsonb not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (dataset_key, row_key)
);

create index if not exists idx_dataset_rows_dataset_date
    on public.dataset_rows (dataset_key, event_date desc);

create index if not exists idx_dataset_rows_dataset_athlete
    on public.dataset_rows (dataset_key, athlete);

create or replace function public.set_dataset_rows_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists trg_dataset_rows_updated_at on public.dataset_rows;
create trigger trg_dataset_rows_updated_at
before update on public.dataset_rows
for each row
execute function public.set_dataset_rows_updated_at();

comment on table public.dataset_rows is
'Persistencia generica de datasets TeamBuildr para Threshold S&C usando payload JSONB.';

-- ── Seguridad ───────────────────────────────────────────────────────────
-- RLS sin policies para anon/authenticated: solo service_role (la app,
-- server-side) lee y escribe. Grants en 20261026150000_evaluations_align_prod.
alter table public.evaluations enable row level security;
alter table public.dataset_rows enable row level security;
