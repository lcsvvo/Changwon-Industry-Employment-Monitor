# -*- coding: utf-8 -*-
"""인증정보 로딩과 마스킹.

원칙
    - 실제 키 값은 프로세스 메모리 밖으로 나가지 않는다.
      로그·예외메시지·metadata·CSV·JSON 어디에도 남기지 않는다.
    - 키의 존재 여부만 boolean 으로 보고한다.
    - 키를 다른 파일로 복사하지 않는다. `.env.txt` 하나만 읽는다.

키 파일
    저장소 루트의 `.env.txt` (gitignore 대상). `.env` 도 있으면 함께 읽되
    이미 설정된 환경변수를 덮어쓰지 않는다.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

ENV_FILES = (".env.txt", ".env")
KNOWN_KEYS = ("KOSIS_API_KEY", "DATA_GO_KR_SERVICE_KEY", "KEPCO_API_KEY", "ECOS_API_KEY")

_loaded_from: list[str] = []
# 마스킹 대상 값. load_env() 가 채운다.
_secret_values: set[str] = set()


def load_env(root: Path | None = None, *, override: bool = False) -> list[str]:
    """`.env.txt` → `.env` 순으로 읽어 os.environ 에 넣는다. 값은 반환하지 않는다."""
    root = Path(root) if root else Path(__file__).resolve().parents[3]
    loaded = []
    for name in ENV_FILES:
        p = root / name
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if not k or not v:
                continue
            if override or not os.environ.get(k):
                os.environ[k] = v
            _secret_values.add(os.environ[k])
        loaded.append(name)
    _loaded_from[:] = loaded
    return loaded


def available(names: tuple[str, ...] = KNOWN_KEYS) -> dict[str, bool]:
    """키 존재 여부만. 값이나 길이, 앞뒤 일부도 노출하지 않는다."""
    return {n: bool(os.environ.get(n)) for n in names}


def report_availability(names: tuple[str, ...] = KNOWN_KEYS) -> str:
    return "\n".join(f"{n}: {'AVAILABLE' if ok else 'MISSING'}"
                     for n, ok in available(names).items())


def require(name: str) -> str | None:
    """키를 읽는다. 없으면 None. 호출부는 값을 출력하거나 저장하지 않는다."""
    v = os.environ.get(name)
    if v:
        _secret_values.add(v)
    return v


# ---------------------------------------------------------------- 마스킹
# URL 쿼리스트링에 실려 오는 인증 파라미터. 대소문자 구분 없이 잡는다.
_PARAM_RE = re.compile(
    r"(?i)\b(serviceKey|apiKey|api_key|authKey|auth_key|accessKey|key|token|"
    r"secret|password)=([^&\s\"'<>]+)")
# 경로에 키를 끼워 넣는 API (ECOS 가 그렇다): /api/<서비스>/<KEY>/json/...
_PATH_KEY_RE = re.compile(r"(?i)(/api/[A-Za-z]+/)([A-Za-z0-9]{8,})(/)")

MASK = "***REDACTED***"


def mask(text: str) -> str:
    """문자열에서 인증정보로 보이는 부분을 지운다. 로그·metadata 로 나가기 전 필수."""
    if not text:
        return text
    s = str(text)
    for v in _secret_values:
        if v and len(v) >= 8 and v in s:
            s = s.replace(v, MASK)
    s = _PARAM_RE.sub(lambda m: f"{m.group(1)}={MASK}", s)
    s = _PATH_KEY_RE.sub(lambda m: f"{m.group(1)}{MASK}{m.group(3)}", s)
    return s


def mask_params(params: dict) -> dict:
    """요청 파라미터 dict 에서 인증 항목을 제거한다(기록용)."""
    drop = {"servicekey", "apikey", "api_key", "authkey", "auth_key",
            "accesskey", "key", "token", "secret", "password"}
    return {k: v for k, v in params.items() if k.lower() not in drop}


def assert_clean(text: str, where: str = "") -> None:
    """산출물에 키가 섞였는지 확인. 섞였으면 저장 전에 멈춘다."""
    s = str(text)
    for v in _secret_values:
        if v and len(v) >= 8 and v in s:
            raise RuntimeError(f"인증정보가 산출물에 포함됐다: {where or '(위치 미상)'}")
