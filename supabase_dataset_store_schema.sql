-- ⚠️ REFERENCIA HISTORICA. NO EJECUTAR NI EDITAR.
-- La fuente de verdad del esquema es supabase/migrations/ (ver
-- docs/supabase-grants.md). Este script describia lo que "deberia" haber en
-- la base, no lo que habia: el 26/10/2026 listaba 17 columnas que produccion
-- no tenia y el guardado de evaluaciones fallaba.
--
-- Threshold S&C
-- Tabla generica para persistir datasets TeamBuildr sin depender de un schema rigido.
-- Guarda una fila por registro operativo usando payload JSONB y clave de upsert estable.

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

-- Row Level Security: sin politicas para anon/authenticated, esta tabla
-- queda inaccesible via PostgREST para esas keys. La app debe usar
-- SUPABASE_SERVICE_ROLE_KEY (bypassa RLS por diseno en Postgres/Supabase),
-- nunca la anon key, para leer o escribir estos datasets.
alter table public.dataset_rows enable row level security;

-- Grants explicitos para la Data API (PostgREST). Desde el 30/10/2026 las
-- tablas nuevas en public no reciben grants automaticos; las existentes
-- conservan los suyos, asi que en produccion esto no cambia nada. Sirve para
-- que este script funcione igual si se recrea la tabla en un proyecto nuevo.
-- Solo service_role: la app es server-side y usa SUPABASE_SERVICE_ROLE_KEY.
-- anon y authenticated no reciben nada a proposito: son datos de atletas y
-- la tabla no tiene policies para ellos.
grant select, insert, update, delete on table public.dataset_rows to service_role;
