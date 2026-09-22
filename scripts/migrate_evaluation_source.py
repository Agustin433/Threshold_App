"""One-shot migration: add the Source column to the local evaluations history.

Context: evaluations used to be keyed by (Athlete, Date) alone, which assumed
every measurement came from the same device. Once MyJump2 / contact-mat data
can be loaded, that assumption breaks: a plate and a mat measurement on the
same day would collapse into a single row and one would silently overwrite the
other. `Source` is now part of the dedupe key (see local_store.DATASET_SPECS).

Every row recorded before this change came from the force platform, so
backfilling `platform` is a statement of fact, not a guess.

Usage (run once from the repo root):
    .venv/Scripts/python.exe scripts/migrate_evaluation_source.py

Safe to re-run: rows that already carry a Source are left untouched, and a
fresh backup is written before the live CSV is modified.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pandas as pd

# Al invocar `python scripts/x.py`, sys.path[0] es scripts/, no la raiz del
# repo, asi que los modulos de la app no se resuelven sin esto.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import local_store
from modules.evaluation_sources import (
    DEFAULT_SOURCE,
    SOURCE_LABELS,
    normalize_source,
)

BACKUP_SUFFIX = "_backup_pre_source_split"


def main() -> None:
    csv_path = local_store._dataset_path("jump_df")
    if not csv_path.exists():
        print(f"No hay archivo en {csv_path}, nada para migrar.")
        return

    backup_path = csv_path.with_name(f"{csv_path.stem}{BACKUP_SUFFIX}{csv_path.suffix}")
    shutil.copy2(csv_path, backup_path)
    print(f"Backup creado: {backup_path}")

    df = pd.read_csv(csv_path)
    total = len(df)

    if "Source" not in df.columns:
        df["Source"] = DEFAULT_SOURCE
        backfilled = total
    else:
        missing_mask = df["Source"].isna() | (df["Source"].astype(str).str.strip() == "")
        backfilled = int(missing_mask.sum())
        df.loc[missing_mask, "Source"] = DEFAULT_SOURCE
        df["Source"] = df["Source"].map(normalize_source)

    if "Device" not in df.columns:
        df["Device"] = pd.NA

    df.to_csv(csv_path, index=False)
    print(f"Filas totales: {total} · backfilleadas a '{DEFAULT_SOURCE}': {backfilled}")

    reloaded = local_store.read_full_dataset("jump_df")
    print("\n--- Verificacion post-migracion (local_store.read_full_dataset) ---")
    if reloaded.empty:
        print("El dataset quedo vacio.")
        return

    counts = reloaded["Source"].map(normalize_source).value_counts()
    for source_key, count in counts.items():
        print(f"  {SOURCE_LABELS.get(source_key, source_key)}: {count} fila(s)")

    duplicated = reloaded.duplicated(subset=["Athlete", "Date", "Source"]).sum()
    print(f"Duplicados por (Athlete, Date, Source): {duplicated}")
    if duplicated:
        print("  ATENCION: revisar antes de seguir, no deberia haber ninguno.")


if __name__ == "__main__":
    main()
