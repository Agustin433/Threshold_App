"""Importar perfiles de atleta desde el Google Form "Perfil de Cliente".

Lee la planilla de respuestas con una service account (solo lectura, solo las
columnas permitidas) o, como respaldo, el CSV exportado a mano. Nada se guarda
sin pasar por la vista previa: listos / requieren confirmacion / rechazados.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import local_store
from modules.page_state import ensure_page_state
from modules.persistence_guard import (
    clear_remote_save_failure,
    record_remote_save_failure,
    render_persistence_banners,
)
from modules.profile_form_import import (
    ImportItem,
    ImportPlan,
    build_import_plan,
    final_profile,
    read_form_csv,
    read_form_sheet,
    refresh_item_diff,
    service_account_token,
)
from modules.remote_store import save_remote_dataset, supabase_dataset_store_enabled

PLAN_KEY = "profile_import_plan"
EXISTING_KEY = "profile_import_existing"
TEAMBUILDR_DATASETS = ("rpe_df", "wellness_df", "completion_df", "raw_df", "maxes_df", "session_notes_df", "rep_load_df")
NO_IMPORT = "— No importar —"
DEFAULT_WORKSHEET = "Respuestas de formulario 1"

st.header("Importar perfiles")
st.caption(
    "Respuestas del formulario \"THRESHOLD S&C — Perfil de Cliente\". Solo se leen las columnas del "
    "perfil: teléfonos, contacto de emergencia y datos de salud no se leen ni se guardan."
)
ensure_page_state(load_models=False)
render_persistence_banners()


def _secret(name: str, default=None):
    try:
        return st.secrets[name] if name in st.secrets else default
    except Exception:
        return default


def _teambuildr_names() -> list[str]:
    names: set[str] = set()
    for key in TEAMBUILDR_DATASETS:
        frame = local_store.read_full_dataset(key)
        if frame is not None and not frame.empty and "Athlete" in frame.columns:
            names.update(local_store.normalize_athlete_name(value) for value in frame["Athlete"].dropna())
    names.discard("")
    return sorted(names)


def _existing_profiles() -> pd.DataFrame:
    frame = local_store.read_full_dataset("athlete_profile_df")
    return frame if frame is not None else pd.DataFrame()


teambuildr_names = _teambuildr_names()
if not teambuildr_names:
    st.error(
        "No hay nombres de TeamBuildr cargados en esta instancia, así que no se puede resolver a quién "
        "corresponde cada respuesta. Abrí primero el dashboard principal (sincroniza desde Supabase) o "
        "cargá los exports de TeamBuildr, y volvé."
    )
    st.stop()
st.caption(f"{len(teambuildr_names)} atleta(s) de TeamBuildr para resolver nombres.")

# ── 1. Lectura ──────────────────────────────────────────────────────────────
sheet_id = _secret("PROFILE_FORM_SPREADSHEET_ID")
service_account = _secret("gcp_service_account")
sources = ["Google Sheets (service account)", "CSV exportado a mano"] if sheet_id and service_account else ["CSV exportado a mano"]
source = st.radio("Origen", sources, horizontal=True)
if len(sources) == 1:
    st.info(
        "Google Sheets no está configurado. Para leer la planilla directo: crear una service account, "
        "compartir la planilla SOLO con su email en modo lector y cargar en los secrets "
        "`gcp_service_account` (el JSON) y `PROFILE_FORM_SPREADSHEET_ID`. Nunca publicar la planilla en la web."
    )

responses: pd.DataFrame | None = None
if source.startswith("Google"):
    worksheet = _secret("PROFILE_FORM_WORKSHEET", DEFAULT_WORKSHEET)
    if st.button("Leer respuestas de la planilla"):
        try:
            token = service_account_token(service_account)
            responses = read_form_sheet(str(sheet_id), str(worksheet), token)
        except Exception as exc:
            st.error(f"No se pudo leer la planilla: {exc}")
else:
    uploaded = st.file_uploader("CSV de respuestas", type=["csv"], key="profile_form_csv")
    if uploaded is not None and st.button("Leer CSV"):
        try:
            responses = read_form_csv(uploaded)
        except Exception as exc:
            st.error(f"No se pudo leer el CSV: {exc}")

if responses is not None:
    existing = _existing_profiles()
    st.session_state[PLAN_KEY] = build_import_plan(responses, teambuildr_names, existing)
    st.session_state[EXISTING_KEY] = {
        local_store.normalize_athlete_name(row.get("Athlete")): row.to_dict()
        for _, row in existing.iterrows()
        if local_store.normalize_athlete_name(row.get("Athlete"))
    }

plan: ImportPlan | None = st.session_state.get(PLAN_KEY)
if plan is None:
    st.stop()

# ── 2. Vista previa ─────────────────────────────────────────────────────────
ready = plan.by_status("listo")
pending = plan.by_status("requiere_confirmacion")
rejected = plan.by_status("rechazado")
unchanged = plan.by_status("sin_cambios")
cols = st.columns(4)
cols[0].metric("Listos", len(ready))
cols[1].metric("Requieren confirmación", len(pending))
cols[2].metric("Rechazados", len(rejected))
cols[3].metric("Sin cambios", len(unchanged))
for warning in plan.warnings:
    st.warning(warning)


def _profile_row(item: ImportItem) -> dict[str, object]:
    profile = item.profile
    return {
        "Fila": item.row_number,
        "Nombre (form)": item.form_name,
        "Atleta TeamBuildr": item.athlete or "",
        "Nacimiento": profile.get("Fecha_nacimiento"),
        "Altura_cm": profile.get("Altura_cm"),
        "Peso_kg": profile.get("Peso_kg"),
        "Sexo": profile.get("Sexo"),
        "Contexto": profile.get("Contexto"),
        "Nivel": profile.get("Nivel"),
        "Objetivo": profile.get("Objetivo_primario"),
        "RTP": profile.get("Es_RTP"),
        "Avisos": " · ".join(item.warnings),
    }


selected: dict[int, bool] = {}
st.subheader(f"Listos ({len(ready)})")
if ready:
    st.dataframe(pd.DataFrame([_profile_row(item) for item in ready]), hide_index=True, width="stretch")
    for item in ready:
        selected[item.row_number] = True

st.subheader(f"Requieren confirmación ({len(pending)})")
existing_by_name = st.session_state.get(EXISTING_KEY, {})
for item in pending:
    with st.expander(f"Fila {item.row_number} · {item.form_name}", expanded=True):
        for reason in item.confirmations:
            st.write(f"- {reason}")
        for warning in item.warnings:
            st.caption(f"Aviso: {warning}")
        if item.form_name not in set(teambuildr_names) or item.athlete is None or item.candidates:
            options = [NO_IMPORT] + [name for name, _ in item.candidates] + [
                name for name in teambuildr_names if name not in {c for c, _ in item.candidates}
            ]
            labels = {name: f"{name} — {why}" for name, why in item.candidates}
            choice = st.selectbox(
                "Atleta de TeamBuildr (se guarda con este nombre)",
                options,
                index=0,
                format_func=lambda name: labels.get(name, name),
                key=f"pf_athlete_{item.row_number}",
            )
            item.athlete = None if choice == NO_IMPORT else choice
            refresh_item_diff(item, existing_by_name)
        if item.diff:
            st.write("Ya tiene perfil. Cambios campo por campo:")
            st.dataframe(
                pd.DataFrame(item.diff, columns=["Campo", "Actual", "Nuevo"]).astype(str),
                hide_index=True,
                width="stretch",
            )
        elif item.unchanged:
            st.caption("Ya tiene un perfil idéntico: no hace falta importarlo.")
        st.dataframe(pd.DataFrame([_profile_row(item)]), hide_index=True, width="stretch")
        confirmed = st.checkbox(
            "Confirmo importar" + (" y actualizar el perfil existente" if item.diff else ""),
            key=f"pf_confirm_{item.row_number}",
            disabled=not item.athlete or item.unchanged,
        )
        selected[item.row_number] = bool(item.athlete) and not item.unchanged and confirmed

st.subheader(f"Rechazados ({len(rejected)})")
if rejected:
    st.dataframe(
        pd.DataFrame(
            [{"Fila": item.row_number, "Nombre (form)": item.form_name, "Motivo": " · ".join(item.errors)} for item in rejected]
        ),
        hide_index=True,
        width="stretch",
    )

# ── 3. Importar ─────────────────────────────────────────────────────────────
to_import = [item for item in plan.items if selected.get(item.row_number)]
targets = [item.athlete for item in to_import]
repeated = sorted({name for name in targets if targets.count(name) > 1})
if repeated:
    st.error(
        "Dos respuestas apuntan al mismo atleta de TeamBuildr: " + ", ".join(repeated) + ". Corregí la selección."
    )
if st.button(f"Importar confirmados ({len(to_import)})", type="primary", disabled=not to_import or bool(repeated)):
    saved_local: list[str] = []
    merged = None
    for item in to_import:
        merged = local_store.upsert_athlete_profile(final_profile(item))
        saved_local.append(item.athlete)
    if merged is not None:
        st.session_state.athlete_profile_df = None if merged.empty else merged
    imported_rows = merged[merged["Athlete"].isin(saved_local)] if merged is not None else pd.DataFrame()

    if not supabase_dataset_store_enabled():
        st.error(
            f"{len(saved_local)} perfil(es) guardados SOLO en esta instancia: Supabase no está configurado, "
            "se pierden cuando la app se reinicia."
        )
    else:
        try:
            stats = save_remote_dataset("athlete_profile_df", imported_rows)
            clear_remote_save_failure("athlete_profile_df")
            st.success(
                f"{stats['upserted']} perfil(es) guardados en Supabase (confirmados): {', '.join(saved_local)}."
            )
            st.session_state.pop(PLAN_KEY, None)
        except Exception as exc:
            st.error(
                record_remote_save_failure(
                    "athlete_profile_df", "Importar perfiles", exc, total_hint=len(imported_rows)
                )
            )
