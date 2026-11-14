# -*- coding: utf-8 -*-
"""저장 산출물을 최종 교수 검토 노트북에 붙인다.

분석 로직은 ``professor_feedback.py``에 있고, 이 파일은 계산 결과를 읽어
설명·표·그림 셀을 구성하기만 한다. 반복 실행해도 17절은 하나만 남는다.
"""
from __future__ import annotations

import json
import re
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
        markdown_cell = cell.get("cell_type") == "markdown"
        for old, new in (replacements if markdown_cell else CODE_REPLACEMENTS).items():
            source = source.replace(old, new)
        if markdown_cell:  # 보고서 최종본과 같은 용어·분기 표기로 맞춘다(반복 실행해도 결과가 같다)
            for old, new in REPORT_TERMS.items():
                source = source.replace(old, new)
            source = korean_quarters(source)
        cell["source"] = _lines(source)


# 보고서 최종본의 용어 띄어쓰기·해석 수위에 맞춘다. 새 값에 옛 값이 들어 있지 않아 반복 실행해도 안전하다.
REPORT_TERMS = {
    "이 결과는 본 구조를 미래 예측모형으로 사용할 수 없다는 근거다.":
        "이번 평가에서는 이 구조를 미래 예측모형으로 사용할 만한 성능을 확인하지 못했다.",
    "규모게이트": "규모 게이트",
    "균형정확도": "균형 정확도",
    "범주수용도지수": "범주 수용도 지수",
    "확인질문": "확인 질문",
    "동시점": "동일 시점",
    "운영값": "운영 값",
    "본분석": "본 분석",
    "현장확인": "현장 확인",
}


def korean_quarters(text: str) -> str:
    """설명 문단의 '2026Q2'를 보고서와 같은 '2026년 2분기'로 바꾼다. 백틱 안(코드·경로)은 그대로 둔다."""
    parts = re.split(r"(`[^`\n]*`)", text)
    return "".join(p if p.startswith("`") else re.sub(r"(?<!\d)(20\d\d)Q([1-4])(?!\d)", r"\1년 \2분기", p)
                   for p in parts)


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
                 "Triage 단계 산식은 변경하지 않았고, ELECTRE/SMAA는 추가확인군 보조 재검토 역할을 유지한다. "
                 "서술은 최종 분석보고서의 표현(분기 표기 ‘2026년 2분기’, 용어 띄어쓰기, 해석 수위)에 맞췄다."),
        markdown("## 17.1 목재종이 수준 급변 QA\n\n"
                 "정본에서 2024년 4분기→2025년 1분기 고용 214→479명, 명목 생산 62.71→183.70억 원, 가동업체 44→45개를 "
                 "확인했다. 2022년 3분기→4분기 생산도 137.54→69.14억 원으로 줄었고, 2022년 4분기~2023년 3분기 생산 YoY는 "
                 "-45.75~-52.43%였다. 분기별 원본에서도 같은 수치를 확인해 전처리 과정에서 새로 발생한 값은 아닌 것으로 보았다. "
                 "KICOX의 2025년 1분기 공표와 2022년 10월~2025년 1분기 연간보정본, 공공데이터포털의 분기별 원본도 대조했다. "
                 "다만 공개 업종 집계표에는 기업 편입·업종 재분류·집계기준 변경을 식별할 주석이 없어 급증 원인은 확인하지 못했다. "
                 "2026년 2분기는 44개 가동업체·428명에서 48명이 감소해 한두 기업 집중 여부를 현장에서 확인한다. 직접 확인된 값, "
                 "가능한 집계·분류·기업구성 변화, 확인하지 못한 원인을 분리한다. 아래 QA는 유효 구간 |QoQ| 95백분위와 업체 수 "
                 "변화 중앙값을 사용하며(분류단절 전후 제외, 180행 중 15행 표시) 오류를 확정하지 않는다."),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/wood_paper_source_audit.csv"),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/qa_level_shift_cases.csv",
                   ["industry", "quarter", "emp_qoq_pct", "production_qoq_pct", "firms_op_qoq_delta",
                    "qa_level_shift_flag", "qa_level_shift_reason"]),
        markdown("### 수준변화를 분리한 전년동기 변화(기저효과 점검)\n\n"
                 "전년동기 차이는 직전 4개 분기 전분기 차이의 합이므로, 비교창 안에 있는 QA 급변 분기의 한 분기 변화를 "
                 "분리하면 나머지 변화의 방향을 볼 수 있다. 2025년 네 분기는 2025년 1분기 급증을 분리하면 고용 −2.4~−11.0%, "
                 "생산 −12.7~−25.8%로 모두 **생산↓·고용↓** 방향이다. 따라서 2025년 S1(동반확대) 관찰은 앞서 확인한 급증의 "
                 "영향을 받았을 가능성을 고려해야 한다. 2023년 1~3분기 생산 −45.7~−52.4%도 2022년 4분기 수준 하락을 분리하면 "
                 "−1.8~+4.0%에 그쳐, 매 분기 새 급락이 아니라 2022년 4분기 한 번의 수준 하락이 전년동기 비교에 이어진 결과다. "
                 "이 분해는 해석용이며 국면·단계를 재분류하지 않는다."),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/wood_paper_level_shift_decomposition.csv",
                   ["quarter", "q1_state", "stage", "emp_yoy_pct", "emp_level_shift_component",
                    "emp_yoy_pct_excluding_shift", "prod_yoy_pct", "prod_level_shift_component",
                    "prod_yoy_pct_excluding_shift", "direction_excluding_shift"]),
        markdown("## 17.2 기계 고용 감소: YoY와 QoQ 병기\n\n"
                 "2026년 2분기 전년동기 감소 3,979명과 순감소 기여율 91.85%는 그대로 제시한다. 동시에 2025년 2분기 고용 "
                 "62,763명, 2026년 1분기 58,888명, 2026년 2분기 58,784명과 최근 QoQ −104명을 함께 보면, 최근 한 분기의 급격한 "
                 "신규 감소보다 2023년 이후 고점인 2025년 2분기 이후의 완만한 조정이 YoY에 크게 포착된 측면을 확인할 수 있다. "
                 "기존 `qoq_yoy_comparison`의 `qoq_recovery_while_yoy_below`는 False이므로 전분기 대비 회복은 아니지만 "
                 "감소폭은 작다. 따라서 기계의 현장 확인 질문은 급감 원인보다 조정의 지속 여부와 기업 단위 감원 여부에 맞춘다."),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/machine_yoy_qoq_interpretation.csv"),
        markdown("### 우선점검 17행의 비교기준 고점 여부\n\n"
                 "같은 점검을 우선점검 전체에 적용했다. 비교기준 분기(4분기 전)가 그 앞 8개 분기 중 최고 고용이었던 행은 "
                 "2026년 2분기 기계, 2026년 1분기 목재종이, 2025년 4분기 음식료의 3건이다. 2026년 2분기 기계는 전년동기 감소 "
                 "3,979명 중 최근 1분기 변화가 104명(2.6%)이어서, 감소의 대부분은 2025년 2분기 고점 이후 앞선 분기들에 누적됐다. "
                 "반면 2023년 1분기 기계는 최근 1분기 변화가 전년동기 감소의 63.8%로, 해당 분기 자체의 감소가 컸다."),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/priority_base_peak_check.csv",
                   ["industry", "quarter", "base_quarter", "base_employment", "employment", "yoy_delta",
                    "qoq_delta", "latest_quarter_share_of_yoy_pct", "max_employment_prior_8q",
                    "base_is_prior_8q_peak"]),
        markdown("## 17.3 목재종이 E 상위경계 여유\n\n"
                 "2026년 2분기는 48명 감소로 E=10.084%이며 47명 감소라면 9.874%다. 상위경계 이탈까지 1명이다. "
                 "2026년 1분기는 51명 감소로 경계 인원(479명의 10% = 47.9명)보다 3.1명 많고, 감소가 47명 이하였다면(4명 적게) "
                 "상위경계를 벗어난다. 현재 고용 428명은 300인 규모 게이트보다 128명 많아, 목재종이의 판정을 좌우하는 경계는 "
                 "규모 게이트가 아니라 E 10% 상위경계다."),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/wood_paper_boundary_margin.csv"),
        markdown("### 비율 경계의 인원 민감도와 규모 게이트\n\n"
                 "E 진입(5%)·상위(10%) 충족 여부가 몇 명 차이로 바뀌는지 180행 전체에서 계산했다. 고용 300인 미만 행(66행)은 "
                 "E 1%p가 중앙값 약 2명에 해당해 2명 이내 변화만으로 E 충족 여부가 바뀌는 행이 27.3%(18행)였던 반면, "
                 "300인 이상 행(114행)은 1.8%(2행)에 그쳤다. 소규모 업종의 비율 신호가 한두 명에 좌우되는 이 특성이 우선점검에 "
                 "최소 고용규모(규모 게이트)를 둔 이유다. 2026년 2분기 목재종이(428명)는 300인 이상이지만 기준 고용 476명으로 "
                 "E 1%p가 4.8명에 불과해 1명 차이로 상위경계를 통과했다."),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/ratio_boundary_headcount_summary.csv",
                   ["size_group", "rows", "median_employment", "median_persons_per_E_1pp", "rows_flip_within_2",
                    "share_flip_within_2_pct"]),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/ratio_boundary_headcount_latest.csv"),
        markdown("## 17.4 시점분리 검증의 측정대상\n\n"
                 "주평가 양성은 2분기 뒤 고용이 더 줄고 전년동기 경로도 악화되는 경우(`u_E<0 and d_E<0`)다. "
                 "이 검증은 미래 추가수축 예측을 측정하며, 현시점 점검 우선순위를 정하는 Triage의 운영 목적과 다르다. "
                 "균형 정확도(Triage 0.473, ELECTRE 0.445)는 제한적 사후 기술통계로 제시하며, 이번 평가에서는 이를 "
                 "예측모형으로 사용할 만한 성능을 확인하지 못했다."),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/signal_followup_summary.csv"),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/validation_model_comparison.csv"),
        markdown("### 동일 시점 외부 맥락 사례\n\n"
                 "기업경기실사지수(BSI)·수출·노동이동 자료에서 불리한 신호가 동시에 관측된 우선점검 사례 3개를 제시한다. "
                 "이는 맥락·타당성 보강용이며 Triage 단계 재산정에는 사용하지 않는다."),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/external_contemporaneous_cases.csv"),
        markdown("### 창원상공회의소 경제동향과의 동일 시점 대조\n\n"
                 "창원상공회의소 「창원지역 경제동향」의 〔창원국가산업단지 업종별 현황〕 표(2023년 1분기~2024년 1분기, "
                 "2025년 2분기~2026년 1분기 전사본, `data/raw/changwon_chamber/`)를 같은 분기 판정 패널과 대조했다. 업종을 따로 "
                 "공표하는 6개 업종 54행에서 고용 전년동기 방향은 51/54행, **우선점검 9행은 9/9행** 일치했다. 기계가 우선점검이던 "
                 "2023년 1~4분기에 창원상의도 기계 고용을 −14.4%·−14.1%·−14.4%·−6.8%로 보고했고, 판정이 관찰로 바뀐 "
                 "2024년 1분기에는 −0.3%였다. 생산 방향은 42/48행 일치했으며, 기계 2023년 1·3분기는 창원상의 표(KICOX 속보치)가 "
                 "+16.0%·+15.4%, 판정 패널(연간보정본)이 −3.6%·−2.0%로 달랐다. 따라서 해당 분기 P(생산감소) 보강은 연간보정 "
                 "자료에 근거한다는 점을 함께 밝힌다. 창원상의 2025년 1분기 자료는 목재종이를 ‘기타’에 합쳐 제시해 2025년 "
                 "목재종이 급증 원인은 독립적으로 확인할 수 없었다. 창원상의 값은 판정 입력이 아니다."),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/cci_concurrent_summary.csv",
                   ["group", "rows", "emp_direction_agree", "prod_direction_agree", "median_abs_emp_gap_pp"]),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/cci_concurrent_check.csv",
                   ["industry", "quarter", "stage", "e_yoy", "cci_emp_yoy", "emp_direction_agree",
                    "production_yoy", "cci_prod_yoy", "prod_direction_agree", "cci_export_yoy"],
                   query="stage == '우선점검' or (industry == '기계' and quarter <= '2024Q1')"),
        markdown("### 언론·기관 발표와의 동일 시점 대조\n\n"
                 "언론·기관 발표 12건을 출처 URL과 함께 수기 근거표(`professor_feedback/sources/press_concurrent_sources.csv`)로 "
                 "정리하고 판정 결과와 나란히 놓았다. 기계가 우선점검이었던 2022년에는 창원국가산단 고용이 2017년 이후 매년 "
                 "감소했다는 보도가 있었다. 2026년 2분기 기계 업종과 관련해 살펴본 기계·장비 경기전망지수는 2026년 1분기 96.4, "
                 "3분기 84.6으로 기준치를 밑돌았고, 산단 가동률도 2024년 85.3%에서 2026년 1분기 80.3%로 낮아졌다. 2025년에는 "
                 "산단 내 현대위아 공작기계 사업부 매각에 따른 고용 우려가 제기됐다. 다만 이 자료들만으로 기계 업종의 고용 감소 "
                 "원인을 확인할 수는 없다.\n\n"
                 "집계 범위가 달라 판정과 방향이 다른 신호도 있었다. 2026년 상반기 창원시 전역의 ‘기타 기계 및 장비’ 고용은 "
                 "2.6% 증가해 창원국가산단 기계 업종의 감소율(−6.34%)과 달랐고, 같은 시기 창원시 제조업 신규취업자는 전년 동기보다 "
                 "11.8% 감소했다. 전기전자 업종은 2026년 관찰로 분류됐지만, LG전자 창원 생산직 희망퇴직과 창원 전기장비 제조업의 "
                 "고용둔화 지원 대상 지정도 발표됐다. 모집단과 업종 정의가 다르고 일부 발표는 판정 이후에 나왔으므로 이 자료로 "
                 "Triage 단계를 바꾸지 않으며, 현장 확인에서 고용보험 통계와 기업 발표를 함께 살펴본다."),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/press_concurrent_cases.csv",
                   ["case_id", "industry", "quarters", "panel_stages", "panel_emp_yoy_range", "outlet", "published",
                    "indicator", "assessment"]),
        markdown("### 평균회귀 가설의 보강 점검 — 균형 정확도 0.5 미만의 해석\n\n"
                 "주평가 양성은 ‘고용 수준 감소 AND 전년동기 대비 이동 악화’다. 두 조건을 나누면 우선점검 13건 중 84.6%는 "
                 "2분기 뒤 고용 수준이 더 줄었지만(관찰 53.6%) 증감률이 악화된 비율은 46.2%에 그쳤고, 현재 증감률과 이후 "
                 "증감률 변화의 순위상관은 −0.45였다. 고용 인원의 회복보다는, 고용 감소가 이어지는 가운데 전년동기 증감률이 "
                 "평균 쪽으로 되돌아오는 양상이 관측되었다. 이는 균형 정확도가 0.5 미만으로 나온 결과를 해석할 때 함께 고려할 "
                 "부분이며, 다른 규칙과의 성능 비교에 쓰지 않는다. 사전등록 주평가(0.447)는 그대로다."),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/mean_reversion_by_stage.csv",
                   ["stage", "N", "level_down_rate", "yoy_worse_rate", "primary_positive_rate", "median_d_E_pp"]),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/mean_reversion_by_current_yoy.csv"),
        table_cell("outputs/final_model/06_report_assets/professor_feedback/tables/mean_reversion_summary.csv",
                   ["item", "value", "note"]),
        markdown("## 17.5 보고서 분석 그림\n\n"
                 "기존 Q1 사분면, Q2 고용 증감·비중, 비례기준선 비교와 새로 저장한 Triage 단계 격자를 본문에 순차 번호로 배치했다. "
                 "그림의 분기 표기는 본문과 같이 ‘2026년 2분기’ 형식으로 통일했고, 단계 격자의 열 머리글은 ‘2022년/1분기’처럼 "
                 "두 줄로 적었다.\n\n"
                 "![Triage 단계 격자](../outputs/final_model/06_report_assets/professor_feedback/figures/F10_Triage_단계격자.png)\n\n"
                 "격자는 우선점검이 2022~2023년 기계에, 2025~2026년 일부 업종에 집중된 시점을 한눈에 보여준다. 과거 분기는 후향 재구성이다.\n\n"
                 "보고서 그림 5(Triage 운영경계 민감도)는 중립구간 국면 민감도(표 4와 같은 내용) 대신, 운영경계를 바꿀 때의 "
                 "우선점검 건수로 바꿨다. 기준(A 1%/2%·300인) 17건, A 경계 2%/4% 11건, 300인 조건 제거 41건이며 "
                 "`logs/validation/triage/sensitivity_own_rules.csv`의 15개 사양 재실행 결과를 그린 것이다.\n\n"
                 "![Triage 운영경계 민감도](../outputs/final_model/06_report_assets/professor_feedback/figures/F11_Triage_운영경계_민감도.png)"),
        markdown("## 17.6 서술·용어 정리\n\n"
                 "단계 명칭은 **우선점검·추가확인·관찰**로 통일했다. Triage는 최초 등장 시 ‘선제점검 단계분류’로, "
                 "규모 게이트는 ‘우선점검 진입용 최소 고용규모’로 풀어 쓴다. 분기는 ‘2026년 2분기’처럼 적고, 확인 질문·규모 게이트·"
                 "균형 정확도·동일 시점·운영 값·범주 수용도 지수의 띄어쓰기를 보고서와 맞췄다. 제한사항은 한계 절에 모으고, 본문은 "
                 "담당자가 확인할 업종·근거·질문을 좁혀주는 기능을 중심으로 기술한다."),
        markdown("## 17.7 선별효과 표현\n\n"
                 "2026년 2분기는 업종 수 기준 10개 중 2개를 우선점검으로 선별했다. 두 업종의 고용 비중 합계는 51.56%다. "
                 "따라서 업종 수 기준으로 범위를 좁혔지만 고용 규모 기준으로는 전체의 절반 이상을 포함한다고 제시하며, "
                 "‘80% 효율 향상·업무 절감’으로 확장하지 않는다. 실제 행정시간 절감률은 시범운영 자료로 평가한다."),
        markdown("## 17.8 검토 패키지와 재현성\n\n"
                 "검토 패키지는 저장 출력 확인용으로 정의하고 `00_개요.txt`의 목록을 실제 파일과 1:1로 맞췄다. "
                 "최종 분석보고서는 패키지 안에서 직접 편집한 문서라 패키지 생성 스크립트가 복사하지 않고 존재 여부만 확인한다. "
                 "전체 재실행 기준은 GitHub 저장소이며, 실행 진입점과 최종 노트북 경로를 안내에 명시했다."),
        markdown("## 17.9 Streamlit 화면 반영\n\n"
                 "업종 이름 바로 옆 표식은 회색 테두리 도형(● 우선점검·▲ 추가확인·■ 관찰·× 자료확인)에 단계별 색을 채우고 같은 "
                 "도형으로 범례를 붙였으며, 단계명은 마우스 도움말로 보여준다. 대기열에서 선택된 카드 버튼을 주색으로 강조한다. "
                 "Q1·Q2·Q3 요약은 3개 카드로 정리하고 Q2 카드에 YoY·산단 비중·전분기 변화를 함께 보여준다. 진단카드 제목 아래 "
                 "기준 정보 줄에는 분석본 성격(기준분기 분석본·후향 재구성)과 분석본 등록일을 함께 적는다. 판정 추이는 `↺` 후향 "
                 "재구성(빗금), `×` 핵심자료 미확인(흐림·점선 테두리)을 구분하고 단계 색은 유지한다. 채용카드는 실제 포함관계"
                 "(목록 ⊇ 현재 유효 ⊇ 그중 상세 검증) 순서로 배치했다. 제안된 순서(목록→상세 검증→현재 유효)는 기계의 상세 검증 "
                 "134건 중 2건이 현재 유효 밖에 있어 포함관계가 성립하지 않았다. 상단에는 섹션 바로가기를 둔다. 화면 표기는 "
                 "보고서와 같이 ‘우선점검’으로 통일했다."),
        markdown("## 17.10 분석본 등록 시점 표기\n\n"
                 "2026년 2분기 분석본은 2026년 2분기까지의 자료로 2026년 9월에 산출·등록했다. 분기 자료는 분기가 끝난 뒤 "
                 "공표되므로 ‘그 분기에 실행해 등록한 분석본(당시 분석본)’이라는 이전 표현은 등록 기록과 맞지 않았다. 이를 "
                 "‘기준분기 분석본’으로 바꾸고, 화면에는 실제 등록일을 함께 표시한다. 개발 중 등록한 초안 분석본은 제출 전 "
                 "정리했으며 현재 분석본은 첫 공식본(v1)이다. 2022년 1분기~2026년 1분기는 각 분기에 저장된 판정본이 없어 "
                 "현재 확보한 자료와 현행 규칙으로 후향 재구성한 값이므로, 당시 실제로 산출·활용한 판정으로 해석하지 않는다."),
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
