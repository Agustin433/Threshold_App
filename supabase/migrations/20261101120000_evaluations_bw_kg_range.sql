-- Threshold S&C
-- Peso corporal valido: 30-200 kg o NULL. Algunas plataformas exportan
-- "weight (kg) = 0" cuando no se peso al atleta (caso real: Santiago Gray,
-- 2026-05-07). Con 0 la app calculaba fuerza relativa y momentum absurdos o
-- infinitos. La app ya lo trata como vacio (modules/evaluation_rules.py);
-- esto deja la base coherente y bloquea nuevos valores fuera de rango.
-- Idempotente: se puede aplicar dos veces.

update public.evaluations
set bw_kg = null
where bw_kg is not null and (bw_kg < 30 or bw_kg > 200);

do $$
begin
    if to_regclass('public.evaluations') is not null
       and not exists (
           select 1 from pg_constraint
           where conname = 'evaluations_bw_kg_range'
             and conrelid = 'public.evaluations'::regclass
       ) then
        alter table public.evaluations
            add constraint evaluations_bw_kg_range
            check (bw_kg is null or (bw_kg >= 30 and bw_kg <= 200));
    end if;
end
$$;
