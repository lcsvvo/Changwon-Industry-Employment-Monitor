"""한국산업단지공단 FactoryOn 공장등록 공개정보 수집·매칭.

공공데이터포털 서비스 15087611의 공식 산업단지명 조회 operation을 사용한다.
인증키는 ``KICOX_FACTORY_API_KEY``에서만 읽으며 URL·로그·예외·산출물에
기록하지 않는다. 대표자·전화·팩스 등 개인정보성 필드는 저장하지 않는다.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import requests

from . import secrets

ROOT = Path(__file__).resolve().parents[3]
BASE_URL = "https://apis.data.go.kr/B550624/fctryRegistInfo"
PORTAL_SPEC_URL = "https://www.data.go.kr/data/15087611/openapi.do"
PORTAL_CHANGE_NOTICE = (
    "https://www.data.go.kr/bbs/ntc/selectNotice.do?originId=NOTICE_0000000004062")
OPERATIONS = {
    "company": ("getFctryPrdctnService_v2", "cmpnyNm"),
    "complex": ("getFctryListInIrsttService_v2", "irsttNm"),
    "factory_id": ("getFctryByFctryManageNoService_v2", "fctryManageNo"),
}
OFFICIAL_COMPLEX_NAME = "창원국가산업단지"
SOURCE_NAME = "한국산업단지공단 FactoryOn 공장등록생산정보조회서비스"
SOURCE_ID = "kicox_factoryon_public_api"
USER_AGENT = "Changwon-Industry-Employment-Monitor/1.0 (public-data research)"
SNAPSHOT_FIELDS = (
    "factory_id", "company_name", "factory_address", "industrial_complex_name",
    "industry_code", "industry_codes", "industry_name", "product",
    "collected_at", "source", "source_operation",
)


class KicoxFactoryError(RuntimeError):
    pass


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _api_key() -> str:
    secrets.load_env(ROOT)
    key = secrets.require("KICOX_FACTORY_API_KEY")
    if not key:
        raise KicoxFactoryError("KICOX_FACTORY_API_KEY is not configured")
    return urllib.parse.unquote(key)


def _parse_payload(response: requests.Response) -> dict:
    content_type = response.headers.get("Content-Type", "").lower()
    raw = response.content
    if "json" in content_type or raw.lstrip().startswith((b"{", b"[")):
        payload = response.json()
        envelope = payload.get("response", payload)
        header = envelope.get("header", {}) or {}
        body = envelope.get("body", {}) or {}
        items = body.get("items", {}) or {}
        if isinstance(items, dict):
            items = items.get("item", []) or []
        if isinstance(items, dict):
            items = [items]
        return {"header": header, "body": body, "items": items, "format": "JSON"}

    # 서버 명시 UTF-8을 우선한다. 콘솔 표시 인코딩은 응답 인코딩과 무관하다.
    encoding = response.encoding or "utf-8"
    root = ET.fromstring(raw.decode(encoding, errors="strict"))
    header_node = root.find("./header")
    if header_node is None:
        header_node = root.find(".//header")
    body_node = root.find("./body")
    if body_node is None:
        body_node = root.find(".//body")
    header = {
        child.tag: (child.text or "").strip()
        for child in list(header_node) if header_node is not None
    }
    body = {
        child.tag: (child.text or "").strip()
        for child in list(body_node) if body_node is not None and child.tag != "items"
    }
    items = [
        {child.tag: (child.text or "").strip() for child in list(item)}
        for item in root.findall(".//items/item")
    ]
    return {"header": header, "body": body, "items": items, "format": "XML"}


@dataclass
class KicoxFactoryClient:
    timeout: int = 30
    delay: float = 0.3
    max_retries: int = 3

    def __post_init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.key = _api_key()
        self.calls = 0
        self._last_request = 0.0

    def request(self, operation: str, query: str, *, page_no: int = 1,
                num_rows: int = 10, response_type: str | None = None) -> dict:
        if operation not in OPERATIONS:
            raise ValueError(f"unknown operation: {operation}")
        op_path, query_param = OPERATIONS[operation]
        params = {"serviceKey": self.key, query_param: query,
                  "pageNo": page_no, "numOfRows": num_rows}
        if response_type:
            params["type"] = response_type
        url = f"{BASE_URL}/{op_path}"
        last_error = None
        for attempt in range(self.max_retries):
            remaining = self.delay - (time.monotonic() - self._last_request)
            if remaining > 0:
                time.sleep(remaining)
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                self.calls += 1
                self._last_request = time.monotonic()
                if response.status_code in (401, 403, 429):
                    raise KicoxFactoryError(f"HTTP {response.status_code}; collection stopped")
                if response.status_code >= 500:
                    last_error = KicoxFactoryError(f"HTTP {response.status_code}")
                elif response.status_code != 200:
                    raise KicoxFactoryError(f"HTTP {response.status_code}")
                else:
                    parsed = _parse_payload(response)
                    code = str(parsed["header"].get("resultCode", ""))
                    parsed.update({"http_status": response.status_code,
                                   "operation": operation,
                                   "operation_path": op_path,
                                   "query_parameter": query_param})
                    if code not in {"00", "0", "0000"}:
                        msg = secrets.mask(str(parsed["header"].get("resultMsg", "API_ERROR")))
                        raise KicoxFactoryError(f"API {code or 'UNKNOWN'}: {msg}")
                    return parsed
            except KicoxFactoryError:
                raise
            except (requests.RequestException, ValueError, ET.ParseError, UnicodeError) as exc:
                last_error = KicoxFactoryError(type(exc).__name__)
            if attempt < self.max_retries - 1:
                time.sleep(2 ** attempt)
        raise last_error or KicoxFactoryError("request failed")


def _safe_item(item: dict, collected_at: str) -> dict[str, str]:
    return {
        "factory_id": item.get("fctryManageNo", ""),
        "company_name": item.get("cmpnyNm", ""),
        "factory_address": item.get("rnAdres", ""),
        "industrial_complex_name": item.get("irsttNm", ""),
        "industry_code": item.get("rprsntvIndutyCode", ""),
        "industry_codes": item.get("indutyCodes", ""),
        "industry_name": item.get("indutyNm", ""),
        "product": item.get("mainProductCn", ""),
        "collected_at": collected_at,
        "source": SOURCE_ID,
        "source_operation": OPERATIONS["complex"][0],
    }


def collect_complex_snapshot(date_stamp: str = "20260923", *,
                             client: KicoxFactoryClient | None = None,
                             page_size: int = 1000) -> dict:
    """공식 산업단지명 exact 결과를 페이지 끝까지 수집하고 검증한다."""
    if not re.fullmatch(r"\d{8}", date_stamp):
        raise ValueError("date_stamp must use YYYYMMDD")
    client = client or KicoxFactoryClient()
    collected_at = utcnow()
    rows: list[dict[str, str]] = []
    page_no = 1
    expected_total: int | None = None
    response_format = ""
    while expected_total is None or len(rows) < expected_total:
        result = client.request("complex", OFFICIAL_COMPLEX_NAME,
                                page_no=page_no, num_rows=page_size)
        response_format = result["format"]
        total = int(result["body"].get("totalCount") or 0)
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise KicoxFactoryError("totalCount changed during pagination")
        page_items = result["items"]
        if not page_items and len(rows) < expected_total:
            raise KicoxFactoryError("pagination ended before totalCount")
        rows.extend(_safe_item(item, collected_at) for item in page_items)
        page_no += 1

    by_id = {row["factory_id"]: row for row in rows if row["factory_id"]}
    missing_ids = sum(not row["factory_id"] for row in rows)
    if len(rows) != expected_total or missing_ids or len(by_id) != len(rows):
        raise KicoxFactoryError(
            "snapshot integrity failed: totalCount/factory_id uniqueness mismatch")
    if any(row["industrial_complex_name"] != OFFICIAL_COMPLEX_NAME for row in rows):
        raise KicoxFactoryError("API returned non-exact industrial complex rows")

    out_dir = ROOT / "data/raw/kicox/datagokr"
    metadata_dir = out_dir / "_metadata"
    out_path = out_dir / f"kicox_factory_changwon_national_{date_stamp}.csv"
    metadata_path = metadata_dir / f"kicox_factory_changwon_national_{date_stamp}.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SNAPSHOT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with out_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reread = list(csv.DictReader(handle))
    if len(reread) != len(rows) or any(
            "�" in str(value) for row in reread for value in row.values()):
        raise KicoxFactoryError("UTF-8 snapshot round-trip validation failed")

    metadata = {
        "collected_at": collected_at,
        "service_name": SOURCE_NAME,
        "source": SOURCE_ID,
        "portal_spec_url": PORTAL_SPEC_URL,
        "portal_change_notice": PORTAL_CHANGE_NOTICE,
        "base_endpoint": BASE_URL,
        "operation": OPERATIONS["complex"][0],
        "query_parameter": OPERATIONS["complex"][1],
        "query_value": OFFICIAL_COMPLEX_NAME,
        "authentication_succeeded": True,
        "api_key_exposed": False,
        "response_format": response_format,
        "api_total_count": expected_total,
        "rows": len(rows),
        "unique_factories": len(by_id),
        "unique_companies": len({normalize_company(row["company_name"]) for row in rows}),
        "pages": page_no - 1,
        "fields_saved": list(SNAPSHOT_FIELDS),
        "personal_fields_saved": False,
        "snapshot": str(out_path),
        "freshness": ("공식 설명상 FactoryOn 등록공장 실시간 조회; 이 파일은 collected_at "
                      "시점 snapshot이며 별도 기준일 필드는 API 응답에 없음"),
    }
    rendered = json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
    secrets.assert_clean(rendered, "KICOX factory metadata")
    metadata_path.write_text(rendered, encoding="utf-8")
    metadata["metadata"] = str(metadata_path)
    metadata["api_calls"] = client.calls
    return metadata


_LEGAL_FORMS = re.compile(
    r"(?:주식회사|유한회사|합자회사|합명회사|사단법인|재단법인|"
    r"\(\s*[주유]\s*\)|㈜|㈲|^\s*[주유]\s*\)|\(\s*[주유]\s*$)", re.I)


def normalize_company(value: str | None) -> str:
    value = (value or "").replace("（", "(").replace("）", ")")
    value = _LEGAL_FORMS.sub("", value)
    return re.sub(r"[^0-9A-Za-z가-힣]", "", value).casefold()


def normalize_address(value: str | None) -> str:
    value = (value or "").replace("경상남도", "").replace("경남", "")
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"지도\s*보기|길찾기", " ", value)
    return re.sub(r"[^0-9A-Za-z가-힣]", "", value).casefold()


def _address_parts(value: str | None) -> dict[str, set[str] | str]:
    text = (value or "").replace("경상남도", "").replace("경남", "")
    district = next(iter(re.findall(
        r"(?:의창구|성산구|마산합포구|마산회원구|진해구)", text)), "")
    roads = set(re.findall(r"[가-힣0-9·\.]+(?:대로|로|길)", text))
    localities = set(re.findall(r"[가-힣0-9·\.]+(?:동|읍|면|리)", text))
    numbers = set(re.findall(r"(?<![가-힣0-9])\d+(?:-\d+)?", text))
    return {"district": district, "roads": roads,
            "localities": localities, "numbers": numbers}


def address_aligned(left: str | None, right: str | None) -> bool:
    """구가 같고 정확 주소 또는 도로/동+번호가 겹칠 때만 강한 주소 근거."""
    if not left or not right:
        return False
    ln, rn = normalize_address(left), normalize_address(right)
    lp, rp = _address_parts(left), _address_parts(right)
    if not lp["district"] or lp["district"] != rp["district"]:
        return False
    if ln == rn:
        return True
    same_place = bool(lp["roads"] & rp["roads"] or
                      lp["localities"] & rp["localities"])
    return bool(same_place and lp["numbers"] & rp["numbers"])


def match_company(company_name: str, addresses: list[str],
                  official_rows: list[dict[str, str]]) -> dict[str, str | bool]:
    """한 기업을 보수적으로 매칭한다. 유사도만으로 CONFIRMED하지 않는다."""
    normalized = normalize_company(company_name)
    exact = [row for row in official_rows
             if normalize_company(row["company_name"]) == normalized]
    aligned = [row for row in exact if any(
        address_aligned(address, row["factory_address"]) for address in addresses)]
    if aligned:
        return _match_result("CONFIRMED", "OFFICIAL_EXACT_COMPANY_NAME_AND_ADDRESS",
                             True, aligned)
    if exact:
        return _match_result(
            "POSSIBLE",
            "OFFICIAL_EXACT_COMPANY_NAME_ADDRESS_INSUFFICIENT_OR_CONFLICTING",
            False, exact)

    fuzzy = []
    for row in official_rows:
        candidate = normalize_company(row["company_name"])
        score = SequenceMatcher(None, normalized, candidate).ratio() if normalized and candidate else 0
        if score >= 0.9 and any(
                address_aligned(address, row["factory_address"]) for address in addresses):
            fuzzy.append(row)
    if fuzzy:
        return _match_result(
            "POSSIBLE", "OFFICIAL_FUZZY_COMPANY_NAME_WITH_ADDRESS_MANUAL_REVIEW",
            False, fuzzy)
    return _match_result("UNKNOWN", "NO_CONSERVATIVE_OFFICIAL_FACTORY_MATCH",
                         False, [])


def _match_result(status: str, basis: str, official: bool,
                  rows: list[dict[str, str]]) -> dict[str, str | bool]:
    return {
        "status": status,
        "basis": basis,
        "official_evidence": official,
        "factory_ids": "|".join(sorted({row["factory_id"] for row in rows})),
        "industrial_complex_name": "|".join(sorted({
            row["industrial_complex_name"] for row in rows})),
        "official_source": SOURCE_ID,
    }


def safe_probe(operation: str, query: str, response_type: str | None = None) -> dict:
    client = KicoxFactoryClient()
    result = client.request(operation, query, page_no=1, num_rows=1,
                            response_type=response_type)
    body = result["body"]
    return {
        "authentication_succeeded": True,
        "http_status": result["http_status"],
        "response_code": result["header"].get("resultCode"),
        "response_message": result["header"].get("resultMsg"),
        "format": result["format"],
        "operation_path": result["operation_path"],
        "query_parameter": result["query_parameter"],
        "page_no": body.get("pageNo"),
        "num_rows": body.get("numOfRows"),
        "total_count": body.get("totalCount"),
        "item_keys": sorted(result["items"][0]) if result["items"] else [],
        "api_key_exposed": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=("probe", "collect"))
    parser.add_argument("--operation", choices=tuple(OPERATIONS), default="complex")
    parser.add_argument("--query", default=OFFICIAL_COMPLEX_NAME)
    parser.add_argument("--response-type", choices=("json", "xml"))
    parser.add_argument("--date-stamp", default="20260923")
    args = parser.parse_args(argv)
    try:
        result = (collect_complex_snapshot(args.date_stamp) if args.command == "collect"
                  else safe_probe(args.operation, args.query, args.response_type))
    except Exception as exc:
        result = {"authentication_succeeded": False,
                  "error": secrets.mask(f"{type(exc).__name__}: {exc}"),
                  "api_key_exposed": False}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    secrets.assert_clean(rendered, "KICOX command output")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
