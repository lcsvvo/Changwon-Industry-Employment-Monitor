"""정책 RAG 결과의 충분성 판정(PolicyRAG.search()는 바꾸지 않고 결과만 평가).

lexical FOUND는 '관련 문구가 있다'는 뜻일 뿐이다. 다음을 모두 만족하는 hit만 충분한 공식 근거로 본다.
  1. 공식 문서(DocumentMaster.official)이고 팀 제안(TEAM_PROPOSAL)이 아님
  2. score ≥ MIN_SCORE
  3. 질문의 주제어가 hit 본문·제목·섹션에 실제로 등장(흔한 말 '신청·가능·사업'만 겹친 hit 제외)
  4. 최신성 질문(현재·최근·모집 중·올해…)이면 추가로
     - 접수 상태가 OPEN (UNKNOWN·CLOSED·NOT_APPLICABLE은 '현재 가능'의 근거가 아님)
     - verified_at이 기준일로부터 MAX_AGE_DAYS 이내
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

MIN_SCORE = 6
MAX_AGE_DAYS = 30
# 질문에서 주제어로 보지 않는 말(시간·요청·일반 명사). 조사 제거 후 비교한다.
GENERIC = {
    "현재", "지금", "최근", "최신", "올해", "이번", "요즘", "모집", "모집중", "접수", "접수중", "신청", "신청가능",
    "가능", "가능한", "있어", "있나", "있나요", "있는", "있을까", "있습니까", "알려줘", "알려주세요", "무엇", "무엇인가",
    "뭐야", "어떤", "어디", "어디야", "사업", "지원", "지원사업", "정보", "관련", "받을", "수", "곳", "대상", "경우",
    "창원", "창원시", "기업", "업종", "우리", "이", "그", "좀", "공식", "근거", "연결", "검토", "해줘", "주세요",
    "추천", "추천해줘", "맞는", "해당", "제도", "프로그램", "사업은", "것", "뭐", "무슨",
    # 문법 잔여어(주제어가 아님): '모집 중인', '신청할 수 있는' 등
    "중인", "신청할", "할", "있는지", "가능할", "되는", "이용", "이용할", "지금", "알려", "해당하는", "받을수",
}
PARTICLES = ("으로", "에서", "에게", "까지", "부터", "하고", "이나", "은", "는", "이", "가", "을", "를", "에", "의",
             "로", "와", "과", "도", "만", "요")


def topic_terms(question: str) -> list[str]:
    terms = []
    for token in re.findall(r"[0-9A-Za-z가-힣]+", question or ""):
        token = token.lower()
        for particle in PARTICLES:
            if len(token) > len(particle) + 1 and token.endswith(particle):
                token = token[: -len(particle)]
                break
        if len(token) >= 2 and token not in GENERIC and token not in terms:
            terms.append(token)
    return terms


@dataclass
class Sufficiency:
    sufficient: bool
    reasons: list[str] = field(default_factory=list)
    usable_hits: list[dict] = field(default_factory=list)
    topic_terms: list[str] = field(default_factory=list)


def _age_days(verified_at: str | None, today: date) -> int | None:
    try:
        return (today - date.fromisoformat(str(verified_at)[:10])).days
    except (TypeError, ValueError):
        return None


def evaluate(rag: dict, question: str, *, needs_recency: bool, doc_meta: dict[str, dict],
             today: date) -> Sufficiency:
    """doc_meta: document_id → {"official": bool, "institution": str|None} (DocumentMaster 읽기 전용 조회)."""
    terms = topic_terms(question)
    if rag.get("status") != "FOUND" or not rag.get("hits"):
        return Sufficiency(False, ["공식 원문 색인에서 관련 근거 없음"], [], terms)
    usable, reasons = [], []
    for hit in rag["hits"]:
        meta = doc_meta.get(hit["document_id"], {})
        text = f"{hit.get('title') or ''} {hit.get('section') or ''} {hit.get('excerpt') or ''}".lower()
        problems = []
        if hit.get("source_class") == "TEAM_PROPOSAL" or not meta.get("official"):
            problems.append("공식 문서 아님")
        if (hit.get("score") or 0) < MIN_SCORE:
            problems.append(f"관련도 낮음(score {hit.get('score')} < {MIN_SCORE})")
        if terms and not any(term in text for term in terms):
            problems.append(f"주제어({', '.join(terms)}) 미포함")
        if needs_recency:
            if hit.get("current_intake_status") != "OPEN":
                problems.append(f"현재 접수 여부 미확인({hit.get('current_intake_status')})")
            age = _age_days(hit.get("verified_at"), today)
            if age is None or age > MAX_AGE_DAYS:
                problems.append(f"확인일 경과({hit.get('verified_at')})")
        if problems:
            reasons.append(f"{hit['document_id']}: " + " · ".join(problems))
        else:
            usable.append(hit)
    if usable:
        return Sufficiency(True, [], usable, terms)
    return Sufficiency(False, list(dict.fromkeys(reasons)), [], terms)
