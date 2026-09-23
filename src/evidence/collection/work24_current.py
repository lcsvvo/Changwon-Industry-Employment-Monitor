"""현행 work24.go.kr 공개 채용정보의 소량 감사·우선업종 보강 수집기.

레거시 ``work.go.kr`` 센터 목록 수집기는 보존한다. 이 모듈은 현행
``/wk/a/b/1200`` 검색과 ``/wk/a/b/1500`` 상세만 별도로 다루며, 실행할 때마다
도메인별 robots.txt를 다시 확인한다. ``enrich-priority`` 명령은 최신 진단에서
우선점검으로 확정된 산업의 기존 매핑 공고만 대상으로 한다. 한 번의 실행에 적용하는
10건 한도는 샘플 수집 안전장치이며, 140건 요청의 이용범위 해당 여부를 뜻하지 않는다.
140건 자동 요청은 한국고용정보원 이용범위 확인 전 보류한다.

연락 담당자 이름·전화·이메일 영역은 파싱하지 않는다. 직무내용 안에 섞인
전화·이메일도 저장 전에 제거한다.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[3]
EXISTING_DATA = ROOT / "data/processed/work24/work24_analysis_ready.csv"
LATEST_TRIAGE = ROOT / "outputs/final_model/02_triage/tables/triage_latest.csv"
RAW_WORK24_DIR = ROOT / "data/raw/work24"
PROCESSED_WORK24_DIR = ROOT / "data/processed/work24"

CURRENT_ORIGIN = "https://www.work24.go.kr"
CURRENT_ROBOTS_URL = f"{CURRENT_ORIGIN}/robots.txt"
LEGACY_ROBOTS_URL = "https://www.work.go.kr/robots.txt"
LIST_URL = f"{CURRENT_ORIGIN}/wk/a/b/1200/retriveDtlEmpSrchList.do"
LIST_POST_URL = f"{CURRENT_ORIGIN}/wk/a/b/1200/retriveDtlEmpSrchListInPost.do"
DETAIL_URL = f"{CURRENT_ORIGIN}/wk/a/b/1500/empDetailAuthView.do"
TERMS_URL = f"{CURRENT_ORIGIN}/cm/c/d/0130/retrieveUtzeStpt.do"

CURRENT_PATHS = {
    "search_prefix": "/wk/a/b/1200/",
    "detail_prefix": "/wk/a/b/1500/",
    "search_page": "/wk/a/b/1200/retriveDtlEmpSrchList.do",
    "detail_page": "/wk/a/b/1500/empDetailAuthView.do",
}
CHANGWON_REGION_CODES = ("48125", "48127", "48123", "48121", "48129")
USER_AGENT = (
    "Changwon-Industry-Employment-Monitor/1.1 "
    "(academic research; public non-personal job information)"
)
REQUEST_DELAY_SEC = 2.0
REQUEST_TIMEOUT_SEC = 30
MAX_RETRIES = 3
SAMPLE_MAX = 10
EXPECTED_PRIORITY_INDUSTRIES = ("기계", "목재종이")
KICOX_INDUSTRIES = (
    "음식료", "섬유의복", "목재종이", "석유화학", "비금속",
    "철강", "기계", "전기전자", "운송장비", "기타",
)

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?<!\d)(?:01[016789]|0\d{1,2})[- )]?\d{3,4}[- ]?\d{4}(?!\d)")


class Work24AccessStop(RuntimeError):
    """robots 또는 HTTP 차단 신호로 안전하게 중단됨."""


class Work24HTTPError(RuntimeError):
    """재시도하면 안 되는 HTTP 오류."""

    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def redact_contact(value: str | None, *, collapse_whitespace: bool = True) -> str | None:
    """업무 텍스트에 혼입된 이메일·전화번호를 저장 전에 제거한다."""
    if value is None:
        return None
    value = EMAIL_RE.sub("[CONTACT_REDACTED]", value)
    value = PHONE_RE.sub("[CONTACT_REDACTED]", value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    if collapse_whitespace:
        return re.sub(r"\s+", " ", value).strip()
    return "\n".join(line.rstrip() for line in value.split("\n")).strip()


def robots_allows(robots_text: str, robots_url: str, target_url: str,
                  user_agent: str = USER_AGENT) -> bool:
    parser = RobotFileParser()
    parser.set_url(robots_url)
    parser.parse(robots_text.splitlines())
    return parser.can_fetch(user_agent, target_url)


def relevant_robots_rules(robots_text: str) -> list[str]:
    """보고용: User-agent * 그룹과 선행 Allow/Sitemap만 보존한다."""
    lines = [line.strip() for line in robots_text.splitlines()]
    kept: list[str] = []
    in_star = False
    for line in lines:
        if not line or line.startswith("#"):
            continue
        lower = line.lower()
        if lower.startswith("user-agent:"):
            in_star = line.split(":", 1)[1].strip() == "*"
            if in_star:
                kept.append(line)
            continue
        if in_star and lower.startswith(("allow:", "disallow:")):
            kept.append(line)
        elif not kept and lower.startswith(("allow:", "sitemap:")):
            kept.append(line)
    return kept


@dataclass
class SafeSession:
    delay: float = REQUEST_DELAY_SEC
    timeout: int = REQUEST_TIMEOUT_SEC
    max_retries: int = MAX_RETRIES

    def __post_init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        self._last_request = 0.0
        self.stopped = False
        self.status_counts: Counter[int] = Counter()
        self.network_errors = 0

    def get(self, url: str, params: dict | None = None) -> requests.Response:
        if self.stopped:
            raise Work24AccessStop("client already stopped after an access signal")
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            remaining = self.delay - (time.monotonic() - self._last_request)
            if remaining > 0:
                time.sleep(remaining)
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                self._last_request = time.monotonic()
                self.status_counts[response.status_code] += 1
                if response.status_code in (403, 429):
                    self.stopped = True
                    raise Work24AccessStop(
                        f"HTTP {response.status_code}; no retry and all collection stopped")
                if response.status_code == 200:
                    if not response.encoding or response.encoding.lower() in {"iso-8859-1", "ascii"}:
                        response.encoding = response.apparent_encoding or "utf-8"
                    return response
                if response.status_code < 500:
                    raise Work24HTTPError(response.status_code)
                last_error = requests.HTTPError(f"HTTP {response.status_code}")
            except Work24AccessStop:
                raise
            except Work24HTTPError:
                raise
            except requests.RequestException as exc:
                self.network_errors += 1
                last_error = exc
            if attempt < self.max_retries - 1:
                time.sleep(2.0 ** (attempt + 1))
        raise RuntimeError(f"request failed after bounded retries: {type(last_error).__name__}")


def audit_robots(client: SafeSession) -> dict:
    current = client.get(CURRENT_ROBOTS_URL).text
    legacy = client.get(LEGACY_ROBOTS_URL).text
    current_results = {
        name: robots_allows(current, CURRENT_ROBOTS_URL, CURRENT_ORIGIN + path)
        for name, path in CURRENT_PATHS.items()
    }
    legacy_detail = "https://www.work.go.kr/empInfo/empInfoSrch/detail/empDetailAuthView.do"
    return {
        "checked_at": utcnow(),
        "work24": {
            "url": CURRENT_ROBOTS_URL,
            "relevant_rules": relevant_robots_rules(current),
            "paths": current_results,
        },
        "legacy_work_go": {
            "url": LEGACY_ROBOTS_URL,
            "relevant_rules": relevant_robots_rules(legacy),
            "legacy_empinfo_detail_allowed": robots_allows(
                legacy, LEGACY_ROBOTS_URL, legacy_detail),
        },
    }


def list_params(page_index: int = 1, result_count: int = 10,
                region_codes: tuple[str, ...] = CHANGWON_REGION_CODES,
                registered_from: str = "", registered_to: str = "") -> dict[str, str]:
    """현행 UI가 제출하는 핵심 공개 검색 파라미터.

    날짜는 UI JavaScript와 같이 YYYYMMDD 형식이며 지역은 ``|`` 구분 코드다.
    """
    if not 1 <= result_count <= 50:
        raise ValueError("result_count must be between 1 and 50")
    for value in (registered_from, registered_to):
        if value and not re.fullmatch(r"\d{8}", value):
            raise ValueError("registration dates must use YYYYMMDD")
    return {
        "pageIndex": str(page_index),
        "currentPageNo": str(page_index),
        "resultCnt": str(result_count),
        "sortField": "DATE",
        "sortOrderBy": "DESC",
        "region": "|".join(region_codes),
        "regDateStdtParam": registered_from,
        "regDateEndtParam": registered_to,
        "empTpGbcd": "1",
        "siteClcd": "all",
    }


def parse_current_list(html: str) -> list[dict]:
    """서버 렌더 HTML 목록에서 상세 링크와 목록 필드만 읽는다."""
    soup = BeautifulSoup(html, "html.parser")
    records: list[dict] = []
    table = soup.select_one("#contentArea")
    if table is None:
        return records
    for row in table.select("tr"):
        link = row.select_one('a[href*="/wk/a/b/1500/empDetailAuthView.do"]')
        if link is None:
            continue
        href = urljoin(CURRENT_ORIGIN, link.get("href", ""))
        query = parse_qs(urlparse(href).query)
        wanted = (query.get("wantedAuthNo") or [""])[0]
        if not wanted:
            continue
        cells = [re.sub(r"\s+", " ", cell.get_text(" ", strip=True))
                 for cell in row.select("th,td")]
        first = row.select_one(".cp_name, .corp_info, .company, [class*='corp']")
        company = first.get_text(" ", strip=True) if first else None
        full_text = " ".join(cells)
        due = re.search(r"마감일\s*:\s*([0-9.-]+|채용시까지|상시)", full_text)
        registered = re.search(r"등록일\s*:\s*([0-9.-]+)", full_text)
        records.append({
            "wanted_auth_no": wanted,
            "company": redact_contact(company),
            "title": redact_contact(link.get_text(" ", strip=True)),
            "list_text": redact_contact(full_text),
            "due_date_raw": due.group(1) if due else None,
            "registration_date_raw": registered.group(1) if registered else None,
            "info_type_cd": (query.get("infoTypeCd") or [None])[0],
            "info_type_group": (query.get("infoTypeGroup") or [None])[0],
            "source_url": href,
            "acquisition_path": "CURRENT_LIST_HTML",
        })
    return records


DETAIL_LABELS = {
    "모집 인원": "recruitment_count_raw",
    "모집 직종": "occupation_raw",
    "관련 직종": "related_occupation",
    "직종 키워드": "occupation_keywords",
    "경력": "career",
    "학력": "education",
    "자격 면허": "certificate_raw",
    "고용 형태": "employment_type",
    "임금 조건": "wage",
    "근무 시간": "work_hours_raw",
    "근무 형태": "work_pattern_raw",
    "우대 조건": "preference_raw",
    "기타 우대 사항": "other_preference_raw",
    "컴퓨터 활용 능력": "computer_skill_raw",
    "근무 예정지": "workplace_address",
    "채용공고 등록일시": "registered_at",
    "구인인증번호": "wanted_auth_no",
}


def _table_fields(soup: BeautifulSoup) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for row in soup.select("table tr"):
        cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True))
                 for c in row.select("th,td")]
        for index in range(0, len(cells), 2):
            label = cells[index]
            if label in DETAIL_LABELS:
                value = cells[index + 1] if index + 1 < len(cells) else None
                result[DETAIL_LABELS[label]] = redact_contact(value)
    return result


def parse_current_detail(html: str, source_url: str, collected_at: str | None = None) -> dict:
    """현행 Work24 상세 HTML에서 공개 비개인정보만 최소 파싱한다."""
    soup = BeautifulSoup(html, "html.parser")
    fields = _table_fields(soup)
    query_id = (parse_qs(urlparse(source_url).query).get("wantedAuthNo") or [None])[0]
    company = soup.select_one(".corp_info strong")
    title = soup.select_one(".tit_area strong.title")

    description_raw = None
    for box in soup.select("div.fold"):
        label = box.find("strong")
        if label and label.get_text(" ", strip=True) == "직무내용":
            label.extract()
            description_raw = redact_contact(
                box.get_text("\n", strip=True), collapse_whitespace=False)
            break

    closing_date = None
    label = next((node for node in soup.find_all("strong")
                  if node.get_text(" ", strip=True) == "접수 마감일"), None)
    if label and label.parent:
        value = label.parent.find("p")
        closing_date = redact_contact(value.get_text(" ", strip=True) if value else None)

    wanted = fields.get("wanted_auth_no") or query_id
    if query_id and wanted and query_id != wanted:
        raise ValueError("wantedAuthNo differs between URL and rendered detail")
    recruitment_count_raw = fields.get("recruitment_count_raw")
    address_parts = parse_changwon_address(fields.get("workplace_address"))
    record = {
        "wanted_auth_no": wanted,
        "company": company.get_text(" ", strip=True) if company else None,
        "title": title.get_text(" ", strip=True) if title else None,
        "job_description_raw": description_raw,
        "job_description_clean": redact_contact(description_raw),
        **fields,
        "occupation": fields.get("occupation_raw"),
        "certificate": fields.get("certificate_raw"),
        "job_description": redact_contact(description_raw),
        "recruitment_count": parse_recruitment_count(recruitment_count_raw),
        "city": address_parts["city"],
        "district": address_parts["district"],
        "dong_eup_myeon": address_parts["dong_eup_myeon"],
        "closing_date": closing_date,
        "is_until_hired": bool(closing_date and "채용시까지" in closing_date),
        "source": "work24",
        "source_url": source_url,
        "collected_at": collected_at or utcnow(),
        "acquisition_path": "CURRENT_DETAIL_HTML",
        "personal_contact_fields_collected": False,
    }
    return {key: redact_contact(value) if isinstance(value, str) else value
            for key, value in record.items()}


def parse_recruitment_count(value: str | None) -> int | None:
    """정확히 ``N명``인 경우만 분석용 숫자로 변환한다."""
    if not value:
        return None
    matched = re.fullmatch(r"\s*([0-9][0-9,]*)\s*명\s*", value)
    return int(matched.group(1).replace(",", "")) if matched else None


def parse_changwon_address(value: str | None) -> dict[str, str | None]:
    """명시된 창원시 주소에서 확실한 시·구·읍면동만 파생한다."""
    result = {"city": None, "district": None, "dong_eup_myeon": None}
    if not value:
        return result
    matched = re.search(
        r"(?:경상남도|경남)\s+창원시(?:\s+(의창구|성산구|마산합포구|마산회원구|진해구))?"
        r"(?:\s+([가-힣0-9]+(?:동|읍|면)))?",
        value,
    )
    if matched:
        result.update({
            "city": "창원시",
            "district": matched.group(1),
            "dong_eup_myeon": matched.group(2),
        })
    return result


def current_detail_url(wanted_auth_no: str) -> str:
    return DETAIL_URL + "?" + urlencode({
        "wantedAuthNo": wanted_auth_no,
        "infoTypeCd": "VALIDATION",
        "infoTypeGroup": "tb_workinfoworknet",
    })


def existing_ids(limit: int = 5, source_path: Path = EXISTING_DATA) -> list[str]:
    if not 1 <= limit <= SAMPLE_MAX:
        raise ValueError(f"sample limit must be between 1 and {SAMPLE_MAX}")
    with Path(source_path).open("r", encoding="utf-8-sig", newline="") as handle:
        return [row["wanted_auth_no"] for row in csv.DictReader(handle)][:limit]


DETAIL_SNAPSHOT_FIELDS = (
    "request_status", "http_status", "error", "target_industry",
    "kicox_mapping_status", "kicox_mapping_confidence", "wanted_auth_no",
    "company", "title", "source", "source_url", "collected_at", "acquisition_path",
    "recruitment_count_raw", "recruitment_count", "occupation_raw",
    "related_occupation", "occupation_keywords", "job_description_raw",
    "job_description_clean", "employment_type", "career", "education", "wage",
    "work_hours_raw", "work_pattern_raw", "certificate_raw", "preference_raw",
    "other_preference_raw", "computer_skill_raw", "workplace_address", "city",
    "district", "dong_eup_myeon", "registered_at", "closing_date",
    "is_until_hired", "personal_contact_fields_collected",
)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def current_priority_industries(triage_path: Path = LATEST_TRIAGE) -> tuple[str, ...]:
    rows = read_csv_rows(triage_path)
    return tuple(row["industry"] for row in rows if row.get("decision_stage") == "우선점검")


def priority_targets(
    source_path: Path = EXISTING_DATA,
    triage_path: Path = LATEST_TRIAGE,
) -> tuple[list[dict[str, str]], dict]:
    """최신 진단 우선업종과 기존 산업 매핑만으로 상세 대상 ID를 만든다."""
    actual = current_priority_industries(triage_path)
    invalid = set(actual) - set(KICOX_INDUSTRIES)
    if invalid:
        raise RuntimeError(f"latest priority industries are outside the KICOX axis: {invalid}")
    rows = read_csv_rows(source_path)
    targets = [row for row in rows if row.get("kicox_industry") in actual]
    ids = [row.get("wanted_auth_no", "").strip() for row in targets]
    if not all(ids):
        raise RuntimeError("priority-industry target contains a missing wanted_auth_no")
    if len(ids) != len(set(ids)):
        raise RuntimeError("priority-industry target contains duplicate wanted_auth_no")
    counts = Counter(row["kicox_industry"] for row in targets)
    return targets, {
        "existing_total": len(rows),
        "priority_industries": list(actual),
        "industry_counts": dict(counts),
        "priority_target_count": len(targets),
        "unique_wanted_auth_no": len(set(ids)),
        "request_reduction_pct": round((1 - len(set(ids)) / len(rows)) * 100, 2),
    }


def industry_targets(
    industry: str = "all",
    source_path: Path = EXISTING_DATA,
) -> tuple[list[dict[str, str]], dict]:
    """기존 기업 기반 KICOX 매핑으로만 산업별 상세 대상을 반환한다."""
    if industry != "all" and industry not in KICOX_INDUSTRIES:
        raise ValueError(f"industry must be one of {KICOX_INDUSTRIES} or 'all'")
    rows = read_csv_rows(source_path)
    targets = [
        row for row in rows
        if row.get("kicox_industry") in KICOX_INDUSTRIES
        and (industry == "all" or row.get("kicox_industry") == industry)
    ]
    ids = [row.get("wanted_auth_no", "").strip() for row in targets]
    if not all(ids) or len(ids) != len(set(ids)):
        raise RuntimeError("industry target IDs must be present and unique")
    counts = Counter(row["kicox_industry"] for row in targets)
    return targets, {
        "existing_total": len(rows),
        "selected_industry": industry,
        "industry_counts": {name: counts.get(name, 0) for name in KICOX_INDUSTRIES},
        "target_count": len(targets),
        "unique_wanted_auth_no": len(set(ids)),
    }


def interleaved_targets(targets: list[dict[str, str]]) -> list[dict[str, str]]:
    """최근 공고부터 두 우선업종이 모두 포함되도록 안정적으로 교차한다."""
    present = {row["kicox_industry"] for row in targets}
    order = [name for name in EXPECTED_PRIORITY_INDUSTRIES if name in present]
    order.extend(name for name in KICOX_INDUSTRIES if name in present and name not in order)
    groups = {
        industry: sorted(
            (row for row in targets if row["kicox_industry"] == industry),
            key=lambda row: (row.get("reg_date", ""), row["wanted_auth_no"]),
            reverse=True,
        )
        for industry in order
    }
    result: list[dict[str, str]] = []
    index = 0
    while any(index < len(group) for group in groups.values()):
        for industry in order:
            group = groups[industry]
            if index < len(group):
                result.append(group[index])
        index += 1
    return result


def terms_gate(client: SafeSession) -> dict:
    response = client.get(TERMS_URL)
    text = re.sub(r"\s+", " ", BeautifulSoup(response.text, "html.parser").get_text(" "))
    return {
        "url": TERMS_URL,
        "checked_at": utcnow(),
        "sha256": hashlib.sha256(response.content).hexdigest(),
        "separate_contract_for_bulk_or_special_use": (
            "별도" in text and "계약" in text and ("대량" in text or "특수" in text)
        ),
        "automated_personal_data_restriction_detected": (
            "자동" in text and "개인정보" in text
        ),
    }


def current_access_gate(client: SafeSession) -> dict:
    response = client.get(CURRENT_ROBOTS_URL)
    results = {
        name: robots_allows(
            response.text, CURRENT_ROBOTS_URL, CURRENT_ORIGIN + path)
        for name, path in CURRENT_PATHS.items()
    }
    if not all(results.values()):
        raise Work24AccessStop("current Work24 search/detail path is disallowed by robots.txt")
    return {
        "robots": {
            "url": CURRENT_ROBOTS_URL,
            "checked_at": utcnow(),
            "relevant_rules": relevant_robots_rules(response.text),
            "paths": results,
        },
        "terms": terms_gate(client),
    }


def append_detail_row(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DETAIL_SNAPSHOT_FIELDS, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerow({field: row.get(field) for field in DETAIL_SNAPSHOT_FIELDS})
        handle.flush()


def detail_rows_by_id(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    result: dict[str, dict[str, str]] = {}
    for row in read_csv_rows(path):
        wanted = row.get("wanted_auth_no", "")
        if wanted in result:
            raise RuntimeError(f"duplicate wanted_auth_no in detail snapshot: {wanted}")
        result[wanted] = row
    return result


def collect_priority_details(
    targets: list[dict[str, str]],
    snapshot_path: Path,
    *,
    max_requests: int = 5,
    scope_confirmed: bool = False,
) -> tuple[dict, dict]:
    if max_requests < 0:
        raise ValueError("max_requests must be non-negative")
    if not scope_confirmed and max_requests > SAMPLE_MAX:
        raise ValueError(
            f"without confirmation that this request fits the permitted use scope, "
            f"max_requests cannot exceed the sample safety cap ({SAMPLE_MAX})")

    client = SafeSession()
    gate = current_access_gate(client)
    prior = detail_rows_by_id(snapshot_path)
    if not scope_confirmed and len(prior) >= SAMPLE_MAX and max_requests:
        raise Work24AccessStop(
            f"sample safety cap reached ({SAMPLE_MAX} requests); "
            "the use-scope status of the planned 140 requests is unclear, "
            "so automated requests remain paused pending KEIS confirmation")
    queue = []
    for target in interleaved_targets(targets):
        previous = prior.get(target["wanted_auth_no"])
        if previous and previous.get("request_status") == "SUCCESS":
            continue
        if previous:
            continue
        queue.append(target)
    remaining_cap = max_requests if scope_confirmed else min(
        max_requests, SAMPLE_MAX - len(prior))
    selected = queue[:remaining_cap]
    stopped_reason = None
    gate_status_counts = client.status_counts.copy()
    attempted = 0
    for target in selected:
        wanted = target["wanted_auth_no"]
        url = current_detail_url(wanted)
        base = {
            "target_industry": target["kicox_industry"],
            "kicox_mapping_status": target.get("kicox_mapping_status"),
            "kicox_mapping_confidence": target.get("kicox_mapping_confidence"),
            "wanted_auth_no": wanted,
            "source_url": url,
            "collected_at": utcnow(),
        }
        response = None
        try:
            attempted += 1
            response = client.get(url)
            parsed = parse_current_detail(response.text, url)
            if not parsed.get("company") or not parsed.get("title"):
                raise ValueError("detail content did not contain company and title")
            row = {**base, **parsed, "request_status": "SUCCESS", "http_status": 200}
            append_detail_row(snapshot_path, row)
        except Work24AccessStop as exc:
            stopped_reason = str(exc)
            break
        except Work24HTTPError as exc:
            append_detail_row(snapshot_path, {
                **base, "request_status": "FAILED", "http_status": exc.status_code,
                "error": str(exc),
            })
        except Exception as exc:  # bounded request errors or parsing failures
            append_detail_row(snapshot_path, {
                **base, "request_status": "FAILED",
                "http_status": response.status_code if response is not None else None,
                "error": f"{type(exc).__name__}: {exc}",
            })

    latest = detail_rows_by_id(snapshot_path)
    return latest, {
        "access_gate": gate,
        "max_requests_this_run": max_requests,
        "selected_this_run": len(selected),
        "attempted_this_run": attempted,
        "stopped_reason": stopped_reason,
        "http_status_counts_including_gate": {
            str(key): value for key, value in sorted(client.status_counts.items())
        },
        "http_status_counts_detail_this_run": {
            str(key): client.status_counts[key] - gate_status_counts[key]
            for key in sorted(client.status_counts)
            if client.status_counts[key] - gate_status_counts[key]
        },
        "network_errors": client.network_errors,
    }


def write_enriched_dataset(
    targets: list[dict[str, str]],
    details: dict[str, dict[str, str]],
    output_path: Path,
) -> list[dict]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    base_fields = (
        "snapshot_id", "crawl_timestamp", "wanted_auth_no", "kicox_industry",
        "kicox_mapping_status", "kicox_mapping_confidence", "ksic_code", "ksic_name",
        "company_raw", "title_raw", "region_raw", "gu", "reg_date", "due_date",
        "wage_raw", "career_raw", "education_raw", "source_url",
    )
    detail_fields = tuple(field for field in DETAIL_SNAPSHOT_FIELDS if field not in {
        "wanted_auth_no", "target_industry", "kicox_mapping_status",
        "kicox_mapping_confidence", "source_url",
    })
    fieldnames = base_fields + ("list_source_url", "detail_source_url") + detail_fields
    rows: list[dict] = []
    for target in targets:
        wanted = target["wanted_auth_no"]
        detail = details.get(wanted, {})
        row = {field: target.get(field) for field in base_fields}
        row["list_source_url"] = target.get("source_url")
        row["detail_source_url"] = detail.get("source_url") or current_detail_url(wanted)
        row["source_url"] = row["detail_source_url"]
        for field in detail_fields:
            row[field] = detail.get(field)
        row["request_status"] = detail.get("request_status") or "NOT_REQUESTED"
        rows.append(row)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return rows


def privacy_hits(rows: list[dict]) -> dict[str, int]:
    values = "\n".join(
        str(value) for row in rows for value in row.values() if value not in (None, ""))
    return {
        "phone_regex_hits": len(PHONE_RE.findall(values)),
        "email_regex_hits": len(EMAIL_RE.findall(values)),
        "contact_schema_fields_collected": sum(
            1 for row in rows if str(row.get("personal_contact_fields_collected", "")).lower() == "true"),
    }


def build_quality_report(
    target_stats: dict,
    enriched_rows: list[dict],
    run_stats: dict,
    raw_path: Path,
    enriched_path: Path,
) -> dict:
    target_count = len(enriched_rows)
    success = [row for row in enriched_rows if row["request_status"] == "SUCCESS"]
    failed = [row for row in enriched_rows if row["request_status"] == "FAILED"]
    not_requested = [row for row in enriched_rows if row["request_status"] == "NOT_REQUESTED"]
    fields = {
        "recruitment_count": "recruitment_count_raw",
        "occupation": "occupation_raw",
        "job_description": "job_description_raw",
        "employment_type": "employment_type",
        "wage": "wage",
        "career": "career",
        "education": "education",
        "certificate": "certificate_raw",
        "workplace_address": "workplace_address",
        "registration_date": "registered_at",
        "closing_date": "closing_date",
        "work_hours": "work_hours_raw",
        "work_pattern": "work_pattern_raw",
        "preference": "preference_raw",
        "district": "district",
    }
    coverage = {}
    for label, field in fields.items():
        count = sum(1 for row in enriched_rows if str(row.get(field) or "").strip())
        coverage[label] = {
            "count": count,
            "target_count": target_count,
            "coverage_pct": round(count / target_count * 100, 2) if target_count else 0,
            "success_denominator_pct": round(count / len(success) * 100, 2) if success else 0,
        }
    ids = [row["wanted_auth_no"] for row in enriched_rows]
    detail_ids = [row["wanted_auth_no"] for row in success]
    snapshot_http_counts = Counter(
        str(row.get("http_status")) for row in enriched_rows
        if str(row.get("http_status") or "").strip()
    )
    return {
        "generated_at": utcnow(),
        "scope": "latest-diagnosis priority industries using existing KICOX mapping only",
        "target": target_stats,
        "collection": {
            "request_target": target_count,
            "success": len(success),
            "failed": len(failed),
            "not_requested": len(not_requested),
            "http_status_counts_snapshot": dict(sorted(snapshot_http_counts.items())),
            **run_stats,
        },
        "join": {
            "wanted_auth_no_duplicates": len(ids) - len(set(ids)),
            "detail_id_match_count": sum(1 for wanted in detail_ids if wanted in set(ids)),
            "detail_id_match_pct": round(
                sum(1 for wanted in detail_ids if wanted in set(ids)) / len(detail_ids) * 100, 2
            ) if detail_ids else 0,
            "existing_target_join_pct": round(
                sum(1 for wanted in detail_ids if wanted in set(ids)) / len(detail_ids) * 100, 2
            ) if detail_ids else 0,
            "target_enrichment_coverage_pct": round(
                len(success) / target_count * 100, 2) if target_count else 0,
            "failed_ids": [row["wanted_auth_no"] for row in failed],
        },
        "field_coverage": coverage,
        "privacy": privacy_hits(enriched_rows),
        "parsing_failure_count": sum(
            1 for row in failed if "detail content" in str(row.get("error") or "")
            or "ValueError" in str(row.get("error") or "")
        ),
        "artifacts": {"raw_detail_snapshot": str(raw_path), "enriched_dataset": str(enriched_path)},
    }


def run_priority_enrichment(
    *,
    max_requests: int = 5,
    date_stamp: str | None = None,
    scope_confirmed: bool = False,
) -> dict:
    targets, target_stats = priority_targets()
    stamp = date_stamp or dt.datetime.now().strftime("%Y%m%d")
    if not re.fullmatch(r"\d{8}", stamp):
        raise ValueError("date_stamp must use YYYYMMDD")
    raw_path = RAW_WORK24_DIR / f"work24_priority_industry_detail_{stamp}.csv"
    enriched_path = PROCESSED_WORK24_DIR / f"work24_priority_industry_enriched_{stamp}.csv"
    quality_path = PROCESSED_WORK24_DIR / f"work24_priority_industry_quality_{stamp}.json"
    details, run_stats = collect_priority_details(
        targets, raw_path, max_requests=max_requests,
        scope_confirmed=scope_confirmed)
    enriched_rows = write_enriched_dataset(targets, details, enriched_path)
    quality = build_quality_report(
        target_stats, enriched_rows, run_stats, raw_path, enriched_path)
    quality["artifacts"]["quality_report"] = str(quality_path)
    with quality_path.open("w", encoding="utf-8") as handle:
        json.dump(quality, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return quality


def collect_detail(
    industry: str,
    *,
    max_requests: int = 5,
    date_stamp: str | None = None,
    scope_confirmed: bool = False,
) -> dict:
    """산업별 상세수집 진입점.

    산업 분리는 대상·resume 관리를 위한 것이며, 모든 산업이 같은 날짜별 상세
    스냅샷과 동일한 이용조건/lifetime cap을 공유한다. ``all``도 Gate를 우회하지 않는다.
    """
    targets, target_stats = industry_targets(industry)
    stamp = date_stamp or dt.datetime.now().strftime("%Y%m%d")
    if not re.fullmatch(r"\d{8}", stamp):
        raise ValueError("date_stamp must use YYYYMMDD")
    snapshot_path = RAW_WORK24_DIR / f"work24_priority_industry_detail_{stamp}.csv"
    details, run_stats = collect_priority_details(
        targets,
        snapshot_path,
        max_requests=max_requests,
        scope_confirmed=scope_confirmed,
    )
    selected_ids = {row["wanted_auth_no"] for row in targets}
    selected_details = {key: value for key, value in details.items() if key in selected_ids}
    return {
        "industry": industry,
        "target": target_stats,
        "detail_status_counts": dict(Counter(
            row.get("request_status", "NOT_REQUESTED") for row in selected_details.values())),
        "run": run_stats,
        "snapshot_path": str(snapshot_path),
    }


def audit_sample(limit: int = 5) -> dict:
    """robots 2건 + 현행 목록 1페이지 + 기존 ID 상세 N건. 파일은 쓰지 않는다."""
    if not 1 <= limit <= SAMPLE_MAX:
        raise ValueError(f"sample limit must be between 1 and {SAMPLE_MAX}")
    client = SafeSession()
    robots = audit_robots(client)
    if not all(robots["work24"]["paths"].values()):
        raise Work24AccessStop("current Work24 search/detail path is disallowed by robots.txt")

    list_response = client.get(LIST_URL, params=list_params(result_count=10))
    listed = parse_current_list(list_response.text)
    ids = existing_ids(limit)
    details = []
    for wanted_auth_no in ids:
        url = current_detail_url(wanted_auth_no)
        details.append(parse_current_detail(client.get(url).text, url))
    return {
        "status": "SAMPLE_COMPLETE",
        "sample_only": True,
        "full_collection_performed": False,
        "robots": robots,
        "request_structure": {
            "initial_and_canonical_response": "GET text/html",
            "ui_form": {"method": "POST", "action": LIST_POST_URL},
            "pagination": {"endpoint": LIST_URL, "parameter": "pageIndex"},
            "region_parameter": "region (pipe-separated legal-dong codes)",
            "registration_parameters": ["regDateStdtParam", "regDateEndtParam"],
            "wanted_auth_no": "detail-link query parameter wantedAuthNo",
            "json_result_endpoint_observed": False,
        },
        "list_sample_count": len(listed[:10]),
        "detail_sample_count": len(details),
        "details": details,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=("audit", "enrich-priority", "enrich-industry"))
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--date-stamp")
    parser.add_argument("--industry", choices=("all",) + KICOX_INDUSTRIES, default="all")
    parser.add_argument("--scope-confirmed", "--terms-authorized", dest="scope_confirmed",
                        action="store_true",
                        help="한국고용정보원에 예정된 자동요청의 이용범위를 확인한 경우에만 사용")
    args = parser.parse_args(argv)
    try:
        if args.command == "audit":
            result = audit_sample(args.limit)
        elif args.command == "enrich-priority":
            result = run_priority_enrichment(
                max_requests=args.limit,
                date_stamp=args.date_stamp,
                scope_confirmed=args.scope_confirmed,
            )
        else:
            result = collect_detail(
                args.industry,
                max_requests=args.limit,
                date_stamp=args.date_stamp,
                scope_confirmed=args.scope_confirmed,
            )
    except Work24AccessStop as exc:
        result = {"status": "STOPPED", "reason": str(exc),
                  "full_collection_performed": False}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
