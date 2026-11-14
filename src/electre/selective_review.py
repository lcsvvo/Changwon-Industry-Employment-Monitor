"""Build the advisory ELECTRE/SMAA panel for Triage check cases only."""

from __future__ import annotations

import pandas as pd


def build_selective_review(
    decision: pd.DataFrame,
    context: pd.DataFrame,
    electre_smaa: pd.DataFrame,
) -> pd.DataFrame:
    """Return the 35-case second-look panel without changing Triage stages."""
    selected = decision.loc[decision["stage"].eq("추가확인"), [
        "industry", "quarter", "stage_reason", "emp_delta", "E", "P"
    ]].copy()
    if len(selected) != 35:
        raise AssertionError(f"Expected 35 Triage additional-check rows, got {len(selected)}")

    selected = selected.merge(
        electre_smaa,
        on=["industry", "quarter"],
        how="left",
        validate="one_to_one",
    )
    selected["g1"] = (-pd.to_numeric(selected["emp_delta"], errors="coerce")).clip(lower=0)
    selected["g2"] = pd.to_numeric(selected["E"], errors="coerce")
    selected["g3"] = pd.to_numeric(selected["P"], errors="coerce")
    selected["electre_specification"] = "D_small_indifference (same archived run as compatible CAI)"
    selected["triage_stage_preserved"] = "추가확인"
    selected["boundary_action"] = selected["electre_stage"].map({
        "UNDETERMINED": "자료·모형 불확실성 우선 확인",
        "OBSERVE": "Triage-ELECTRE 불일치 확인(관찰로 자동 하향하지 않음)",
        "CHECK": "추가확인 유지",
        "PRIORITY": "추가확인군 내 우선 검토(우선점검으로 자동 승격하지 않음)",
    })
    selected["smaa_parameter_sensitive"] = pd.to_numeric(
        selected["n_possible"], errors="coerce"
    ).gt(1)
    selected["smaa_note"] = (
        "CAI는 명시한 호환 파라미터 표집에서의 배정 비중이며 위기확률·정답률이 아님"
    )
    selected["review_queue_group"] = "6 추가확인"
    selected.loc[selected["electre_stage"].eq("UNDETERMINED"), "review_queue_group"] = "1 자료·모형 불확실 확인"
    selected.loc[selected["electre_stage"].eq("OBSERVE"), "review_queue_group"] = "2 Triage-ELECTRE 불일치 확인"
    selected.loc[
        selected["electre_stage"].eq("PRIORITY") & selected["smaa_parameter_sensitive"],
        "review_queue_group",
    ] = "3 파라미터 민감 우선검토 후보"
    selected.loc[
        selected["electre_stage"].eq("PRIORITY") & ~selected["smaa_parameter_sensitive"],
        "review_queue_group",
    ] = "4 안정 우선검토 후보"
    selected.loc[
        selected["electre_stage"].eq("CHECK") & selected["smaa_parameter_sensitive"],
        "review_queue_group",
    ] = "5 파라미터 민감 추가확인"

    context_columns = [
        "industry", "quarter", "ppi_mapping_grade", "ppi_adjusted_production_yoy",
        "cross_source_available", "trade_data_available", "power_data_available",
        "bsi_data_available", "mfg_flow_data_available", "check_questions_context",
        "handoff_review_functions",
    ]
    selected = selected.merge(
        context[context_columns],
        on=["industry", "quarter"],
        how="left",
        validate="one_to_one",
    )
    selected["external_data_used_as_electre_criterion"] = False
    selected["external_evidence_role"] = (
        "ELECTRE 이후 해석·교차확인; 판정 가중치나 veto로 사용하지 않음"
    )
    keep = [
        "industry", "quarter", "triage_stage_preserved", "stage_reason", "g1", "g2", "g3", "g4",
        "electre_stage", "electre_specification", "boundary_action", "review_queue_group",
        "cai_observe", "cai_check", "cai_priority", "cai_undetermined", "necessary_stage",
        "possible_stages", "n_possible", "smaa_parameter_sensitive", "smaa_note", "prereg_status",
        "ppi_mapping_grade", "ppi_adjusted_production_yoy", "cross_source_available",
        "trade_data_available", "power_data_available", "bsi_data_available",
        "mfg_flow_data_available", "external_data_used_as_electre_criterion",
        "external_evidence_role", "check_questions_context", "handoff_review_functions",
    ]
    return selected[keep].sort_values(
        ["review_queue_group", "quarter", "industry"]
    ).reset_index(drop=True)
