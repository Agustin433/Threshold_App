"""One-shot migration: backfill DJ_drop_height_cm on existing DJ evaluations.

Context: Involution's forceplate export never included a drop-height column,
so `calc_dri()` (modules/jump_analysis.py) had no way to compute DRI for any
historical DJ test and silently produced NaN for all of them. Every DJ test
on file was performed at a 30cm box, EXCEPT Christian Heredia and Agustin
Esterman, who tested at 40cm. `resolve_dj_drop_height_series` (in
modules/jump_analysis.py) encodes that per-athlete exception; this script
just applies it row by row instead of hardcoding 30cm for everyone.

Usage (run once from the repo root):
    .venv/Scripts/python.exe scripts/migrate_dj_drop_height.py

Safe to re-run: it only touches rows that still have DJ_cm/DJ_tc_ms but a
missing/blank DJ_drop_height_cm, and it always writes a fresh timestamped-free
backup (overwriting any previous one) before touching the live CSV.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

import local_store
from modules.jump_analysis import resolve_dj_drop_height_series

DEFAULT_DROP_HEIGHT_CM = 30.0
BACKUP_SUFFIX = "_backup_pre_dri_fix"


def main() -> None:
    csv_path = local_store._dataset_path("jump_df")
    if not csv_path.exists():
        print(f"No hay archivo en {csv_path}, nada para migrar.")
        return

    backup_path = csv_path.with_name(f"{csv_path.stem}{BACKUP_SUFFIX}{csv_path.suffix}")
    shutil.copy2(csv_path, backup_path)
    print(f"Backup creado: {backup_path}")

    df = pd.read_csv(csv_path)
    if "DJ_drop_height_cm" not in df.columns:
        df["DJ_drop_height_cm"] = pd.NA

    dj_cm = pd.to_numeric(df.get("DJ_cm"), errors="coerce")
    dj_tc_ms = pd.to_numeric(df.get("DJ_tc_ms"), errors="coerce")
    drop_height = pd.to_numeric(df["DJ_drop_height_cm"], errors="coerce")

    target_mask = dj_cm.notna() & dj_tc_ms.notna() & drop_height.isna()
    affected = int(target_mask.sum())
    df.loc[target_mask, "DJ_drop_height_cm"] = resolve_dj_drop_height_series(
        df.loc[target_mask, "Athlete"], DEFAULT_DROP_HEIGHT_CM
    )

    df.to_csv(csv_path, index=False)
    print(
        f"Filas migradas: {affected} "
        f"({DEFAULT_DROP_HEIGHT_CM:g} cm por defecto, 40 cm para Christian Heredia y Agustin Esterman)"
    )

    verify_columns = ["Athlete", "Date", "DJ_cm", "DJ_tc_ms", "DJ_drop_height_cm", "DRI", "DRI_Z"]
    reloaded = local_store.read_full_dataset("jump_df")
    reloaded_cols = [c for c in verify_columns if c in reloaded.columns]

    print("\n--- Verificacion post-migracion (local_store.read_full_dataset) ---")
    reloaded_dj_cm = pd.to_numeric(reloaded.get("DJ_cm"), errors="coerce")
    reloaded_dj_tc_ms = pd.to_numeric(reloaded.get("DJ_tc_ms"), errors="coerce")
    still_nan = reloaded.loc[reloaded["DRI"].isna() & reloaded_dj_cm.notna() & reloaded_dj_tc_ms.notna()]
    print(f"Filas con DJ_cm/DJ_tc_ms presentes pero DRI aun NaN: {len(still_nan)}")

    sample_athletes = ["Agustin Esterman", "Alejandro Anadon", "Santiago Gray"]
    sample = reloaded[reloaded["Athlete"].isin(sample_athletes)]
    print("\nMuestra (3 atletas de referencia):")
    print(sample[reloaded_cols].to_string(index=False))


if __name__ == "__main__":
    main()
