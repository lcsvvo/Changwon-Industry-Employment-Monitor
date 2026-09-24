"""고용24 공식 Open API 채용정보 상세 보강기.

목록페이지 상세 URL을 크롤링하지 않는다. 기업/기관 회원으로 승인된
``WORK24_JOB_API_KEY``가 있을 때만 공식 상세 API를 호출한다. 개인회원 키는
고용24가 거부하므로 명확한 외부 한계로 반환하고 기존 자료를 변경하지 않는다.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

from evidence.collection import secrets

ROOT = Path(__file__).resolve().parents[3]
DETAIL_URL = "https://www.work24.go.kr/cm/openApi/call/wk/callOpenApiSvcInfo210D01.do"
COMMON_CODE_URL = "https://www.work24.go.kr/cm/openApi/call/wk/callOpenApiSvcInfo21L01.do"
DEFAULT_INPUT = ROOT / "data/processed/work24/work24_analysis_ready.csv"
DEFAULT_OUTPUT = ROOT / "data/processed/work24/work24_api_enrichment.csv"
DEFAULT_META = ROOT / "data/processed/work24/work24_api_enrichment.metadata.json"


class Work24ApiAccessError(RuntimeError):
    """공식 API 인증·회원유형 때문에 수집을 진행할 수 없음."""


def _text(node: ET.Element | None, path: str) -> str | None:
    value = node.findtext(path) if node is not None else None
    return value.strip() if value and value.strip() else None


def parse_detail_xml(payload: str) -> dict:
    root = ET.fromstring(payload)
    error = _text(root, "error")
    if error:
        code = "PERSONAL_ACCOUNT_NOT_ALLOWED" if "개인회원" in error else "API_ACCESS_DENIED"
        raise Work24ApiAccessError(f"{code}: 고용24 채용정보 API 이용 권한을 확인하세요.")
    detail = root if root.tag == "wantedDtl" else root.find("wantedDtl")
    if detail is None:
        raise Work24ApiAccessError("INVALID_API_RESPONSE: wantedDtl이 없습니다.")
    info = detail.find("wantedInfo")
    keywords = [
        node.text.strip() for node in detail.findall(".//keywordList/srchKeywordNm")
        if node.text and node.text.strip()
    ]
    return {
        "wanted_auth_no": _text(detail, "wantedAuthNo"),
        "occupation": _text(info, "jobsNm"),
        "occupation_code": _text(info, "jobsCd"),
        "related_occupation": _text(info, "relJobsNm"),
        "job_description": _text(info, "jobCont"),
        "recruitment_count": _text(info, "collectPsncnt"),
        "certificate": _text(info, "certificate"),
        "computer_skill": _text(info, "compAbl"),
        "preferred_condition": _text(info, "pfCond"),
        "other_preferred_condition": _text(info, "etcPfCond"),
        "work_region": _text(info, "workRegion"),
        "employment_type": _text(info, "empTpNm"),
        "work_schedule": _text(info, "workdayWorkhrCont"),
        "api_keywords": keywords,
        "source": "WORK24_OFFICIAL_DETAIL_API",
    }


class Work24ApiClient:
    def __init__(self, job_key: str, timeout: int = 30):
        if not job_key:
            raise Work24ApiAccessError("MISSING_KEY: WORK24_JOB_API_KEY가 필요합니다.")
        self.job_key = job_key
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Changwon-Industry-Employment-Monitor/1.0"})

    def detail(self, wanted_auth_no: str) -> dict:
        params = {"authKey": self.job_key, "callTp": "D", "returnType": "XML",
                  "wantedAuthNo": wanted_auth_no, "infoSvc": "VALIDATION"}
        response = self.session.get(DETAIL_URL, params=params, timeout=self.timeout)
        if response.status_code in (403, 429):
            raise Work24ApiAccessError(
                f"ACCESS_SIGNAL_{response.status_code}: 재시도 없이 중단합니다.")
        response.raise_for_status()
        return parse_detail_xml(response.text)


def preflight() -> dict:
    secrets.load_env(ROOT)
    key = secrets.require("WORK24_JOB_API_KEY")
    if not key:
        return {"status": "BLOCKED", "reason": "MISSING_WORK24_JOB_API_KEY"}
    with DEFAULT_INPUT.open("r", encoding="utf-8-sig", newline="") as handle:
        first = next(csv.DictReader(handle), None)
    if not first:
        return {"status": "BLOCKED", "reason": "NO_WORK24_INPUT"}
    try:
        item = Work24ApiClient(key).detail(first["wanted_auth_no"])
    except Work24ApiAccessError as exc:
        return {"status": "BLOCKED", "reason": str(exc).split(":", 1)[0]}
    return {"status": "READY", "sample_id": item["wanted_auth_no"],
            "available_fields": sorted(k for k, v in item.items() if v)}


def enrich(limit: int | None = None, delay: float = 1.0) -> dict:
    """공식 상세 API 결과를 별도 appendable 산출물로 쓴다.

    기존 analysis-ready 파일은 덮어쓰지 않는다. 중단 후 재실행하면 이미 저장된
    구인인증번호를 건너뛰며, 키 값은 어떤 산출물에도 기록하지 않는다.
    """
    secrets.load_env(ROOT)
    key = secrets.require("WORK24_JOB_API_KEY")
    if not key:
        raise Work24ApiAccessError("MISSING_KEY: WORK24_JOB_API_KEY가 필요합니다.")
    with DEFAULT_INPUT.open("r", encoding="utf-8-sig", newline="") as handle:
        source_rows = list(csv.DictReader(handle))
    existing = []
    if DEFAULT_OUTPUT.exists():
        with DEFAULT_OUTPUT.open("r", encoding="utf-8-sig", newline="") as handle:
            existing = list(csv.DictReader(handle))
    seen = {row["wanted_auth_no"] for row in existing}
    pending = [row["wanted_auth_no"] for row in source_rows if row["wanted_auth_no"] not in seen]
    if limit is not None:
        pending = pending[:limit]
    client = Work24ApiClient(key)
    rows = list(existing)
    for wanted_auth_no in pending:
        rows.append(client.detail(wanted_auth_no))
        time.sleep(max(0.0, delay))
    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["wanted_auth_no"]
    tmp = DEFAULT_OUTPUT.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            keywords = row.get("api_keywords") or []
            if isinstance(keywords, str):
                try:
                    keywords = json.loads(keywords)
                except json.JSONDecodeError:
                    keywords = [keywords]
            writer.writerow({**row, "api_keywords": json.dumps(keywords, ensure_ascii=False)})
    os.replace(tmp, DEFAULT_OUTPUT)
    meta = {"status": "COMPLETE" if len(rows) == len(source_rows) else "PARTIAL",
            "source_rows": len(source_rows), "enriched_rows": len(rows),
            "endpoint": DETAIL_URL, "auth_key_stored": False,
            "source": "고용24 공식 채용정보 상세 Open API"}
    DEFAULT_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=("preflight", "enrich"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args(argv)
    result = preflight() if args.command == "preflight" else enrich(args.limit, args.delay)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"READY", "COMPLETE", "PARTIAL"} else 2


if __name__ == "__main__":
    sys.exit(main())
