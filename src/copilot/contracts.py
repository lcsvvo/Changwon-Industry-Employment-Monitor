"""Copilot 응답 계약.

모든 응답은 source_type을 가진다. 등록 진단(INTERNAL_DIAGNOSTIC)이 authoritative source이며,
다른 source_type의 내용은 등록 진단 값을 바꾸거나 대신하지 않는다.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

INTERNAL_DIAGNOSTIC = "INTERNAL_DIAGNOSTIC"
INTERNAL_RAG = "INTERNAL_RAG"
EXTERNAL_WEB = "EXTERNAL_WEB"
GENERAL_LLM = "GENERAL_LLM"
SYSTEM = "SYSTEM"  # 인사·기능 안내·미지원·provider 미설정 안내(사실 주장 없음)
SOURCE_TYPES = (INTERNAL_DIAGNOSTIC, INTERNAL_RAG, EXTERNAL_WEB, GENERAL_LLM, SYSTEM)

SOURCE_LABEL = {
    INTERNAL_DIAGNOSTIC: "등록된 진단결과",
    INTERNAL_RAG: "내부 RAG 근거",
    EXTERNAL_WEB: "외부 최신정보",
    GENERAL_LLM: "일반 AI 설명",
    SYSTEM: "시스템 안내",
}

# route: 질의 라우터가 고른 경로(응답 source_type과 다를 수 있음 — 예: RAG 부족 → 웹 → 미설정 안내)
GREETING = "GREETING"
CAPABILITY = "CAPABILITY"
UNSUPPORTED = "UNSUPPORTED"
ROUTES = (INTERNAL_DIAGNOSTIC, INTERNAL_RAG, EXTERNAL_WEB, GENERAL_LLM, GREETING, CAPABILITY, UNSUPPORTED)

TEMPLATE = "TEMPLATE"  # 결정론적 문구(기존 backend 결과 그대로)
LLM = "LLM"            # 외부 LLM이 작성(guardrail 통과분만)


@dataclass(frozen=True)
class Citation:
    title: str
    url: str
    source_type: str
    official: bool
    institution: str | None = None
    checked_at: str | None = None  # 내부 문서 verified_at 또는 외부 검색 retrieved_at
    locator: str | None = None     # 쪽·섹션
    tier: int | None = None        # 외부 도메인 등급(1: 지정 기관, 2: *.go.kr)


@dataclass
class CopilotAnswer:
    answer: str
    source_type: str
    route: str
    intent: str
    answer_type: str
    composer: str = TEMPLATE
    citations: list[Citation] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    evidence: list = field(default_factory=list)
    route_trace: list[dict] = field(default_factory=list)
    official_evidence_sufficient: bool | None = None
    target: dict = field(default_factory=dict)
    guardrail: str = "PASS"
    meta: dict = field(default_factory=dict)  # 예: Google 검색 제안(searchEntryPoint) 표시용 HTML

    def to_dict(self) -> dict:
        data = asdict(self)
        data["source_label"] = SOURCE_LABEL[self.source_type]
        # 기존 UI·테스트 호환 키: policy_sources = 인용 원문
        data["policy_sources"] = [c for c in data["citations"]]
        return data
