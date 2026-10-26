-- Threshold S&C
-- dj_rsi: la app la mapea y la manda en cada guardado de DJ (columna "RSI"
-- del export de plataforma -> DJ_RSI -> dj_rsi), pero no figuraba en ningun
-- script de esquema del repo. Lo detecto el test de contrato
-- tests/test_evaluation_db_contract.py.
--
-- Antes de aplicar, verificar en produccion:
--   select column_name from information_schema.columns
--   where table_schema = 'public' and table_name = 'evaluations'
--     and column_name = 'dj_rsi';
-- Si ya existe, esta migracion no hace nada. Si no existe, los guardados de
-- DJ con RSI estan fallando con PGRST204 y esto lo corrige.

alter table if exists public.evaluations add column if not exists dj_rsi double precision;
