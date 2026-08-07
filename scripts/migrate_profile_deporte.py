"""One-shot migration: unifica las grafias del campo Deporte en los perfiles.

Context: `Deporte` se cargaba con un campo de texto libre, asi que el mismo
deporte quedo escrito de varias formas ("Futbol", "Futboll", "Futbo"). Eso
fragmenta cualquier agrupacion por deporte: tres atletas de futbol aparecian
como tres grupos de uno.

El campo pasa a cargarse desde una lista cerrada, y este script normaliza lo
que ya estaba guardado con `normalize_deporte`. Los deportes que no estan en
la lista se conservan tal cual: son datos validos cargados por la opcion
"Otro", no errores de tipeo.

Usage (una sola vez, desde la raiz del repo):
    .venv/Scripts/python.exe scripts/migrate_profile_deporte.py

Es seguro re-ejecutarlo y escribe un backup antes de tocar el CSV vivo.
"""

from __future__ import annotations

import shutil
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import local_store
from modules.athlete_profile import normalize_deporte

BACKUP_SUFFIX = "_backup_pre_deporte"


def main() -> None:
    csv_path = local_store._dataset_path("athlete_profile_df")
    if not csv_path.exists():
        print(f"No hay archivo en {csv_path}, nada para migrar.")
        return

    backup_path = csv_path.with_name(f"{csv_path.stem}{BACKUP_SUFFIX}{csv_path.suffix}")
    shutil.copy2(csv_path, backup_path)
    print(f"Backup creado: {backup_path}")

    df = pd.read_csv(csv_path)
    if "Deporte" not in df.columns:
        print("El perfil no tiene columna Deporte, nada para migrar.")
        return

    antes = Counter(
        str(value).strip()
        for value in df["Deporte"].dropna()
        if str(value).strip() and str(value).strip().lower() != "nan"
    )
    df["Deporte"] = df["Deporte"].map(normalize_deporte)
    despues = Counter(df["Deporte"].dropna())

    cambios = sum(
        1
        for original, normalizado in zip(pd.read_csv(csv_path)["Deporte"], df["Deporte"])
        if str(original).strip() != str(normalizado or "")
    )
    df.to_csv(csv_path, index=False)

    print(f"\nAntes:   {dict(antes)}")
    print(f"Despues: {dict(despues)}")
    print(f"Filas normalizadas: {cambios}")

    reloaded = local_store.read_full_dataset("athlete_profile_df")
    if not reloaded.empty and "Deporte" in reloaded.columns:
        print("\n--- Verificacion post-migracion ---")
        for deporte, count in Counter(reloaded["Deporte"].dropna()).most_common():
            print(f"  {deporte}: {count} atleta(s)")


if __name__ == "__main__":
    main()
