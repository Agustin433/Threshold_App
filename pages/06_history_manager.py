"""Vista de gestion de historial local y remoto."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from local_store import DATASET_LABELS, DATASET_SPECS, build_dataset_summaries, load_full_history_state
from modules.history_manager import (
    create_history_backup,
    filter_history_frame,
    load_remote_history_frame,
    refresh_session_state_from_store,
    replace_local_history,
    replace_remote_history,
    supabase_dataset_store_enabled,
    supabase_evaluations_enabled,
)
from modules.page_state import ensure_page_state


def _dataset_options() -> list[tuple[str, str]]:
    return [(state_key, DATASET_LABELS.get(state_key, state_key)) for state_key in DATASET_SPECS]


def _backup_notice(backup_info: dict[str, object]) -> str:
    rows = int(backup_info.get("rows", 0))
    return (
        f"Backup previo disponible ({rows} fila(s)): `{backup_info['filename']}` en `{backup_info['path']}`. "
        "Si algo sale mal, podes restaurar este CSV manualmente."
    )


def _render_operation_error(prefix: str, exc: Exception, backup_info: dict[str, object] | None) -> None:
    detail = _backup_notice(backup_info) if backup_info else "No se genero backup previo."
    st.error(f"{prefix}. {detail}")
    st.caption(f"Detalle tecnico: {exc}")


ensure_page_state(load_models=True)

st.header("Gestion de Historial")
st.caption("Revisa, descarga, recorta y sincroniza el historial persistido sin editar archivos manualmente.")
st.page_link("app.py", label="Abrir dashboard principal")

full_state = load_full_history_state()
summary_rows = build_dataset_summaries(full_state, keys=list(DATASET_SPECS.keys()))
if summary_rows:
    st.markdown("### Resumen de datasets guardados")
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

dataset_pairs = _dataset_options()
labels_by_key = {state_key: label for state_key, label in dataset_pairs}
selected_key = st.selectbox(
    "Dataset",
    [state_key for state_key, _ in dataset_pairs],
    format_func=lambda key: labels_by_key[key],
)

selected_label = labels_by_key[selected_key]
full_df = full_state.get(selected_key)
if full_df is None:
    full_df = pd.DataFrame()
spec = DATASET_SPECS[selected_key]
athlete_col = spec.get("athlete_col")
date_col = str(spec["date_col"])

st.markdown(f"### {selected_label}")

filters_left, filters_right, filters_extra = st.columns(3)
athlete_filter = "Todos"
if athlete_col and athlete_col in full_df.columns:
    athlete_options = ["Todos"] + sorted(full_df[athlete_col].dropna().astype(str).str.strip().unique().tolist())
    with filters_left:
        athlete_filter = st.selectbox("Atleta", athlete_options, key=f"history_athlete_{selected_key}")
else:
    with filters_left:
        st.caption("Sin columna de atleta para este dataset.")

date_from = None
date_to = None
if date_col in full_df.columns and not full_df.empty:
    parsed_dates = pd.to_datetime(full_df[date_col], errors="coerce").dropna().sort_values()
    if not parsed_dates.empty:
        with filters_right:
            date_from = st.date_input(
                "Desde",
                value=parsed_dates.min().date(),
                key=f"history_from_{selected_key}",
            )
        with filters_extra:
            date_to = st.date_input(
                "Hasta",
                value=parsed_dates.max().date(),
                key=f"history_to_{selected_key}",
            )

text_query = st.text_input(
    "Buscar texto libre",
    value="",
    placeholder="Nombre de atleta, ejercicio, tag, perfil...",
    key=f"history_query_{selected_key}",
)

filtered_df, filtered_mask = filter_history_frame(
    full_df,
    athlete=athlete_filter,
    athlete_col=athlete_col if isinstance(athlete_col, str) else None,
    date_col=date_col if date_col in full_df.columns else None,
    date_from=date_from,
    date_to=date_to,
    text_query=text_query,
)

metrics = st.columns(4)
metrics[0].metric("Filas locales", len(full_df))
metrics[1].metric("Filas filtradas", len(filtered_df))
metrics[2].metric(
    "Atletas",
    int(full_df[athlete_col].dropna().nunique()) if athlete_col and athlete_col in full_df.columns and not full_df.empty else 0,
)
if date_col in full_df.columns and not full_df.empty:
    latest_date = pd.to_datetime(full_df[date_col], errors="coerce").dropna()
    metrics[3].metric("Ultima fecha", latest_date.max().strftime("%d/%m/%Y") if not latest_date.empty else "-")
else:
    metrics[3].metric("Ultima fecha", "-")

if full_df.empty:
    st.info("Todavia no hay historial local para este dataset.")
else:
    st.dataframe(filtered_df, use_container_width=True, hide_index=True)
    st.caption("Antes de cada accion destructiva local se genera un backup automatico en `.local/store/_history_backups/`.")

    csv_bytes = filtered_df.to_csv(index=False).encode("utf-8") if not filtered_df.empty else b""
    action_left, action_center, action_right = st.columns(3)
    with action_left:
        st.download_button(
            "Descargar CSV filtrado",
            data=csv_bytes,
            file_name=f"{selected_key}_filtrado.csv",
            mime="text/csv",
            disabled=filtered_df.empty,
        )
    with action_center:
        confirm_delete = st.checkbox(
            "Confirmo borrar las filas filtradas del historial local",
            key=f"confirm_delete_{selected_key}",
        )
        if st.button("Borrar filas filtradas", key=f"delete_filtered_{selected_key}"):
            if filtered_df.empty:
                st.warning("No hay filas filtradas para borrar.")
            elif not confirm_delete:
                st.warning("Activa la confirmacion antes de borrar filas del historial.")
            else:
                backup_info = None
                try:
                    backup_info = create_history_backup(
                        selected_key,
                        full_df,
                        source="local",
                        action="delete_filtered_rows",
                    )
                    remaining_df = full_df.loc[~filtered_mask].copy()
                    replace_local_history(selected_key, remaining_df)
                except Exception as exc:
                    _render_operation_error("No se pudo completar el borrado", exc, backup_info)
                else:
                    st.success(f"Se actualizaron {selected_label} en local. Se borraron {len(filtered_df)} fila(s).")
                    st.info(_backup_notice(backup_info))
                    st.rerun()
    with action_right:
        confirm_clear = st.checkbox(
            "Confirmo vaciar todo el dataset local",
            key=f"confirm_clear_{selected_key}",
        )
        if st.button("Vaciar dataset local", key=f"clear_dataset_{selected_key}"):
            if full_df.empty:
                st.warning("No hay historial local para vaciar.")
            elif not confirm_clear:
                st.warning("Activa la confirmacion antes de vaciar el dataset.")
            else:
                backup_info = None
                try:
                    backup_info = create_history_backup(
                        selected_key,
                        full_df,
                        source="local",
                        action="clear_local_dataset",
                    )
                    replace_local_history(selected_key, pd.DataFrame())
                except Exception as exc:
                    _render_operation_error("No se pudo vaciar el dataset", exc, backup_info)
                else:
                    st.success(f"Se vacio {selected_label} del historial local.")
                    st.info(_backup_notice(backup_info))
                    st.rerun()

st.markdown("---")
st.markdown("### Sincronizacion remota")
remote_enabled = supabase_evaluations_enabled() if selected_key == "jump_df" else supabase_dataset_store_enabled()

if remote_enabled:
    st.caption("Las acciones de esta seccion reemplazan el dataset remoto o el local completo para este origen.")
    st.caption("Antes de cada accion destructiva remota se genera un backup local recuperable en `.local/store/_history_backups/`.")
    remote_left, remote_right = st.columns(2)
    with remote_left:
        confirm_push_remote = st.checkbox(
            "Confirmo publicar y reemplazar el dataset remoto completo",
            key=f"confirm_push_remote_{selected_key}",
        )
        if st.button("Publicar local -> Supabase", key=f"push_remote_{selected_key}"):
            if not confirm_push_remote:
                st.warning("Activa la confirmacion antes de sobrescribir el dataset remoto.")
            else:
                backup_info = None
                try:
                    remote_before_df = load_remote_history_frame(selected_key)
                    backup_info = create_history_backup(
                        selected_key,
                        remote_before_df,
                        source="remote",
                        action="replace_remote_with_local",
                    )
                    stats = replace_remote_history(selected_key, full_df)
                except Exception as exc:
                    _render_operation_error("No se pudo actualizar Supabase", exc, backup_info)
                else:
                    st.success(
                        f"{selected_label}: Supabase actualizado. Upserts: {stats['upserted']} · Eliminados remotos: {stats['deleted']}."
                    )
                    st.info(_backup_notice(backup_info))
    with remote_right:
        confirm_pull_remote = st.checkbox(
            "Confirmo reemplazar el dataset local completo con Supabase",
            key=f"confirm_pull_remote_{selected_key}",
        )
        if st.button("Reemplazar local <- Supabase", key=f"pull_remote_{selected_key}"):
            if not confirm_pull_remote:
                st.warning("Activa la confirmacion antes de reemplazar el dataset local.")
            else:
                backup_info = None
                try:
                    backup_info = create_history_backup(
                        selected_key,
                        full_df,
                        source="local",
                        action="replace_local_from_remote",
                    )
                    remote_df = load_remote_history_frame(selected_key)
                    replace_local_history(selected_key, remote_df)
                except Exception as exc:
                    _render_operation_error("No se pudo reemplazar el historial local", exc, backup_info)
                else:
                    st.success(f"{selected_label}: historial local reemplazado con {len(remote_df)} fila(s) de Supabase.")
                    st.info(_backup_notice(backup_info))
                    st.rerun()
else:
    st.info("Supabase no esta configurado para este tipo de historial. La gestion sigue disponible en modo local.")

if st.button("Recargar estado desde el store local", key="reload_history_state"):
    refresh_session_state_from_store()
    st.success("Se recargo el estado visible desde el historial local.")
