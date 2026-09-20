import json
import os
import pandas as pd
import streamlit as st
from google import genai
from google.genai import types

# -------------------------------------------------------------
# 1. 페이지 및 환경 설정 (Streamlit UI)
# -------------------------------------------------------------
st.set_page_config(page_title="창원산단 산업·고용 전환진단 코파일럿", layout="wide")
st.title("🏭 창원국가산단 산업·고용 전환진단 행정 지원 AI 코파일럿")
st.caption("KICOX 패널(CORE) + Triage 규칙 엔진 + 채용 Evidence Layer 기반 Human-in-the-Loop 의사결정 지원 시스템")

# 사이드바: Google Gemini API Key 입력창
default_api_key = os.environ.get("GEMINI_API_KEY", "")
api_key_input = st.sidebar.text_input(
    "🔑 Google Gemini API Key 입력",
    value=default_api_key,
    type="password",
    help="AI Studio에서 발급받은 API 키를 입력하세요.",
)

# -------------------------------------------------------------
# 2. 결정론적 계산 엔진 (KICOX 실측 패널 + 채용공고 증거 매핑)
# -------------------------------------------------------------
def run_triage_engine(industry: str, quarter: str = "2026Q2"):
    """창원산단 분석 결과(03~06 통합 보고서) 기반 확정 팩트 데이터베이스"""
    mock_db = {
        "기계": {
            "quarter": quarter,
            "industry": "기계",
            "q1_state": "S4 (동반감소: 생산 YoY -6.34%, 고용 YoY -6.34%)",
            "q2_scale": {
                "emp_delta": -3979,
                "contribution_ratio": "91.9%",
                "excess_delta": "-1,697명 (비례 기준선 대비 초과 감소)",
                "emp_share": "3.47%",
            },
            "q3_time": "2분기 연속 S4 지속 (악화 상태 유지)",
            "triage_grade": "🔴 우선점검 (Priority Check)",
            "evidence_macro": "PPI 보정 후에도 실물 생산 감소세 유지, KEPCO 전력 사용량 둔화 동조",
            "recruitment_evidence": {
                "active_firms_count": 48,
                "sample_firms": ["기계 정밀가공업체 A사", "스마트공구 제작 B사", "중공업 1차 협력사"],
                "experience_req": "신입보다 경력 3~5년 중심 모집 (72%)",
                "tech_keywords": ["CNC/MCT 가공", "스마트팩토리 설비보전", "PLC 제어"],
                "wage_type": "월급 280만~350만 원 선 형성",
            },
        },
        "목재종이": {
            "quarter": quarter,
            "industry": "목재종이",
            "q1_state": "S4 (동반감소: 생산 감소, 고용 감소)",
            "q2_scale": {
                "emp_delta": -48,
                "contribution_ratio": "0.04%",
                "excess_delta": "절대 규모는 작으나 YoY -10.08% 급락 및 산단평균 대비 열위",
                "emp_share": "0.04%",
            },
            "q3_time": "직전 분기 대비 악화 반복",
            "triage_grade": "🔴 우선점검 (Priority Check)",
            "evidence_macro": "원자재 PPI 상승 충격 존재, 영세 사업장 중심",
            "recruitment_evidence": {
                "active_firms_count": 3,
                "sample_firms": ["제지·포장 C사"],
                "experience_req": "단순 노무/생산직 중심",
                "tech_keywords": ["포장", "물류", "지게차 운전"],
                "wage_type": "시급/최저임금 수준 형성",
            },
        },
        "철강": {
            "quarter": quarter,
            "industry": "철강",
            "q1_state": "S2 (생산↑·고용↓ 고용 없는 성장 디커플링)",
            "q2_scale": {
                "emp_delta": -112,
                "contribution_ratio": "0.10%",
                "excess_delta": "경미",
                "emp_share": "0.10%",
            },
            "q3_time": "4분기 연속 지속",
            "triage_grade": "🟢 일반관찰 (Observe)",
            "evidence_macro": "생산자물가지수(PPI) 상승 효과 분리 확인 필요, 가동률은 안정적",
            "recruitment_evidence": {
                "active_firms_count": 12,
                "sample_firms": ["특수강 열처리 D사", "철강 코일가공 E사"],
                "experience_req": "압연/용접 기능사 및 현장 숙련공 모집",
                "tech_keywords": ["열처리", "크레인 운전", "용접"],
                "wage_type": "월급 300만~400만 원 선 형성",
            },
        },
        "운송장비": {
            "quarter": quarter,
            "industry": "운송장비",
            "q1_state": "S1 (동반확대 국면 또는 생산 호조)",
            "q2_scale": {
                "emp_delta": -129,
                "contribution_ratio": "0.11%",
                "excess_delta": "경미",
                "emp_share": "0.11%",
            },
            "q3_time": "2분기 지속",
            "triage_grade": "🟢 일반관찰 (Observe)",
            "evidence_macro": "방산·완성차 수주 호조 유지, 고용 축 진입신호 미달",
            "recruitment_evidence": {
                "active_firms_count": 35,
                "sample_firms": ["방산 유압부품 F사", "상용차 차체조립 G사"],
                "experience_req": "품질관리 및 설계 인력 구인 활발",
                "tech_keywords": ["CATIA", "품질보증(QA)", "조립"],
                "wage_type": "월급 320만~450만 원 선 형성",
            },
        },
    }
    return mock_db.get(industry, None)


# -------------------------------------------------------------
# 3. Gemini 기반 진단서 생성 함수 (최신 gemini-2.0-flash 적용)
# -------------------------------------------------------------
def generate_diagnosis_card(fact_data: dict, api_key: str) -> str:
    client = genai.Client(api_key=api_key)

    system_instruction = (
        "당신은 창원특례시 산업정책과 AI 비서입니다. 제공된 정량 팩트만 사용하고, "
        "원인을 섣불리 단정하지 말며, 공무원이 현장 기업에 직접 던져야 할 실사 체크리스트 질문을 정교하게 도출하십시오."
    )

    prompt = f"""
    아래의 [확정된 데이터 팩트 JSON]을 분석하여 지자체 담당 공무원이 바로 들고 현장으로 나갈 수 있는
    '창원국가산단 산업·고용 1페이지 현장 진단카드'를 규격화된 마크다운 형식으로 작성하라.

    [확정된 데이터 팩트 JSON]:
    {json.dumps(fact_data, ensure_ascii=False, indent=2)}

    [작성 요구사항]
    1. '1. 최종 조치등급 및 핵심 수치', '2. 데이터가 확인한 사실 vs 단정할 수 없는 한계', '3. 채용시장 증거(Recruitment Evidence)', '4. 현장 실사팀 핵심 체크리스트(확인 질문 3가지)', '5. 창원시 기존 지원기능 연계 권고' 순으로 일목요연하게 작성할 것.
    2. 데이터만으로 '자동화 때문이다' 또는 '폐업했다'고 원인을 함부로 단정하지 말고, 반드시 '현장 확인 필요 질문'으로 도출할 것.
    """

    # 404 에러 방지를 위한 최신 정식 모델명 지정
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.2,
        ),
    )
    return response.text


# -------------------------------------------------------------
# 4. Streamlit 화면 레이아웃 및 챗봇 인터페이스
# -------------------------------------------------------------
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("📌 진단 대상 선택")
    selected_quarter = st.selectbox("분기 선택", ["2026Q2", "2026Q1", "2025Q4"])
    selected_ind = st.selectbox("업종 선택", ["기계", "목재종이", "철강", "운송장비"])

    generate_btn = st.button("진단카드 생성 및 현장 실사 브리핑", type="primary")

    if generate_btn:
        if not api_key_input:
            st.error("좌측 사이드바에 Google Gemini API Key를 먼저 입력해주세요!")
        else:
            fact_result = run_triage_engine(selected_ind, selected_quarter)
            if fact_result:
                with st.spinner("Gemini 엔진이 진단서를 작성하고 있습니다..."):
                    try:
                        report = generate_diagnosis_card(fact_result, api_key_input)
                        st.session_state["current_report"] = report
                        st.session_state["fact_data"] = fact_result
                    except Exception as e:
                        st.error(f"Gemini API 호출 오류: {e}")
            else:
                st.error("해당 업종 데이터가 존재하지 않습니다.")

with col2:
    st.subheader("📋 1페이지 표준 진단 리포트")
    if "current_report" in st.session_state:
        st.markdown(st.session_state["current_report"])

        st.divider()
        st.subheader("💬 AI 어시스턴트 추가 질의응답")
        user_query = st.text_input(
            "진단 결과에 대해 공무원 관점에서 질문하세요 (예: 목재종이와 기계의 차이가 뭐야? / 현장 방문 시 첫 질문은?)"
        )
        if user_query:
            if not api_key_input:
                st.error("좌측 사이드바에 Google Gemini API Key를 먼저 입력해주세요!")
            else:
                context_prompt = f"""
                현재 보고서 데이터:
                {json.dumps(st.session_state['fact_data'], ensure_ascii=False)}

                사용자 질문: {user_query}

                지침: 공무원 비서로서 원칙(단정 금지, 팩트 기반 질문 도출)을 지켜 명쾌하고 친절하게 답변할 것.
                """
                with st.spinner("답변 생성 중..."):
                    try:
                        client = genai.Client(api_key=api_key_input)
                        chat_resp = client.models.generate_content(
                            model="gemini-2.0-flash",
                            contents=context_prompt,
                            config=types.GenerateContentConfig(temperature=0.2),
                        )
                        st.info(chat_resp.text)
                    except Exception as e:
                        st.error(f"질의응답 오류: {e}")