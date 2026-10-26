-- Threshold S&C — reparacion de nombres con U+FFFD en public.dataset_rows
-- ═══════════════════════════════════════════════════════════════════════
-- NO se corre automaticamente. Revisar la vista previa antes de aplicar.
--
-- Que paso: parse_questionnaire_raw_csv leia los exports de TeamBuildr en
-- Windows-1252 como UTF-8 con errors="replace". Cada letra acentuada quedo
-- como U+FFFD (chr(65533)) y despues .title() capitalizo la letra siguiente:
-- "Gaston Castaño" se guardo como "Gaston Casta�O".
--
-- Que hace:
--   1. Busca cada nombre con chr(65533) (columna athlete o payload->>'Athlete').
--   2. Propone el nombre correcto buscandolo en completion_df (que se lee con
--      otro parser y no esta corrupto): � = exactamente una letra cualquiera,
--      sin distinguir mayusculas (ILIKE).
--   3. Solo corrige los nombres con UN unico candidato. Ambiguos o sin
--      candidato quedan listados para resolver a mano.
--   4. Por cada fila: actualiza athlete, payload->'Athlete' Y row_key.
--
-- Por que row_key: row_key = sha1 del JSON de las dedupe_cols del dataset
-- (modules/remote_store.py::_dataset_row_signature), y todas incluyen
-- Athlete. Si solo se cambiara el nombre, la proxima carga del mismo
-- archivo generaria otro row_key y duplicaria las filas. El script
-- recalcula row_key con el mismo formato que Python
-- (json.dumps(sort_keys=True, ensure_ascii=False)) y, antes de tocar nada,
-- verifica que ese calculo reproduce EXACTAMENTE el row_key guardado de
-- cada fila afectada. Si alguna no coincide, aborta.
--
-- Conflictos: si el row_key corregido ya existe (ese atleta y fecha ya
-- estaban bien cargados), la fila corrupta NO se actualiza: queda en la
-- vista previa como "conflicto" para decidir a mano (normalmente, borrarla).
--
-- Como usarlo (SQL Editor de Supabase):
--   1. Correr el archivo tal cual: modo vista previa, no escribe nada.
--   2. Revisar los tres resultados de la vista previa.
--   3. Cambiar 'off' por 'on' en la linea marcada APLICAR y volver a correr.
--      Todo va en una transaccion; si algun chequeo falla, no cambia nada.
--   4. Reiniciar la app (Reboot) para que rehidrate desde Supabase.
--
-- Requiere pgcrypto (Supabase lo trae en el schema "extensions").
-- ═══════════════════════════════════════════════════════════════════════

begin;

-- ─── APLICAR: 'off' = solo vista previa | 'on' = aplica la reparacion ───
select set_config('threshold.apply_fffd_repair', 'off', true);

-- dedupe_cols de cada dataset remoto (local_store.DATASET_SPECS).
create temp table fffd_dedupe_cols (dataset_key text primary key, cols text[]) on commit drop;
insert into fffd_dedupe_cols values
    ('rpe_df',             array['Athlete', 'Date']),
    ('wellness_df',        array['Athlete', 'Date']),
    ('completion_df',      array['Athlete', 'Date']),
    ('rep_load_df',        array['Athlete', 'Date', 'Exercise']),
    ('raw_df',             array['Athlete', 'Assigned Date', 'Exercise Name', 'Set Number']),
    ('maxes_df',           array['Athlete', 'Added Date', 'Exercise Name']),
    ('session_notes_df',   array['Athlete', 'Date', 'Date_Assigned', 'Assigned_Exercise', 'Opt_Out_Type', 'Explanation_Text']),
    ('athlete_profile_df', array['Athlete']);

-- row_key igual a Python: sha1(json.dumps({col: payload[col] for col in
-- dedupe_cols if col in payload}, sort_keys=True, ensure_ascii=False)).
-- Claves ordenadas por code point (collate "C"), separadores ", " y ": ".
create or replace function pg_temp.threshold_row_key(p_dataset_key text, p_payload jsonb)
returns text
language sql
stable
as $$
    with key_cols as (
        select k
          from unnest(
                   coalesce(
                       (select cols from fffd_dedupe_cols where dataset_key = p_dataset_key),
                       array(select jsonb_object_keys(p_payload))
                   )
               ) as k
         where p_payload ? k
    )
    select encode(
               extensions.digest(
                   convert_to(
                       '{' || string_agg(to_jsonb(k)::text || ': ' || (p_payload -> k)::text, ', ' order by k collate "C") || '}',
                       'UTF8'
                   ),
                   'sha1'
               ),
               'hex'
           )
      from key_cols
$$;

-- Nombres rotos y su candidato en completion_df.
create temp table fffd_name_map on commit drop as
with broken as (
    select distinct name
      from (
          select athlete as name from public.dataset_rows
          union all
          select payload ->> 'Athlete' from public.dataset_rows
      ) names
     where strpos(name, chr(65533)) > 0
),
candidates as (
    select distinct athlete as candidate
      from public.dataset_rows
     where dataset_key = 'completion_df'
       and athlete is not null
       and strpos(athlete, chr(65533)) = 0
),
patterns as (
    select name,
           replace(
               replace(replace(replace(name, '\', '\\'), '%', '\%'), '_', '\_'),
               chr(65533),
               '_'
           ) as like_pattern
      from broken
)
select p.name as broken_name,
       count(c.candidate) as candidates,
       array_remove(array_agg(c.candidate order by c.candidate), null) as candidate_list,
       case when count(c.candidate) = 1 then min(c.candidate) end as new_name,
       case count(c.candidate)
           when 1 then 'unico'
           when 0 then 'sin_candidato'
           else 'ambiguo'
       end as status
  from patterns p
  left join candidates c on c.candidate ilike p.like_pattern
 group by p.name;

-- Filas afectadas con su row_key nuevo.
create temp table fffd_row_plan on commit drop as
select d.dataset_key,
       d.row_key as old_row_key,
       d.athlete as old_athlete,
       d.payload ->> 'Athlete' as old_payload_athlete,
       m.new_name,
       m.status,
       pg_temp.threshold_row_key(d.dataset_key, d.payload) = d.row_key as row_key_formula_ok,
       case
           when m.new_name is null then null
           else pg_temp.threshold_row_key(
               d.dataset_key,
               jsonb_set(d.payload, '{Athlete}', to_jsonb(m.new_name))
           )
       end as new_row_key
  from public.dataset_rows d
  join fffd_name_map m
    on m.broken_name = coalesce(d.payload ->> 'Athlete', d.athlete)
    or m.broken_name = d.athlete;

alter table fffd_row_plan add column conflict boolean;
update fffd_row_plan p
   set conflict = p.new_row_key is not null and exists (
           select 1 from public.dataset_rows d
            where d.dataset_key = p.dataset_key
              and d.row_key = p.new_row_key
       )
       -- dos filas rotas distintas que convergen al mismo row_key
       or (select count(*) from fffd_row_plan q
            where q.dataset_key = p.dataset_key and q.new_row_key = p.new_row_key) > 1;

-- ═══ VISTA PREVIA 1: nombres rotos y propuesta ═══════════════════════════
select broken_name                          as "nombre roto",
       new_name                             as "nombre propuesto",
       status                               as "estado",
       candidate_list                       as "candidatos en completion_df",
       (select count(*) from fffd_row_plan p where p.old_athlete = m.broken_name
            or p.old_payload_athlete = m.broken_name) as "filas"
  from fffd_name_map m
 order by status desc, broken_name;

-- ═══ VISTA PREVIA 2: resumen por dataset ═════════════════════════════════
select dataset_key,
       count(*)                                                         as filas_afectadas,
       count(*) filter (where status = 'unico' and not conflict)        as se_actualizan,
       count(*) filter (where conflict)                                 as conflictos,
       count(*) filter (where status <> 'unico')                        as sin_resolver,
       bool_and(row_key_formula_ok)                                     as row_key_formula_ok
  from fffd_row_plan
 group by dataset_key
 order by dataset_key;

-- ═══ VISTA PREVIA 3: conflictos y sin resolver (no se tocan) ════════════
select dataset_key, old_athlete, new_name, status, conflict,
       old_row_key, new_row_key
  from fffd_row_plan
 where conflict or status <> 'unico'
 order by dataset_key, old_athlete;

-- Las evaluaciones no pasan por el Questionnaire Raw CSV, pero por las dudas:
select count(*) as "evaluations con U+FFFD (se corrigen aparte)"
  from public.evaluations
 where strpos(athlete, chr(65533)) > 0;

-- ═══ APLICAR ═════════════════════════════════════════════════════════════
do $$
declare
    bad_formula int;
    updated int;
begin
    if current_setting('threshold.apply_fffd_repair') <> 'on' then
        raise notice 'Modo vista previa: no se modifico nada.';
        return;
    end if;

    select count(*) into bad_formula from fffd_row_plan where not row_key_formula_ok;
    if bad_formula > 0 then
        raise exception
            'Abortado: en % fila(s) el row_key recalculado no coincide con el guardado. '
            'El formato de _dataset_row_signature cambio; no es seguro recalcular row_key.',
            bad_formula;
    end if;

    update public.dataset_rows d
       set athlete = p.new_name,
           payload = jsonb_set(d.payload, '{Athlete}', to_jsonb(p.new_name)),
           row_key = p.new_row_key
      from fffd_row_plan p
     where d.dataset_key = p.dataset_key
       and d.row_key = p.old_row_key
       and p.status = 'unico'
       and not p.conflict;
    get diagnostics updated = row_count;

    if exists (
        select 1 from public.dataset_rows d
          join fffd_row_plan p on p.dataset_key = d.dataset_key and p.new_row_key = d.row_key
         where p.status = 'unico' and not p.conflict
           and pg_temp.threshold_row_key(d.dataset_key, d.payload) <> d.row_key
    ) then
        raise exception 'Abortado: despues del UPDATE algun row_key no coincide con su payload.';
    end if;

    raise notice 'Reparacion aplicada: % fila(s) actualizadas.', updated;
end
$$;

-- Estado final (en modo vista previa muestra el estado actual).
select dataset_key, count(*) as "filas con U+FFFD que quedan"
  from public.dataset_rows
 where strpos(athlete, chr(65533)) > 0
    or strpos(payload ->> 'Athlete', chr(65533)) > 0
 group by dataset_key
 order by dataset_key;

commit;
