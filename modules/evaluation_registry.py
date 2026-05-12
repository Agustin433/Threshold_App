from __future__ import annotations

from copy import deepcopy


IMTP_STORAGE_MAPPING: dict[str, str] = {
    "force_max_n": "IMTP_N",
    "force_avg_n": "IMTP_avg_N",
    "force_left_max_n": "IMTP_force_L_N",
    "force_right_max_n": "IMTP_force_R_N",
    "asymmetry_pct": "IMTP_asym_pct",
    "pre_tension_n": "IMTP_pretension",
    "time_to_peak_s": "IMTP_time_max_s",
    "time_pull_s": "IMTP_time_pull_s",
    "force_50_n": "IMTP_force_50_N",
    "force_100_n": "IMTP_force_100_N",
    "force_150_n": "IMTP_force_150_N",
    "force_200_n": "IMTP_force_200_N",
    "force_250_n": "IMTP_force_250_N",
    "rfd_50_n_s": "IMTP_rfd_50_N_s",
    "rfd_100_n_s": "IMTP_rfd_100_N_s",
    "rfd_150_n_s": "IMTP_rfd_150_N_s",
    "rfd_250_n_s": "IMTP_rfd_250_N_s",
}

IMTP_LEGACY_ALIASES: dict[str, str] = {
    "RFD_50": "IMTP_rfd_50_N_s",
    "RFD_100": "IMTP_rfd_100_N_s",
    "RFD_150": "IMTP_rfd_150_N_s",
    "RFD_250": "IMTP_rfd_250_N_s",
}

EVALUATION_SPECS: dict[str, dict[str, object]] = {
    "imtp": {
        "id": "imtp",
        "display_name": "IMTP",
        "category": "maximal_isometric_strength",
        "dashboard_group": "Perfil neuromuscular principal",
        "primary_metric": "force_max_n",
        "unit": "N",
        "higher_is_better": True,
        "has_limb_asymmetry": True,
        "interpretation_model": "imtp_force_time",
        "report_levels": ["athlete", "professional"],
        "upload_enabled": True,
        "storage_mapping": deepcopy(IMTP_STORAGE_MAPPING),
        "legacy_storage_aliases": deepcopy(IMTP_LEGACY_ALIASES),
    }
}


def get_evaluation_spec(test_id: str | None) -> dict[str, object] | None:
    clean = str(test_id or "").strip().lower()
    spec = EVALUATION_SPECS.get(clean)
    return deepcopy(spec) if spec is not None else None


def get_storage_mapping(test_id: str | None) -> dict[str, str]:
    spec = get_evaluation_spec(test_id)
    if spec is None:
        return {}
    mapping = spec.get("storage_mapping", {})
    return dict(mapping) if isinstance(mapping, dict) else {}


def list_evaluation_specs() -> list[dict[str, object]]:
    return [deepcopy(spec) for spec in EVALUATION_SPECS.values()]
