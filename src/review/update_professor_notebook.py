# -*- coding: utf-8 -*-
"""저장 산출물을 최종 교수 검토 노트북에 붙인다.

분석 로직은 ``professor_feedback.py``에 있고, 이 파일은 계산 결과를 읽어
설명·표·그림 셀을 구성하기만 한다. 반복 실행해도 17절은 하나만 남는다.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK = ROOT / "notebooks/07_professor_review_master.ipynb"
TABLES = ROOT / "outputs/final_model/06_report_assets/professor_feedback/tables"
MARKER = "# 17. 교수님 피드백 반영 결과"


def _lines(text: str) -> list[str]:
    return text.splitlines(keepends=True) or [text]


def markdown(text: str) -> dict:
    return {"cell_type": "markdown", "id": uuid.uuid4().hex[:8], "metadata": {}, "source": _lines(text)}


def table_cell(path: str, columns: list[str] | None = None, query: str | None = None) -> dict:
    frame = pd.read_csv(ROOT / path)
    if query:
        frame = frame.query(query)
    if columns:
        frame = frame[columns]
    select = (f".query({query!r})" if query else "") + (f"[{columns!r}]" if columns else "")
    source = f"feedback_table = pd.read_csv(ROOT / {path!r}){select}\nshow_table(feedback_table)"
    html = frame.to_html(index=False, border=0, classes="dataframe")
    text = frame.to_string(index=False)
    return {
        "cell_type": "code", "execution_count": None, "id": uuid.uuid4().hex[:8], "metadata": {},
        "source": _lines(source),
        "outputs": [{"data": {"text/html": [html], "text/plain": [text]}, "metadata": {}, "output_type": "display_data"}],
    }


def replace_text(nb: dict) -> None:
    replacements = {
        "이를 Triage 규칙으로 묶어 분기별 점검 단계를 정한다.":
            "이를 선제점검 단계분류(Triage) 규칙으로 묶어 분기별 점검 단계를 정한다.",
        "따라서 우선점검 목록은 현재 임계값 아래의 결과다. 2026Q2에서도 기계는 A 경계에, 목재종이는 규모 gate 기준에 따라 우선점검을 벗어날 수 있다.":
            "따라서 우선점검 목록은 현재 임계값 아래의 결과다. 2026Q2 기계는 A 경계 변화에 민감하다. 목재종이는 현재 고용 428명으로 300인 규모 기준에는 128명의 여유가 있으며, 더 직접적인 민감성은 E 10% 상위경계다. 48명 감소는 10.08%지만 47명 감소라면 9.87%가 되어 상위경계를 벗어난다.",
        "BA(balanced accuracy)는 양성·음성 적중률의 평균이며, 무작위 선별의 기대값은 0.5다.":
            "균형정확도(BA; balanced accuracy)는 양성·음성 적중률의 평균이다. 여기서는 2분기 뒤 추가수축 예측을 측정하므로, 현재 담당자가 먼저 확인할 업종을 선별하는 Triage의 운영 목적과 구분해 해석한다.",
        "BA(balanced accuracy)는 양성·음성 적중률의 평균이다.":
            "균형정확도(BA; balanced accuracy)는 양성·음성 적중률의 평균이다.",
        "ELECTRE TRI-B와 SMAA-TRI는 추가확인 사례만 다시 보는 보조모형이다.":
            "다기준 범주분류(ELECTRE TRI-B)와 파라미터 민감도 분석(SMAA-TRI)은 추가확인 사례만 다시 보는 보조모형이다.",
        "→ 검증(§10) → External Evidence(§11)":
            "→ 검증(§10) → 외부근거(External Evidence, §11)",
        "# 11. External Evidence — 판정 뒤에 무엇을 더 확인하는가":
            "# 11. 외부근거(External Evidence) — 판정 뒤에 무엇을 더 확인하는가",
        "규모 gate(현재 고용 300인 미만이면 우선점검에서 제외하는 조건)":
            "우선점검 진입용 최소 고용규모(규모게이트; 현재 고용 300인 미만이면 우선점검에서 제외하는 조건)",
        "단계는 E·R·A 신호와 gate가 정한다.":
            "단계는 E·R·A 신호와 규모게이트가 정한다.",
        "고용 34명으로 규모 gate 미달":
            "고용 34명으로 우선점검 진입용 최소 고용규모(규모게이트) 미달",
        "규모 gate를 없애면": "규모게이트를 없애면",
        "규모 gate의 득실": "규모게이트의 득실",
        "보조모형의 PRIORITY를 우선점검 승격으로, OBSERVE를 관찰 하향으로 읽지 않는다.":
            "보조모형의 우선점검 수준(PRIORITY)을 Triage 우선점검 승격으로, 관찰 수준(OBSERVE)을 Triage 관찰 하향으로 읽지 않는다.",
        "추가확인 35행의 ELECTRE 배정은 PRIORITY 20, CHECK 9, UNDETERMINED 4, OBSERVE 2다.":
            "추가확인 35행의 ELECTRE 배정은 우선점검 수준(PRIORITY) 20, 추가확인 수준(CHECK) 9, 자료·모형상 단일 범주 확정 곤란(UNDETERMINED) 4, 관찰 수준(OBSERVE) 2다.",
        "UNDETERMINED는 파라미터 때문이 아니라 생산 자료 결측 때문에 생긴다.":
            "자료·모형상 단일 범주 확정 곤란(UNDETERMINED)은 파라미터 때문이 아니라 생산 자료 결측 때문에 생긴다.",
        "CAI(범주 수용도, 표집한 파라미터 조합 중 그 범주가 나온 비율)":
            "범주수용도지수(CAI; 표집한 파라미터 조합 중 그 범주가 나온 비율)",
        "CAI가 한 범주에서 1인 행": "범주수용도지수(CAI)가 한 범주에서 1인 행",
        "보조모형 PRIORITY 20행": "보조모형의 우선점검 수준(PRIORITY) 20행",
        "UNDETERMINED 4행은 생산 기준 결측":
            "자료·모형상 단일 범주 확정 곤란(UNDETERMINED) 4행은 생산 기준 결측",
    }
    for cell in nb["cells"]:
        source = "".join(cell.get("source", []))
        for old, new in (replacements if cell.get("cell_type") == "markdown" else CODE_REPLACEMENTS).items():
            source = source.replace(old, new)
        cell["source"] = _lines(source)


# 검토 패키지처럼 src가 없는 곳에서 열면 StopIteration 대신 재실행 위치를 안내하고 멈춘다(저장된 출력은 그대로 읽힌다).
CODE_REPLACEMENTS = {
    "ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p / 'src').is_dir())\n":
        "ROOT = next((p for p in [Path.cwd(), *Path.cwd().parents] if (p / 'src').is_dir()), None)\n"
        "if ROOT is None:\n"
        "    raise SystemExit('이 노트북은 저장소 루트(src 포함)에서 재실행합니다. 검토 패키지에는 실행 결과가 저장돼 있어 '\n"
        "                     '재실행 없이 열람할 수 있습니다. 재실행: https://github.com/lcsvvo/Changwon-Industry-Employment-Monitor '\n"
        "                     '를 내려받아 저장소 루트에서 notebooks/07_professor_review_master.ipynb 를 실행하세요.')\n",
}


def build_cells() -> list[dict]:
    return [
        markdown(MARKER + "\n\n"
                 "이 절은 별도 Python 모듈 `src/review/professor_feedback.py`가 만든 저장 산출물을 읽는다. "
                 "Triage 단계 산식은 변경하지 않았고, ELECTRE/SMAA는 추가확인군 보조 재검토 역할을 유지한다."),
        markdown("## 17.1 목재종이 수준 급변 QA\n\n"
                 "정본에서 2024Q4→2025Q1 고용 214→479명, 명목 생산 62.71→183.70억 원, 가동업체 44→45개를 확인했다. "
                 "2022Q3→Q4 생산도 137.54→69.14억 원으로 줄었고, 2022Q4~2023Q3 생산 YoY는 -45.75~-52.43%였다. "
                 "분류단절 표시와 저장소 내 공식 주석에서는 두 급변의 원인을 확인하지 못했다. 따라서 2025년 S1 관찰에는 실제 개선과 "
                 "수준 급증 뒤 기저효과 가능성을 함께 표시한다. 2026Q2는 44개 가동업체·428명에서 48명이 감소해 한두 기업 집중 여부를 "
                 "현장에서 확인한다. 직접 확인된 값, 가능한 집계·분류·기업구성 변화, 확인 불가한 원인을 분리한다. 아래 QA는 유효 구간 "
                 "|QoQ| 95백분위와 업체 수 변화 중앙값을 사용하며 오류를 확정하지 않는다."),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/wood_paper_source_audit.csv"),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/qa_level_shift_cases.csv",
                   ["industry", "quarter", "emp_qoq_pct", "production_qoq_pct", "firms_op_qoq_delta",
                    "qa_level_shift_flag", "qa_level_shift_reason"]),
        markdown("### 수준변화를 분리한 전년동기 변화(기저효과 점검)\n\n"
                 "전년동기 차이는 직전 4개 분기 전분기 차이의 합이므로, 비교창 안에 있는 QA 급변 분기의 한 분기 변화를 "
                 "분리하면 나머지 변화의 방향을 볼 수 있다. 2025년 네 분기는 2025Q1 급증을 분리하면 고용 −2.4~−11.0%, "
                 "생산 −12.7~−25.8%로 모두 **생산↓·고용↓** 방향이다. 따라서 2025년 S1(동반확대) 관찰은 실제 개선보다 "
                 "2025Q1 수준 급증이 전년동기 비교에 반영된 기저효과로 읽는다. 2023Q1~Q3 생산 −45.7~−52.4%도 2022Q4 수준 "
                 "하락을 분리하면 −1.8~+4.0%에 그쳐, 매 분기 새 급락이 아니라 2022Q4 한 번의 수준변화가 이어진 결과다. "
                 "이 분해는 해석용이며 국면·단계를 재분류하지 않는다."),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/wood_paper_level_shift_decomposition.csv",
                   ["quarter", "q1_state", "stage", "emp_yoy_pct", "emp_level_shift_component",
                    "emp_yoy_pct_excluding_shift", "prod_yoy_pct", "prod_level_shift_component",
                    "prod_yoy_pct_excluding_shift", "direction_excluding_shift"]),
        markdown("## 17.2 기계 고용 감소: YoY와 QoQ 병기\n\n"
                 "2026Q2 전년동기 감소 3,979명과 순감소 기여율 91.85%는 그대로 제시한다. 동시에 2025Q2 고용 62,763명, "
                 "2026Q1 58,888명, 2026Q2 58,784명과 최근 QoQ −104명을 함께 보면, 최근 한 분기의 급격한 신규 감소보다 "
                 "2025Q2가 2023년 이후 고점이며 그 이후 조정이 YoY에 크게 포착된 측면을 확인할 수 있다. 기존 "
                 "`qoq_yoy_comparison`의 `qoq_recovery_while_yoy_below`는 False이므로 전분기 대비 회복은 아니지만 감소폭은 작다."),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/machine_yoy_qoq_interpretation.csv"),
        markdown("### 우선점검 17행의 비교기준 고점 여부\n\n"
                 "같은 점검을 우선점검 전체에 적용했다. 비교기준 분기(4분기 전)가 그 앞 8개 분기 중 최고 고용이었던 행은 "
                 "기계 2026Q2, 목재종이 2026Q1, 음식료 2025Q4의 3건이다. 기계 2026Q2는 전년동기 감소 3,979명 중 최근 1분기 "
                 "변화가 104명(2.6%)이어서, 감소의 대부분은 2025Q2 고점 이후 앞선 분기들에 누적됐다. 반면 2023Q1 기계는 "
                 "최근 1분기 변화가 전년동기 감소의 63.8%로, 해당 분기 자체의 감소가 컸다."),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/priority_base_peak_check.csv",
                   ["industry", "quarter", "base_quarter", "base_employment", "employment", "yoy_delta",
                    "qoq_delta", "latest_quarter_share_of_yoy_pct", "max_employment_prior_8q",
                    "base_is_prior_8q_peak"]),
        markdown("## 17.3 목재종이 E 상위경계 여유\n\n"
                 "2026Q2는 48명 감소로 E=10.084%이며 47명 감소라면 9.874%다. 상위경계 이탈까지 1명이다. "
                 "2026Q1은 51명 감소로 경계 인원(479명의 10% = 47.9명)보다 3.1명 많고, 감소가 47명 이하였다면(4명 적게) "
                 "상위경계를 벗어난다. 현재 고용 428명은 300인 규모게이트보다 128명 많아, 목재종이의 직접 민감성은 "
                 "규모게이트가 아니라 E 10% 상위경계다."),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/wood_paper_boundary_margin.csv"),
        markdown("### 비율 경계의 인원 민감도와 규모게이트\n\n"
                 "E 진입(5%)·상위(10%) 충족 여부가 몇 명 차이로 바뀌는지 180행 전체에서 계산했다. 고용 300인 미만 행(66행)은 "
                 "E 1%p가 중앙값 약 2명에 해당하고, 27.3%(18행)가 2명 이내 변화로 E 충족 여부가 바뀐다. 300인 이상 행(114행)은 "
                 "1.8%(2행)다. 소규모 업종의 비율 신호가 한두 명에 좌우된다는 점이 우선점검에 최소 고용규모(규모게이트)를 둔 근거다. "
                 "2026Q2 목재종이(428명)는 300인 이상이지만 기준 고용 476명으로 E 1%p가 4.8명에 불과해 1명 차이로 상위경계를 통과했다."),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/ratio_boundary_headcount_summary.csv",
                   ["size_group", "rows", "median_employment", "median_persons_per_E_1pp", "rows_flip_within_2",
                    "share_flip_within_2_pct"]),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/ratio_boundary_headcount_latest.csv"),
        markdown("## 17.4 시점분리 검증의 측정대상\n\n"
                 "주평가 양성은 2분기 뒤 고용이 더 줄고 전년동기 경로도 악화되는 경우(`u_E<0 and d_E<0`)다. "
                 "이 검증은 미래 추가수축 예측을 측정하며, 현시점 점검 우선순위를 정하는 Triage의 운영 목적과 다르다. "
                 "따라서 BA(Triage 0.473, ELECTRE 0.445)는 제한적 사후 기술통계로 제시한다."),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/signal_followup_summary.csv"),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/validation_model_comparison.csv"),
        markdown("### 동시기 외부 맥락 사례\n\n"
                 "기존 BSI·수출·노동이동 자료에서 불리한 신호가 동시에 관측된 우선점검 사례 3개를 제시한다. "
                 "이는 맥락·타당성 보강용이며 Triage 단계 재산정에는 사용하지 않는다."),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/external_contemporaneous_cases.csv"),
        markdown("### 창원상공회의소 경제동향과의 동시점 대조\n\n"
                 "창원상공회의소 「창원지역 경제동향」의 〔창원국가산업단지 업종별 현황〕 표(2023Q1~2024Q1, 2025Q2~2026Q1 전사본, "
                 "`data/raw/changwon_chamber/`)를 같은 분기 판정 패널과 대조했다. 업종을 따로 공표하는 6개 업종 54행에서 고용 "
                 "전년동기 방향은 51/54행, **우선점검 9행은 9/9행** 일치했다. 기계가 우선점검이던 2023Q1~Q4에 창원상의도 기계 고용을 "
                 "−14.4%·−14.1%·−14.4%·−6.8%로 보고했고, 판정이 관찰로 바뀐 2024Q1에는 −0.3%였다. 생산 방향은 42/48행 일치했으며, "
                 "기계 2023Q1·Q3는 창원상의 표(KICOX 속보치)가 +16.0%·+15.4%, 판정 패널(연간보정본)이 −3.6%·−2.0%로 달랐다. "
                 "따라서 해당 분기 P(생산감소) 보강은 연간보정 자료에 의존한다는 점을 함께 밝힌다. 창원상의 값은 판정 입력이 아니다."),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/cci_concurrent_summary.csv",
                   ["group", "rows", "emp_direction_agree", "prod_direction_agree", "median_abs_emp_gap_pp"]),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/cci_concurrent_check.csv",
                   ["industry", "quarter", "stage", "e_yoy", "cci_emp_yoy", "emp_direction_agree",
                    "production_yoy", "cci_prod_yoy", "prod_direction_agree", "cci_export_yoy"],
                   query="stage == '우선점검' or (industry == '기계' and quarter <= '2024Q1')"),
        markdown("### 언론·기관 발표와의 동시점 대조\n\n"
                 "언론·기관 발표 10건을 출처 URL과 함께 수기 근거표(`professor_feedback/sources/press_concurrent_sources.csv`)로 "
                 "정리하고 같은 시기 판정과 나란히 놓았다. 2022년 산단 고용 감소 보도, 2026년 창원상의 경기전망지수(기계·장비 "
                 "96.4·84.6)와 가동률 하락 보도는 판정과 방향이 같았다. 반면 2026년 상반기 창원시 전역 고용보험의 ‘기타 기계 및 장비’ "
                 "+2.6%와 창원 전기장비 고용둔화 지원 지정(2026.7, Triage 2026년 관찰)은 판정과 달랐다. 모집단·업종 정의 차이가 "
                 "있으나 산단 밖·중소 사업장 신호를 놓칠 수 있다는 한계로 기록한다."),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/press_concurrent_cases.csv",
                   ["case_id", "industry", "quarters", "panel_stages", "panel_emp_yoy_range", "outlet", "published",
                    "indicator", "assessment"]),
        markdown("### 평균회귀 가설의 정밀 점검과 목적 맞춤 보강 검증(사후 분석)\n\n"
                 "주평가 양성은 ‘고용 수준 감소 AND 전년동기 대비 이동 악화’다. 두 조건을 나누면 우선점검 13건은 2분기 뒤 고용 "
                 "수준이 84.6% 더 줄었지만(관찰 53.6%) 증감률 악화는 46.2%였다. 현재 증감률과 이후 증감률 변화의 순위상관은 "
                 "−0.45다. 고용 인원이 회복되는 평균회귀가 아니라 **증감률의 평균회귀**가 균형정확도 0.5 미만의 원인이다.\n\n"
                 "Triage 목적(지금 감소가 큰 업종을 먼저 확인)에 맞춘 보강 기준 ‘2분기 뒤에도 고용 감소율 5% 이상 유지’로 보면 "
                 "Triage 경보 48건의 정밀도 50.0%, 오경보율 20.3%로 단순 규칙(현재 고용 감소 전체 84건: 39.3%·43.2%)보다 낫다. "
                 "판정 분기 묶음 부트스트랩 95% 구간은 정밀도 차 +2.0~+20.8%p, 오경보율 차 −29.4~−16.9%p다. 재현율은 −21.4%p로 "
                 "낮다. Triage의 부가가치는 적은 점검 건수로 오경보를 줄이는 효율이다. 이 기준은 결과를 본 뒤 정한 사후 보강 "
                 "분석이며 사전등록 주평가(균형정확도 0.447)를 대체하지 않는다."),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/mean_reversion_by_stage.csv",
                   ["stage", "N", "level_down_rate", "yoy_worse_rate", "primary_positive_rate", "median_d_E_pp"]),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/mean_reversion_by_current_yoy.csv"),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/purpose_aligned_validation.csv"),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/purpose_aligned_bootstrap.csv",
                   ["metric", "triage_minus_simple_rule", "ci95_low", "ci95_high", "share_triage_better"]),
        markdown("## 17.5 보고서 분석 그림\n\n"
                 "기존 Q1 사분면, Q2 고용 증감·비중, 비례기준선 비교와 새로 저장한 Triage 단계 격자를 본문에 순차 번호로 배치했다.\n\n"
                 "![Triage 단계 격자](../outputs/final_model/06_report_assets/professor_feedback/figures/F10_Triage_단계격자.png)\n\n"
                 "격자는 우선점검이 2022~2023년 기계에, 2025~2026년 일부 업종에 집중된 시점을 한눈에 보여준다. 과거 분기는 후향 재구성이다."),
        markdown("## 17.6 서술·용어 정리\n\n"
                 "단계 명칭은 **우선점검·추가확인·관찰**로 통일했다. Triage는 최초 등장 시 ‘선제점검 단계분류’로, "
                 "규모게이트는 ‘우선점검 진입용 최소 고용규모’로 풀어 쓴다. 제한사항은 한계 절에 모으고, 본문은 담당자가 "
                 "확인할 업종·근거·질문을 좁혀주는 기능을 중심으로 기술한다."),
        markdown("## 17.7 선별효과 표현\n\n"
                 "2026Q2는 업종 수 기준 10개 중 2개를 우선점검으로 선별했다. 두 업종의 고용 비중 합계는 51.56%다. "
                 "따라서 업종 수 기준으로 범위를 좁혔지만 고용 규모 기준으로는 전체의 절반 이상을 포함한다고 제시하며, "
                 "‘80% 효율 향상·업무 절감’으로 확장하지 않는다."),
        markdown("## 17.8 검토 패키지와 재현성\n\n"
                 "검토 패키지는 저장 출력 확인용으로 정의하고 `00_개요.txt`의 목록을 실제 파일과 1:1로 맞췄다. "
                 "전체 재실행 기준은 GitHub 저장소이며, 실행 진입점과 최종 노트북 경로를 안내에 명시했다."),
        markdown("## 17.9 Streamlit 화면 반영\n\n"
                 "업종 이름 바로 옆 표식은 회색 테두리 도형(● 우선점검·▲ 추가확인·■ 관찰·× 자료확인)에 단계 색을 채우고 같은 도형의 범례를 "
                 "붙였으며, 단계명은 마우스 도움말로 보여준다. 대기열에서 선택된 카드 버튼을 주색으로 강조한다. Q1·Q2·Q3 요약은 "
                 "3개 카드로 정리하고 Q2 카드에 YoY·산단 비중·전분기 변화를 함께 보여준다. 판정 추이는 `↺` 후향 재구성(빗금), "
                 "`×` 핵심자료 미확인(흐림·점선 테두리)을 구분하고 단계 색은 유지한다. 채용카드는 실제 포함관계(목록 ⊇ 현재 유효 ⊇ "
                 "그중 상세 검증) 순서로 배치했다. 제안된 순서(목록→상세 검증→현재 유효)는 기계의 상세 검증 134건 중 2건이 현재 유효 "
                 "밖에 있어 포함관계가 성립하지 않았다. 상단에는 섹션 바로가기를 둔다. 화면 표기는 보고서와 같이 ‘우선점검’으로 통일했다."),
    ]


def main() -> None:
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    replace_text(nb)
    cut = next((i for i, cell in enumerate(nb["cells"])
                if MARKER in "".join(cell.get("source", []))), len(nb["cells"]))
    nb["cells"] = nb["cells"][:cut] + build_cells()
    NOTEBOOK.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"updated {NOTEBOOK.relative_to(ROOT)}: {len(nb['cells'])} cells")


if __name__ == "__main__":
    main()
