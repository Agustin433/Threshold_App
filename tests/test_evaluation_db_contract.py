"""Contrato entre las columnas de evaluacion de la app y la tabla evaluations.

Cubre el bug de octubre 2026: cinco metricas de CMJ estaban en
EVALUATION_PERSIST_COLUMNS pero no en EVALUATION_DB_COLUMN_MAP, y cada
guardado de un CMJ de plataforma terminaba en KeyError.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from modules import remote_store
from modules.data_loader import EVALUATION_DB_COLUMN_MAP, EVALUATION_PERSIST_COLUMNS
from modules.remote_store import (
    EvaluationColumnMappingError,
    jump_df_to_db_records,
    unmapped_evaluation_persist_columns,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

CMJ_FORMER_LOCAL_ONLY = {
    "CMJ_propulsive_PF_N": "cmj_propulsive_pf_n",
    "CMJ_rel_impulse": "cmj_rel_impulse",
    "CMJ_landing_force_N": "cmj_landing_force_n",
    "CMJ_landing_asym_pct": "cmj_landing_asym_pct",
    "CMJ_stabilization_ms": "cmj_stabilization_ms",
}

_IDENT = r"([a-z_][a-z0-9_]*)"
_NOT_COLUMNS = {"primary", "constraint", "unique", "foreign", "check"}


MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"


def _evaluations_schema_columns() -> set[str]:
    """Columnas de public.evaluations segun SOLO supabase/migrations/.

    Nunca se lee supabase_evaluations_schema.sql: ese script describe lo que
    "deberia" haber y llego a listar 17 columnas que produccion no tenia,
    con este mismo test en verde. Las migraciones se recorren en orden de
    version, igual que las aplica la CLI de Supabase.
    """
    columns: set[str] = set()
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8").lower())
        create = re.search(
            r"create table (?:if not exists )?public\.evaluations\s*\((.*?)\n\);", sql, re.S
        )
        if create:
            for line in create.group(1).splitlines():
                match = re.match(r"\s*" + _IDENT + r"\s+\w", line)
                if match and match.group(1) not in _NOT_COLUMNS:
                    columns.add(match.group(1))
        columns.update(
            re.findall(
                r"public\.evaluations\s+add column (?:if not exists )?" + _IDENT, sql
            )
        )
        for dropped in re.findall(
            r"public\.evaluations\s+drop column (?:if exists )?" + _IDENT, sql
        ):
            columns.discard(dropped)
    return columns


class EvaluationDbContractTest(unittest.TestCase):
    def test_every_persist_column_has_db_mapping(self):
        self.assertEqual(unmapped_evaluation_persist_columns(), [])

    def test_every_mapped_db_column_exists_in_versioned_schema(self):
        schema_columns = _evaluations_schema_columns()
        self.assertIn("athlete", schema_columns)  # el parser del SQL funciona
        missing = sorted(set(EVALUATION_DB_COLUMN_MAP.values()) - schema_columns)
        self.assertEqual(
            missing,
            [],
            "Columnas mapeadas que ninguna migracion de supabase/migrations/ crea: "
            f"{missing}. Agrega un archivo de migracion con su add column.",
        )

    def test_former_local_only_cmj_columns_are_persisted(self):
        for app_col, db_col in CMJ_FORMER_LOCAL_ONLY.items():
            self.assertIn(app_col, EVALUATION_PERSIST_COLUMNS)
            self.assertEqual(EVALUATION_DB_COLUMN_MAP.get(app_col), db_col)

    def test_cmj_frame_with_five_metrics_builds_record_with_five_columns(self):
        values = {
            "CMJ_propulsive_PF_N": 2650.5,
            "CMJ_rel_impulse": 2.81,
            "CMJ_landing_force_N": 4120.0,
            "CMJ_landing_asym_pct": 4.1,
            "CMJ_stabilization_ms": np.float64(612.0),
        }
        df = pd.DataFrame(
            [
                {
                    "Athlete": "ana lopez",
                    "Date": pd.Timestamp("2026-10-20"),
                    "Source": "platform",
                    "CMJ_cm": 32.0,
                    **values,
                }
            ]
        )

        records = jump_df_to_db_records(df)

        self.assertEqual(len(records), 1)
        record = records[0]
        for app_col, db_col in CMJ_FORMER_LOCAL_ONLY.items():
            self.assertIn(db_col, record)
            self.assertIsInstance(record[db_col], float)
            self.assertAlmostEqual(record[db_col], float(values[app_col]))
        self.assertEqual(record["date"], "2026-10-20")
        self.assertEqual(record["cmj_cm"], 32.0)

    def test_unmapped_column_raises_clear_error_naming_it(self):
        broken_map = {
            k: v for k, v in EVALUATION_DB_COLUMN_MAP.items() if k != "CMJ_landing_asym_pct"
        }
        df = pd.DataFrame(
            [
                {
                    "Athlete": "Ana Lopez",
                    "Date": "2026-10-20",
                    "CMJ_cm": 32.0,
                    "CMJ_landing_asym_pct": 4.1,
                }
            ]
        )
        with patch.object(remote_store, "EVALUATION_DB_COLUMN_MAP", broken_map):
            self.assertEqual(
                unmapped_evaluation_persist_columns(), ["CMJ_landing_asym_pct"]
            )
            with self.assertRaises(EvaluationColumnMappingError) as ctx:
                jump_df_to_db_records(df)

        self.assertNotIsInstance(ctx.exception, KeyError)
        self.assertIn("CMJ_landing_asym_pct", str(ctx.exception))

    def test_unmapped_column_absent_from_frame_does_not_block_save(self):
        broken_map = {
            k: v for k, v in EVALUATION_DB_COLUMN_MAP.items() if k != "CMJ_landing_asym_pct"
        }
        df = pd.DataFrame([{"Athlete": "Ana Lopez", "Date": "2026-10-20", "SJ_cm": 28.0}])
        with patch.object(remote_store, "EVALUATION_DB_COLUMN_MAP", broken_map):
            records = jump_df_to_db_records(df)
        self.assertEqual(records[0]["sj_cm"], 28.0)


if __name__ == "__main__":
    unittest.main()
