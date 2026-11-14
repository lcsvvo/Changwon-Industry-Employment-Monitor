"""분석본에 등록된 참조 문서(방법론 등) 원문 인용 — 읽기 전용.

화면은 방법론을 새로 쓰지 않고, 분석본 provenance_refs 에 해시가 등록된 문서의 절을 그대로 인용한다.
현재 파일 해시가 등록 해시와 다르면 불일치로 표시한다(문서가 분석본 등록 이후 바뀐 경우).
"""
from __future__ import annotations

import re

from export.snapshot import ROOT, Snapshot, _sha256


def registered_document(snapshot: Snapshot, key: str, root=ROOT) -> dict:
    ref = next((r for r in snapshot.meta.get("provenance_refs", []) if r["key"] == key), None)
    if ref is None:
        return {"key": key, "available": False, "reason": "이 분석본에 등록되지 않은 문서"}
    path = root / ref["path"]
    if not path.exists():
        return {"key": key, "available": False, "path": ref["path"], "reason": "문서 파일 없음"}
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    sections: dict[str, str] = {}
    title, current = None, None
    for line in text.split("\n"):
        if line.startswith("# ") and title is None:
            title = line[2:].strip()
        elif line.startswith("## "):
            current = line[3:].strip()
            sections[current] = ""
        elif current is not None:
            sections[current] += line + "\n"
    # 화면에서 그릴 수 없는 코드 블록(mermaid 등)은 원문 위치만 남기고 뺀다
    sections = {k: re.sub(r"```.*?```", "", v, flags=re.S).strip() for k, v in sections.items()}
    actual = _sha256(path)
    return {"key": key, "available": True, "path": ref["path"], "title": title, "sections": sections,
            "registered_sha256": ref["sha256"], "sha256": actual, "hash_match": actual == ref["sha256"]}
