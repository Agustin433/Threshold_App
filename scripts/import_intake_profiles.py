"""One-shot import: carga el formulario de admision de Google Forms (Google
Sheets "Respuestas de formulario 1") a `athlete_profile_df`, local y remoto.

Contexto: el formulario de admision no tiene ni el mismo esquema ni las
mismas opciones cerradas que el "Perfil de atleta" de la app (deportes y
objetivos son texto libre / multi-select ahi, selectbox cerrado aca), asi
que este script mapea cada respuesta a los campos y opciones reales de
`ATHLETE_PROFILE_COLUMNS` antes de guardar:

- Nivel: "Recreativo / amateur" -> "Recreativo", "Competitivo local /
  provincial" -> "Competitivo", "Nacional" -> "Alto rendimiento".
- Deporte: pasa por `normalize_deporte`, que ya resuelve grafias conocidas
  (futbol/fulbo/fulbol -> Futbol). Lo que no matchea una opcion del
  desplegable (deportes compuestos como "Futbol o voley", o poco comunes
  como "Trail Running") se guarda tal cual como texto libre: el storage no
  fuerza la lista cerrada, solo el selectbox de la UI lo hace.
- Objetivos: el formulario permite marcar varios como texto separado por
  comas. Cada uno se mapea a la opcion mas cercana de OBJETIVO_OPTIONS; el
  primero mapeado queda de Objetivo_primario, el resto de secundarios. Lo
  que no tiene equivalente exacto (ej: "Mejorar velocidad / potencia", que
  no existe como opcion propia) se preserva en Objetivo_otro_texto en vez
  de perderse.
- Contexto: el formulario no lo pregunta. Confirmado con el coach que las
  31 respuestas son de un unico gimnasio -> "Gimnasio" fijo para todos.
- Altura: una fila trae 1.79 en vez de 179 (metros en vez de cm, error de
  carga en el formulario, confirmado con el coach). Cualquier altura menor
  a 3 se interpreta como metros y se multiplica por 100.
- Misma persona respondio el formulario dos veces (Gaston Castaño, con 4
  meses de diferencia): se conserva solo la respuesta mas reciente por
  `Marca temporal`.

Usage (una sola vez, desde la raiz del repo):
    .venv/Scripts/python.exe scripts/import_intake_profiles.py "ruta/al/formulario.xlsx"

Requiere `.streamlit/secrets.toml` configurado para sincronizar a Supabase;
sin eso, igual guarda todo en local (`.local/store/athlete_profiles.csv`).

Es seguro re-ejecutarlo: `upsert_athlete_profile` reemplaza la fila
completa por atleta (por nombre normalizado), asi que corridas repetidas
con el mismo archivo no duplican filas. Escribe un backup del CSV de
perfiles antes de tocar nada, si ya existe uno previo.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import local_store
from modules.athlete_profile import (
    DEPORTE_OPTIONS,
    normalize_deporte,
    validate_profile_fields,
)

BACKUP_SUFFIX = "_backup_pre_intake_import"

CONTEXTO_FIJO = "Gimnasio"

NIVEL_MAP: dict[str, str] = {
    "Recreativo / amateur": "Recreativo",
    "Competitivo local / provincial": "Competitivo",
    "Nacional": "Alto rendimiento",
}

RTP_OPTION = "Rehabilitación y retorno deportivo (RTP)"

OBJETIVO_MAP: dict[str, str | None] = {
    "Mejorar rendimiento deportivo específico": "Rendimiento deportivo específico",
    "Aumentar fuerza máxima": "Fuerza máxima",
    "Mejorar composición corporal (hipertrofia)": "Hipertrofia",
    "Perder grasa corporal": "Recomposición corporal",
    "Prevención de lesiones": "Prevención de lesiones",
    "Rehabilitación y retorno deportivo": RTP_OPTION,
    "Mejorar resistencia física": "Resistencia física",
    "Mejorar salud general y calidad de vida": "Salud general y calidad de vida",
    # Sin equivalente exacto en OBJETIVO_OPTIONS -> texto libre.
    "Mejorar velocidad / potencia": None,
}

COL_NOMBRE = "Nombre y Apellido"
COL_TIMESTAMP = "Marca temporal"
COL_NACIMIENTO = "Fecha de Nacimiento"
COL_SEXO = "Sexo Biológico"
COL_ALTURA = "Talla (cm) – ej: 175"
COL_PESO = "Peso corporal aproximado (kg) – ej: 78"
COL_DEPORTE = "¿Cuál/es deportes practicás o practicabas? (especificá)"
COL_NIVEL = "Nivel competitivo alcanzado"
COL_OBJETIVOS = "¿Cuáles son tus objetivos principales? (marcá hasta 3)"


def _map_objectives(raw: object) -> tuple[str, list[str], str]:
    tokens = [t.strip() for t in str(raw or "").split(",") if t.strip()]
    mapped: list[str] = []
    unmapped: list[str] = []
    for token in tokens:
        target = OBJETIVO_MAP.get(token)
        if target and target not in mapped:
            mapped.append(target)
        elif target is None and token not in unmapped:
            unmapped.append(token)
    primario = mapped[0] if mapped else "Otro"
    secundarios = mapped[1:]
    return primario, secundarios, ", ".join(unmapped)


def _row_to_profile(row: pd.Series) -> dict[str, object]:
    altura = pd.to_numeric(pd.Series([row.get(COL_ALTURA)]), errors="coerce").iloc[0]
    if pd.notna(altura) and 0 < altura < 3:
        altura = round(altura * 100, 1)

    primario, secundarios, otro_texto = _map_objectives(row.get(COL_OBJETIVOS))
    es_rtp = RTP_OPTION in ([primario] + secundarios)

    deporte_raw = row.get(COL_DEPORTE)
    deporte = normalize_deporte(deporte_raw) if pd.notna(deporte_raw) else None

    nivel_raw = str(row.get(COL_NIVEL) or "").strip()

    return {
        "Athlete": str(row[COL_NOMBRE]).strip(),
        "Fecha_nacimiento": pd.Timestamp(row[COL_NACIMIENTO]).date().isoformat(),
        "Sexo": row.get(COL_SEXO),
        "Altura_cm": altura if pd.notna(altura) else None,
        "Peso_kg": row.get(COL_PESO),
        "Contexto": CONTEXTO_FIJO,
        "Deporte": deporte,
        "Nivel": NIVEL_MAP.get(nivel_raw, nivel_raw or None),
        "Objetivo_primario": primario,
        "Objetivos_secundarios": "|".join(secundarios),
        "Objetivo_otro_texto": otro_texto or None,
        "Es_RTP": es_rtp,
    }


def main() -> None:
    if len(sys.argv) != 2:
        print("Uso: python scripts/import_intake_profiles.py <ruta al xlsx>")
        sys.exit(1)

    xlsx_path = Path(sys.argv[1])
    if not xlsx_path.exists():
        print(f"No se encontro el archivo: {xlsx_path}")
        sys.exit(1)

    df = pd.read_excel(xlsx_path, sheet_name="Respuestas de formulario 1")
    df[COL_NOMBRE] = df[COL_NOMBRE].astype(str).str.strip()
    before = len(df)
    df = df.sort_values(COL_TIMESTAMP).drop_duplicates(COL_NOMBRE, keep="last")
    print(f"Respuestas en el archivo: {before} -> atletas unicos (ultima respuesta): {len(df)}")

    profile_csv_path = local_store._dataset_path("athlete_profile_df")
    if profile_csv_path.exists():
        backup_path = profile_csv_path.with_name(f"{profile_csv_path.stem}{BACKUP_SUFFIX}{profile_csv_path.suffix}")
        shutil.copy2(profile_csv_path, backup_path)
        print(f"Backup de perfiles existentes: {backup_path}")

    imported: list[str] = []
    errors: list[str] = []
    merged = None

    for _, row in df.iterrows():
        athlete = str(row[COL_NOMBRE]).strip()
        try:
            profile = _row_to_profile(row)
        except Exception as exc:
            errors.append(f"{athlete}: error armando el perfil ({exc})")
            continue

        validation_errors = validate_profile_fields(profile)
        if validation_errors:
            errors.append(f"{athlete}: {'; '.join(validation_errors)}")
            continue

        merged = local_store.upsert_athlete_profile(profile)
        imported.append(athlete)

    print(f"\nImportados a local: {len(imported)}")
    if errors:
        print(f"Con error (no se guardaron): {len(errors)}")
        for e in errors:
            print(f"  - {e}")

    if merged is None or merged.empty:
        print("No se importo ningun perfil, no hay nada para sincronizar.")
        return

    try:
        from modules.remote_store import save_remote_dataset, supabase_dataset_store_enabled

        if supabase_dataset_store_enabled():
            stats = save_remote_dataset("athlete_profile_df", merged)
            print(f"\nSupabase: {stats.get('upserted', 0)} fila(s) sincronizada(s).")
        else:
            print("\nSupabase no esta configurado en este entorno: quedo solo en local.")
    except Exception as exc:
        print(f"\nNo se pudo sincronizar con Supabase: {exc}")
        print("Los datos ya quedaron guardados en local de todas formas.")


if __name__ == "__main__":
    main()
