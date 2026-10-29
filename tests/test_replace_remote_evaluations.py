"""Gestion de Historial > "Publicar local -> Supabase" para evaluaciones.

Bug: la identidad era (atleta, fecha) y la PK real es (atleta, fecha, fuente).
Una medicion de plataforma y una de alfombra del mismo dia se pisaban.
Se prueba contra una tabla falsa en memoria que imita PostgREST y la PK.
"""

from __future__ import annotations

import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import pandas as pd

from modules import history_manager, remote_store
from modules.remote_store import RemoteSaveError, SupabaseHTTPError

SERVICE_ENV = {"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "service-key"}
PK = ("athlete", "date", "source")


@contextmanager
def patched_env():
    original = {key: os.environ.get(key) for key in SERVICE_ENV}
    os.environ.update(SERVICE_ENV)
    try:
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class FakeEvaluationsTable:
    """PostgREST minimo: filtros eq., select, paginado, PK unica."""

    def __init__(self, rows: list[dict], fail_on: tuple[str, str] | None = None):
        self.rows = [dict(row) for row in rows]
        self.fail_on = fail_on
        self.deletes: list[dict] = []

    @staticmethod
    def _matches(row: dict, query: dict) -> bool:
        for key, value in (query or {}).items():
            if isinstance(value, str) and value.startswith("eq."):
                if str(row.get(key)) != value[3:]:
                    return False
        return True

    def _check_pk(self) -> None:
        keys = [tuple(row.get(col) for col in PK) for row in self.rows]
        if len(keys) != len(set(keys)):
            raise SupabaseHTTPError(409, "Conflict", '{"code":"23505","message":"duplicate key"}')

    def request(self, method, table, query=None, payload=None, prefer=None, **kwargs):
        query = query or {}
        if method == "GET":
            columns = query.get("select", "*").split(",")
            offset, limit = int(query.get("offset", 0)), int(query.get("limit", 1000))
            page = self.rows[offset : offset + limit]
            return [{col: row.get(col) for col in columns} for row in page]
        if method == "PATCH":
            if self.fail_on and (payload.get("athlete"), payload.get("source")) == self.fail_on:
                raise SupabaseHTTPError(500, "Internal Server Error", "{}")
            matched = [row for row in self.rows if self._matches(row, query)]
            for row in matched:
                row.update(payload)
            self._check_pk()
            return [dict(row) for row in matched]
        if method == "POST":
            self.rows.append(dict(payload))
            self._check_pk()
            return [dict(payload)]
        if method == "DELETE":
            matched = [row for row in self.rows if self._matches(row, query)]
            self.rows = [row for row in self.rows if row not in matched]
            self.deletes.append(dict(query))
            return matched
        raise AssertionError(method)

    def get(self, athlete: str, date: str, source: str) -> dict | None:
        return next(
            (row for row in self.rows if (row["athlete"], row["date"], row["source"]) == (athlete, date, source)),
            None,
        )


def _local(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _run(table: FakeEvaluationsTable, local_df: pd.DataFrame) -> dict:
    with patched_env(), patch.object(history_manager, "_supabase_request", side_effect=table.request), patch.object(
        remote_store, "_supabase_request", side_effect=table.request
    ):
        return history_manager.replace_remote_history("jump_df", local_df)


DAY = "2026-10-20"


class ReplaceRemoteEvaluationsTest(unittest.TestCase):
    def test_platform_and_mat_same_day_keep_their_own_values(self):
        table = FakeEvaluationsTable(
            [
                {"athlete": "Ana Lopez", "date": DAY, "source": "platform", "cmj_cm": 30.0},
                {"athlete": "Ana Lopez", "date": DAY, "source": "nonplatform", "cmj_cm": 28.0},
            ]
        )
        local_df = _local(
            [
                {"Athlete": "Ana Lopez", "Date": DAY, "Source": "platform", "CMJ_cm": 31.0},
                {"Athlete": "Ana Lopez", "Date": DAY, "Source": "nonplatform", "CMJ_cm": 29.0},
            ]
        )
        stats = _run(table, local_df)
        self.assertEqual(stats["upserted"], 2)
        self.assertEqual(stats["deleted"], 0)
        self.assertEqual(table.get("Ana Lopez", DAY, "platform")["cmj_cm"], 31.0)
        self.assertEqual(table.get("Ana Lopez", DAY, "nonplatform")["cmj_cm"], 29.0)
        self.assertEqual(len(table.rows), 2)

    def test_mat_row_is_not_overwritten_with_platform_data(self):
        # Remoto: solo alfombra. Local: solo plataforma ese dia.
        table = FakeEvaluationsTable([{"athlete": "Ana Lopez", "date": DAY, "source": "nonplatform", "cmj_cm": 28.0}])
        local_df = _local([{"Athlete": "Ana Lopez", "Date": DAY, "Source": "platform", "CMJ_cm": 31.0}])
        stats = _run(table, local_df)
        # La de plataforma se inserta como fila propia; la de alfombra, que ya
        # no esta en local, se borra por su propia clave (nunca se reescribe).
        self.assertEqual(table.get("Ana Lopez", DAY, "platform")["cmj_cm"], 31.0)
        self.assertIsNone(table.get("Ana Lopez", DAY, "nonplatform"))
        self.assertEqual(stats["deleted"], 1)
        self.assertEqual(table.deletes, [{"athlete": "eq.Ana Lopez", "date": f"eq.{DAY}", "source": "eq.nonplatform"}])

    def test_only_the_missing_source_is_deleted(self):
        table = FakeEvaluationsTable(
            [
                {"athlete": "Ana Lopez", "date": DAY, "source": "platform", "cmj_cm": 30.0},
                {"athlete": "Ana Lopez", "date": DAY, "source": "nonplatform", "cmj_cm": 28.0},
            ]
        )
        local_df = _local([{"Athlete": "Ana Lopez", "Date": DAY, "Source": "platform", "CMJ_cm": 30.0}])
        stats = _run(table, local_df)
        self.assertIsNotNone(table.get("Ana Lopez", DAY, "platform"))
        self.assertIsNone(table.get("Ana Lopez", DAY, "nonplatform"))
        self.assertEqual(stats["deleted"], 1)

    def test_failed_upsert_raises_and_deletes_nothing(self):
        table = FakeEvaluationsTable(
            [
                {"athlete": "Ana Lopez", "date": DAY, "source": "platform", "cmj_cm": 30.0},
                {"athlete": "Bruno Rey", "date": DAY, "source": "platform", "cmj_cm": 40.0},
            ],
            fail_on=("Ana Lopez", "platform"),
        )
        # Bruno ya no esta en local: se borraria si el upsert saliera bien.
        local_df = _local([{"Athlete": "Ana Lopez", "Date": DAY, "Source": "platform", "CMJ_cm": 31.0}])
        with self.assertRaises(RemoteSaveError) as ctx:
            _run(table, local_df)
        self.assertIn("No se borro nada", str(ctx.exception))
        self.assertEqual(table.deletes, [])
        self.assertIsNotNone(table.get("Bruno Rey", DAY, "platform"))


if __name__ == "__main__":
    unittest.main()
