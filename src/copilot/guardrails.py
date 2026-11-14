"""응답 안전장치.

- 모든 응답은 유효한 source_type을 가진다.
- EXTERNAL_WEB(공식 API 공고)은 공식 도메인 인용(URL·기관·확인일) 없이는 내보내지 않는다.
- Google 검색 grounding 답변(WEB_GROUNDED)은 Gemini API 약관에 따라 수정·선별 없이 원문 그대로 두고,
  '시스템 미검증' 표시는 원문 밖(caveat·화면 라벨)에 붙인다. 표시하지 않는 것만 고를 수 있다.
- LLM이 쓴 문장은 (1) 원본에 없는 숫자 (2) 등록 판정과 다른 단계어 (3) 공식 근거 없는 단정 표현
  (4) 업종 A 신호를 산단 전체 고용 감소율로 바꾼 표현이 있으면 폐기한다.
- 등록 진단 답변에 붙는 LLM 쉬운 설명은 숫자를 아예 쓸 수 없다(수치는 등록 원문 그대로 함께 표시). 폐기 시 호출부가 결정론적 원문으로 되돌린다.
"""
from __future__ import annotations

import re
from dataclasses import replace

from .contracts import (
    EXTERNAL_WEB, GENERAL_LLM, INTERNAL_RAG, LLM, SOURCE_TYPES, SYSTEM, Citation, CopilotAnswer,
)
from .domains import classify

STAGES = ("우선점검", "추가확인", "관찰")
# 공식 근거 없이 쓰면 안 되는 단정 표현(대상·선정·원인 확정, 추천)
ASSERTIVE = re.compile(
    r"(지원\s*대상(입니다|이다|에\s*해당합니다|으로\s*확정)|선정(되었|됩니다|됐)|대상으로\s*확정|확정(되었|됩니다|적으로)|"
    r"원인은[^.。\n]{0,30}(때문|입니다)|때문입니다|추천합니다|받을\s*수\s*있습니다|반드시\s*받)")
NUMBER = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
# 업종 신호(A = 업종 감소인원 ÷ 산단 제조업 고용)를 산단 전체 고용 감소율로 바꿔 쓴 문장
# 차단: '산업단지 제조업 고용이 3.47% 줄어' · 통과: '산단 제조업 고용의 3.47%에 해당'
PARK_WIDE_DECLINE = re.compile(
    r"(?:산단|산업단지)\s*(?:전체\s*)?(?:제조업\s*)?(?:전체\s*)?고용(?:이|은|는|도)?\s+(?:[^\s.\n의]+\s+){0,3}?"
    r"[-+]?\d+(?:\.\d+)?\s*%\s*(?:가|이|나|만큼|정도)?\s*(?:줄|감소|하락|떨어)")
# '진입신호 없음'(경계 미달)을 '고용 감소(신호)가 없다'로 바꾼 문장 — 관찰 업종도 고용은 줄었을 수 있다
NO_DECLINE = re.compile(r"고용\s*(?:이|은|의)?\s*(?:감소|줄)[^.\n]{0,8}?(?:없|않았)")

WEB_GROUNDED = "WEB_GROUNDED"
WEB_GROUNDED_CAVEAT = ("Google 검색 기반 Gemini 답변을 수정 없이 표시한 외부 정보로, 시스템이 검증하지 않았습니다. "
                       "등록 진단 값을 바꾸지 않으며, 신청 가능 여부는 담당기관에 확인하세요.")

STANDARD_CAVEAT = {
    GENERAL_LLM: "일반 지식 설명이며 공식 근거나 본 시스템의 등록 진단이 아닙니다.",
    EXTERNAL_WEB: "외부 공식 도메인의 최신 정보입니다. 등록 진단 값을 바꾸지 않으며, 신청 가능 여부는 담당기관에 확인하세요.",
    INTERNAL_RAG: "검색 근거는 수집 시점의 자료이므로 담당자가 원문과 현재 상태를 확인해야 합니다.",
}


def numbers(text: str) -> set[str]:
    """비교용 숫자 집합(쉼표·부호 제거, 불필요한 소수 0 정리)."""
    out = set()
    for raw in NUMBER.findall(text or ""):
        value = raw.replace(",", "").lstrip("+-")
        if "." in value:
            value = value.rstrip("0").rstrip(".")
        if value:
            out.add(value)
    return out


def new_numbers(original: str, rewritten: str) -> set[str]:
    """재작성문에만 있는 숫자(원본에 없는 수치 생성 여부)."""
    return numbers(rewritten) - numbers(original)


def stage_changed(original: str, rewritten: str, registered_stage: str | None) -> bool:
    """재작성문이 등록 단계와 다른 단계어를 쓰는가."""
    allowed = {s for s in STAGES if s in (original or "")} | ({registered_stage} if registered_stage else set())
    return any(s in (rewritten or "") and s not in allowed for s in STAGES)


# 일반 AI 설명이 본 시스템의 판정·신호를 말하면 안 된다(그 질문은 등록 진단 경로가 답한다)
INTERNAL_JUDGMENT = re.compile(
    r"(우선점검|추가확인|조치\s*등급|판정(은|이|을|결과)|(?<![A-Za-z])[ERAP]\s*값|Q[1-3]\s*상태|"
    r"창원국가산단[^.\n]{0,20}(진단|판정))")


def mentions_internal_judgment(text: str) -> bool:
    return bool(INTERNAL_JUDGMENT.search(text or ""))


def numbers_supported(text: str, sources: list[str]) -> set[str]:
    """요약문 숫자 중 근거 원문 어디에도 없는 것."""
    allowed = set().union(*(numbers(s) for s in sources)) if sources else set()
    return numbers(text) - allowed


def assertive(text: str) -> list[str]:
    return [m.group(0) for m in ASSERTIVE.finditer(text or "")]


def check_rewrite(original: str, rewritten: str, registered_stage: str | None) -> tuple[bool, str]:
    """LLM 재작성 수용 여부. (통과, 사유)"""
    if not (rewritten or "").strip():
        return False, "EMPTY"
    extra = new_numbers(original, rewritten)
    if extra:
        return False, f"NEW_NUMBERS:{','.join(sorted(extra))}"
    if stage_changed(original, rewritten, registered_stage):
        return False, "STAGE_CHANGED"
    if assertive(rewritten) and not assertive(original):
        return False, "ASSERTIVE"
    if PARK_WIDE_DECLINE.search(rewritten) and not PARK_WIDE_DECLINE.search(original or ""):
        return False, "SIGNAL_MEANING_CHANGED"
    return True, "PASS"


def check_explanation(original: str, explanation: str, registered_stage: str | None) -> tuple[bool, str]:
    """등록 답변 뒤에 붙는 LLM 쉬운 설명의 수용 여부. 수치는 등록 원문이 맡으므로 설명에는 숫자가 없어야 한다."""
    if not (explanation or "").strip():
        return False, "EMPTY"
    if re.search(r"\d", explanation):
        return False, "NUMBER_IN_EXPLANATION"
    if stage_changed(original, explanation, registered_stage):
        return False, "STAGE_CHANGED"
    if assertive(explanation) and not assertive(original):
        return False, "ASSERTIVE"
    if NO_DECLINE.search(explanation):
        return False, "SIGNAL_MEANING_CHANGED"
    return True, "PASS"


CITE_MARK = re.compile(r"\[S\d+\]")


def check_summary(summary: str) -> tuple[bool, str]:
    """정책 원문 발췌에 붙는 LLM 요약의 수용 여부. 금액·기간 등 수치는 발췌 원문이 맡으므로 요약에는 숫자가 없어야
    한다([S1] 같은 근거 번호 표시만 예외)."""
    body = CITE_MARK.sub("", summary or "")
    if not body.strip():
        return False, "EMPTY"
    if re.search(r"\d", body):
        return False, "NUMBER_IN_SUMMARY"
    if assertive(body):
        return False, "ASSERTIVE"
    return True, "PASS"


def official_citations(citations: list[Citation]) -> list[Citation]:
    """외부 인용 중 공식 도메인이며 URL·기관·확인일이 모두 있는 것만."""
    kept = []
    for c in citations:
        tier, institution = classify(c.url)
        if tier is None or not c.url.startswith(("http://", "https://")) or not c.checked_at:
            continue
        kept.append(replace(c, tier=tier, institution=c.institution or institution, official=True))
    return kept


def finalize(ans: CopilotAnswer) -> CopilotAnswer:
    if ans.source_type not in SOURCE_TYPES:
        raise ValueError(f"unknown source_type: {ans.source_type}")
    if ans.answer_type == WEB_GROUNDED:
        # Google 검색 grounding 답변은 약관상 수정·선별하지 않는다 — 미검증 표시만 원문 밖에 붙인다
        return replace(ans, caveats=[*ans.caveats, WEB_GROUNDED_CAVEAT])
    if ans.source_type == EXTERNAL_WEB:
        cited = official_citations(ans.citations)
        if not cited:
            return replace(ans, source_type=SYSTEM, composer="TEMPLATE", citations=[],
                           answer="외부 공식 도메인에서 인용 가능한 근거를 확인하지 못해 외부 정보로 답하지 않습니다.",
                           guardrail="BLOCKED_NO_OFFICIAL_CITATION")
        ans = replace(ans, citations=cited)
    if ans.composer == LLM and ans.official_evidence_sufficient is not True and assertive(ans.answer):
        return replace(ans, source_type=SYSTEM, composer="TEMPLATE", citations=[],
                       answer="공식 근거가 충분하지 않은 단정 표현이 포함되어 답변을 표시하지 않습니다. "
                              "담당기관 공식 안내를 확인하세요.",
                       guardrail="BLOCKED_ASSERTIVE")
    caveat = STANDARD_CAVEAT.get(ans.source_type)
    if caveat and caveat not in ans.caveats:
        ans = replace(ans, caveats=[*ans.caveats, caveat])
    return ans
