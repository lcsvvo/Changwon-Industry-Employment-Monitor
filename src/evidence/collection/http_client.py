# -*- coding: utf-8 -*-
"""공개데이터 수집용 최소 HTTP 클라이언트.

접근통제 우회 기능을 두지 않는다. 로그인, CAPTCHA, 유료 우회를 시도하지 않으며
서버가 401/403/429 를 반환하면 그대로 기록하고 중단한다.
"""
from __future__ import annotations

import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from .secrets import mask

USER_AGENT = (
    "Changwon-Industry-Employment-Monitor/1.0 (academic research; "
    "public open data collection)"
)
DEFAULT_DELAY_SEC = 1.5          # 호출 간 최소 간격 (서버 부하 배려)
DEFAULT_TIMEOUT_SEC = 60

_last_call: dict[str, float] = {}


@dataclass
class Response:
    url: str                      # 인증 파라미터가 마스킹된 URL (원본 아님)
    status: int
    body: bytes
    headers: dict = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self) -> None:
        # 이 객체는 로그·metadata 로 흘러가므로 생성 시점에 인증정보를 지운다.
        self.url = mask(self.url)
        if self.error:
            self.error = mask(self.error)

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status < 300

    def filename(self) -> str | None:
        disp = self.headers.get("Content-Disposition") or ""
        if "filename=" not in disp:
            return None
        raw = disp.split("filename=", 1)[1].strip().strip('"')
        # data.go.kr 은 UTF-8 바이트를 latin-1 로 실어 보낸다.
        try:
            raw = raw.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        return urllib.parse.unquote(raw)


def _throttle(url: str, delay: float) -> None:
    host = urllib.parse.urlsplit(url).netloc
    prev = _last_call.get(host)
    if prev is not None:
        wait = delay - (time.monotonic() - prev)
        if wait > 0:
            time.sleep(wait)
    _last_call[host] = time.monotonic()


def fetch(url: str, *, headers: dict | None = None, timeout: int = DEFAULT_TIMEOUT_SEC,
          delay: float = DEFAULT_DELAY_SEC, retries: int = 2,
          verify_tls: bool = True) -> Response:
    """단일 GET. 예외를 던지지 않고 Response.error 로 돌려준다."""
    h = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    h.update(headers or {})
    ctx = ssl.create_default_context()
    if not verify_tls:
        # 일부 국가기관 사이트는 중간 인증서 체인을 보내지 않는다. 사용처를 명시적으로 남긴다.
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    last: Response | None = None
    for attempt in range(retries + 1):
        _throttle(url, delay)
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=h), timeout=timeout, context=ctx
            ) as r:
                return Response(url, r.status, r.read(), dict(r.headers))
        except urllib.error.HTTPError as e:
            body = b""
            try:
                body = e.read()
            except Exception:  # noqa: BLE001 - 본문 없는 오류 응답
                pass
            last = Response(url, e.code, body, dict(e.headers or {}),
                            f"HTTPError {e.code}")
            if e.code in (401, 403, 429):
                return last          # 접근통제/호출제한은 재시도하지 않는다
        except (urllib.error.URLError, socket.timeout, ssl.SSLError, OSError) as e:
            # 예외 문자열에 요청 URL(=키 포함)이 끼어들 수 있다. Response 가 마스킹한다.
            last = Response(url, 0, b"", {}, f"{type(e).__name__}: {e}")
        if attempt < retries:
            time.sleep(2.0 * (attempt + 1))
    return last or Response(url, 0, b"", {}, "unknown failure")
