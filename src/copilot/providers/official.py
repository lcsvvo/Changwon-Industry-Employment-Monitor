"""공식 구조화 API provider — 기업마당(bizinfo.go.kr) 지원사업정보 API.

역할: 정책 RAG(어떤 제도·기관·지원기능이 있는지)를 대체하지 않고, '지금 모집 중인 공식 공고가 있는지'만 보완한다.
진단(Q1~Q3·E/R/A/P·판정)에는 어떤 영향도 주지 않는다.

실제 응답(2026-09-23 live 확인)
  GET https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do?crtfcKey=<키>&dataType=json&searchCnt=100&hashtags=경남
  → {"jsonArray": [ {...}, ... ]}   (hashtags=경남은 서버 측 필터: 경남 태그 공고만, totCnt=전체 건수)
  항목 필드: pblancId, pblancNm(공고명), jrsdInsttNm(소관기관), excInsttNm(수행기관), bsnsSumryCn(개요, HTML),
            trgetNm(지원대상 유형), reqstBeginEndDe(신청기간 'YYYY-MM-DD ~ YYYY-MM-DD' 또는 '예산 소진시까지' 등),
            pldirSportRealmLclasCodeNm/MlsfcCodeNm(지원분야 대·중분류), hashtags(지역·분야 태그), pblancUrl(상세),
            rceptEngnHmpgUrl(신청 누리집, 일부만), creatPnttm, totCnt 등. 별도의 '모집상태' 필드는 없다.
  인증: BIZINFO_API_KEY를 crtfcKey 쿼리 파라미터로만 보낸다(API 규격). 요청 URL·키를 기록·출력하지 않는다.

판정 원칙(결정론, LLM 미사용)
  - 접수상태: 신청기간이 날짜로 주어지고 오늘이 그 안이면 OPEN, 시작 전이면 UPCOMING, 종료면 CLOSED,
    날짜가 없는 문구('예산 소진시까지'·'상시 접수' 등)는 UNKNOWN. 검색 결과에 있다는 이유만으로 OPEN으로 두지 않는다.
  - 지역·업종: 공고의 hashtags·소관기관·대상·제목·개요에 적힌 표현만 근거로 표시한다.
  - 개별 기업 자격(eligibility_verified)은 항상 False — 세부 자격은 공고문으로 확인해야 한다.
"""
from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Callable

from ..domains import classify
from .base import WebResult, WebSearchResult

BIZINFO_URL = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"
BIZINFO_BASE = "https://www.bizinfo.go.kr"
REGION_TAG = "경남"   # 창원국가산단 소재 광역(서버 측 hashtags 필터)
FETCH_COUNT = 100    # 최근 등록 순 1회 조회(페이지 순회 없음 — 조회 범위는 답변에 표시)
CACHE_SECONDS = 600  # 같은 날 반복 질문마다 API를 부르지 않도록 짧게 재사용
PERIOD = re.compile(r"(\d{4})[.-]?(\d{2})[.-]?(\d{2})\s*~\s*(\d{4})[.-]?(\d{2})[.-]?(\d{2})")
TAG = re.compile(r"<[^>]+>")
SIDO = ("서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원", "충북", "충남", "전북", "전남",
        "경북", "경남", "제주")
GYEONGNAM_SIGUN = ("창원", "진주", "통영", "사천", "김해", "밀양", "거제", "양산", "의령", "함안", "창녕", "고성",
                   "남해", "하동", "산청", "함양", "거창", "합천")
NATIONWIDE_MIN_REGIONS = 10  # 여러 시도가 함께 태그된 공고는 전국 공모로 본다(태그 근거)
MANUFACTURING_WORDS = ("제조업", "제조기업", "제조 기업", "제조")

OPEN, UPCOMING, CLOSED, UNKNOWN = "OPEN", "UPCOMING", "CLOSED", "UNKNOWN"
STATUS_LABEL = {OPEN: "접수 중", UPCOMING: "접수 예정", CLOSED: "접수 종료", UNKNOWN: "접수기간 확인 필요"}

Getter = Callable[..., object]  # requests.get 호환


def _default_get(url, *, params, timeout):
    import requests
    return requests.get(url, params=params, timeout=timeout)


def _clean(text) -> str:
    return re.sub(r"\s+", " ", TAG.sub(" ", html.unescape(str(text or "")))).strip()


def application_period(text: str | None) -> tuple[date | None, date | None]:
    m = PERIOD.search(text or "")
    if not m:
        return None, None
    try:
        return date(*map(int, m.group(1, 2, 3))), date(*map(int, m.group(4, 5, 6)))
    except ValueError:
        return None, None


def recruitment_status(period_text: str | None, today: date) -> str:
    start, end = application_period(period_text)
    if not (start and end) or start > end:
        return UNKNOWN
    if today < start:
        return UPCOMING
    return OPEN if today <= end else CLOSED


def region_match(item: dict) -> dict:
    tags = {t.strip() for t in str(item.get("hashtags") or "").split(",") if t.strip()}
    title, agency = _clean(item.get("pblancNm")), _clean(item.get("jrsdInsttNm"))
    regions = {s for s in SIDO if s in tags or any(s in t for t in tags if len(t) <= 6)}
    if "창원" in title or any("창원" in t for t in tags) or "창원" in agency:
        return {"level": "CHANGWON", "evidence": "공고에 '창원' 명시"}
    locality = next((n for n in GYEONGNAM_SIGUN[1:] if re.search(rf"{n}(시|군)", title)), None)
    if locality:  # 예: '[경남] 함양군 …' — 창원 소재 기업 대상 공고가 아님
        return {"level": "OTHER_LOCALITY", "evidence": f"경남 내 다른 시·군({locality}) 공고"}
    if len(regions) >= NATIONWIDE_MIN_REGIONS:
        return {"level": "NATIONWIDE", "evidence": f"여러 시도 태그({len(regions)}개) — 전국 공모로 표시"}
    if "경남" in regions or agency == "경상남도":
        return {"level": "GYEONGNAM", "evidence": "경남 태그·소관기관 명시"}
    if regions:
        return {"level": "OTHER_REGION", "evidence": f"다른 지역 태그({', '.join(sorted(regions))})"}
    return {"level": "NOT_STATED", "evidence": "지역 표기 없음"}


def industry_match(item: dict, industry_terms: tuple[str, ...]) -> dict:
    text = " ".join(_clean(item.get(k)) for k in ("pblancNm", "hashtags", "bsnsSumryCn"))
    direct = [t for t in industry_terms if t and t in text]
    if direct:
        return {"level": "DIRECT", "evidence": f"공고에 '{', '.join(direct)}' 명시"}
    if any(w in text for w in MANUFACTURING_WORDS):
        return {"level": "MANUFACTURING", "evidence": "공고에 '제조' 명시(특정 업종 아님)"}
    target = _clean(item.get("trgetNm"))
    if target:
        return {"level": "BUSINESS_TYPE_ONLY", "evidence": f"대상 유형 '{target}'만 명시(업종 무관)"}
    return {"level": "NOT_STATED", "evidence": "업종 표기 없음"}


@dataclass(frozen=True)
class BizinfoItem:
    """UI·답변용 결정론 view model(원 필드 + 계산된 표시값)."""
    title: str
    detail_url: str
    agency: str | None
    executor: str | None
    period_text: str
    start: str | None
    end: str | None
    recruitment_status: str
    target: str | None
    category: str | None
    apply_url: str | None
    region_match: dict = field(default_factory=dict)
    industry_match: dict = field(default_factory=dict)
    topic_hit: bool = True
    eligibility_verified: bool = False  # 항상 False — 세부 자격은 공고문 확인 필요


class BizinfoProvider:
    name, model = "bizinfo_api", None

    def __init__(self, api_key: str | None, *, getter: Getter | None = None, timeout: int = 15,
                 fetch_count: int = FETCH_COUNT, region_tag: str = REGION_TAG):
        self._key = api_key
        self._get = getter or _default_get
        self._timeout = timeout
        self._count = fetch_count
        self._region = region_tag
        self._cache = None

    @property
    def available(self) -> bool:
        return bool(self._key)

    def _fetch(self, today: date) -> tuple[list[dict] | None, int | None, str | None]:
        """같은 날·같은 조건 조회는 CACHE_SECONDS 동안 메모리에서 재사용(성공 응답만, 디스크 저장 없음)."""
        import time
        cached = self._cache
        if cached and cached[0] == today and time.monotonic() - cached[1] < CACHE_SECONDS:
            return cached[2], cached[3], None
        items, total, error = self._request()
        if error is None:
            self._cache = (today, time.monotonic(), items, total)
        return items, total, error

    def _request(self) -> tuple[list[dict] | None, int | None, str | None]:
        try:
            response = self._get(BIZINFO_URL, params={"crtfcKey": self._key, "dataType": "json",
                                                      "searchCnt": str(self._count), "hashtags": self._region},
                                 timeout=self._timeout)
        except Exception as exc:  # 예외 메시지에는 요청 URL(키 포함)이 섞일 수 있어 유형만 남긴다
            return None, None, f"TRANSPORT_{type(exc).__name__}"
        status = getattr(response, "status_code", None)
        if status != 200:
            return None, None, f"HTTP_{status}"
        try:
            payload = response.json()
        except ValueError:
            return None, None, "BAD_JSON"
        if not isinstance(payload, dict) or "jsonArray" not in payload:
            return None, None, "UNEXPECTED_SCHEMA"  # 예: 인증 실패 시 다른 형식의 응답
        root = payload["jsonArray"]
        root = root.get("item", []) if isinstance(root, dict) else root
        root = [root] if isinstance(root, dict) else root
        if not isinstance(root, list):
            return None, None, "UNEXPECTED_SCHEMA"
        items = [item for item in root if isinstance(item, dict) and item.get("pblancNm")]
        total = next((item.get("totCnt") for item in items if item.get("totCnt")), None)
        try:
            total = int(total) if total is not None else None
        except (TypeError, ValueError):
            total = None
        return items, total, None if items else "EMPTY"

    def search(self, query: str, *, terms: list[str], today: date, max_results: int = 5,
               industry_terms: tuple[str, ...] = ()) -> WebSearchResult:
        """오늘 접수 중(OPEN)이고 타 지역 전용이 아닌 공고만 결과로 낸다. 주제어(terms)가 있으면 포함 공고만."""
        if not self._key:
            return WebSearchResult(ok=False, provider=self.name, error="OFFICIAL_API_NOT_CONFIGURED")
        items, total, error = self._fetch(today)
        if error:
            return WebSearchResult(ok=False, provider=self.name, error=error,
                                   meta={"fetched": 0 if items is None else len(items), "total_count": total})
        views: list[BizinfoItem] = []
        status_counts: dict[str, int] = {}
        for item in items:
            status = recruitment_status(item.get("reqstBeginEndDe"), today)
            status_counts[status] = status_counts.get(status, 0) + 1
            title = _clean(item.get("pblancNm"))
            body = " ".join(_clean(item.get(k)) for k in ("pblancNm", "bsnsSumryCn", "trgetNm", "hashtags",
                                                          "pldirSportRealmLclasCodeNm",
                                                          "pldirSportRealmMlsfcCodeNm")).lower()
            url = str(item.get("pblancUrl") or "")
            url = url if url.startswith("http") else f"{BIZINFO_BASE}{url}" if url.startswith("/") else ""
            if not url or classify(url)[0] is None:
                continue
            start, end = application_period(item.get("reqstBeginEndDe"))
            apply_url = str(item.get("rceptEngnHmpgUrl") or "").strip()
            views.append(BizinfoItem(
                title=title, detail_url=url, agency=_clean(item.get("jrsdInsttNm")) or None,
                executor=_clean(item.get("excInsttNm")) or None, period_text=_clean(item.get("reqstBeginEndDe")),
                start=start.isoformat() if start else None, end=end.isoformat() if end else None,
                recruitment_status=status, target=_clean(item.get("trgetNm")) or None,
                category=" > ".join(x for x in (_clean(item.get("pldirSportRealmLclasCodeNm")),
                                                _clean(item.get("pldirSportRealmMlsfcCodeNm"))) if x) or None,
                apply_url=apply_url if apply_url.startswith(("http://", "https://")) else None,
                region_match=region_match(item), industry_match=industry_match(item, industry_terms),
                topic_hit=not terms or any(t in body for t in terms)))
        region_rank = {"CHANGWON": 0, "GYEONGNAM": 1, "NATIONWIDE": 2, "NOT_STATED": 3}
        industry_rank = {"DIRECT": 0, "MANUFACTURING": 1, "BUSINESS_TYPE_ONLY": 2, "NOT_STATED": 3}
        shown = sorted((v for v in views if v.recruitment_status == OPEN and v.topic_hit
                        and v.region_match["level"] not in ("OTHER_REGION", "OTHER_LOCALITY")),
                       key=lambda v: (region_rank.get(v.region_match["level"], 9),
                                      industry_rank.get(v.industry_match["level"], 9), v.end or "9999"))[:max_results]
        results = tuple(WebResult(title=v.title, url=v.detail_url, domain="bizinfo.go.kr", tier=1,
                                  institution=f"{v.agency} (기업마당 공고)" if v.agency else "기업마당",
                                  snippet=f"접수 {v.start} ~ {v.end}", retrieved_at=today.isoformat())
                        for v in shown)
        return WebSearchResult(
            ok=bool(shown), results=results, provider=self.name, raw_result_count=len(items),
            error=None if shown else "NO_MATCHING_OPEN_ITEMS",
            meta={"items": [asdict(v) for v in shown], "status_counts": status_counts, "fetched": len(items),
                  "total_count": total, "region_filter": self._region, "topic_terms": list(terms),
                  "industry_terms": list(industry_terms), "checked_at": today.isoformat()})
