"""Benchmark de velocidad por vista con AppTest y datos de tamano real.

Uso:
    python scripts/benchmark_views.py            # siembra un store temporal y mide
    python scripts/benchmark_views.py --keep     # deja el store sembrado (imprime ruta)

Volumen sembrado (igual al export real de oct/2026): 82.791 series de Raw
Workouts y 12.482 maximos, 30 atletas, ~1 ano de historia. Los datos son
sinteticos (determinísticos, seed fija): miden costo de computo, no contenido.

Metodo: AppTest.from_file(app.py). "primera carga" = primer at.run() en la
vista por defecto (hidrata el store). "rerun" = at.run() sin cambios en la vista.
"entrar" = cambio de vista principal; "cambio selector" = mover el selector
de atleta en Profile / Team (PR O) o el selector compartido de Atleta (PR P);
"abrir pestana" = cambiar la pestana activa (pestanas con estado).
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


TEAMBUILDR_LIFT_NAMES = {
    "Back Squat": "Barbell Back Squat",
    "Bench Press": "Barbell Bench Press",
    "Overhead Press": "Barbell Military Press",
}


def _athletes() -> list[str]:
    return [f"{FIRST[i % len(FIRST)]} {LAST[(i * 7) % len(LAST)]}{'' if i < 20 else ' B'}" for i in range(N_ATHLETES)]


def seed_store(
    store_dir: Path,
    *,
    n_athletes: int = N_ATHLETES,
    days_back: int = 364,
    raw_rows: int | None = RAW_ROWS,
    maxes_rows: int = MAXES_ROWS,
    flight_times: bool = False,
    teambuildr_lift_names: bool = False,
) -> None:
    """Siembra un store sintetico. Los defaults son los del benchmark (tamano real).

    `flight_times=True` agrega CMJ por tiempo de vuelo (el mapa del gimnasio lo
    necesita) y `teambuildr_lift_names=True` usa los nombres de TeamBuildr de
    los levantamientos principales (la fuerza estimada los necesita). El
    benchmark los deja apagados para medir siempre el mismo store.
    """
    from modules.app_clock import app_today

    rng = np.random.default_rng(433)
    today = app_today()
    start = today - pd.Timedelta(days=days_back)
    athletes = _athletes()[:n_athletes] if n_athletes <= N_ATHLETES else [f"Atleta {i:02d}" for i in range(n_athletes)]
    days = pd.date_range(start, today, freq="D")
    training_days = [d for d in days if d.dayofweek in (0, 2, 4)]

    # ── Raw Workouts (formato export TeamBuildr) ─────────────────────
    rows = []
    workout_id = 1000
    for athlete in athletes:
        for day in training_days:
            for ex_idx in rng.choice(len(EXERCISES), size=6, replace=False):
                name, tag, base = EXERCISES[ex_idx]
                if teambuildr_lift_names:
                    name = TEAMBUILDR_LIFT_NAMES.get(name, name)
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
    if raw_rows is not None:
        raw = raw.iloc[:raw_rows]
    raw_csv = store_dir.parent / "raw_export.csv"
    raw.to_csv(raw_csv, index=False)

    # ── Maxes ────────────────────────────────────────────────────────
    max_rows = []
    for i in range(maxes_rows):
        athlete = athletes[i % len(athletes)]
        name, _, base = EXERCISES[(i // len(athletes)) % len(EXERCISES)]
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
            date = (today - pd.Timedelta(days=int((330 - take * 45) * days_back / 364))).strftime("%Y-%m-%d")
            cmj = 30.0 + idx * 0.3 + take * 0.4 + rng.normal(0, 1)
            sj = cmj * 0.93
            flight = {"CMJ_flight_ms": round(1000 * (8 * cmj / 100 / 9.81) ** 0.5, 1)} if flight_times else {}
            eval_rows.append({
                **flight,
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


def _set_tab(at, key: str, tab: str):
    at.session_state[key] = tab
    return at.run()


def run_benchmark(store_dir: Path) -> list[tuple[str, float]]:
    from streamlit.testing.v1 import AppTest

    os.environ["THRESHOLD_STORE_DIR"] = str(store_dir)
    import local_store as local_store_module
    importlib.reload(local_store_module)

    results: list[tuple[str, float]] = []
    at = AppTest.from_file(str(APP_ROOT / "app.py"), default_timeout=600)
    _timed("Primera carga", at.run, results)
    if not _has_view(at, "Hoy"):
        return _run_legacy_views(at, results)

    _timed("Hoy · rerun", at.run, results)
    _timed("Hoy · rerun (2)", at.run, results)
    _timed("Atleta · entrar (Resumen)", lambda: _nav(at, "Atleta"), results)
    _timed("Atleta · rerun (Resumen)", at.run, results)
    box = at.selectbox(key="atleta_sel")
    target = next(opt for opt in box.options if opt != box.value)
    _timed("Atleta · cambio atleta (Resumen)", lambda: box.set_value(target).run(), results)
    for tab in ("Evaluación", "Carga y bienestar", "Fuerza"):
        _timed(f"Atleta · abrir {tab}", lambda t=tab: _set_tab(at, "atleta_tab", t), results)
        _timed(f"Atleta · rerun ({tab})", at.run, results)
        box = at.selectbox(key="atleta_sel")
        target = next(opt for opt in box.options if opt != box.value)
        _timed(f"Atleta · cambio atleta ({tab})", lambda b=box, t=target: b.set_value(t).run(), results)
    _timed("Equipo · entrar (Mapa)", lambda: _nav(at, "Equipo"), results)
    _timed("Equipo · rerun (Mapa)", at.run, results)
    for tab in ("Carga del grupo", "Rankings"):
        _timed(f"Equipo · abrir {tab}", lambda t=tab: _set_tab(at, "equipo_tab", t), results)
        _timed(f"Equipo · rerun ({tab})", at.run, results)
    _timed("No-Plataforma · entrar", lambda: _nav(at, "No-Plataforma"), results)
    _timed("Reportes · entrar", lambda: _nav(at, "Reportes"), results)
    _timed("Reportes · rerun", at.run, results)
    _timed("Hoy · volver", lambda: _nav(at, "Hoy"), results)
    _timed("Hoy · rerun (final)", at.run, results)
    return results


def _has_view(at, name: str) -> bool:
    try:
        nav = next(bg for bg in at.button_group if bg.label == "Vista principal")
    except StopIteration:
        return True  # antes del primer run: se decide despues
    return name in nav.options


def _run_legacy_views(at, results: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Secuencia de PR O (9 vistas), para medir el antes de PR P con el mismo script."""
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
