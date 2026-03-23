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
    dj_flight_ms double precision,
    dj_force_l_n double precision,
    dj_force_r_n double precision,
    dj_peak_force_n double precision,
    dj_tc_ms double precision,
    dri double precision,
    imtp_asym_pct double precision,
    imtp_avg_n double precision,
    imtp_force_l_n double precision,
    imtp_force_r_n double precision,
    imtp_n double precision,
    imtp_pretension double precision,
    imtp_time_max_s double precision,
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
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (athlete, date)
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
'Fuente unica de verdad para evaluaciones individuales de saltos e IMTP.';
