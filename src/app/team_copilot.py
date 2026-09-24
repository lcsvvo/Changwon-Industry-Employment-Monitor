"""'공모전 팀 제안' 탭 전용 답변(앱 계층).

Copilot backend(라우팅·등록 진단·RAG·기업마당)는 바꾸지 않는다. 팀 제안 탭에서, 기존 라우터가 범위 밖·인사·안내로
보내거나 팀 제안을 묻는 질문일 때만 이 모듈이 답한다.
- 근거 = 화면과 같은 정본 텍스트(view_models.team_proposals_text) 뿐. 업종·분기·세션 입력은 LLM에 보내지 않는다
  (특정 업종 '추천 정책'처럼 답하지 않게).
- LLM 문장은 기존 guardrails.check_rewrite(새 숫자·단계어·단정 표현)를 통과해야 쓰고, 아니면 정본 요약을 그대로 보인다.
"""
from __future__ import annotations

import re

from copilot import guardrails
from copilot import router as R
from copilot.contracts import CAPABILITY, EXTERNAL_WEB, GENERAL_LLM, GREETING, INTERNAL_RAG, SYSTEM, UNSUPPORTED

from app.view_models import TEAM_PROPOSALS, team_kpis, team_proposals_text

TEAM_HINTS = ("제안", "팀", "추천", "공모전", "기대효과", "지표", "성과", "KPI", "작동", "조기경보", "정례협의체", "버팀이음",
              "바우처", "조기진단", "협력사", "원청", "방산", "항공", "근로환경", "정책체계", "정책 흐름")
TEAM_SYSTEM = (
    "당신은 창원국가산단 산업·고용 전환진단 시스템의 행정 AI 비서입니다. 사용자는 지금 '공모전 팀 제안' 화면을 보고 있습니다. "
    "아래 [공모전 팀 제안 정본]만 근거로 한국어로 답하세요.\n"
    "- 팀 제안은 현재 시행 중인 공식 지원사업이 아니라 기존 사업·제도와 분석 결과를 바탕으로 팀이 구성한 정책 개선·신규 "
    "제안이며 전 업종 공통입니다. 특정 업종에 맞춘 정책이나 특정 업종에 권하는 정책처럼 말하지 마세요.\n"
    "- 정본에 없는 사업비·지원액·대상요건·기관·성과수치·기간·숫자를 만들지 마세요. 정본의 숫자는 그대로 쓰세요.\n"
    "- 기대효과(무엇이 나아지기를 기대하는가)와 성과 확인 지표(KPI, 실제로 나아졌는지 무엇으로 확인하는가)를 구분하세요. "
    "KPI는 정본에 있는 것만 쓰고, 없으면 '정본에 별도 KPI가 없다'고 하세요.\n"
    "- 기대효과를 이미 실현·입증된 효과처럼 쓰지 말고 '기대', '제안'으로 쓰세요. 8번 직무전환 바우처는 조건부 검토안입니다.\n"
    "- 공식 지원사업이나 지금 신청할 수 있는 사업을 물으면 '[공식 지원 연계] 탭에서 기존 공식 지원사업과 관련 기관을 "
    "확인할 수 있다'고 안내하세요.\n"
    "- 3~6문장 또는 짧은 목록으로 답하세요. 선정·확정·'받을 수 있습니다' 같은 표현은 쓰지 마세요.")
CAVEAT = "공모전 팀 제안(공식 정책 아님) 정본만 근거로 답했습니다. 현재 시행 중인 공식 지원사업이 아닙니다."
_KEYWORDS = {1: ("조기경보", "정례협의체", "협의체"), 2: ("버팀이음",), 3: ("재취업 패키지", "직무전환·재취업"),
             4: ("조기진단",), 5: ("원청",), 6: ("근로환경",), 7: ("방산", "항공"), 8: ("바우처",)}


def applies(question: str, decision: R.RouteDecision) -> bool:
    """팀 제안 탭에서 이 모듈이 답할 질문인가. 등록 진단·최신 공고·외부 검색 질문은 기존 경로가 그대로 답한다."""
    if decision.route in (GREETING, CAPABILITY, UNSUPPORTED):
        return True
    if decision.route == EXTERNAL_WEB or decision.needs_recency:
        return False
    if decision.route in (INTERNAL_RAG, GENERAL_LLM, SYSTEM):
        return any(h.lower() in (question or "").lower() for h in TEAM_HINTS)
    return bool(matched(question))  # 등록 진단 질문은 제안명이 직접 언급될 때만


def matched(question: str) -> list[dict]:
    compact = re.sub(r"\s+", "", question or "")
    return [p for p in TEAM_PROPOSALS if any(w.replace(" ", "") in compact for w in _KEYWORDS[p["no"]])]


def fallback(question: str) -> str:
    """결정론적 답(정본 문구만). LLM 미설정·실패·검증 불통과 시."""
    hits = matched(question)
    q = question or ""
    if "달라" in q or "차이" in q:
        return ("공식 지원 연계는 지금 활용 가능한 기존 제도와 기관을 선택 업종·분기 기준으로 보여줍니다.\n"
                "공모전 팀 제안은 분석 결과를 바탕으로 팀이 구성한 정책 개선·신규 제안 8건이며, 현재 시행 중인 공식 "
                "지원사업이 아니고 전 업종 공통입니다.")
    if len(hits) == 1:
        p = hits[0]
        kpis = team_kpis(p)
        return "\n".join([
            f"{p['title']} ({p['kind']} · 연계 단계 {'·'.join(p['stages'])})",
            f"제안: {p['summary']}",
            f"작동 방식: {' → '.join(p['flow'])}",
            f"기대효과: {p['effect']}",
            f"성과 확인 지표: {' / '.join(kpis) if kpis else '정본에 별도 KPI 없음'}"])
    if "지표" in q or "KPI" in q.upper() or "성과" in q:
        return "\n".join(f"{p['no']}. {p['title']}: {' / '.join(team_kpis(p)) or '정본에 별도 KPI 없음(조건부 검토안)'}"
                         for p in TEAM_PROPOSALS)
    return "공모전 팀 제안 8건(전 업종 공통, 공식 지원사업 아님)\n" + "\n".join(
        f"{p['no']}. {p['title']} · {p['kind']} · {'·'.join(p['stages'])}" for p in TEAM_PROPOSALS)


def answer(question: str, llm, decision: R.RouteDecision) -> dict:
    """copilot.ask()와 같은 모양의 결과(dict). 근거 유형은 SYSTEM, answer_type TEAM_PROPOSAL(화면이 전용 badge로 표시)."""
    base = fallback(question)
    text, composer, caveats = base, "TEMPLATE", [CAVEAT]
    if getattr(llm, "available", False):
        source = team_proposals_text()
        result = llm.generate(f"{source}\n\n[질문]\n{question}", system=TEAM_SYSTEM)
        if result.ok:
            ok, _why = guardrails.check_rewrite(f"{source} {question}", result.text, None)
            if ok:
                text, composer = result.text, "LLM"
            else:
                caveats.append("AI 문장이 정본 보존 검증을 통과하지 못해 정본 요약을 그대로 표시합니다.")
        else:
            caveats.append("AI 답변을 만들지 못해 정본 요약을 그대로 표시합니다.")
    return {"answer": text, "caveats": caveats, "source_type": SYSTEM, "citations": [], "route": decision.route,
            "intent": decision.intent, "meta": {"scope": "team_proposals"}, "composer": composer,
            "answer_type": "TEAM_PROPOSAL", "target": None}
