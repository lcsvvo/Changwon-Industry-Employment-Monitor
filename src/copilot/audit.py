"""Copilot 호출 감사 기록(최소 메타데이터, 추가 전용 JSONL).

저장하지 않는 것: 질문 전문, 답변 본문, 체크리스트 답변·세션 메모, 담당자 이름, workflow 기록, API key.
질문은 HMAC-SHA256 digest 앞 16자리만 남긴다. salt는 COPILOT_AUDIT_SALT(없으면 프로세스마다 새로 생성 →
재시작 후에는 같은 질문끼리도 연결되지 않음).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets as _secrets
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "app_state" / "copilot_audit.jsonl"
_PROCESS_SALT = _secrets.token_bytes(16)


def audit_path_for(database_url: str | None, env: dict | None = None) -> Path:
    """COPILOT_AUDIT_LOG > (SQLite workflow DB와 같은 폴더) > app_state 기본값.

    업무 DB와 같은 위치에 두어, 임시 DB로 도는 테스트·시연이 운영 감사 파일에 섞이지 않게 한다.
    """
    env = os.environ if env is None else env
    if env.get("COPILOT_AUDIT_LOG"):
        return Path(env["COPILOT_AUDIT_LOG"])
    if database_url and database_url.startswith("sqlite:///"):
        return Path(database_url.removeprefix("sqlite:///")).parent / "copilot_audit.jsonl"
    return DEFAULT_PATH


def question_digest(question: str, env: dict | None = None) -> str:
    env = os.environ if env is None else env
    salt = env.get("COPILOT_AUDIT_SALT", "").encode() or _PROCESS_SALT
    normalized = " ".join((question or "").split()).lower().encode()
    return hmac.new(salt, normalized, hashlib.sha256).hexdigest()[:16]


@dataclass(frozen=True)
class AuditRecord:
    timestamp: str
    question_digest: str
    route: str
    intent: str
    source_type: str
    provider: str = "none"
    model: str | None = None
    llm_used: bool = False
    web_search_used: bool = False
    searched_domains: tuple[str, ...] = ()
    citation_count: int = 0
    latency_ms: int = 0
    success: bool = True
    guardrail: str = "PASS"
    error: str | None = None
    stages: tuple[str, ...] = field(default_factory=tuple)  # 거친 단계(route_trace의 stage 이름만)


class AuditSink(Protocol):
    def record(self, record: AuditRecord) -> None: ...


class NullAuditSink:
    def record(self, record: AuditRecord) -> None:
        return None


class MemoryAuditSink:
    def __init__(self):
        self.records: list[AuditRecord] = []

    def record(self, record: AuditRecord) -> None:
        self.records.append(record)


class JsonlAuditSink:
    """추가 전용. 기록 실패가 답변을 막지 않는다(감사 실패는 조용히 건너뜀)."""
    _lock = threading.Lock()

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or os.environ.get("COPILOT_AUDIT_LOG") or DEFAULT_PATH)

    def record(self, record: AuditRecord) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(asdict(record), ensure_ascii=False)
            with self._lock, self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            pass
