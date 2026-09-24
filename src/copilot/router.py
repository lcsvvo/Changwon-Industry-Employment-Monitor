"""결정론적 질의 라우터.

우선순위: INTERNAL_DIAGNOSTIC > INTERNAL_RAG > EXTERNAL_WEB > GENERAL_LLM.
어느 경로에도 해당하지 않으면 UNSUPPORTED이며, 현재 업종 진단으로 대신 답하지 않는다.
LLM은 라우팅에 관여하지 않는다(결정론 규칙 + 회귀 테스트로 관리).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .contracts import (
    CAPABILITY, EXTERNAL_WEB, GENERAL_LLM, GREETING, INTERNAL_DIAGNOSTIC, INTERNAL_RAG, UNSUPPORTED,
)

# 진단 세부 의도
STAGE, SIGNAL, Q1, Q2, Q3, CHANGE, COMPARE, RECRUITMENT, FIELD, GAPS, REPHRASE = (
    "STAGE", "SIGNAL", "Q1", "Q2", "Q3", "CHANGE", "COMPARE", "RECRUITMENT", "FIELD", "GAPS", "REPHRASE")
# 정책·외부·일반 세부 의도
POLICY, SUPPORT_FUNCTIONS, TREND, CONCEPT = "POLICY", "SUPPORT_FUNCTIONS", "TREND", "CONCEPT"
# 단정 가능 여부(구조조정·산업위기·채용난·원인) · 지원 적격 판단 요청 · 담당기관 · 진단카드 요약
LIMIT, ELIGIBILITY, INSTITUTION, SUMMARY = "LIMIT", "ELIGIBILITY", "INSTITUTION", "SUMMARY"
# LIMIT 세부 주제(subintents) — 등록 진단으로 '단정할 수 없다'고 답하는 질문
LIMIT_TOPICS: dict[str, tuple[str, ...]] = {
    "RESTRUCTURING": ("구조조정", "정리해고", "고용조정", "대량해고"),
    "CRISIS": ("산업위기", "위기업종", "위기산업", "위기라고", "위기인가", "위기인지", "위기야", "위기로볼", "위기로판단"),
    "HIRING": ("채용난", "구인난", "인력난", "인력부족", "미스매치", "미충원"),
    "CAUSE": ("원인", "때문"),
}
# 정책어와 함께 와도 '판단·단정' 질문으로 보는 표지(없으면 '구조조정 지원사업' 같은 정책 질의로 둔다)
JUDGE_MARKERS = ("볼수", "보면", "인가", "인지", "맞나", "맞아", "맞습", "라고", "단정", "판단", "때문", "원인", "발생")
ELIGIBILITY_TERMS = ("대상인지", "대상인가", "대상여부", "대상이맞", "대상이될", "적격", "자격이되", "자격이있", "선정될",
                     "선정여부", "해당되는지", "해당하는지")
INSTITUTION_TERMS = ("지원기관", "담당기관", "관련기관", "어느기관", "어떤기관", "기관은어디", "기관이어디", "인계기관",
                     "어디에연락", "어디로연락", "연결기관")
SUMMARY_TERMS = ("진단카드", "진단결과를설명", "진단결과설명", "진단요약", "진단을설명", "진단내용", "카드를설명",
                 "현재진단")

STRONG, WEAK = 2, 1
THRESHOLD = 2

# (공백 제거·소문자 문장에서 찾는 용어, 가중치)
DIAGNOSTIC_TERMS: dict[str, tuple[tuple[str, int], ...]] = {
    STAGE: (("조치등급", STRONG), ("우선점검", STRONG), ("추가확인", STRONG), ("관찰", STRONG),
            ("판정근거", STRONG), ("판정", STRONG), ("등급", WEAK), ("단계", WEAK), ("triage", STRONG)),
    SIGNAL: (("고용감소율", STRONG), ("상대열위", STRONG), ("산단평균대비", STRONG), ("규모효과", STRONG),
             ("감소규모", STRONG), ("생산감소", STRONG), ("진입경계", STRONG), ("상위경계", STRONG),
             ("경계값", STRONG), ("규모gate", STRONG), ("규모게이트", STRONG), ("신호", WEAK), ("지표", WEAK)),
    Q1: (("q1", STRONG), ("국면", STRONG), ("동반감소", STRONG), ("고용없는성장", STRONG),
         ("생산과고용", STRONG), ("생산·고용", STRONG)),
    Q2: (("q2", STRONG), ("고용증감", STRONG), ("고용변화", STRONG), ("감소인원", STRONG), ("기여율", STRONG),
         ("고용비중", STRONG), ("몇명", STRONG), ("고용규모", STRONG)),
    Q3: (("q3", STRONG), ("몇분기", STRONG), ("지속", STRONG), ("반복", STRONG), ("연속", STRONG)),
    CHANGE: (("이전분기", STRONG), ("직전분기", STRONG), ("지난분기", STRONG), ("전분기", STRONG),
             ("판정변화", STRONG), ("최근판정", STRONG), ("바뀌", STRONG), ("달라졌", STRONG), ("변했", STRONG)),
    COMPARE: (("비교", STRONG), ("vs", STRONG)),
    RECRUITMENT: (("채용", STRONG), ("구인", STRONG), ("work24", STRONG), ("직무", STRONG), ("키워드", STRONG),
                  ("모집직종", STRONG), ("요구기술", STRONG), ("채용공고", STRONG)),
    FIELD: (("현장", STRONG), ("체크리스트", STRONG), ("확인질문", STRONG), ("무엇을확인", STRONG),
            ("뭘확인", STRONG), ("뭐확인", STRONG), ("실사", STRONG), ("방문", WEAK)),
    GAPS: (("한계", STRONG), ("데이터부족", STRONG), ("부족한부분", STRONG), ("미확인", STRONG),
           ("불확실", STRONG), ("주의사항", STRONG), ("믿을수", STRONG), ("신뢰", WEAK)),
}
POLICY_TERMS: dict[str, tuple[tuple[str, int], ...]] = {
    SUPPORT_FUNCTIONS: (("지원기능", STRONG), ("기능후보", STRONG), ("지원체계", STRONG)),
    POLICY: (("지원사업", STRONG), ("지원금", STRONG), ("지원제도", STRONG), ("장려금", STRONG),
             ("보조금", STRONG), ("바우처", STRONG), ("컨설팅", STRONG), ("정책", STRONG), ("고용유지", STRONG),
             ("직업훈련", STRONG), ("훈련", STRONG), ("내일배움", STRONG), ("재취업", STRONG), ("전직", STRONG),
             ("고용센터", STRONG), ("담당기관", STRONG), ("관할", STRONG), ("기관", STRONG), ("공식지원", STRONG),
             ("공식근거", STRONG), ("공식문서", STRONG), ("신청", STRONG), ("사업", WEAK), ("지원", WEAK),
             ("공고", WEAK)),
}
TREND_TERMS = (("동향", STRONG), ("뉴스", STRONG), ("기사", STRONG), ("전망", STRONG), ("업황", STRONG),
               ("시장상황", STRONG), ("경기", WEAK))
RECENCY_TERMS = ("현재", "지금", "최근", "최신", "올해", "이번달", "이번주", "요즘", "모집중", "접수중",
                 "신청가능", "마감", "새로", "신규")
REPHRASE_TERMS = ("쉽게", "한문장", "요약해", "요약하", "풀어서", "쉬운말", "간단히설명", "간단하게설명",
                  "쉽게설명", "초보자", "비전문가")
CONCEPT_MARKERS = ("뭐야", "뭔가요", "뭐예요", "무엇인가", "무엇입니까", "이란", "란무엇", "란?", "뜻", "의미",
                   "차이", "정의", "뭐지", "뭐임", "무슨말")
CONCEPT_ACRONYM = re.compile(r"(?<![A-Za-z])(CNC|MCT|PLC|CAD|CAM|AX|DX|MES|ERP|HACCP|SMT|NC|AI|IoT|KSIC|PPI|BSI)"
                             r"(?![A-Za-z])", re.I)
GREETING_RE = re.compile(r"^(안녕(하세요|하십니까)?|반갑(습니다|네요)?|반가워(요)?|hello|hi|hey|하이|좋은(아침|하루))"
                         r"[\s!.~?ㅎㅋ^]*$", re.I)
CAPABILITY_TERMS = ("뭘할수", "무엇을할수", "뭐할수", "어떤기능", "할수있는게", "할수있는일", "도움말", "사용법",
                    "사용방법", "help", "기능이뭐", "뭘도와", "무엇을도와", "어떻게써")
Q_RANGE = re.compile(r"q1(~|-|–|부터|에서)q3")
SIGNAL_LETTER = re.compile(r"(?<![A-Za-z])([ERAP])(?![A-Za-z])")
QUARTER_RE = re.compile(r"(20\d{2})\s*(?:[Qq]|년\s*)([1-4])\s*분?기?|(?<!\d)(\d{2})\s*[Qq]([1-4])")
# 원 업종명 외에 레퍼런스 화면이 쓰던 약칭만 허용한다(추정 매핑 없음). '기타'는 일상어라 '기타업종'만.
INDUSTRY_ALIASES = {"목재": "목재종이", "종이": "목재종이", "운송": "운송장비", "석유": "석유화학",
                    "섬유": "섬유의복", "의복": "섬유의복", "기타업종": "기타"}


@dataclass(frozen=True)
class RouteDecision:
    route: str
    intent: str
    needs_recency: bool = False
    industries: tuple[str, ...] = ()
    quarter: str | None = None
    signals: tuple[str, ...] = ()
    subintents: tuple[str, ...] = ()
    scores: dict = field(default_factory=dict)
    reason: str = ""


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def _score(compact: str, terms) -> int:
    return sum(weight for term, weight in terms if term in compact)


def mentioned_industries(question: str, industries: list[str]) -> tuple[str, ...]:
    """업종명 언급(앞 글자가 한글이면 합성어의 일부로 보고 제외: '공작기계'≠'기계')."""
    found: list[str] = []
    names = [(name, name) for name in industries if name != "기타"] + list(INDUSTRY_ALIASES.items())
    for token, industry in names:
        if industry not in industries:
            continue
        for m in re.finditer(re.escape(token), question):
            prev = question[m.start() - 1] if m.start() > 0 else ""
            if not re.match(r"[가-힣]", prev) and industry not in found:
                found.append(industry)
    return tuple(found)


def mentioned_quarter(question: str, quarters: list[str]) -> str | None:
    for m in QUARTER_RE.finditer(question):
        quarter = f"{m.group(1)}Q{m.group(2)}" if m.group(1) else f"20{m.group(3)}Q{m.group(4)}"
        if quarter in quarters:
            return quarter
    return None


def route(question: str, industries: list[str], quarters: list[str]) -> RouteDecision:
    text = (question or "").strip()
    compact = _compact(text)
    inds = mentioned_industries(text, industries)
    quarter = mentioned_quarter(text, quarters)
    recency = any(term in compact for term in RECENCY_TERMS)
    common = dict(needs_recency=recency, industries=inds, quarter=quarter)
    if not compact:
        return RouteDecision(UNSUPPORTED, "EMPTY", reason="빈 질문", **common)
    if GREETING_RE.match(text) or (len(compact) <= 8 and compact.startswith("안녕")):
        return RouteDecision(GREETING, GREETING, reason="인사", **common)
    if any(term in compact for term in CAPABILITY_TERMS):
        return RouteDecision(CAPABILITY, CAPABILITY, reason="기능 안내 요청", **common)

    signals = tuple(dict.fromkeys(m.group(1) for m in SIGNAL_LETTER.finditer(text)))
    diag = {name: _score(compact, terms) for name, terms in DIAGNOSTIC_TERMS.items()}
    if Q_RANGE.search(compact):  # 'Q1~Q3', 'Q1-Q3', 'Q1부터 Q3' → 세 축 모두
        for name in (Q1, Q2, Q3):
            diag[name] = max(diag[name], STRONG)
    if signals:
        diag[SIGNAL] += STRONG
    if len(inds) >= 2:
        diag[COMPARE] += STRONG
    if "근거" in compact and diag[STAGE]:
        diag[STAGE] += WEAK
    policy = {name: _score(compact, terms) for name, terms in POLICY_TERMS.items()}
    trend = _score(compact, TREND_TERMS)
    rephrase = any(term in compact for term in REPHRASE_TERMS)
    concept_marker = any(term in compact for term in CONCEPT_MARKERS)
    acronym = bool(CONCEPT_ACRONYM.search(text))
    scores = {**{f"diag.{k}": v for k, v in diag.items() if v},
              **{f"policy.{k}": v for k, v in policy.items() if v},
              **({"trend": trend} if trend else {})}

    # 충돌 규칙 1: '공고'·'직무'·'훈련'이 함께 오면 채용이 아니라 지원사업·훈련 질의일 수 있다.
    #   채용 의도는 '채용/구인/work24/모집직종' 같은 채용 고유어가 있을 때만 강하게 본다.
    if diag[RECRUITMENT] and policy[POLICY] >= STRONG and not any(
            t in compact for t in ("채용", "구인", "work24", "모집직종")):
        diag[RECRUITMENT] = 0
    # 충돌 규칙 2: '정책 변경'처럼 변화어가 정책과 함께 오면 판정 변화가 아니다.
    if diag[CHANGE] and policy[POLICY] >= STRONG and not diag[STAGE]:
        diag[CHANGE] = 0
    # 충돌 규칙 3: '비교'는 업종이 둘이거나(또는 업종 하나 + 비교어) 진단 문맥일 때만 업종 비교.
    if diag[COMPARE] and len(inds) < 2 and not (inds and "비교" in compact):
        diag[COMPARE] = 0
    # 충돌 규칙 4: 'Q1 상태'의 '상태' 등 일반어는 가중치가 없고, '지속'은 정책 문맥('지속 지원')이면 제외.
    if diag[Q3] and policy[POLICY] >= STRONG and not any(t in compact for t in ("q3", "몇분기", "반복")):
        diag[Q3] = 0

    diag_hits = sorted(((v, k) for k, v in diag.items() if v >= THRESHOLD), reverse=True)
    # '판정'은 거의 모든 진단 질문에 들어가므로, 더 구체적인 의도가 함께 있으면 STAGE를 뒤로 보낸다.
    if len(diag_hits) > 1:
        diag_hits = [hit for hit in diag_hits if hit[1] != STAGE] + [hit for hit in diag_hits if hit[1] == STAGE]
    policy_hits = sorted(((v, k) for k, v in policy.items() if v >= THRESHOLD), reverse=True)

    # 개별 기업의 지원 대상·적격 판단 요청 → 판단하지 않는다고 답한다(정책 RAG 검색 결과로 대신하지 않음)
    if any(term in compact for term in ELIGIBILITY_TERMS):
        return RouteDecision(INTERNAL_RAG, ELIGIBILITY, signals=signals, scores=scores,
                             reason="지원 대상·적격 판단 요청 — 자동 판정하지 않음", **common)
    # 구조조정·산업위기·채용난·원인을 '단정할 수 있는가' — 등록 진단 범위(점검 신호)로만 답한다
    topics = tuple(k for k, words in LIMIT_TOPICS.items() if any(w in compact for w in words))
    if topics and (not policy_hits or any(m in compact for m in JUDGE_MARKERS)):
        return RouteDecision(INTERNAL_DIAGNOSTIC, LIMIT, signals=signals, subintents=topics, scores=scores,
                             reason="원인·구조조정·위기·채용난 단정 여부 질의", **common)
    # 담당기관·관련기관 — 등록된 기관 매핑과 검증상태로만 답한다('관할'은 사업장 주소 기준 RAG가 맡는다)
    if any(term in compact for term in INSTITUTION_TERMS) and "관할" not in compact:
        return RouteDecision(INTERNAL_RAG, INSTITUTION, signals=signals, scores=scores,
                             reason="담당기관 검증상태 질의", **common)

    # 재표현 요청: 진단 대상을 쉬운 말로(P1: LLM 재작성 + 수치 보존 검증). 개념어만 있으면 일반 설명.
    if rephrase and not (acronym and not diag_hits):
        subs = tuple(k for _, k in diag_hits)
        return RouteDecision(INTERNAL_DIAGNOSTIC, REPHRASE, signals=signals, subintents=subs,
                             scores=scores, reason="명시적 쉬운 설명·요약 요청", **common)

    # 현재 진단카드 설명 요청 → 등록 진단 요약(상태·규모·시간·판정 이유·우선 확인)
    if any(term in compact for term in SUMMARY_TERMS):
        return RouteDecision(INTERNAL_DIAGNOSTIC, SUMMARY, signals=signals, scores=scores,
                             reason="진단카드 요약 요청", **common)

    # 정책 질의가 명확하면(지원사업·지원금·훈련·기관…) 진단어는 문맥으로만 본다.
    #   정책이 이기는 경우: 진단어가 없거나, 지원기능 질의이거나, 정책 점수가 강어+보조어(≥4)이면서
    #   진단어가 수치형 의도(E/R/A/P·Q1~Q3)가 아닐 때. 수치 질문은 항상 등록 진단이 먼저다.
    numeric_diag = any(k in (SIGNAL, Q1, Q2, Q3) for _, k in diag_hits)
    policy_focus = bool(policy_hits) and (
        not diag_hits or policy[SUPPORT_FUNCTIONS] >= THRESHOLD
        or (policy[POLICY] >= 2 * STRONG and not numeric_diag))
    if diag_hits and not policy_focus:
        intents = tuple(k for _, k in diag_hits)
        # 정의형 질문이라도 E/R/A/P·Q1~Q3 같은 시스템 고유 개념은 등록 정의로 답한다
        return RouteDecision(INTERNAL_DIAGNOSTIC, intents[0], signals=signals, subintents=intents,
                             scores=scores, reason="등록 진단 관련 질의", **common)
    if policy_hits:
        intent = SUPPORT_FUNCTIONS if policy[SUPPORT_FUNCTIONS] >= THRESHOLD else POLICY
        return RouteDecision(INTERNAL_RAG, intent, signals=signals, scores=scores,
                             reason="지원사업·기관·공식근거 질의 — 정책 RAG 우선", **common)
    if trend >= THRESHOLD:
        return RouteDecision(EXTERNAL_WEB, TREND, signals=signals, scores=scores,
                             reason="최신 동향 질의 — 등록 진단·정책 원문 범위 밖", **common)
    if concept_marker or acronym:
        return RouteDecision(GENERAL_LLM, CONCEPT, scores=scores, reason="일반 개념 설명 질의", **common)
    return RouteDecision(UNSUPPORTED, UNSUPPORTED, scores=scores,
                         reason="지원 범위 밖 — 현재 업종 진단으로 대신 답하지 않음", **common)
