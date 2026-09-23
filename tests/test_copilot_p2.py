"""Copilot P2 — 공식 API(기업마당) → 정책 RAG → Gemini Google Search grounding(공식 도메인 사후 필터)."""
from __future__ import annotations

import hashlib
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from copilot import Copilot  # noqa: E402
from copilot.audit import MemoryAuditSink  # noqa: E402
from copilot.contracts import EXTERNAL_WEB, INTERNAL_RAG, SYSTEM  # noqa: E402
from copilot.providers.base import (  # noqa: E402
    WebResult, WebSearchResult, official_apis_from_env, providers_from_env,
)
from copilot.providers.gemini import GeminiProvider, GeminiSearchProvider  # noqa: E402
from copilot.providers.official import (  # noqa: E402
    BizinfoProvider, application_period, industry_match, recruitment_status, region_match,
)
from export.snapshot import SNAPSHOT_ROOT, load_snapshot  # noqa: E402
from policy.decision_support import DecisionSupportService  # noqa: E402
from policy.rag import rebuild_policy_index  # noqa: E402
from policy.work24_evidence import register_work24_snapshot  # noqa: E402
from workflow import models as M  # noqa: E402
from workflow.service import WorkflowService  # noqa: E402

TODAY = date(2026, 9, 23)
KEY = "biz-key-0123456789abcdef"
MEMO = "비밀메모-담당자홍길동"


class Resp:
    def __init__(self, status, payload=None):
        self.status_code, self._payload = status, payload

    def json(self):
        if self._payload is None:
            raise ValueError
        return self._payload


def biz_item(name, period, *, url="https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId=P1",
             summary="스마트공장 구축 지원", tags="기술,경남,2026,경상남도,중소기업", agency="경상남도", target="중소기업"):
    """2026-09-23 live 응답과 같은 형식(jsonArray 목록, 'YYYY-MM-DD ~ YYYY-MM-DD')."""
    return {"pblancId": "P1", "pblancNm": name, "jrsdInsttNm": agency, "excInsttNm": "경남테크노파크",
            "bsnsSumryCn": f"&lt;p&gt;{summary}&lt;/p&gt;", "trgetNm": target, "reqstBeginEndDe": period,
            "pblancUrl": url, "hashtags": tags, "pldirSportRealmLclasCodeNm": "기술",
            "pldirSportRealmMlsfcCodeNm": "컨설팅", "rceptEngnHmpgUrl": "https://www.smart-factory.kr/",
            "creatPnttm": "2026-09-01 10:00:00", "totCnt": "580"}


# ------------------------------------------------------------------ 기업마당 API (live 스키마 기준)
def test_bizinfo_parses_live_schema_open_only_and_key_in_params_only():
    calls = []

    def getter(url, *, params, timeout):
        calls.append((url, params))
        return Resp(200, {"jsonArray": [
            biz_item("2026 스마트공장 보급사업", "2026-09-01 ~ 2026-10-31"),
            biz_item("스마트공장 마감 공고", "2026-01-01 ~ 2026-01-31"),                # CLOSED
            biz_item("스마트공장 예정 공고", "2026-10-01 ~ 2026-10-31"),                # UPCOMING
            biz_item("스마트공장 상시", "예산 소진시까지"),                              # UNKNOWN → 표시 안 함
            biz_item("수출 바우처", "2026-09-01 ~ 2026-10-31", summary="해외 판로"),     # 주제 불일치
        ]})
    result = BizinfoProvider(KEY, getter=getter).search("현재 스마트공장 지원사업", terms=["스마트공장"], today=TODAY)
    assert result.ok and [r.title for r in result.results] == ["2026 스마트공장 보급사업"]
    item = result.results[0]
    assert item.url.startswith("https://www.bizinfo.go.kr/") and item.tier == 1
    assert item.institution == "경상남도 (기업마당 공고)" and item.retrieved_at == "2026-09-23"
    view = result.meta["items"][0]
    assert view["recruitment_status"] == "OPEN" and (view["start"], view["end"]) == ("2026-09-01", "2026-10-31")
    assert view["eligibility_verified"] is False and view["apply_url"] == "https://www.smart-factory.kr/"
    assert result.meta["status_counts"] == {"OPEN": 2, "CLOSED": 1, "UPCOMING": 1, "UNKNOWN": 1}
    assert result.meta["total_count"] == 580 and result.meta["fetched"] == 5
    params = calls[0][1]
    assert params["crtfcKey"] == KEY and params["hashtags"] == "경남" and KEY not in calls[0][0]


def test_recruitment_status_is_deterministic_from_dates_only():
    assert recruitment_status("2026-09-01 ~ 2026-10-31", TODAY) == "OPEN"
    assert recruitment_status("2026-09-23 ~ 2026-09-23", TODAY) == "OPEN"
    assert recruitment_status("2026-01-01 ~ 2026-09-22", TODAY) == "CLOSED"
    assert recruitment_status("2026-09-24 ~ 2026-10-31", TODAY) == "UPCOMING"
    for text in ("예산 소진시까지", "상시 접수", "세부사업별 상이", "", None, "2026-10-31 ~ 2026-09-01"):
        assert recruitment_status(text, TODAY) == "UNKNOWN"   # 날짜로 확인 못 하면 OPEN으로 두지 않는다
    assert application_period("20260901 ~ 20261031") == (date(2026, 9, 1), date(2026, 10, 31))


def test_region_and_industry_evidence_come_only_from_announcement_fields():
    assert region_match(biz_item("x", "", tags="기술,경남,경상남도"))["level"] == "GYEONGNAM"
    assert region_match(biz_item("창원 제조기업 지원", "", tags="기술"))["level"] == "CHANGWON"
    many = ",".join(["서울", "부산", "대구", "인천", "대전", "울산", "세종", "경기", "강원", "충북", "경남"])
    assert region_match(biz_item("x", "", tags=many, agency="중소벤처기업부"))["level"] == "NATIONWIDE"
    assert region_match(biz_item("x", "", tags="내수,전북", agency="전북특별자치도"))["level"] == "OTHER_REGION"
    assert region_match(biz_item("x", "", tags="", agency="보건복지부"))["level"] == "NOT_STATED"
    assert industry_match(biz_item("기계부품 공정혁신", ""), ("기계",))["level"] == "DIRECT"
    assert industry_match(biz_item("제조업 스마트화", ""), ("기계",))["level"] == "MANUFACTURING"
    general = industry_match(biz_item("온라인 판로", "", summary="판로"), ("기계",))
    assert general["level"] == "BUSINESS_TYPE_ONLY" and "업종 무관" in general["evidence"]


def test_other_region_items_are_not_shown_and_eligibility_is_never_inferred():
    items = [biz_item("전북 스마트공장", "2026-09-01 ~ 2026-10-31", tags="기술,전북", agency="전북특별자치도"),
             biz_item("경남 스마트공장", "2026-09-01 ~ 2026-10-31")]
    result = BizinfoProvider(KEY, getter=lambda url, **kw: Resp(200, {"jsonArray": items})).search(
        "q", terms=[], today=TODAY, industry_terms=("기계",))
    assert [v["title"] for v in result.meta["items"]] == ["경남 스마트공장"]
    assert all(v["eligibility_verified"] is False for v in result.meta["items"])


@pytest.mark.parametrize("getter,error", [
    (lambda url, **kw: Resp(500), "HTTP_500"),
    (lambda url, **kw: Resp(200, None), "BAD_JSON"),
    (lambda url, **kw: Resp(200, {"resultCode": "99", "resultMsg": "인증키 오류"}), "UNEXPECTED_SCHEMA"),
    (lambda url, **kw: Resp(200, {"jsonArray": "error"}), "UNEXPECTED_SCHEMA"),
    (lambda url, **kw: Resp(200, {"jsonArray": []}), "EMPTY"),
])
def test_bizinfo_failures_are_reported_without_crash(getter, error):
    result = BizinfoProvider(KEY, getter=getter).search("q", terms=[], today=TODAY)
    assert not result.ok and result.error == error


def test_bizinfo_reuses_same_day_response_and_does_not_cache_failures():
    calls = []

    def getter(url, *, params, timeout):
        calls.append(1)
        return Resp(200, {"jsonArray": [biz_item("스마트공장", "2026-09-01 ~ 2026-10-31")]}) if len(calls) > 1 else Resp(503)
    api = BizinfoProvider(KEY, getter=getter)
    assert api.search("q", terms=[], today=TODAY).error == "HTTP_503"          # 실패는 캐시하지 않음
    assert api.search("q", terms=[], today=TODAY).ok and api.search("q", terms=["없는주제"], today=TODAY).error
    assert len(calls) == 2                                                     # 성공 응답은 재사용
    api.search("q", terms=[], today=date(2026, 9, 24))
    assert len(calls) == 3                                                     # 날짜가 바뀌면 다시 조회


def test_bizinfo_timeout_error_does_not_leak_key():
    def boom(url, *, params, timeout):
        raise TimeoutError(f"timed out: {url}?crtfcKey={params['crtfcKey']}")
    result = BizinfoProvider(KEY, getter=boom).search("q", terms=[], today=TODAY)
    assert result.error == "TRANSPORT_TimeoutError" and KEY not in repr(result)
    assert not BizinfoProvider(None).available


# ------------------------------------------------------------------ Gemini grounding (공식 도메인 사후 필터)
def grounding_payload():
    return {"candidates": [{"content": {"parts": [{"text": "ignored"}]}, "groundingMetadata": {
        "webSearchQueries": ["산업일자리전환 지원금 2026 신청"],
        "searchEntryPoint": {"renderedContent": "<div>검색 제안</div>"},
        "groundingChunks": [
            {"web": {"uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AAA", "title": "moel.go.kr"}},
            {"web": {"uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/BBB", "title": "blog.example.com"}},
            {"web": {"uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/CCC", "title": "gyeongnam.go.kr"}},
        ],
        "groundingSupports": [
            {"segment": {"text": "고용노동부는 2026년 산업·일자리전환 지원금을 안내하고 있습니다."}, "groundingChunkIndices": [0]},
            {"segment": {"text": "블로그에 따르면 신청이 쉽습니다."}, "groundingChunkIndices": [1]},
            {"segment": {"text": "기계 업종은 우선점검입니다."}, "groundingChunkIndices": [0]},
            {"segment": {"text": "경상남도도 관련 사업을 공고했습니다."}, "groundingChunkIndices": [2, 1]},
        ]}}]}


RESOLVED = {"AAA": "https://www.moel.go.kr/news/notice/1", "BBB": "https://blog.example.com/post",
            "CCC": "https://www.gyeongnam.go.kr/board/9"}


def resolver(uri):
    return RESOLVED.get(uri.rsplit("/", 1)[-1])


def test_grounding_keeps_only_official_supported_segments():
    calls = []

    def transport(url, *, headers, json, timeout):
        calls.append(json)
        return Resp(200, grounding_payload())
    web = GeminiSearchProvider(GeminiProvider("gkey", transport=transport), resolver=resolver, today=lambda: TODAY)
    result = web.search("산업일자리전환 지원금 현재 신청 가능?", domains=("moel.go.kr", "go.kr"))
    assert calls[0]["tools"] == [{"google_search": {}}]
    assert result.ok and [r.url for r in result.results] == [RESOLVED["AAA"], RESOLVED["CCC"]]
    assert [r.institution for r in result.results] == ["고용노동부", "경상남도"]
    assert all(r.retrieved_at == "2026-09-23" for r in result.results)
    assert "안내하고 있습니다. [1]" in result.answer and "공고했습니다. [2]" in result.answer
    assert "블로그" not in result.answer and "우선점검" not in result.answer   # 비공식·내부판정 문장 제거
    assert result.meta["search_entry_point"] == "<div>검색 제안</div>" and result.raw_result_count == 3


def test_grounding_without_official_support_or_unresolvable_links_returns_nothing():
    web = GeminiSearchProvider(GeminiProvider("gkey", transport=lambda url, **kw: Resp(200, grounding_payload())),
                               resolver=lambda uri: None, today=lambda: TODAY)
    result = web.search("q", domains=("go.kr",))
    assert not result.ok and result.error == "NO_OFFICIAL_SUPPORT" and not result.answer


def test_web_providers_are_opt_in():
    _, web = providers_from_env({"GEMINI_API_KEY": "k"})
    assert not web.available
    _, web = providers_from_env({"GEMINI_API_KEY": "k", "COPILOT_WEB_PROVIDER": "gemini_grounding"})
    assert isinstance(web, GeminiSearchProvider) and web.available
    assert official_apis_from_env({"BIZINFO_API_KEY": KEY}) == []
    apis = official_apis_from_env({"COPILOT_OFFICIAL_APIS": "bizinfo", "BIZINFO_API_KEY": KEY})
    assert len(apis) == 1 and apis[0].available


# ------------------------------------------------------------------ 오케스트레이터 흐름
class FakeWeb:
    name, model = "fake_web", "fake-grounding"

    def __init__(self, results=(), segments=(), ok=True):
        self.calls, self._results, self._segments, self._ok = [], tuple(results), list(segments), ok

    @property
    def available(self):
        return True

    def search(self, query, *, domains, max_results=5, recency_days=None):
        self.calls.append((query, domains))
        answer = " ".join(f"{s['text']} {s['marks']}" for s in self._segments)
        return WebSearchResult(ok=self._ok, results=self._results, answer=answer, provider=self.name, model=self.model,
                               raw_result_count=len(self._results), meta={"segments": self._segments,
                                                                          "search_entry_point": "<div>제안</div>"},
                               error=None if self._ok else "NO_OFFICIAL_SUPPORT")


MOEL = WebResult(title="고용노동부 공지", url="https://www.moel.go.kr/news/notice/1", domain="moel.go.kr",
                 institution="고용노동부", tier=1, retrieved_at="2026-09-23")


class FakeBiz(BizinfoProvider):
    def __init__(self, items):
        super().__init__(KEY, getter=lambda url, **kw: Resp(200, {"jsonArray": items}))


@pytest.fixture(scope="module")
def service(tmp_path_factory):
    path = tmp_path_factory.mktemp("copilot_p2") / "workflow.db"
    Session = M.make_session_factory(f"sqlite:///{path.as_posix()}")
    rebuild_policy_index(Session)
    register_work24_snapshot(Session)
    return DecisionSupportService(Session, load_snapshot("2026Q2", "v3"), WorkflowService(Session))


def make(service, *, web=None, apis=None):
    audit = MemoryAuditSink()
    return Copilot(service, web=web, audit=audit, today=lambda: TODAY, official_apis=apis or []), audit


def ask(copilot, question):
    return copilot.ask(question, "2026Q2", "기계", field_context={"responses": [], "note": MEMO})


class CountingBiz(BizinfoProvider):
    def __init__(self, items=None, *, fail=None):
        self.calls = 0

        def getter(url, *, params, timeout):
            self.calls += 1
            if fail:
                raise fail
            return Resp(200, {"jsonArray": items or []})
        super().__init__(KEY, getter=getter)


OPEN_GN = biz_item("2026 경남 제조기업 스마트공장 지원", "2026-09-01 ~ 2026-10-31", summary="제조기업 공정 개선")
FORBIDDEN = ("신청 가능합니다", "반드시 지원받을 수", "가장 적합", "지원 대상입니다")


def test_bizinfo_supplements_policy_rag_for_recency_question(service):
    biz, web = CountingBiz([OPEN_GN]), FakeWeb([MOEL], [{"text": "웹", "marks": "[1]"}])
    copilot, audit = make(service, web=web, apis=[biz])
    result = ask(copilot, "기계업종 기업이 지금 신청할 수 있는 지원사업 있어?")
    stages = [(s["stage"], s.get("status")) for s in result["route_trace"]]
    assert stages[1][0] == INTERNAL_RAG and ("OFFICIAL_API", "OK") in stages     # RAG 먼저, BIZINFO 보완
    assert biz.calls == 1 and web.calls == []                                   # 공고 확인 → Grounding 미호출
    assert "[현재 모집 공고 · 기업마당 공식 API" in result["answer"]
    assert "실제 신청 가능 여부는 공고의 세부 자격 확인이 필요합니다." in result["answer"]
    assert not any(phrase in result["answer"] for phrase in FORBIDDEN)
    view = result["meta"]["bizinfo"]
    assert view["status"] == "OK" and view["eligibility_verified"] is False
    item = view["items"][0]
    assert item["recruitment_status"] == "OPEN" and item["region_match"]["level"] == "GYEONGNAM"
    assert item["industry_match"]["level"] == "MANUFACTURING"                    # '기계' 아님 — 제조 일반
    assert any(c["url"].startswith("https://www.bizinfo.go.kr/") for c in result["citations"])
    assert "기계: 우선점검)을 대체하지 않습니다" in result["answer"]            # 진단 불변 안내
    assert service.snapshot.get("기계", "2026Q2")["triage"]["stage"] == "우선점검"
    record = audit.records[-1]
    assert record.provider == "bizinfo_api" and record.web_search_used and record.searched_domains == ("bizinfo.go.kr",)


def test_bizinfo_is_not_called_for_non_recency_policy_questions(service):
    biz = CountingBiz([OPEN_GN])
    copilot, _ = make(service, apis=[biz])
    for question in ("직업훈련 지원사업 있어?", "고용유지 지원이 뭐야?", "산업·일자리전환 채용장려금 지원금액은?"):
        result = ask(copilot, question)
        assert result["route"] == INTERNAL_RAG and "bizinfo" not in result["meta"]
    assert biz.calls == 0


def test_bizinfo_topic_filter_reports_no_matching_open_notice(service):
    biz = CountingBiz([OPEN_GN])
    copilot, _ = make(service, apis=[biz])
    result = ask(copilot, "고용유지 관련 현재 모집 중인 사업 있어?")
    assert biz.calls == 1 and result["meta"]["bizinfo"]["status"] == "NO_MATCH"
    assert "관련된 접수 중 공고를 찾지 못했습니다" in result["answer"]
    assert "스마트공장" not in result["answer"]                                  # 무관 공고를 끼워 넣지 않음


def test_bizinfo_outage_keeps_policy_rag_and_says_not_checked(service):
    biz = CountingBiz(fail=TimeoutError("timeout"))
    copilot, audit = make(service, apis=[biz])
    result = ask(copilot, "현재 모집 중인 창원 제조업 지원사업 있어?")
    assert result["source_type"] in (INTERNAL_RAG, SYSTEM) and result["meta"]["bizinfo"]["status"] == "UNAVAILABLE"
    assert any("실시간 확인하지 못했습니다" in c for c in result["caveats"])
    assert audit.records[-1].error == "TRANSPORT_TimeoutError"


def test_grounding_is_off_by_default_and_never_called_automatically(service):
    llm, web = providers_from_env({"GEMINI_API_KEY": "k", "COPILOT_LLM_PROVIDER": "gemini"})
    assert llm.available and not web.available                                   # 일반 LLM만 켜짐
    for value in ("off", "OFF", "", "on", "true", "gemini"):
        assert not providers_from_env({"GEMINI_API_KEY": "k", "COPILOT_WEB_PROVIDER": value})[1].available
    copilot, audit = make(service)                                              # 기본 = Null web
    result = ask(copilot, "현재 산업·일자리전환 채용장려금 신청 가능해?")
    assert ("EXTERNAL_WEB", "NOT_CONFIGURED") in [(s["stage"], s.get("status")) for s in result["route_trace"]]
    assert audit.records[-1].web_search_used is False


def test_insufficient_rag_falls_back_to_grounded_official_web(service):
    web = FakeWeb([MOEL], [{"text": "고용노동부가 2026년 지원금 신청을 안내 중입니다.", "marks": "[1]"}])
    copilot, audit = make(service, web=web)
    result = ask(copilot, "현재 산업·일자리전환 채용장려금 신청 가능해?")
    assert result["source_type"] == EXTERNAL_WEB and result["answer_type"] == "WEB_GROUNDED"
    assert result["composer"] == "LLM" and result["citations"][0]["institution"] == "고용노동부"
    assert result["meta"]["search_entry_point"] == "<div>제안</div>"
    stages = [(s["stage"], s.get("status")) for s in result["route_trace"]]
    assert (INTERNAL_RAG, "FOUND") in stages and (EXTERNAL_WEB, "OK") in stages   # RAG 부족 → 웹
    assert web.calls[0][0] == "현재 산업·일자리전환 채용장려금 신청 가능해?" and MEMO not in str(web.calls)
    assert audit.records[-1].provider == "fake_web" and audit.records[-1].searched_domains == ("moel.go.kr",)


def test_sufficient_rag_does_not_search_web(service):
    web = FakeWeb([MOEL], [{"text": "x", "marks": "[1]"}])
    copilot, _ = make(service, web=web)
    result = ask(copilot, "산업·일자리전환 채용장려금 지원금액은?")
    assert result["source_type"] == INTERNAL_RAG and web.calls == []


def test_non_official_web_result_is_blocked(service):
    blog = WebResult(title="블로그", url="https://blog.example.com/x", domain="blog.example.com", retrieved_at="2026-09-23")
    copilot, _ = make(service, web=FakeWeb([blog], [{"text": "모집 중입니다.", "marks": "[1]"}]))
    result = ask(copilot, "현재 산업·일자리전환 채용장려금 신청 가능해?")
    assert result["source_type"] == SYSTEM and result["guardrail"] == "BLOCKED_NO_OFFICIAL_CITATION"


def test_assertive_web_sentences_are_removed(service):
    segments = [{"text": "고용노동부가 지원금을 안내하고 있습니다.", "marks": "[1]"},
                {"text": "귀사는 지원 대상입니다.", "marks": "[1]"}]
    copilot, _ = make(service, web=FakeWeb([MOEL], segments))
    result = ask(copilot, "현재 산업·일자리전환 채용장려금 신청 가능해?")
    assert "안내하고 있습니다" in result["answer"] and "지원 대상입니다" not in result["answer"]
    step = next(s for s in result["route_trace"] if s["stage"] == EXTERNAL_WEB)
    assert step["assertive_removed"] == 1
    only_bad = make(service, web=FakeWeb([MOEL], segments[1:]))[0]
    fallback = ask(only_bad, "현재 산업·일자리전환 채용장려금 신청 가능해?")
    assert fallback["source_type"] == INTERNAL_RAG and fallback["official_evidence_sufficient"] is False


def test_external_trend_never_replaces_registered_diagnosis(service):
    files = sorted((SNAPSHOT_ROOT / "2026Q2" / "v3").glob("*.json"))
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    web = FakeWeb([MOEL], [{"text": "최근 기계산업 수출이 회복세라는 발표가 있었습니다.", "marks": "[1]"}])
    copilot, _ = make(service, web=web)
    result = ask(copilot, "창원 기계산업 최근 동향은?")
    stage = service.snapshot.get("기계", "2026Q2")["triage"]["stage"]
    assert result["source_type"] == EXTERNAL_WEB and "회복세" in result["answer"]
    assert f"기계: {stage})을 대체하지 않습니다" in result["answer"] and "등록 진단이 기준" in result["answer"]
    assert service.snapshot.get("기계", "2026Q2")["triage"]["stage"] == stage
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files} == before


def test_trend_web_failure_says_not_found_rather_than_not_configured(service):
    # live 검증에서 발견: 설정돼 있는데 결과가 없을 때 '설정되지 않음'으로 안내하던 문구
    copilot, _ = make(service, web=FakeWeb(ok=False))
    result = ask(copilot, "창원 기계산업 최근 동향은?")
    assert result["source_type"] == SYSTEM and result["answer_type"] == "WEB_NO_OFFICIAL_RESULT"
    assert "찾지 못했습니다" in result["answer"] and "설정되지 않았습니다" not in result["answer"]
    assert "이 판정을 바꾸지 않습니다" in result["answer"]


def test_web_failure_keeps_internal_partial_answer(service):
    copilot, audit = make(service, web=FakeWeb(ok=False))
    result = ask(copilot, "현재 산업·일자리전환 채용장려금 신청 가능해?")
    assert result["source_type"] == INTERNAL_RAG and result["official_evidence_sufficient"] is False
    assert audit.records[-1].web_search_used and audit.records[-1].citation_count == len(result["citations"])


def test_other_gyeongnam_locality_notice_is_not_listed_for_changwon():
    # live 검증에서 발견: '[경남] 함양군 …' 공고가 경남 대상으로만 표시됐다 → 제목의 다른 시·군은 제외
    items = [biz_item("[경남] 함양군 2026년 채용장려금 지원사업 모집 공고", "2026-09-01 ~ 2026-10-31"),
             biz_item("[경남] 2026년 스마트공장 지원", "2026-09-01 ~ 2026-10-31")]
    assert region_match(items[0])["level"] == "OTHER_LOCALITY"
    result = BizinfoProvider(KEY, getter=lambda url, **kw: Resp(200, {"jsonArray": items})).search(
        "q", terms=[], today=TODAY)
    assert [v["title"] for v in result.meta["items"]] == ["[경남] 2026년 스마트공장 지원"]


def test_policy_question_without_rag_hit_uses_function_requirement_cards(service):
    biz = CountingBiz([OPEN_GN])
    copilot, _ = make(service, apis=[biz])
    result = ask(copilot, "직업훈련 지원사업 있어?")                          # live: 어휘 RAG 무결과였던 질문
    assert result["source_type"] == INTERNAL_RAG and result["answer_type"] == "REQUIREMENT_CARDS"
    assert "직업훈련" in result["answer"] and "자동 판정하지 않습니다" in result["answer"]
    assert result["citations"] and biz.calls == 0                             # 제도 설명 질문 → BIZINFO 미호출
