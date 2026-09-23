"""Copilot P1 — Gemini provider(가짜 transport)·일반 개념·명시적 쉬운 설명·수치 보존 guardrail."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from copilot import Copilot  # noqa: E402
from copilot.audit import MemoryAuditSink  # noqa: E402
from copilot.contracts import GENERAL_LLM, INTERNAL_DIAGNOSTIC, INTERNAL_RAG, SYSTEM  # noqa: E402
from copilot.providers.base import LLMResult, NullLLMProvider, SourceDoc, providers_from_env  # noqa: E402
from copilot.providers.gemini import GeminiProvider  # noqa: E402
from export.snapshot import load_snapshot  # noqa: E402
from policy.decision_support import DecisionSupportService  # noqa: E402
from policy.rag import rebuild_policy_index  # noqa: E402
from policy.work24_evidence import register_work24_snapshot  # noqa: E402
from workflow import models as M  # noqa: E402
from workflow.service import WorkflowService  # noqa: E402

KEY = "test-key-0123456789abcdef"
SECRET_MEMO = "비밀메모-담당자홍길동"


# ------------------------------------------------------------------ Gemini provider (네트워크 없음)
class FakeResponse:
    def __init__(self, status: int, payload: dict | None = None):
        self.status_code, self._payload = status, payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def gemini_payload(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


class RecordingTransport:
    def __init__(self, response):
        self.response, self.calls = response, []

    def __call__(self, url, *, headers, json, timeout):
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_gemini_request_keeps_key_in_header_only():
    transport = RecordingTransport(FakeResponse(200, gemini_payload("CNC는 컴퓨터 수치 제어입니다.")))
    provider = GeminiProvider(KEY, "gemini-test", transport=transport)
    result = provider.generate("CNC가 뭐야?", system="규칙")
    assert result.ok and result.text.startswith("CNC는") and result.model == "gemini-test"
    call = transport.calls[0]
    assert call["url"].endswith("/models/gemini-test:generateContent")
    assert call["headers"]["x-goog-api-key"] == KEY
    assert KEY not in call["url"] and KEY not in json.dumps(call["json"], ensure_ascii=False)
    assert call["json"]["systemInstruction"]["parts"][0]["text"] == "규칙"
    assert call["json"]["contents"][0]["parts"][0]["text"] == "CNC가 뭐야?"


@pytest.mark.parametrize("response,error", [
    (FakeResponse(429), "HTTP_429"), (FakeResponse(200, {"candidates": []}), "EMPTY"),
    (FakeResponse(200, None), "BAD_JSON"), (TimeoutError("timed out " + KEY), "TRANSPORT_TimeoutError"),
])
def test_gemini_failures_are_reported_without_secret(response, error):
    result = GeminiProvider(KEY, transport=RecordingTransport(response)).generate("q")
    assert not result.ok and result.error == error and KEY not in (result.error or "")


def test_gemini_rejects_truncated_or_blocked_output_and_disables_thinking_on_25_flash():
    # live 검증에서 발견: 2.5 Flash thinking 토큰이 한도를 먹어 답변이 잘린 채 성공 처리됐다(finishReason MAX_TOKENS)
    for reason in ("MAX_TOKENS", "SAFETY"):
        payload = {"candidates": [{"content": {"parts": [{"text": "잘린 답"}]}, "finishReason": reason}]}
        result = GeminiProvider(KEY, transport=RecordingTransport(FakeResponse(200, payload))).generate("q")
        assert not result.ok and result.error == f"FINISH_{reason}"
    stop = {"candidates": [{"content": {"parts": [{"text": "완결"}]}, "finishReason": "STOP"}]}
    transport = RecordingTransport(FakeResponse(200, stop))
    assert GeminiProvider(KEY, "gemini-2.5-flash", transport=transport).generate("q").ok
    assert transport.calls[0]["json"]["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}
    other = RecordingTransport(FakeResponse(200, stop))
    GeminiProvider(KEY, "gemini-other", transport=other).generate("q")
    assert "thinkingConfig" not in other.calls[0]["json"]["generationConfig"]   # 다른 계열은 건드리지 않음


def test_gemini_generate_with_sources_requires_valid_citations():
    sources = [SourceDoc("D11:8", "시행지침", "채용장려금 월 60만원"), SourceDoc("D01:1", "안내", "고용유지")]
    ok = GeminiProvider(KEY, transport=RecordingTransport(FakeResponse(200, gemini_payload(
        "채용장려금은 월 60만원입니다 [S1].")))).generate_with_sources("금액은?", sources)
    assert ok.ok and ok.cited_ids == ("D11:8",)
    for text in ("근거 없이 답함.", "월 60만원 [S9]."):
        bad = GeminiProvider(KEY, transport=RecordingTransport(FakeResponse(200, gemini_payload(text)))) \
            .generate_with_sources("금액은?", sources)
        assert not bad.ok and bad.error == "BAD_CITATIONS"


def test_gemini_is_opt_in_via_environment():
    llm, _ = providers_from_env({"GEMINI_API_KEY": KEY})                      # 키만으로는 켜지지 않음
    assert isinstance(llm, NullLLMProvider)
    llm, _ = providers_from_env({"COPILOT_LLM_PROVIDER": "gemini"})           # 키 없으면 사용 불가
    assert isinstance(llm, GeminiProvider) and not llm.available
    llm, _ = providers_from_env({"COPILOT_LLM_PROVIDER": "gemini", "GEMINI_API_KEY": KEY,
                                 "COPILOT_LLM_MODEL": "gemini-x"})
    assert llm.available and llm.model == "gemini-x"
    source = (ROOT / "src" / "copilot").rglob("*.py")
    assert all(KEY not in p.read_text(encoding="utf-8") for p in source)   # 코드에 key 없음


# ------------------------------------------------------------------ 오케스트레이터 + 가짜 LLM
class FakeLLM:
    name, model = "fake", "fake-1"

    def __init__(self, reply=None, *, ok=True):
        self.reply, self.ok, self.calls = reply, ok, []

    @property
    def available(self):
        return True

    def generate(self, prompt, *, system=None):
        self.calls.append(("generate", prompt, system))
        if not self.ok:
            return LLMResult(ok=False, provider=self.name, model=self.model, error="HTTP_503")
        text = self.reply(prompt) if callable(self.reply) else self.reply
        return LLMResult(ok=True, text=text, provider=self.name, model=self.model)

    def generate_with_sources(self, question, sources, *, system=None):
        self.calls.append(("sources", question + " " + " ".join(s.text for s in sources), system))
        text = self.reply(question) if callable(self.reply) else self.reply
        return LLMResult(ok=True, text=text, provider=self.name, model=self.model, cited_ids=(sources[0].id,))


@pytest.fixture(scope="module")
def service(tmp_path_factory):
    path = tmp_path_factory.mktemp("copilot_p1") / "workflow.db"
    Session = M.make_session_factory(f"sqlite:///{path.as_posix()}")
    rebuild_policy_index(Session)
    register_work24_snapshot(Session)
    snap = load_snapshot("2026Q2", "v3")
    return DecisionSupportService(Session, snap, WorkflowService(Session))


def make(service, llm, **kw):
    audit = MemoryAuditSink()
    return Copilot(service, llm=llm, audit=audit, today=lambda: date(2026, 9, 23), **kw), audit


def ask(copilot, question, **kw):
    return copilot.ask(question, "2026Q2", "기계",
                       field_context={"responses": [], "note": SECRET_MEMO}, **kw)


def test_general_concept_sends_question_only_and_is_labelled(service):
    llm = FakeLLM("CNC는 컴퓨터로 공작기계를 제어하는 방식입니다. MCT는 공구 교환이 자동인 CNC 장비입니다.")
    copilot, audit = make(service, llm)
    result = ask(copilot, "CNC가 뭐야?")
    assert result["source_type"] == GENERAL_LLM and result["composer"] == "LLM"
    assert result["source_label"] == "일반 AI 설명" and "공식 근거" in " ".join(result["caveats"])
    assert llm.calls == [("generate", "CNC가 뭐야?", llm.calls[0][2])]    # 질문 문장만
    assert "기계" not in llm.calls[0][2] or "창원국가산단의 특정 업종" in llm.calls[0][2]
    record = audit.records[-1]
    assert record.llm_used and record.provider == "fake" and record.model == "fake-1" and record.success


def test_general_answer_about_internal_judgment_is_blocked(service):
    copilot, _ = make(service, FakeLLM("CNC는 가공 방식이며 기계 업종은 우선점검입니다."))
    result = ask(copilot, "CNC가 뭐야?")
    assert result["source_type"] == SYSTEM and result["guardrail"] == "BLOCKED_INTERNAL_JUDGMENT"
    assert "우선점검입니다" not in result["answer"]


def test_general_answer_with_eligibility_claim_is_blocked(service):
    copilot, _ = make(service, FakeLLM("CNC 교육을 들으면 지원 대상입니다."))
    result = ask(copilot, "CNC가 뭐야?")
    assert result["source_type"] == SYSTEM and result["guardrail"] == "BLOCKED_ASSERTIVE"


def test_default_diagnostic_answers_never_call_llm(service):
    llm = FakeLLM("무시")
    copilot, _ = make(service, llm)
    for question in ("E값은?", "기계가 왜 우선점검이야?", "Q1~Q3 알려줘", "현장에서는 뭘 확인해야 해?",
                     "산업·일자리전환 채용장려금 지원금액은?"):
        assert ask(copilot, question)["composer"] == "TEMPLATE"
    assert llm.calls == []


def _easy(prompt: str) -> str:
    # 원문 숫자·단계만 쓰는 재작성(원문에서 추출해 그대로 사용)
    assert "우선점검" in prompt and "6.3%" in prompt and "19.5%" in prompt
    return ("기계 업종은 2026Q2에 우선점검 단계예요. 고용이 6.3% 줄었고 생산도 19.5% 줄었어요. "
            "원인을 판정한 것은 아니라서 현장 확인이 필요해요.")


def test_explicit_rephrase_accepts_number_preserving_rewrite(service):
    llm = FakeLLM(_easy)
    copilot, _ = make(service, llm)
    result = ask(copilot, "이 결과를 쉽게 설명해줘")
    assert result["source_type"] == INTERNAL_DIAGNOSTIC and result["composer"] == "LLM"
    assert result["answer"].startswith("기계 업종은 2026Q2에 우선점검")
    original = next(e["registered_answer"] for e in result["evidence"] if "registered_answer" in e)
    assert llm.calls[0][1] == original                         # 입력 = 등록 답변 원문뿐
    assert SECRET_MEMO not in llm.calls[0][1]
    assert any("자동 검증" in c for c in result["caveats"])


@pytest.mark.parametrize("rewrite,reason", [
    ("기계는 우선점검이에요. 고용이 7.2% 줄었어요.", "NEW_NUMBERS"),          # 원문에 없는 숫자
    ("기계는 관찰 단계예요. 고용이 6.3% 줄었어요.", "STAGE_CHANGED"),          # 판정 변경
    ("기계는 우선점검이라 지원 대상입니다.", "ASSERTIVE"),                    # 대상 확정
    ("", "EMPTY"),
])
def test_rephrase_violations_fall_back_to_registered_template(service, rewrite, reason):
    copilot, _ = make(service, FakeLLM(rewrite))
    result = ask(copilot, "이 결과를 쉽게 설명해줘")
    assert result["composer"] == "TEMPLATE" and result["source_type"] == INTERNAL_DIAGNOSTIC
    assert result["guardrail"].startswith(f"REPHRASE_REJECTED:{reason}")
    assert "등록된 판정 근거는" in result["answer"]                 # 원래 template 그대로
    assert any("검증을 통과하지 못해" in c for c in result["caveats"])


def test_rephrase_of_signal_uses_signal_template(service):
    llm = FakeLLM(lambda prompt: "E 고용감소율은 6.34%로 진입 5%를 넘었어요. 상위 10%에는 못 미쳐요.")
    copilot, _ = make(service, llm)
    result = ask(copilot, "E값을 쉽게 설명해줘")
    assert "E 고용감소율: 6.34%" in llm.calls[0][1]              # 무엇을 쉽게 할지 = 신호 답변
    assert result["composer"] == "LLM"


def test_llm_failure_falls_back_and_is_audited(service):
    copilot, audit = make(service, FakeLLM(ok=False))
    general = ask(copilot, "CNC가 뭐야?")
    assert general["source_type"] == SYSTEM and general["answer_type"] == "LLM_FAILED"
    assert audit.records[-1].success is False and audit.records[-1].error == "HTTP_503"
    rephrase = ask(copilot, "쉽게 설명해줘")
    assert rephrase["composer"] == "TEMPLATE" and "등록된 판정 근거는" in rephrase["answer"]


def test_rag_summary_is_opt_in_and_number_checked(service):
    question = "산업·일자리전환 채용장려금 지원금액은?"
    llm = FakeLLM("근거에 따른 요약입니다 [S1].")
    copilot, _ = make(service, llm)                                # 기본: 요약 꺼짐
    assert ask(copilot, question)["composer"] == "TEMPLATE" and llm.calls == []
    copilot, _ = make(service, llm, summarize_rag=True)
    summarized = ask(copilot, question)
    assert summarized["source_type"] == INTERNAL_RAG and summarized["composer"] == "LLM"
    assert "근거 원문:" in summarized["answer"] and summarized["citations"]
    copilot, _ = make(service, FakeLLM("지원금은 월 987654원입니다 [S1]."), summarize_rag=True)
    rejected = ask(copilot, question)                              # 원문에 없는 금액 → 요약 폐기
    assert rejected["composer"] == "TEMPLATE"
    step = next(s for s in rejected["route_trace"] if s.get("stage") == "RAG_SUMMARY_LLM")
    assert step["status"] == "REJECTED" and "987654" in step["unsupported_numbers"]


def test_session_input_never_reaches_llm(service):
    llm = FakeLLM(lambda prompt: "쉬운 설명: 2026Q2 우선점검. 6.3% 19.5%")
    copilot, _ = make(service, llm, summarize_rag=True)
    for question in ("CNC가 뭐야?", "이 결과를 쉽게 설명해줘", "현장에서는 뭘 확인해야 해?",
                     "산업·일자리전환 채용장려금 지원금액은?", "E값은?"):
        ask(copilot, question)
    sent = " ".join(f"{prompt} {system}" for _, prompt, system in llm.calls)
    assert llm.calls and SECRET_MEMO not in sent and "홍길동" not in sent


def test_rephrase_prompt_forbids_new_facts_numbers_and_eligibility():
    # live 검증에서 Gemini가 원문에 없는 숫자(1, 3, 4)를 추가해 guardrail에 걸렸다 → 프롬프트 제약을 명시(guardrail은 그대로)
    from copilot.orchestrator import REPHRASE_SYSTEM
    for phrase in ("새로운 숫자", "새로운 비율", "새로운 순위", "새로운 단계", "새로운 기간", "새로운 예시",
                   "새로운 정책 자격", "새로운 신청 가능 여부", "새로운 인과관계", "값·단위·부호·소수점을 그대로"):
        assert phrase in REPHRASE_SYSTEM, phrase


def test_assertive_rewrite_rejection_records_only_matched_phrase(service):
    copilot, _ = make(service, FakeLLM("기계는 생산이 줄었기 때문입니다. 2026Q2 우선점검."))
    result = ask(copilot, "이 결과를 쉽게 설명해줘")
    step = next(s for s in result["route_trace"] if s.get("stage") == "REPHRASE_LLM")
    assert step["check"] == "ASSERTIVE" and step["matched"] == ["때문입니다"]
    assert result["composer"] == "TEMPLATE" and "등록된 판정 근거는" in result["answer"]
