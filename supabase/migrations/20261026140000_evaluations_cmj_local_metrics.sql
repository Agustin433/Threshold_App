-- Threshold S&C
-- Metricas de CMJ de plataforma que el parser lee del export real pero que
-- hasta ahora la app marcaba como "solo local" y no tenian mapeo a la base.
-- Por ese hueco, jump_df_to_db_records fallaba con KeyError en cada guardado
-- de un CMJ de plataforma y ninguna evaluacion de CMJ llegaba a Supabase.
--
-- Produccion ya tiene estas columnas (agregadas a mano). Los add column if
-- not exists dejan el esquema versionado y no hacen nada si ya existen.
-- No crea tablas: no cambia grants ni RLS de public.evaluations.

alter table if exists public.evaluations add column if not exists cmj_propulsive_pf_n double precision;
alter table if exists public.evaluations add column if not exists cmj_rel_impulse double precision;
alter table if exists public.evaluations add column if not exists cmj_landing_force_n double precision;
alter table if exists public.evaluations add column if not exists cmj_landing_asym_pct double precision;
alter table if exists public.evaluations add column if not exists cmj_stabilization_ms double precision;
