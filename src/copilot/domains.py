"""외부 근거로 인정하는 공식 도메인.

Tier 1: 지정 기관(기관명 표시). Tier 2: 그 밖의 *.go.kr(정부기관). 그 외 일반 웹은 답변 근거로 쓰지 않는다.
"""
from __future__ import annotations

from urllib.parse import urlparse

TIER1 = {
    "changwon.go.kr": "창원특례시",
    "gyeongnam.go.kr": "경상남도",
    "work24.go.kr": "고용24(고용노동부)",
    "moel.go.kr": "고용노동부",
    "motie.go.kr": "산업통상자원부",
    "kicox.or.kr": "한국산업단지공단",
    "bizinfo.go.kr": "기업마당(중소벤처기업부)",
    "gntp.or.kr": "경남테크노파크",
    "cwip.or.kr": "창원산업진흥원",
}
TIER1_DOMAINS = tuple(TIER1)
TIER2_SUFFIX = ".go.kr"


def domain_of(url_or_domain: str | None) -> str | None:
    value = (url_or_domain or "").strip().lower()
    if not value:
        return None
    host = urlparse(value).hostname if "://" in value else value.split("/")[0]
    return (host or "").removeprefix("www.") or None


def classify(url_or_domain: str | None) -> tuple[int | None, str | None]:
    """(tier, 기관명). 허용 목록 밖이면 (None, None)."""
    host = domain_of(url_or_domain)
    if not host:
        return None, None
    for domain, institution in TIER1.items():
        if host == domain or host.endswith("." + domain):
            return 1, institution
    if host.endswith(TIER2_SUFFIX) or host == TIER2_SUFFIX.lstrip("."):
        return 2, f"정부기관({host})"
    return None, None


def is_official(url_or_domain: str | None) -> bool:
    return classify(url_or_domain)[0] is not None
