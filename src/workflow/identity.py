"""실행 맥락과 신원 경계(auth boundary).

업무 계층은 '누가(Actor)'와 '어떤 기록 범위(운영/시연)'를 이 모듈을 통해서만 받는다.
화면의 자유입력 이름을 직접 신원으로 쓰지 않도록 경계를 둔 것이며, 인증 기능을 흉내 내지 않는다.

- local-prototype: 로컬·공모전 프로토타입. 이름을 입력받아 'local:<이름>' 으로 식별한다. 인증 없음.
- external: 외부 인증 공급자(SSO/OAuth) 연결 자리. 아직 구현하지 않았으므로 선택하면 실행을 멈춘다.

시연 범위(demo)는 실행 환경(DSS_DEMO_MODE=1)으로만 정해진다. 화면·서비스 호출로 바꿀 수 없다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

LOCAL_PROTOTYPE = "local-prototype"
EXTERNAL = "external"
AUTH_MODES = (LOCAL_PROTOTYPE, EXTERNAL)


class AuthNotConfigured(RuntimeError):
    pass


@dataclass(frozen=True)
class Actor:
    actor_id: str       # 인증 공급자 식별자(로컬: 'local:<이름>')
    display_name: str   # 업무 기록·화면에 남기는 이름
    auth_mode: str


@dataclass(frozen=True)
class RuntimeContext:
    auth_mode: str
    demo: bool

    @property
    def authenticated(self) -> bool:
        return self.auth_mode != LOCAL_PROTOTYPE

    @property
    def banner(self) -> str:
        parts = ["프로토타입 · 인증 미연결"] if not self.authenticated else []
        if self.demo:
            parts.append("시연 모드 — 이 실행의 모든 업무기록은 시연 기록(운영지표 제외)")
        return " · ".join(parts)


def runtime_context(env: dict | None = None) -> RuntimeContext:
    env = os.environ if env is None else env
    mode = env.get("DSS_AUTH_MODE", LOCAL_PROTOTYPE)
    if mode not in AUTH_MODES:
        raise AuthNotConfigured(f"알 수 없는 인증 모드: {mode}")
    if mode == EXTERNAL:
        raise AuthNotConfigured("외부 인증 공급자 연결은 아직 구현되지 않았습니다(DSS_AUTH_MODE=external 사용 불가).")
    return RuntimeContext(auth_mode=mode, demo=env.get("DSS_DEMO_MODE") == "1")


def local_actor(name: str | None) -> Actor | None:
    """로컬 프로토타입 신원: 화면에서 입력한 이름. 인증된 신원이 아니다."""
    name = (name or "").strip()
    if not name:
        return None
    return Actor(actor_id=f"local:{name}", display_name=name, auth_mode=LOCAL_PROTOTYPE)
