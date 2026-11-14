"""지원 필요 기능 카탈로그와 기능→담당기관 매핑(function_catalog.json).

- 기능 목록은 이 카탈로그 한 곳에서만 정의한다(화면·서비스·검증이 모두 여기서 읽는다).
- 기관 상태: verified(인계 대상) / proposed(검토 중, 인계 불가) / rejected(인계 대상 아님).
  카탈로그는 기존 최종 산출물 institution_routing_map 행만 담는다. 새 기관은 DB 등록부에 proposed 로만 제안되며,
  관리자 검증(로그인 도입 후)으로 verified 가 되기 전에는 인계 대상이 아니다.
- 기관 기능 확인(function_verified)과 실제 접수경로 확인(intake_route_verified)은 따로 관리한다.
- 매핑 키는 기능뿐이다. 업종·분기·Triage 단계로 기관을 고르지 않는다.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

CATALOG_PATH = Path(__file__).with_name("function_catalog.json")
UNMAPPED_LABEL = "담당기관 미확정"
NO_VERIFIED_MAPPING = "현재 검증된 담당기관 매핑 없음"
NO_REQUIREMENT_CARD = "검증된 지원사업 요건이 아직 등록되지 않았습니다."


@lru_cache(maxsize=1)
def load_catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def catalog_version() -> str:
    return load_catalog()["catalog_version"]


def functions() -> list[dict]:
    return list(load_catalog()["functions"])


def function_tags() -> tuple[str, ...]:
    return tuple(f["tag"] for f in functions())


def function(tag: str) -> dict | None:
    return next((f for f in functions() if f["tag"] == tag), None)


def label(tag: str) -> str:
    f = function(tag)
    return f["label"] if f else tag


def routing_audit() -> list[dict]:
    return list(load_catalog()["routing_audit"])


def _in_routing_map(entry: dict, routing_map: list[dict]) -> bool:
    return any(r.get("institution") == entry["institution"] and r.get("source_url") == entry["source_url"]
               for r in routing_map)


def institution_candidates(tag: str, routing_map: list[dict], registry: list[dict] | None = None) -> list[dict]:
    """기능 하나의 인계 가능 기관 후보(status=verified 만). 없으면 빈 목록(= 담당기관 미확정).

    - 카탈로그 행: verified 이고, 그 행이 해당 분석본의 기관 기능표(routing map)에 실제로 있을 때.
    - 기관 후보 등록부(registry) 행: 관리자 검증으로 verified 가 된 행만. proposed·rejected 는 제외.
    """
    out = []
    for e in routing_audit():
        if e["status"] == "verified" and tag in e["function_tags"] and _in_routing_map(e, routing_map):
            out.append({
                "function_tag": tag, "institution": e["institution"], "unit": e["unit"],
                "function": e["function"], "source_url": e["source_url"], "source": "catalog",
                "verified_at": e["verified_at"], "verification_basis": e["verification_basis"],
                "function_verified": e["function_verified"],
                "intake_route_verified": e["intake_route_verified"], "intake_route": e["intake_route"],
            })
    for r in registry or []:
        if r["status"] == "verified" and tag in (r["function_tags"] or []):
            out.append({
                "function_tag": tag, "institution": r["institution"], "unit": r["unit"],
                "function": r["function_description"], "source_url": r["source_url"],
                "source": f"registry:{r['id']}", "verified_at": (r["reviewed_at"] or "")[:10] or None,
                "verification_basis": r["review_note"], "function_verified": True,
                "intake_route_verified": bool(r["intake_route_verified"]), "intake_route": r["intake_route"],
            })
    return out
