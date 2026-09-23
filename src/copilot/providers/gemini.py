"""Gemini provider (REST generateContent) — P1: 일반 개념 설명·명시적 쉬운 설명·근거 요약.

- API key는 환경변수 GEMINI_API_KEY에서만 읽고 요청 헤더(x-goog-api-key)로만 보낸다(URL·로그·예외에 남기지 않음).
- 새 SDK 의존성 없이 requests로 호출한다. 네트워크 계층은 transport로 주입해 테스트한다.
- 판정·수치를 만들지 않는다: 호출부(orchestrator)가 입력을 고르고, 결과는 guardrail 검증 후에만 쓴다.
"""
from __future__ import annotations

import re
from typing import Callable

from .base import LLMResult, SourceDoc

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-2.5-flash"  # COPILOT_LLM_MODEL로 교체 가능(배포 시 사용 가능 모델 확인)
TIMEOUT_SEC = 20
CITE = re.compile(r"\[S(\d+)\]")

Transport = Callable[..., object]  # requests.post 호환: (url, headers=, json=, timeout=) → response


def _default_transport(url, *, headers, json, timeout):
    import requests
    return requests.post(url, headers=headers, json=json, timeout=timeout)


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str | None, model: str | None = None, *, transport: Transport | None = None,
                 timeout: int = TIMEOUT_SEC, temperature: float = 0.2, max_output_tokens: int = 700):
        self._key = api_key
        self.model = model or DEFAULT_MODEL
        self._transport = transport or _default_transport
        self._timeout = timeout
        self._config = {"temperature": temperature, "maxOutputTokens": max_output_tokens}
        # 2.5 계열은 thinking 토큰이 maxOutputTokens에 포함돼 답변이 잘릴 수 있다(finishReason MAX_TOKENS).
        # 짧은 개념 설명·재표현에는 추론이 필요 없어 끈다(공식 문서: 2.5 Flash thinkingBudget 0 = 비활성).
        if self.model.startswith("gemini-2.5-flash"):
            self._config["thinkingConfig"] = {"thinkingBudget": 0}

    @property
    def available(self) -> bool:
        return bool(self._key)

    # ------------------------------------------------------------ 공통 호출
    def _call(self, prompt: str, system: str | None, *, tools: list | None = None) -> tuple[dict | None, str | None]:
        if not self._key:
            return None, "LLM_PROVIDER_NOT_CONFIGURED"
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": dict(self._config)}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            body["tools"] = tools
        url = f"{API_BASE}/models/{self.model}:generateContent"
        try:
            response = self._transport(url, headers={"x-goog-api-key": self._key,
                                                     "Content-Type": "application/json"},
                                       json=body, timeout=self._timeout)
        except Exception as exc:  # 네트워크 오류 — 메시지에 key가 섞이지 않도록 유형만 남긴다
            return None, f"TRANSPORT_{type(exc).__name__}"
        status = getattr(response, "status_code", None)
        if status != 200:
            return None, f"HTTP_{status}"
        try:
            return response.json(), None
        except ValueError:
            return None, "BAD_JSON"

    @staticmethod
    def _finish_error(data: dict) -> str | None:
        """정상 종료(STOP)가 아니면 오류. 잘린 답변(MAX_TOKENS)·차단(SAFETY 등)을 성공으로 쓰지 않는다."""
        candidates = data.get("candidates") or []
        reason = candidates[0].get("finishReason") if candidates else None
        return None if reason in (None, "STOP") else f"FINISH_{reason}"

    @staticmethod
    def _text(data: dict) -> str:
        candidates = data.get("candidates") or []
        if not candidates:
            return ""
        parts = (candidates[0].get("content") or {}).get("parts") or []
        return "".join(part.get("text", "") for part in parts).strip()

    # ------------------------------------------------------------ LLMProvider
    def generate(self, prompt: str, *, system: str | None = None) -> LLMResult:
        data, error = self._call(prompt, system)
        error = error or self._finish_error(data)
        if error:
            return LLMResult(ok=False, provider=self.name, model=self.model, error=error)
        text = self._text(data)
        if not text:
            return LLMResult(ok=False, provider=self.name, model=self.model, error="EMPTY")
        return LLMResult(ok=True, text=text, provider=self.name, model=self.model)

    def grounded(self, prompt: str, system: str | None) -> tuple[dict | None, str | None]:
        """Google Search grounding 호출(원 응답 그대로). 도메인 필터는 GeminiSearchProvider가 한다."""
        return self._call(prompt, system, tools=[{"google_search": {}}])

    def generate_with_sources(self, question: str, sources: list[SourceDoc], *,
                              system: str | None = None) -> LLMResult:
        """근거 조각만으로 답하게 하고 [S번호] 인용을 요구한다. 인용이 없거나 없는 번호면 실패."""
        if not sources:
            return LLMResult(ok=False, provider=self.name, model=self.model, error="NO_SOURCES")
        numbered = "\n\n".join(f"[S{i}] {s.title}\n{s.text}" for i, s in enumerate(sources, 1))
        prompt = (f"질문: {question}\n\n근거:\n{numbered}\n\n"
                  "위 근거에 있는 내용만으로 답하세요. 각 문장 끝에 근거 번호를 [S1]처럼 표시하세요. "
                  "근거에 없으면 '근거에서 확인되지 않음'이라고 답하세요.")
        result = self.generate(prompt, system=system)
        if not result.ok:
            return result
        cited = tuple(dict.fromkeys(int(n) for n in CITE.findall(result.text)))
        if not cited or any(n < 1 or n > len(sources) for n in cited):
            return LLMResult(ok=False, text=result.text, provider=self.name, model=self.model, error="BAD_CITATIONS")
        return LLMResult(ok=True, text=result.text, provider=self.name, model=self.model,
                         cited_ids=tuple(sources[n - 1].id for n in cited))


# ------------------------------------------------------------------ P2: Google Search grounding
SEARCH_SYSTEM = (
    "대한민국 공공기관의 최신 공식 정보를 찾아 한국어로 3~5문장 답하세요. 정부·지자체·공공기관 누리집(go.kr 등)을 "
    "우선 참고하고, 공고명·담당기관·신청기간이 확인되면 포함하세요. 확인되지 않은 내용은 쓰지 말고, 특정 기업의 지원 "
    "대상 여부나 선정을 단정하지 마세요. 창원국가산단 업종별 판정·조치등급·진단 수치는 언급하지 마세요.")

Resolver = Callable[[str], str | None]  # 인용 redirect URL → 실제 URL(실패 시 None)


def _default_resolver(url: str) -> str | None:
    import requests
    try:
        response = requests.head(url, allow_redirects=True, timeout=6)
        if response.status_code >= 400 or response.url == url:
            response = requests.get(url, allow_redirects=True, timeout=8, stream=True)
            response.close()
        return response.url
    except Exception:
        return None


class GeminiSearchProvider:
    """Gemini + Google Search grounding. 인용 chunk를 실제 URL로 풀어 공식 도메인만 남기고,
    그 chunk가 뒷받침하는 문장(segment)만 답변으로 쓴다."""
    name = "gemini_grounding"

    def __init__(self, llm: GeminiProvider, *, resolver: Resolver | None = None,
                 today: Callable[[], object] | None = None):
        from datetime import date
        self._llm = llm
        self.model = llm.model
        self._resolve = resolver or _default_resolver
        self._today = today or date.today

    @property
    def available(self) -> bool:
        return self._llm.available

    def search(self, query: str, *, domains: tuple[str, ...], max_results: int = 5, recency_days: int | None = None):
        from ..domains import classify, domain_of
        from ..guardrails import mentions_internal_judgment
        from .base import WebResult, WebSearchResult
        hint = ", ".join(domains[:12])
        data, error = self._llm.grounded(f"{query}\n\n우선 참고할 공식 누리집: {hint}", SEARCH_SYSTEM)
        error = error or GeminiProvider._finish_error(data)
        if error:
            return WebSearchResult(ok=False, provider=self.name, model=self.model, error=error)
        candidate = (data.get("candidates") or [{}])[0]
        meta = candidate.get("groundingMetadata") or {}
        chunks = meta.get("groundingChunks") or []
        retrieved = str(self._today())
        allowed: dict[int, WebResult] = {}
        for index, chunk in enumerate(chunks):
            web = chunk.get("web") or {}
            final = self._resolve(web.get("uri") or "") if web.get("uri") else None
            tier, institution = classify(final)
            if not final or tier is None:
                continue
            allowed[index] = WebResult(title=web.get("title") or domain_of(final) or final, url=final,
                                       domain=domain_of(final), tier=tier, institution=institution,
                                       retrieved_at=retrieved)
        order: list[int] = []
        segments: list[dict] = []
        seen: set[str] = set()
        for support in meta.get("groundingSupports") or []:
            idx = [i for i in support.get("groundingChunkIndices") or [] if i in allowed]
            text = ((support.get("segment") or {}).get("text") or "").strip()
            if not idx or not text or mentions_internal_judgment(text):
                continue  # 공식 도메인 근거가 없거나 본 시스템 판정을 말하는 문장은 버린다
            marks = []
            for i in idx:
                if i not in order:
                    order.append(i)
                marks.append(f"[{order.index(i) + 1}]")
            if text not in seen:
                seen.add(text)
                segments.append({"text": text, "marks": "".join(dict.fromkeys(marks))})
        results = tuple(allowed[i] for i in order[:max_results])
        answer = " ".join(f"{s['text']} {s['marks']}" for s in segments)
        ok = bool(answer and results)
        return WebSearchResult(ok=ok, results=results, answer=answer if ok else "", provider=self.name,
                               model=self.model, queries=tuple(meta.get("webSearchQueries") or ()),
                               raw_result_count=len(chunks), error=None if ok else "NO_OFFICIAL_SUPPORT",
                               meta={"segments": segments,
                                     "search_entry_point": (meta.get("searchEntryPoint") or {}).get("renderedContent")})
