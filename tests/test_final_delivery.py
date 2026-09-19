from pathlib import Path
import sys

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pipeline import build_final_outputs as final

# KEPCO 법정동 패널은 feature/external-data 가 생성한다. 이 브랜치 단독 checkout 에는
# 없는 것이 정상이므로, 그 파일을 읽는 검증만 사유를 밝히고 skip 한다.
needs_external_kepco = pytest.mark.skipif(
    not final.KEPCO_LEGAL_MONTH.exists(),
    reason=(
        "외부데이터 미존재: "
        f"{final.KEPCO_LEGAL_MONTH.relative_to(ROOT).as_posix()} "
        "(feature/external-data 의 build_kepco_legal_dong_panel.py 산출물). "
        "브랜치 통합 후 실행할 것."
    ),
)


def test_role_table_is_complete_and_exclusive():
    roles = final.data_roles()
    assert set(roles.role) <= {"CORE", "VALIDATION", "CONTEXT", "EXCLUDE"}
    assert not roles.dataset_id.duplicated().any()
    required = {
        "kicox_production", "kicox_employment", "kicox_operation", "kicox_firms",
        "ppi", "eis_cci", "customs_trade", "kepco_business_type",
        "kepco_legal_dong_ksic", "changwon_jobs", "kosis_labor_flow",
    }
    assert required <= set(roles.dataset_id)
    assert roles.set_index("dataset_id").loc["kepco_legal_dong_ksic", "role"] == "CONTEXT"
    assert roles.set_index("dataset_id").loc["changwon_jobs", "role"] == "CONTEXT"


def test_final_outputs_preserve_triage_and_keys():
    decision = pd.read_csv(final.DECISION)
    context = pd.read_csv(final.CONTEXT)
    evidence = pd.read_csv(final.EVIDENCE_DIR / "external_evidence_summary.csv")
    core = pd.read_csv(final.CORE_TABLES / "core_panel.csv")
    assert len(decision) == len(context) == len(core) == 180
    assert not core.duplicated(["industry", "quarter"]).any()
    assert len(evidence) == evidence.industry.nunique() == 10
    before = decision[["industry", "quarter", "stage"]].sort_values(["industry", "quarter"]).reset_index(drop=True)
    after = context[["industry", "quarter", "stage"]].sort_values(["industry", "quarter"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(before, after)


def test_kepco_and_jobs_are_context_only_without_imputation():
    """이 브랜치가 생성하는 최종 산출물만으로 확인 가능한 부분."""
    roles = pd.read_csv(final.EVIDENCE_DIR / "data_role_table.csv").set_index("dataset_id")
    evidence = pd.read_csv(final.EVIDENCE_DIR / "external_evidence_summary.csv")
    assert roles.loc["kepco_legal_dong_ksic", "role"] == "CONTEXT"
    assert roles.loc["changwon_jobs", "role"] == "CONTEXT"
    assert not evidence.kepco_legal_dong_2026q2_available.any()
    assert not evidence.jobs_industry_signal_usable.any()
    assert evidence.kepco_legal_mapping_grade.notna().all()
    assert evidence.kepco_legal_complete_quarter_count.eq(0).all()


@needs_external_kepco
def test_kepco_legal_dong_panel_keeps_suppressed_cells_empty():
    """external-data 의 KEPCO 법정동 패널이 함께 있을 때만 도는 통합 검증."""
    legal = pd.read_csv(final.KEPCO_LEGAL_MONTH)
    masked = pd.to_numeric(legal.suppression_flag, errors="coerce").eq(1)
    assert pd.to_numeric(legal.loc[masked, "power_usage"], errors="coerce").isna().all()


def test_electre_is_selective_advisory_and_preserves_triage():
    boundary = pd.read_csv(final.ELECTRE_TABLES / "electre_smaa_review_cases.csv")
    decision = pd.read_csv(final.DECISION)
    assert len(boundary) == int(decision.stage.eq("추가확인").sum()) == 35
    assert boundary.triage_stage_preserved.eq("추가확인").all()
    assert not boundary.external_data_used_as_electre_criterion.any()
    assert set(boundary.electre_stage) <= {"OBSERVE", "CHECK", "PRIORITY", "UNDETERMINED"}
