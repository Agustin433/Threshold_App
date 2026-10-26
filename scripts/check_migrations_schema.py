"""Compara las columnas reales de public.evaluations con lo que la app guarda.

Uso (CI, despues de aplicar supabase/migrations/ a un Postgres vacio):
    psql ... -At -c "select column_name from information_schema.columns
                     where table_schema='public' and table_name='evaluations'" > cols.txt
    python scripts/check_migrations_schema.py cols.txt

Sale con codigo 1 si alguna columna de EVALUATION_DB_COLUMN_MAP no existe en
la base construida solo con migraciones.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.data_loader import EVALUATION_DB_COLUMN_MAP  # noqa: E402

BOOKKEEPING_COLUMNS = {"created_at", "updated_at"}


def main(path: str) -> int:
    db_columns = {line.strip() for line in Path(path).read_text().splitlines() if line.strip()}
    if not db_columns:
        print("::error::No se leyo ninguna columna de public.evaluations")
        return 1
    mapped = set(EVALUATION_DB_COLUMN_MAP.values())
    missing = sorted(mapped - db_columns)
    unused = sorted(db_columns - mapped - BOOKKEEPING_COLUMNS)
    print(f"Columnas en la base: {len(db_columns)} | mapeadas por la app: {len(mapped)}")
    if unused:
        print(f"En la base pero la app no las usa (informativo): {', '.join(unused)}")
    if missing:
        print(
            "::error::La app guarda columnas que ninguna migracion crea: "
            + ", ".join(missing)
        )
        return 1
    print("OK: toda columna mapeada existe en la base creada solo con supabase/migrations/.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
