# -*- coding: utf-8 -*-
"""확인질문 자동 생성.

모든 문장은 원인을 확정하지 않고 "확인할 필요가 있다" 형태로 쓴다.
해석신호만으로 특정 사업·예산을 고르지 않는다. 인계는 '검토 대상 기능' 까지다.
"""
from __future__ import annotations

import pandas as pd

SIGNAL_QUESTIONS = {
    "firms_op_decline_signal":
        "가동업체 감소가 실제 퇴거·폐업·통합·휴업에 따른 것인지, 아니면 조사대상 "
        "변동이나 집계기준 변경에 따른 것인지 확인할 필요가 있다.",
    "operating_rate_decline_signal":
        "가동률 하락이 일시적 생산조정인지 수주·수요 감소에 따른 것인지 확인할 필요가 있다.",
    "ppi_adjusted_production_decline_signal":
        "명목생산 변화에 가격효과가 포함되어 있으므로 실제 물량이 줄었는지 추가로 "
        "확인할 필요가 있다.",
    "production_maintained_employment_decline":
        "생산이 유지되는데 고용이 감소하고 있어 자동화·생산성 변화·미충원·외주화·"
        "인력구조 조정 여부를 확인할 필요가 있다.",
}

FLAG_QUESTIONS = {
    "employment_cross_source_disagreement":
        "산단 고용과 창원시 고용보험 지표의 방향이 달라 모집단 차이·자료 개정·"
        "기업 구성 차이 중 무엇 때문인지 확인할 필요가 있다.",
    "nominal_real_sign_disagreement":
        "명목생산과 PPI 조정 생산의 방향이 달라, 이 분기의 생산 변화가 가격 때문인지 "
        "물량 때문인지 확인할 필요가 있다.",
    "ppi_mapping_uncertain":
        "이 업종은 생산자물가지수 대응 후보가 복수이거나 없어, PPI 조정 생산을 "
        "단일값으로 해석하지 않고 원자료로 확인할 필요가 있다.",
    "small_base_warning":
        "업체수·고용 규모가 작아 비율 변동이 크게 나타난다. 절대 증감 개수로 "
        "다시 확인할 필요가 있다.",
    "op_rate_definition_break":
        "가동률 공표 정의가 바뀐 구간이어서 당기와 전년동기의 산출방식이 다르다. "
        "가동률 증감 해석 전에 정의 차이를 확인할 필요가 있다.",
    "monthly_data_unavailable":
        "이 분기는 월별 원자료가 공표되지 않아 분기 내 지속 여부를 확인할 수 없다. "
        "분기말 단일시점 값에만 의존한 판단임을 감안할 필요가 있다.",
    "source_missing":
        "입력 자료 일부가 미확인이다. 결측을 0이나 정상으로 읽지 말고 원자료 확인이 필요하다.",
    "source_revision_warning":
        "연간보정 개정본을 사용한 구간이다. 이후 재개정 시 값이 달라질 수 있음을 "
        "확인할 필요가 있다.",
    "industry_mapping_uncertain":
        "외부 자료의 업종 구분이 산단 10업종과 정확히 대응하지 않는다. 비교 결과를 "
        "참고로만 읽고 대응 범위를 확인할 필요가 있다.",
}

# 외부 수집자료 기반 확인질문. 전부 '확인할 필요가 있다' 형태다.
EXTERNAL_QUESTIONS = {
    "trade_export_decline_signal":
        "확인된 품목 기준 수출이 함께 감소하고 있어, 외부수요 약화 가능성을 보려면 "
        "수출 감소가 특정 품목·기업에 집중되는지 추가 확인할 필요가 있다.",
    "trade_export_up_employment_down":
        "확인된 품목 기준 수출은 유지·확대되는데 고용이 감소하고 있어 "
        "생산성·자동화·기업구성 변화 등의 가능성을 추가 확인할 필요가 있다.",
    "mfg_flow_acquisition_decrease":
        "창원시 제조업 전체에서 입직자 감소가 함께 관측되므로, 고용 감소가 "
        "신규 채용 둔화와 함께 나타나는지 확인할 필요가 있다.",
    "mfg_flow_loss_increase":
        "창원시 제조업 전체에서 이직자 증가가 함께 관측되므로, 특정 사업장 조정 또는 "
        "노동이동과 관련된 것인지 추가 확인할 필요가 있다.",
    "oprate_power_both_decline":
        "가동률 하락과 창원시 제조업 전력사용 감소가 함께 나타나 실제 생산활동 위축 "
        "여부를 추가 확인할 필요가 있다. 다만 전력은 시 전체 제조업 총계이므로 "
        "이 업종의 값이 아니다.",
    "oprate_power_direction_split":
        "가동률과 전력사용의 방향이 달라 업종 구성·설비 특성·자료범위(산단 vs 시 전체) "
        "차이를 추가 확인할 필요가 있다.",
    "bsi_region_below_100":
        "경남 제조업 업황 심리지수가 기준선(100)을 밑돌아, 업종 고유 요인인지 "
        "지역 전반의 경기 흐름인지 구분해 확인할 필요가 있다.",
    "bsi_industry_below_100":
        "같은 업종의 전국 업황 심리지수도 기준선을 밑돌아, 관측된 변화가 산단 고유 "
        "현상인지 전국 업종 흐름인지 확인할 필요가 있다.",
}
EXTERNAL_REVIEW_FUNCTION = {
    "trade_export_decline_signal": "산업동향 · 기업지원",
    "trade_export_up_employment_down": "고용지원 · 직업훈련",
    "mfg_flow_acquisition_decrease": "고용지원 · 직업훈련",
    "mfg_flow_loss_increase": "고용지원",
    "oprate_power_both_decline": "산업동향 · 기업지원",
    "oprate_power_direction_split": "산업동향",
    "bsi_region_below_100": "산업동향",
    "bsi_industry_below_100": "산업동향",
}

# 인계 검토 대상 기능. 자동 지원연계가 아니라 '어느 기능이 먼저 볼지' 의 제안이다.
SIGNAL_REVIEW_FUNCTION = {
    "firms_op_decline_signal": "산업동향 · 기업지원",
    "operating_rate_decline_signal": "산업동향 · 기업지원",
    "ppi_adjusted_production_decline_signal": "산업동향",
    "production_maintained_employment_decline": "고용지원 · 직업훈련",
}
HANDOFF_NOTE = ("검토 대상 기능의 제안이며 특정 사업·예산의 선정이 아니다. "
                "지원 여부는 담당자의 현장 확인 뒤에 기존 체계에서 결정한다.")


def build_questions(d: pd.DataFrame) -> pd.DataFrame:
    """신호·플래그에 맞춘 확인질문과 인계 검토 대상."""
    out = pd.DataFrame(index=d.index)

    sig_cols = [c for c in SIGNAL_QUESTIONS if c in d.columns]
    flag_cols = [c for c in FLAG_QUESTIONS if c in d.columns]
    ext_cols = [c for c in EXTERNAL_QUESTIONS if c in d.columns]
    # 결측은 여기서 질문을 만들지 않는다. 자료 미확인 자체는
    # source_missing / monthly_data_unavailable 플래그가 별도 질문을 만든다.
    on_sig = d[sig_cols].fillna(False).astype(bool)
    on_flag = d[flag_cols].fillna(False).astype(bool)
    out["signal_questions"] = on_sig.apply(
        lambda r: "\n".join(SIGNAL_QUESTIONS[c] for c in sig_cols if r[c]), axis=1)
    out["quality_questions"] = on_flag.apply(
        lambda r: "\n".join(FLAG_QUESTIONS[c] for c in flag_cols if r[c]), axis=1)
    on_ext = d[ext_cols].fillna(False).astype(bool) if ext_cols else pd.DataFrame(index=d.index)
    out["external_questions"] = (
        on_ext.apply(lambda r: "\n".join(EXTERNAL_QUESTIONS[c] for c in ext_cols if r[c]),
                     axis=1) if ext_cols else "")
    out["check_questions_context"] = (
        out["signal_questions"] + "\n" + out["external_questions"] + "\n"
        + out["quality_questions"]).str.replace(r"\n+", "\n", regex=True).str.strip()
    out.loc[out["check_questions_context"] == "", "check_questions_context"] = (
        "이번 분기 해석층에서 추가로 제기되는 확인질문은 없다. "
        "Triage 단계의 확인질문을 따른다.")
    def _funcs(i):
        fs = [SIGNAL_REVIEW_FUNCTION[c] for c in sig_cols if on_sig.at[i, c]]
        fs += [EXTERNAL_REVIEW_FUNCTION[c] for c in ext_cols if on_ext.at[i, c]]
        return " / ".join(dict.fromkeys(fs)) or "해당 없음(해석층 신호 없음)"
    out["handoff_review_functions"] = [_funcs(i) for i in d.index]
    out["handoff_note"] = HANDOFF_NOTE
    return out
