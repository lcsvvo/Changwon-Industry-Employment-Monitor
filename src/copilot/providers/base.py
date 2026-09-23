"""외부 provider 인터페이스.

provider는 문자열 입력만 받는다. 등록 Snapshot·workflow 객체나 세션 입력(체크리스트 답변·메모·담당자명)은
provider로 넘기지 않는다 — orchestrator가 넘길 값을 고른다. provider 결과는 표시용 텍스트이며
어떤 저장소에도 쓰지 않는다. API key는 환경변수로만 읽는다(코드·로그에 남기지 않음).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SourceDoc:
    """LLM 요약에 넘기는 근거 조각(RAG hit·웹 결과). id로 인용을 대조한다."""
    id: str
    title: str
    text: str
    url: str | None = None
    institution: str | None = None
    checked_at: str | None = None


@dataclass(frozen=True)
class LLMResult:
    ok: bool
    text: str = ""
    provider: str = "none"
    model: str | None = None
    cited_ids: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class WebResult:
    title: str
    url: str
    snippet: str = ""
    domain: str | None = None
    institution: str | None = None
    tier: int | None = None
    published_at: str | None = None
    retrieved_at: str | None = None


@dataclass(frozen=True)
class WebSearchResult:
    ok: bool
    results: tuple[WebResult, ...] = ()
    answer: str = ""  # grounding provider가 함께 준 요약(인용 검증 후에만 사용)
    provider: str = "none"
    model: str | None = None
    queries: tuple[str, ...] = ()
    error: str | None = None
    raw_result_count: int = 0  # 도메인 필터 전 결과 수(감사 기록용)
    meta: dict = field(default_factory=dict)


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    model: str | None

    @property
    def available(self) -> bool: ...

    def generate(self, prompt: str, *, system: str | None = None) -> LLMResult: ...

    def generate_with_sources(self, question: str, sources: list[SourceDoc], *,
                              system: str | None = None) -> LLMResult: ...


@runtime_checkable
class WebSearchProvider(Protocol):
    name: str
    model: str | None

    @property
    def available(self) -> bool: ...

    def search(self, query: str, *, domains: tuple[str, ...], max_results: int = 5,
               recency_days: int | None = None) -> WebSearchResult: ...


class NullLLMProvider:
    """provider 미설정. 호출돼도 내용을 만들지 않는다."""
    name, model = "none", None

    @property
    def available(self) -> bool:
        return False

    def generate(self, prompt: str, *, system: str | None = None) -> LLMResult:
        return LLMResult(ok=False, error="LLM_PROVIDER_NOT_CONFIGURED")

    def generate_with_sources(self, question: str, sources: list[SourceDoc], *,
                              system: str | None = None) -> LLMResult:
        return LLMResult(ok=False, error="LLM_PROVIDER_NOT_CONFIGURED")


class NullWebSearchProvider:
    name, model = "none", None

    @property
    def available(self) -> bool:
        return False

    def search(self, query: str, *, domains: tuple[str, ...], max_results: int = 5,
               recency_days: int | None = None) -> WebSearchResult:
        return WebSearchResult(ok=False, error="WEB_PROVIDER_NOT_CONFIGURED")


def providers_from_env(env: dict | None = None) -> tuple[LLMProvider, WebSearchProvider]:
    """환경변수로 provider를 고른다. 명시적으로 켠 경우에만 외부 호출(기본은 미설정).

    COPILOT_LLM_PROVIDER=gemini + GEMINI_API_KEY → Gemini(일반 개념·명시적 쉬운 설명). 모델: COPILOT_LLM_MODEL.
    key는 저장소 루트 .env.txt(gitignore)나 환경변수로만 설정한다.
    """
    import os

    from evidence.collection import secrets
    if env is None:
        secrets.load_env()  # .env.txt → os.environ (이미 설정된 값은 덮어쓰지 않음)
        env = os.environ
    llm: LLMProvider = NullLLMProvider()
    web: WebSearchProvider = NullWebSearchProvider()
    key = env.get("GEMINI_API_KEY") or None
    if key and env is os.environ:
        secrets.require("GEMINI_API_KEY")  # 마스킹 대상 등록
    want_llm = env.get("COPILOT_LLM_PROVIDER", "").lower() == "gemini"
    # Grounding은 기본 OFF(값 없음·'off'·그 밖의 값 모두 OFF). 현재 구현은 Grounded Result를 문장 단위로
    # 걸러 표시하므로 Gemini API 약관(Grounded Result·Search Suggestions 비수정·비혼합 표시)과 충돌할 수 있다.
    # 약관에 맞는 표시(원문 그대로 + Search Suggestions + 별도 '시스템 확인' 블록)를 갖추기 전에는 켜지 않는다.
    want_web = env.get("COPILOT_WEB_PROVIDER", "off").strip().lower() == "gemini_grounding"
    gemini = None
    if want_llm or want_web:
        from .gemini import GeminiProvider
        gemini = GeminiProvider(key, env.get("COPILOT_LLM_MODEL") or None)
    if want_llm:
        llm = gemini
    if want_web:  # P2: Google Search grounding + 공식 도메인 사후 필터
        from .gemini import GeminiSearchProvider
        web = GeminiSearchProvider(gemini)
    return llm, web


def official_apis_from_env(env: dict | None = None) -> list:
    """공식 구조화 API. COPILOT_OFFICIAL_APIS=bizinfo + BIZINFO_API_KEY일 때만."""
    import os

    from evidence.collection import secrets
    if env is None:
        secrets.load_env()
        env = os.environ
    enabled = {x.strip().lower() for x in env.get("COPILOT_OFFICIAL_APIS", "").split(",") if x.strip()}
    apis = []
    if "bizinfo" in enabled:
        from .official import BizinfoProvider
        key = env.get("BIZINFO_API_KEY") or None
        if key and env is os.environ:
            secrets.require("BIZINFO_API_KEY")
        apis.append(BizinfoProvider(key))
    return apis
