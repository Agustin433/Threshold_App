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
