"""Version del codigo en ejecucion (commit corto), para verificar deploys."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _read_git_commit(root: Path) -> str | None:
    git_dir = root / ".git"
    head_file = git_dir / "HEAD"
    if not head_file.is_file():
        return None
    head = head_file.read_text(encoding="utf-8").strip()
    if not head.startswith("ref:"):
        return head or None
    ref = head.split(":", 1)[1].strip()
    ref_file = git_dir / ref
    if ref_file.is_file():
        return ref_file.read_text(encoding="utf-8").strip() or None
    packed = git_dir / "packed-refs"
    if packed.is_file():
        for line in packed.read_text(encoding="utf-8").splitlines():
            parts = line.strip().split(" ")
            if len(parts) == 2 and parts[1] == ref:
                return parts[0]
    return None


@lru_cache(maxsize=1)
def app_version() -> str:
    """Commit corto del codigo cargado en memoria.

    Se calcula una sola vez por proceso: si el servidor bajo codigo nuevo
    pero no reinicio, esto sigue mostrando la version vieja, que es justo
    lo que hay que detectar.
    """
    env_value = os.environ.get("THRESHOLD_APP_VERSION", "").strip()
    if env_value:
        return env_value[:12]
    try:
        commit = _read_git_commit(_REPO_ROOT)
    except OSError:
        commit = None
    return commit[:7] if commit else "desconocida"
