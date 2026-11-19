"""Benchmark de velocidad por vista con AppTest y datos de tamano real.

Uso:
    python scripts/benchmark_views.py            # siembra un store temporal y mide
    python scripts/benchmark_views.py --keep     # deja el store sembrado (imprime ruta)

Volumen sembrado (igual al export real de oct/2026): 82.791 series de Raw
Workouts y 12.482 maximos, 30 atletas, ~1 ano de historia. Los datos son
sinteticos (determinísticos, seed fija): miden costo de computo, no contenido.

Metodo: AppTest.from_file(app.py). "primera carga" = primer at.run() en
Overview (hidrata el store). "rerun" = at.run() sin cambios en la vista.
"entrar" = cambio de vista principal; "cambio selector" = mover el selector
de atleta en Profile / Team.
"""

from __future__ import annotations

import argparse
import importlib
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

RAW_ROWS = 82_791
MAXES_ROWS = 12_482
N_ATHLETES = 30

FIRST = ["Ana", "Bruno", "Carla", "Diego", "Elena", "Facundo", "Gina", "Hugo", "Ines", "Juan",
         "Karen", "Lucas", "Maria", "Nicolas", "Olga", "Pablo", "Quimey", "Rocio", "Santiago", "Tamara"]
LAST = ["Lopez", "Garcia", "Perez", "Diaz", "Romero", "Sosa", "Torres", "Alvarez", "Ruiz", "Gomez"]
EXERCISES = [
    ("Back Squat", "Dominante de Rodilla", 100.0),
    ("Romanian Deadlift", "Dominante de Cadera", 90.0),
    ("Bench Press", "Empuje Horizontal", 70.0),
    ("Pull Up", "Traccion Vertical", 10.0),
    ("Bulgarian Split Squat", "Dominante de Rodilla/Stance_Split", 30.0),
    ("Barbell Row", "Traccion Horizontal", 60.0),
    ("Overhead Press", "Empuje Vertical", 45.0),
    ("Box Jump", "Jump_Plyo", 0.0),
    ("Power Clean", "DLO", 65.0),
    ("Nordic Curl", "Accessories MMII/Ham_Curl", 0.0),
]


def _athletes() -> list[str]:
    return [f"{FIRST[i % len(FIRST)]} {LAST[(i * 7) % len(LAST)]}{'' if i < 20 else ' B'}" for i in range(N_ATHLETES)]


def seed_store(store_dir: Path) -> None:
    from modules.app_clock import app_today

    rng = np.random.default_rng(433)
    today = app_today()
    start = today - pd.Timedelta(days=364)
    athletes = _athletes()
    days = pd.date_range(start, today, freq="D")
    training_days = [d for d in days if d.dayofweek in (0, 2, 4)]

    # ── Raw Workouts (formato export TeamBuildr) ─────────────────────
    rows = []
    workout_id = 1000
    for athlete in athletes:
        for day in training_days:
            for ex_idx in rng.choice(len(EXERCISES), size=6, replace=False):
                name, tag, base = EXERCISES[ex_idx]
                workout_id += 1
                for set_number in range(1, 4):
                    completed = day - pd.Timedelta(days=int(rng.integers(0, 2)))
                    rows.append((
                        athlete, day.strftime("%Y-%m-%d"), completed.strftime("%Y-%m-%d"), workout_id,
                        name, set_number, round(base * (0.9 + 0.2 * rng.random()), 1),
                        int(rng.integers(3, 10)), tag,
                    ))
    raw = pd.DataFrame(rows, columns=["Athlete", "Assigned Date", "Completed Date", "WorkoutId",
                                      "Exercise Name", "Set Number", "Result", "Reps", "Tags"])
    raw = raw.iloc[:RAW_ROWS]
    raw_csv = store_dir.parent / "raw_export.csv"
    raw.to_csv(raw_csv, index=False)

    # ── Maxes ────────────────────────────────────────────────────────
    max_rows = []
    for i in range(MAXES_ROWS):
        athlete = athletes[i % N_ATHLETES]
        name, _, base = EXERCISES[(i // N_ATHLETES) % len(EXERCISES)]
        added = days[int(rng.integers(0, len(days)))]
        max_rows.append({"Max ID": 500000 + i, "Athlete": athlete, "Added Date": added.strftime("%Y-%m-%d"),
                         "Exercise Name": name, "Max Value": round(max(base, 20.0) * (1 + 0.3 * rng.random()), 1)})
    maxes = pd.DataFrame(max_rows)
    maxes_csv = store_dir.parent / "maxes_export.csv"
    maxes.to_csv(maxes_csv, index=False)

    # ── sRPE y wellness ──────────────────────────────────────────────
    rpe_rows, well_rows = [], []
    for athlete in athletes:
        for day in training_days:
            rpe = int(rng.integers(4, 9))
            dur = int(rng.integers(45, 90))
            rpe_rows.append({"Athlete": athlete, "Date": day.strftime("%Y-%m-%d"), "RPE": rpe,
                             "Duration_min": dur, "sRPE": float(rpe * dur)})
        for day in days[::2]:
            sueno, estres, dolor = float(rng.integers(5, 10)), int(rng.integers(3, 9)), int(rng.integers(3, 9))
            well_rows.append({"Athlete": athlete, "Date": day.strftime("%Y-%m-%d"), "Sueno_hs": sueno,
                              "Estres": estres, "Dolor": dolor, "Wellness_Score": float(sueno + estres + dolor)})
    pd.DataFrame(rpe_rows).to_csv(store_dir / "rpe_history.csv", index=False)
    pd.DataFrame(well_rows).to_csv(store_dir / "wellness_history.csv", index=False)

    pd.DataFrame([
        {"Athlete": a, "Assigned": 150, "Completed": int(rng.integers(90, 150)), "Pct": None, "Percent": None,
         "completion_scope": "uploaded_period_total", "source_type": "completion_report_summary"}
        for a in athletes
    ]).assign(Pct=lambda d: (d["Completed"] / d["Assigned"] * 100).round(2),
              Percent=lambda d: d["Pct"].astype(str) + "%").to_csv(store_dir / "completion_history.csv", index=False)

    # ── Evaluaciones (plataforma + no-plataforma) ────────────────────
    eval_rows = []
    for idx, athlete in enumerate(athletes):
        bw = 60.0 + idx
        for take in range(8):
            date = (today - pd.Timedelta(days=330 - take * 45)).strftime("%Y-%m-%d")
            cmj = 30.0 + idx * 0.3 + take * 0.4 + rng.normal(0, 1)
            sj = cmj * 0.93
            eval_rows.append({
                "Athlete": athlete, "Date": date, "Source": "platform", "BW_kg": bw,
                "CMJ_cm": round(cmj, 2), "SJ_cm": round(sj, 2), "EUR": round(cmj / sj, 4),
                "DJ_cm": round(cmj * 0.85, 2), "DJ_tc_ms": float(rng.integers(170, 240)),
                "DJ_drop_height_cm": 30.0, "IMTP_N": round(2200 + idx * 40 + take * 30 + rng.normal(0, 50), 1),
            })
            if take % 3 == 0:
                eval_rows.append({"Athlete": athlete, "Date": date, "Source": "nonplatform", "BW_kg": bw,
                                  "CMJ_cm": round(cmj - 1, 2), "SJ_cm": round(sj - 1, 2)})
    pd.DataFrame(eval_rows).to_csv(store_dir / "evaluations_history.csv", index=False)

    import local_store as local_store_module
    local_store_module = importlib.reload(local_store_module)
    from modules.data_loader import parse_maxes_health, parse_raw_workouts

    class _Upload:
        def __init__(self, path: Path):
            self._path = path
            self.name = path.name

        def read(self, *args):
            return self._path.read_bytes()

        def seek(self, *args):
            return 0

        def getvalue(self):
            return self._path.read_bytes()

    local_store_module.save_dataset("raw_df", parse_raw_workouts(_Upload(raw_csv)))
    local_store_module.save_dataset("maxes_df", parse_maxes_health(_Upload(maxes_csv)))
    for idx, athlete in enumerate(athletes):
        local_store_module.upsert_athlete_profile({
            "Athlete": athlete, "Sexo": "Masculino" if idx % 2 == 0 else "Femenino",
            "Contexto": "Club", "Deporte": "Handball", "Nivel": "Competitivo",
            "Objetivo_primario": "Fuerza máxima", "Es_RTP": False,
        })
    local_store_module.persist_athlete_names(athletes)
    raw_csv.unlink(missing_ok=True)
    maxes_csv.unlink(missing_ok=True)


def _timed(label: str, fn, results: list[tuple[str, float]]):
    started = time.perf_counter()
    at = fn()
    elapsed = time.perf_counter() - started
    if at is not None and at.exception:
        raise RuntimeError(f"{label}: {at.exception}")
    results.append((label, elapsed))
    print(f"{label:<45} {elapsed:6.2f} s", flush=True)
    return at


def _nav(at, view: str):
    nav = next(bg for bg in at.button_group if bg.label == "Vista principal")
    return nav.set_value(view).run()


def _athlete_select(at):
    for box in at.selectbox:
        if box.label and "tleta" in box.label and len(box.options) > 2:
            return box
    return None


def run_benchmark(store_dir: Path) -> list[tuple[str, float]]:
    from streamlit.testing.v1 import AppTest

    os.environ["THRESHOLD_STORE_DIR"] = str(store_dir)
    import local_store as local_store_module
    importlib.reload(local_store_module)

    results: list[tuple[str, float]] = []
    at = AppTest.from_file(str(APP_ROOT / "app.py"), default_timeout=600)
    _timed("Overview · primera carga", at.run, results)
    _timed("Overview · rerun", at.run, results)
    _timed("Overview · rerun (2)", at.run, results)
    for view in ("Decision", "Load", "Análisis Plataforma", "Profile", "Team", "Reports"):
        _timed(f"{view} · entrar", lambda v=view: _nav(at, v), results)
        _timed(f"{view} · rerun", at.run, results)
        if view in ("Profile", "Team", "Análisis Plataforma"):
            box = _athlete_select(at)
            if box is not None:
                current = box.value
                target = next(opt for opt in box.options if opt != current)
                _timed(f"{view} · cambio selector atleta", lambda b=box, t=target: b.set_value(t).run(), results)
    _timed("Overview · volver", lambda: _nav(at, "Overview"), results)
    _timed("Overview · rerun (final)", at.run, results)
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--store", type=Path, default=None, help="usar un store ya sembrado")
    args = parser.parse_args()

    tmp_root = None
    if args.store:
        store_dir = args.store
    else:
        tmp_root = Path(tempfile.mkdtemp(prefix="threshold_bench_"))
        store_dir = tmp_root / "store"
        store_dir.mkdir(parents=True)
        os.environ["THRESHOLD_STORE_DIR"] = str(store_dir)
        t0 = time.perf_counter()
        seed_store(store_dir)
        print(f"store sembrado en {time.perf_counter() - t0:.1f} s -> {store_dir}", flush=True)
    try:
        run_benchmark(store_dir)
    finally:
        if tmp_root is not None and not args.keep:
            shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    main()
