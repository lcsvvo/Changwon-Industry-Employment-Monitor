"""Shared, repository-relative paths used by the final notebook sequence."""
from __future__ import annotations

from pathlib import Path


def find_root(start: Path | str | None = None) -> Path:
    start_path = Path.cwd() if start is None else Path(start)
    candidates = [start_path, *start_path.parents, Path(__file__).resolve().parents[2]]
    root = next((p for p in candidates if (p / "src").is_dir() and (p / "data").is_dir()), None)
    if root is None:
        raise FileNotFoundError("프로젝트 루트를 찾을 수 없습니다.")
    return root


ROOT = find_root()
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
KICOX_DIR = PROCESSED_DIR / "kicox"
KICOX_INDUSTRY_PATH = KICOX_DIR / "changwon_industry_master.csv"
KICOX_TOTAL_PATH = KICOX_DIR / "changwon_total_master.csv"
STATE_PANEL_PATH = KICOX_DIR / "changwon_state_panel.csv"
CORE_TABLE_DIR = ROOT / "outputs" / "final_model" / "01_core" / "tables"
CORE_FIGURE_DIR = ROOT / "outputs" / "final_model" / "01_core" / "figures"
TRIAGE_TABLE_DIR = ROOT / "outputs" / "final_model" / "02_triage" / "tables"
TRIAGE_PANEL_PATH = TRIAGE_TABLE_DIR / "triage_panel.csv"
TRIAGE_LATEST_PATH = TRIAGE_TABLE_DIR / "triage_latest.csv"
TRIAGE_LATEST_FULL_PATH = TRIAGE_TABLE_DIR / "triage_latest_full.csv"
TRIAGE_RULE_PROVENANCE_PATH = TRIAGE_TABLE_DIR / "triage_rule_provenance.csv"
ELECTRE_TABLE_DIR = ROOT / "outputs" / "final_model" / "03_electre_smaa" / "tables"
ELECTRE_REVIEW_PATH = ELECTRE_TABLE_DIR / "electre_smaa_review_cases.csv"
ELECTRE_SUMMARY_PATH = ELECTRE_TABLE_DIR / "electre_smaa_summary.csv"
ELECTRE_SOURCE_PATH = PROCESSED_DIR / "final_model" / "electre_smaa_check_cases.csv"
EVIDENCE_DIR = ROOT / "outputs" / "final_model" / "04_external_evidence"
EVIDENCE_SUMMARY_PATH = EVIDENCE_DIR / "external_evidence_summary.csv"
DATA_ROLE_PATH = EVIDENCE_DIR / "data_role_table.csv"
HANDOFF_TABLE_DIR = ROOT / "outputs" / "final_model" / "05_handoff" / "tables"
HANDOFF_TRACE_PATH = HANDOFF_TABLE_DIR / "explanation_trace.csv"
HANDOFF_CARD_PATH = HANDOFF_TABLE_DIR / "handoff_cards_latest.csv"
ROUTING_MAP_PATH = HANDOFF_TABLE_DIR / "institution_routing_map.csv"
REPORT_ASSET_DIR = ROOT / "outputs" / "final_model" / "06_report_assets"
VALIDATION_DIR = ROOT / "logs" / "validation"
TRIAGE_SENSITIVITY_PATH = VALIDATION_DIR / "triage" / "sensitivity_own_rules.csv"
TRIAGE_SENSITIVITY_CHANGED_PATH = VALIDATION_DIR / "triage" / "sensitivity_changed_rows.csv"
PPI_DISAGREEMENT_PATH = VALIDATION_DIR / "outputs" / "robustness_extension" / "nominal_real_disagreement.csv"
EXPERIMENT_DIR = ROOT / "logs" / "experiments" / "archived_outputs"
ELECTRE_PARAMETER_PATH = EXPERIMENT_DIR / "candidate_models" / "electre_parameter_registry.csv"
ELECTRE_ROBUSTNESS_PATH = EXPERIMENT_DIR / "candidate_models" / "electre_interval_robustness.csv"
ELECTRE_LIMITATION_PATH = EXPERIMENT_DIR / "candidate_models" / "electre_limitation_record.csv"
MODEL_SELECTION_SUMMARY_PATH = EXPERIMENT_DIR / "model_selection" / "summary.json"
EIS_PANEL_PATH = PROCESSED_DIR / "eis" / "eis_validation_panel.csv"


def relative(path: Path) -> str:
    """Return a portable repository-relative label for notebook display."""
    return path.relative_to(ROOT).as_posix()
