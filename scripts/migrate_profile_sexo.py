"""One-shot migration: add the Sexo column to existing athlete profiles.

Context: `Sexo` pasa a ser parte de la identidad de cohorte y a seleccionar la
tabla de referencia contra la que se calcula un z-score. Los perfiles cargados
antes de este cambio no lo tienen.

No se infiere el sexo de nadie. Todos los perfiles preexistentes quedan en
`no_especificado`, que es un valor valido del enum y bloquea explicitamente el
camino de z de literatura: esos atletas resuelven a banda de criterio o a
lectura intra-individual hasta que alguien complete el campo a mano.

Usage (una sola vez, desde la raiz del repo):
    .venv/Scripts/python.exe scripts/migrate_profile_sexo.py

Es seguro re-ejecutarlo: solo toca filas sin `Sexo` valido, y escribe un
backup antes de modificar el CSV vivo.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import local_store
from modules.athlete_profile import (
    ATHLETE_PROFILE_COLUMNS,
    Sexo,
    normalize_sexo,
    sexo_label,
)

BACKUP_SUFFIX = "_backup_pre_sexo"


def main() -> None:
    csv_path = local_store._dataset_path("athlete_profile_df")
    if not csv_path.exists():
        print(f"No hay archivo en {csv_path}, nada para migrar.")
        return

    backup_path = csv_path.with_name(f"{csv_path.stem}{BACKUP_SUFFIX}{csv_path.suffix}")
    if backup_path.exists():
        print(f"Backup ya existe, se conserva el original: {backup_path}")
    else:
        shutil.copy2(csv_path, backup_path)
        print(f"Backup creado: {backup_path}")

    df = pd.read_csv(csv_path)
    total = len(df)

    if "Sexo" not in df.columns:
        df["Sexo"] = str(Sexo.NO_ESPECIFICADO)
        backfilled = total
    else:
        normalized = df["Sexo"].map(lambda value: str(normalize_sexo(value)))
        backfilled = int((normalized == str(Sexo.NO_ESPECIFICADO)).sum())
        df["Sexo"] = normalized

    # Reordenar segun el esquema canonico, conservando columnas extra al final.
    ordered = [col for col in ATHLETE_PROFILE_COLUMNS if col in df.columns]
    extra = [col for col in df.columns if col not in ordered]
    df = df[ordered + extra]

    df.to_csv(csv_path, index=False)
    print(f"Perfiles totales: {total} · quedaron en 'no_especificado': {backfilled}")

    reloaded = local_store.read_full_dataset("athlete_profile_df")
    if reloaded.empty:
        print("El dataset quedo vacio.")
        return

    print("\n--- Verificacion post-migracion ---")
    counts = reloaded["Sexo"].map(lambda value: sexo_label(value)).value_counts()
    for label, count in counts.items():
        print(f"  {label}: {count} perfil(es)")
    print(
        "\nLos perfiles en 'No especificado' no pueden resolver a z de literatura.\n"
        "Completar el campo a mano en la app para habilitarlo."
    )


if __name__ == "__main__":
    main()
