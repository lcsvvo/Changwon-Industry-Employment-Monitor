# -*- coding: utf-8 -*-
"""고용24(work24) 공개 채용정보 → Decision Gate 후속 확인자료 파이프라인.

무엇을 푸는 문제인가
    Q1~Q3 와 Decision Gate 는 KICOX 업종 단위 집계다. 「기계 업종이 우선점검」
    까지는 나오지만, **그 업종에서 지금 어떤 기업이 어떤 직무를 공개채용하고
    있는지**는 나오지 않는다. 이 모듈은 그 한 칸을 채우는 근거표를 만든다.

무엇을 하지 않는가
    - Q1~Q3 · Decision Gate 의 어떤 값도 다시 계산하거나 수정하지 않는다.
    - 공고 수를 모집인원·노동수요·산업 성장의 지표로 쓰지 않는다.
    - 직무명(용접·조립·품질 …)으로 산업을 추정하지 않는다.
    - 고용24 Open API 를 쓰지 않는다. 두 고용복지+센터 공개 목록페이지의
      공개 요청구조(GET)만 이용한다.

수집 범위와 정책
    robots.txt 는 `/empInfo/` 를 모든 UA 에 Disallow 한다. 따라서 **상세페이지는
    수집하지 않는다.** 센터 목록경로(`/changwon|masan/infoPlace/empInfo/`)는
    그 접두사가 아니므로 `Allow: /` 가 적용된다. 목록에 없는 필드
    (모집인원·상세주소·KSIC·직종)는 만들어내지 않고 상태값으로 남긴다.

실행:
    python src/evidence/collection/work24.py freeze    # 기존 1,504건 동결 metadata
    python src/evidence/collection/work24.py collect   # 5개 구 동일시점 RAW 수집
    python src/evidence/collection/work24.py build     # analysis-ready + evidence
    python src/evidence/collection/work24.py all
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[3]

# ── 경로 ──────────────────────────────────────────────────────────────────
RAW_DIR = ROOT / "data/raw/work24"
OUT_DIR = ROOT / "data/processed/work24"
HISTORICAL = RAW_DIR / "20260918_partial_3gu.csv"
FACTORY = (ROOT / "data/raw/changwon_factory_registry"
           / "changwon_factory_registry_20241231.csv")
KSIC_XLSX = ROOT / "data/raw/ksic/ksic11_linkage_hometax.xlsx"
KSIC_TO_KICOX = (ROOT / "data/processed/final_model/reference/industry_crosswalk"
                 / "ksic_to_kicox.csv")
DONG_CONTEXT = (ROOT / "data/processed/kepco/reference/spatial"
                / "changwon_legal_dong_manufacturing_context.csv")
GATE_SIGNALS = ROOT / "data/processed/final_model/industry_context_signals.csv"

# 공식 KSIC 연계표(통계청 제11차 · 국세청 홈택스 게시본). 없으면 이 URL 에서 받는다.
KSIC_XLSX_URL = (
    "https://teht.hometax.go.kr/doc/rn/a/a/"
    "%EC%97%85%EC%A2%85%EC%BD%94%EB%93%9C-%ED%91%9C%EC%A4%80%EC%82%B0%EC%97%85"
    "%EB%B6%84%EB%A5%98%20%EC%97%B0%EA%B3%84%ED%91%9C_%ED%99%88%ED%83%9D%EC%8A%A4"
    "%20%EA%B2%8C%EC%8B%9C.xlsx"
)

# ── 수집 대상 ─────────────────────────────────────────────────────────────
# region 코드·관할은 2026-09-19 각 센터 페이지 hidden input 에서 직접 확인했다.
# region 파라미터는 무상태 GET 에서 무시되고 센터 관할 전체가 반환된다.
# 따라서 구 분리는 목록의 근무지역 컬럼으로 수집 후 수행한다.
CENTERS = {
    "changwon": {
        "center_name": "창원고용복지+센터",
        "regions": {"48129": "진해구", "48121": "의창구", "48123": "성산구"},
    },
    "masan": {
        "center_name": "마산고용복지+센터",
        "regions": {"48125": "마산합포구", "48127": "마산회원구", "48720": "의령군"},
    },
}
IN_SCOPE_GU = ("의창구", "성산구", "진해구", "마산합포구", "마산회원구")
OUT_OF_SCOPE_GU = ("의령군",)

BASE_URL = "https://www.work.go.kr/{center}/infoPlace/empInfo/empInfoList.do"
ROBOTS_URL = "https://www.work.go.kr/robots.txt"
PAGE_UNIT = 10          # 50 은 6페이지 이후 조용히 0건을 돌려준다(2026-09-19 확인).
REQUEST_DELAY_SEC = 1.2
REQUEST_TIMEOUT_SEC = 30
MAX_RETRIES = 3
USER_AGENT = (
    "Changwon-Industry-Employment-Monitor/1.0 (academic research; "
    "public job posting list pages; contact via repository)"
)
BASE_PARAMS = {
    "sortField": "DATE", "sortOrderBy": "DESC", "subNaviMenuCd": "10200",
    "s": "1", "m": "1", "mode": "search", "menuId": "M200800001",
    "occupation": "", "career": "", "query": "",
    "comm_daily_clcd": "1",          # 상용. 2026-09-19 기준 무필터와 동일 결과.
    "pageUnit": str(PAGE_UNIT),
}

RAW_COLUMNS = [
    "snapshot_id", "crawl_timestamp", "source_center", "center_region_scope",
    "wanted_auth_no", "company_raw", "title_raw", "wage_raw", "wage_type_raw",
    "region_raw", "cert_raw", "education_raw", "career_raw",
    "reg_date_raw", "due_date_raw", "source_url", "page_index",
]

KICOX_INDUSTRIES = ("음식료", "섬유의복", "목재종이", "석유화학", "비금속",
                    "철강", "기계", "전기전자", "운송장비", "기타")
GATE_STAGES_DEFAULT = ("우선점검", "추가확인")


# ═══════════════════════════════════════════════════════════════════════════
# 공통 유틸
# ═══════════════════════════════════════════════════════════════════════════
def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """부분 기록된 파일이 남지 않게 임시파일에 쓰고 교체한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding=encoding, newline="")
    os.replace(tmp, path)


def atomic_write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    os.replace(tmp, path)


def _nfkc(s) -> str:
    return unicodedata.normalize("NFKC", "" if s is None else str(s))


# ═══════════════════════════════════════════════════════════════════════════
# 1. 수집 (PHASE 5)
# ═══════════════════════════════════════════════════════════════════════════
def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT,
                      "Accept": "text/html,application/xhtml+xml"})
    return s


def check_robots(session: requests.Session) -> dict:
    """robots.txt 를 매 수집 때 다시 확인해 기록한다."""
    r = session.get(ROBOTS_URL, timeout=REQUEST_TIMEOUT_SEC)
    r.raise_for_status()
    text = r.text
    star = text.split("User-Agent: *")[-1] if "User-Agent: *" in text else text
    disallowed = re.findall(r"Disallow:\s*(\S+)", star)
    return {
        "checked_at": utcnow(),
        "detail_path_disallowed": "/empInfo/" in disallowed,
        "list_path_allowed": not any(
            "/changwon/infoPlace/empInfo/".startswith(d) for d in disallowed),
        "disallowed_sample": disallowed[:5],
    }


def fetch_page(session: requests.Session, center: str, page_index: int,
               failures: list) -> str | None:
    """목록 1페이지. 실패는 예외로 던지지 않고 failures 에 적고 None 을 돌린다."""
    params = dict(BASE_PARAMS)
    params["region"] = "|".join(CENTERS[center]["regions"])
    params["pageIndex"] = str(page_index)
    params["startCnt"] = str((page_index - 1) * PAGE_UNIT)
    url = BASE_URL.format(center=center)
    for attempt in range(MAX_RETRIES):
        time.sleep(REQUEST_DELAY_SEC)
        try:
            r = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SEC)
            if r.status_code == 200:
                r.encoding = "utf-8"
                return r.text
            if r.status_code in (403, 429):        # 접근통제는 재시도하지 않는다
                failures.append({"center": center, "page_index": page_index,
                                 "status": r.status_code, "kind": "access_denied"})
                return None
            last = {"status": r.status_code, "kind": "http_error"}
        except requests.RequestException as e:
            last = {"status": 0, "kind": type(e).__name__}
        if attempt < MAX_RETRIES - 1:
            time.sleep(2.0 * (attempt + 1))        # exponential backoff
    failures.append({"center": center, "page_index": page_index, **last})
    return None


def parse_total(html: str) -> int | None:
    m = re.search(r"총게시물\s*:\s*<span>([\d,]+)</span>", html)
    return int(m.group(1).replace(",", "")) if m else None


_WANTED = re.compile(r"wantedAuthNo=([A-Z0-9]+)")
_HAK = re.compile(r"var\s+hak\s*=\s*'([^']*)'")
_PAY_CLASS = {"hour": "시급", "day": "일급", "month": "월급", "year": "연봉"}


def parse_list_page(html: str) -> list[dict]:
    """목록 HTML → 행 목록. 가공 전 원문을 그대로 담는다.

    기존 크롤러 대비 두 가지를 더 살린다.
      - 임금 유형: <em class="ico_pay month"> 의 클래스에서 직접 얻는다.
      - 학력: <p id="hakN"> 는 JS 렌더 전이라 비어 있다. 같은 칸의
        `var hak = '...'` 에서 읽는다(기존 CSV 의 education 이 빈 이유).
    """
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.select("table.tbl_list tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 6:
            continue
        company_td, title_td, cert_td, edu_td, reg_td, due_td = tds[:6]

        title_a = title_td.find("a")
        href = title_a.get("href", "") if title_a else ""
        m = _WANTED.search(href or "")
        if not m:
            continue                                   # 공고 ID 를 임의 생성하지 않는다
        wanted_auth_no = m.group(1)

        # 임금: 유형(em.ico_pay) 과 금액문구를 분리해 원문으로 보존
        wage_type_raw, wage_raw = "", ""
        for sp in title_td.find_all("span"):
            if sp.get("class") == ["fs_13"]:
                continue
            em = sp.find("em")
            if em is not None:
                cls = [c for c in (em.get("class") or []) if c != "ico_pay"]
                wage_type_raw = _PAY_CLASS.get(cls[0] if cls else "",
                                               em.get_text(strip=True))
            wage_raw = re.sub(r"\s+", " ", sp.get_text(" ", strip=True))
            break

        region_span = title_td.find("span", class_="fs_13")

        # 학력/경력 칸: <p> 안의 script 에서 학력, <p> 를 뺀 나머지가 경력
        hak = _HAK.search(edu_td.decode_contents() or "")
        education_raw = hak.group(1).strip() if hak else ""
        edu_copy = BeautifulSoup(str(edu_td), "html.parser")
        for p in edu_copy.find_all(["p", "script"]):
            p.decompose()
        career_raw = re.sub(r"\s+", " ", edu_copy.get_text(" ", strip=True))

        rows.append({
            "wanted_auth_no": wanted_auth_no,
            "company_raw": company_td.get_text(strip=True),
            "title_raw": title_a.get_text(strip=True) if title_a else "",
            "wage_raw": wage_raw,
            "wage_type_raw": wage_type_raw,
            "region_raw": region_span.get_text(strip=True) if region_span else "",
            "cert_raw": cert_td.get_text(strip=True),
            "education_raw": education_raw,
            "career_raw": career_raw,
            "reg_date_raw": reg_td.get_text(strip=True),
            "due_date_raw": due_td.get_text(strip=True),
            "source_url": href,
        })
    return rows


def collect(max_extra_pages: int = 3) -> Path:
    """두 센터를 같은 run 에서 수집해 canonical RAW 한 장으로 저장한다."""
    session = make_session()
    robots = check_robots(session)
    if not robots["detail_path_disallowed"]:
        print("  주의: robots.txt 의 /empInfo/ 정책이 바뀌었다. 확인 필요.")

    started = utcnow()
    snapshot_id = dt.datetime.now().strftime("work24_5gu_%Y%m%d_%H%M")
    all_rows, per_center, failures, parse_failures = [], {}, [], 0

    for center, meta in CENTERS.items():
        html = fetch_page(session, center, 1, failures)
        if html is None:
            raise RuntimeError(f"{center} 1페이지 수집 실패 — 수집을 중단한다.")
        expected = parse_total(html)
        if expected is None:
            raise RuntimeError(f"{center} 총게시물 파싱 실패 — selector 변경 의심.")
        pages = math.ceil(expected / PAGE_UNIT)
        print(f"  [{center}] 총게시물 {expected:,}건 → {pages}페이지")

        seen, rows_here, empty_streak = set(), [], 0
        for page in range(1, pages + max_extra_pages + 1):
            page_html = html if page == 1 else fetch_page(session, center, page, failures)
            if page_html is None:
                continue                      # 실패 페이지는 기록만, 전체 중단 없음
            parsed = parse_list_page(page_html)
            if not parsed:
                # 첫 빈 페이지에서 즉시 끊지 않는다. 예상 페이지를 넘긴 뒤에만 종료.
                empty_streak += 1
                if page >= pages and empty_streak >= 2:
                    break
                if page > pages:
                    break
                parse_failures += 1
                continue
            empty_streak = 0
            for row in parsed:
                if row["wanted_auth_no"] in seen:
                    continue                  # 중복은 건너뛰되 페이지 순회는 계속
                seen.add(row["wanted_auth_no"])
                rows_here.append({**row, "page_index": page})
            if page % 25 == 0:
                print(f"    {page}/{pages} … {len(rows_here)}건")

        for row in rows_here:
            row.update({
                "snapshot_id": snapshot_id, "crawl_timestamp": started,
                "source_center": meta["center_name"],
                "center_region_scope": "|".join(meta["regions"].values()),
            })
        all_rows.extend(rows_here)
        per_center[center] = {
            "center_name": meta["center_name"],
            "region_scope": list(meta["regions"].values()),
            "region_codes": list(meta["regions"]),
            "expected_total": expected,
            "collected_total": len(rows_here),
            "pages_requested": min(page, pages + max_extra_pages),
        }
        print(f"  [{center}] 수집 {len(rows_here):,}건 / 기대 {expected:,}건")

    df = pd.DataFrame(all_rows)[RAW_COLUMNS]
    csv_path = RAW_DIR / f"{snapshot_id}.csv"
    atomic_write_csv(df, csv_path)

    gu = df["region_raw"].map(parse_gu)
    meta_path = csv_path.with_suffix(".metadata.json")
    atomic_write_text(meta_path, json.dumps({
        "snapshot_id": snapshot_id,
        "crawl_timestamp": started,
        "retrieval_date": started[:10],
        "source": "work24",
        "source_name": "고용24 고용복지+센터 공개 채용정보 목록",
        "source_url": [BASE_URL.format(center=c) for c in CENTERS],
        "collection_method": ("센터 공개 목록페이지의 공개 요청구조(GET) 수집. "
                              "Open API 미사용, 인증키 미사용, 상세페이지 미수집."),
        "center": {k: v["center_name"] for k, v in CENTERS.items()},
        "region_scope": list(IN_SCOPE_GU),
        "region_scope_note": ("region 파라미터는 무상태 GET 에서 무시되어 센터 관할 "
                              "전체가 반환된다. 구 분리는 근무지역 컬럼으로 수행한다."),
        "out_of_scope_included": list(OUT_OF_SCOPE_GU),
        "query_filters": {k: BASE_PARAMS[k] for k in ("comm_daily_clcd", "pageUnit",
                                                      "sortField", "sortOrderBy")},
        "per_center": per_center,
        "expected_total": sum(c["expected_total"] for c in per_center.values()),
        "collected_total": int(len(df)),
        "pages_requested": sum(c["pages_requested"] for c in per_center.values()),
        "pages_failed": len(failures),
        "page_failures": failures,
        "parse_failures": parse_failures,
        "region_filter_mismatch": int((gu.isna()).sum()),
        "in_scope_rows": int(gu.isin(IN_SCOPE_GU).sum()),
        "out_of_scope_rows": int(gu.isin(OUT_OF_SCOPE_GU).sum()),
        "robots_checked_at": robots["checked_at"],
        "robots": robots,
        "file_sha256": sha256_file(csv_path),
        "row_count": int(len(df)),
        "limitations": [
            "현재 게시 중인 공고 위주의 단면(snapshot)이며 생존편향이 있다.",
            "공개 채용공고만 포함한다. 전체 채용시장·노동수요가 아니다.",
            "모집인원·사업장 상세주소·KSIC·직종은 목록에 없고 상세페이지는 "
            "robots.txt 에서 수집이 허용되지 않는다.",
        ],
        "metadata_schema": "changwon-external-collection/1.0.0",
    }, ensure_ascii=False, indent=2))

    print(f"\n  RAW 저장: {csv_path.relative_to(ROOT)} ({len(df):,}건)")
    print(f"  metadata: {meta_path.name}")
    return csv_path


# ═══════════════════════════════════════════════════════════════════════════
# 2. 기존 1,504건 동결 (PHASE 3)
# ═══════════════════════════════════════════════════════════════════════════
def freeze_historical() -> Path:
    """2026-09-18 부분 snapshot 을 원본 바이트 그대로 둔 채 metadata 만 붙인다."""
    if not HISTORICAL.exists():
        raise FileNotFoundError(f"{HISTORICAL} 가 없다. 원본을 먼저 배치할 것.")
    digest = sha256_file(HISTORICAL)
    df = pd.read_csv(HISTORICAL, encoding="utf-8-sig", dtype=str)
    gu = df["region"].map(parse_gu)
    meta = HISTORICAL.with_suffix(".metadata.json")
    atomic_write_text(meta, json.dumps({
        "snapshot_id": "20260918_partial_3gu",
        "crawl_timestamp": "2026-09-18",
        "retrieval_date": "2026-09-18",
        "source": "work24",
        "source_name": "고용24 창원고용복지+센터 공개 채용정보 목록",
        "source_url": BASE_URL.format(center="changwon"),
        "center": "창원고용복지+센터",
        "region_scope": ["의창구", "성산구", "진해구"],
        "definition": ("2026-09-18 수집 시점에 창원고용복지+센터에서 조회 가능했던 "
                       "의창구·성산구·진해구의 공개 채용공고 1,504건."),
        "is_partial": True,
        "partial_reason": "창원시 5개 구 중 3개 구만 포함. 마산 2개 구 미포함.",
        "row_count": int(len(df)),
        "region_counts": gu.value_counts().to_dict(),
        "file_sha256": digest,
        "original_filename": "changwon_jobs_20260918.csv",
        "provenance": ("commit 9a69168 『고용24 창원 채용정보 크롤러 및 수집 데이터 "
                       "추가』 의 changwon_jobs.csv 와 SHA256 동일."),
        "must_not_be_interpreted_as": [
            "창원시 전체", "창원국가산단 전체", "제조업 전체",
            "KICOX 업종별 전체", "모집인원", "노동수요 전체", "시계열 데이터",
        ],
        "known_defects": [
            "education 컬럼이 전부 비어 있다. 목록의 학력은 JS 렌더 값이라 "
            "렌더 전 <p> 텍스트를 읽은 결과다.",
            "임금 유형(시급/월급 등)이 별도 컬럼으로 분리돼 있지 않다.",
        ],
        "superseded_by": ("동일 실행시점 5개 구 canonical RAW (work24_5gu_*). "
                          "이 파일은 비교·이력 목적으로만 보존한다. 새 자료와 "
                          "행을 섞거나 append 하지 않는다."),
        "metadata_schema": "changwon-external-collection/1.0.0",
    }, ensure_ascii=False, indent=2))
    print(f"  동결: {HISTORICAL.name} ({len(df):,}건) sha256={digest[:16]}…")
    return meta


# ═══════════════════════════════════════════════════════════════════════════
# 3. 정규화 (PHASE 8)
# ═══════════════════════════════════════════════════════════════════════════
_CORP = re.compile(r"주식회사|\(주\)|㈜|\(유\)|유한회사|유한책임회사|\(재\)|재단법인"
                   r"|\(사\)|사단법인|\(합\)|합자회사|합명회사")
_NONWORD = re.compile(r"[^0-9A-Za-z가-힣]")
# 영문병기: 괄호 안이 영문·숫자·구두점뿐인 덩어리. 「인시스(INSYS)」의 뒷부분.
_ENG_PAREN = re.compile(r"\((?=[^)]*[A-Za-z])[A-Za-z0-9 .,&'\-]+\)")


def normalize_company(name) -> str:
    """법인격 표기·공백·특수문자를 걷어낸 대조용 키. 원문은 따로 보존한다."""
    s = _CORP.sub("", _nfkc(name))
    return _NONWORD.sub("", s).upper()


def company_match_keys(name) -> list[str]:
    """대조 후보 키. 영문병기를 뗀 형태까지 **완전일치**로만 시도한다.

    두 형태를 모두 시도하는 이유: 공고는 「인시스(INSYS)」, 공장등록현황은
    「인시스」로 적는 경우가 있고 그 반대도 있다. fuzzy match 가 아니라
    표기변형 두 가지에 대한 정확일치이므로 서로 다른 기업을 붙이지 않는다.
    """
    base = normalize_company(name)
    stripped = normalize_company(_ENG_PAREN.sub("", _nfkc(name)))
    return [k for k in dict.fromkeys([base, stripped]) if k]


def parse_gu(region) -> str | None:
    s = _nfkc(region)
    for g in IN_SCOPE_GU + OUT_OF_SCOPE_GU:
        if g in s:
            return g
    return None


_WAGE_NUM = re.compile(r"([\d,]+)\s*(만원|원)")


def parse_wage(wage_raw, wage_type_raw) -> dict:
    """시급·일급·월급·연봉을 구분해 보존한다. 근무시간이 없으므로 단위 간 환산은 하지 않는다."""
    text = _nfkc(wage_raw)
    wtype = _nfkc(wage_type_raw).strip() or None
    if wtype is None:
        for k in ("시급", "일급", "월급", "연봉", "주급"):
            if k in text:
                wtype = k
                break
    nums = []
    for value, unit in _WAGE_NUM.findall(text):
        try:
            n = int(value.replace(",", ""))
        except ValueError:
            continue
        nums.append(n * 10000 if unit == "만원" else n)
    if not text.strip():
        return {"wage_type": wtype, "wage_min": None, "wage_max": None,
                "wage_unit": "원", "wage_parse_status": "EMPTY"}
    if not nums:
        return {"wage_type": wtype, "wage_min": None, "wage_max": None,
                "wage_unit": "원", "wage_parse_status": "UNPARSED"}
    return {"wage_type": wtype, "wage_min": min(nums), "wage_max": max(nums),
            "wage_unit": "원",
            "wage_parse_status": "PARSED" if wtype else "PARSED_NO_TYPE"}


_CAREER_Y = re.compile(r"경력\s*(\d+)\s*년")
_CAREER_M = re.compile(r"경력\s*(\d+)\s*(?:개월|달)")


def parse_career(career_raw) -> dict:
    """'관계없음' 과 '신입' 을 같은 0개월로 뭉개지 않는다."""
    s = _nfkc(career_raw).strip()
    if not s:
        return {"career_type": None, "career_min_months": None,
                "career_parse_status": "EMPTY"}
    if "관계없" in s or "무관" in s:
        # 경력 요건을 두지 않는다는 뜻이며 '0개월 필요'와 다르다.
        return {"career_type": "관계없음", "career_min_months": None,
                "career_parse_status": "PARSED"}
    if "신입" in s and "경력" not in s:
        return {"career_type": "신입", "career_min_months": 0,
                "career_parse_status": "PARSED"}
    if "신입" in s and "경력" in s:
        return {"career_type": "신입/경력", "career_min_months": None,
                "career_parse_status": "PARSED"}
    my = _CAREER_Y.search(s)
    mm = _CAREER_M.search(s)
    if my:
        return {"career_type": "경력", "career_min_months": int(my.group(1)) * 12,
                "career_parse_status": "PARSED"}
    if mm:
        return {"career_type": "경력", "career_min_months": int(mm.group(1)),
                "career_parse_status": "PARSED"}
    if "경력" in s:
        return {"career_type": "경력", "career_min_months": None,
                "career_parse_status": "PARSED_NO_DURATION"}
    return {"career_type": None, "career_min_months": None,
            "career_parse_status": "UNPARSED"}


_DATE = re.compile(r"^(\d{2})-(\d{2})-(\d{2})$")


def parse_date(raw) -> tuple[str | None, str]:
    """'26-09-18' → '2026-09-18'. 비정상 값은 flag 로 남긴다."""
    s = _nfkc(raw).strip()
    if not s:
        return None, "EMPTY"
    m = _DATE.match(s)
    if not m:
        return None, "UNPARSED"
    yy, mo, dd = (int(x) for x in m.groups())
    try:
        return dt.date(2000 + yy, mo, dd).isoformat(), "PARSED"
    except ValueError:
        return None, "INVALID_DATE"


# ═══════════════════════════════════════════════════════════════════════════
# 4. 공식 KSIC 대조표 (PHASE 11)
# ═══════════════════════════════════════════════════════════════════════════
_KSIC_KEY = re.compile(r"[\s,.·\-()]")
_OIJONG = re.compile(r"\s*외\s*\d+\s*종\s*$")


def ksic_key(name) -> str:
    """대조용 키. 공백·구두점만 제거하며 의미는 바꾸지 않는다."""
    return _KSIC_KEY.sub("", _nfkc(name)).upper()


def ensure_ksic_table() -> Path:
    if KSIC_XLSX.exists():
        return KSIC_XLSX
    print("  공식 KSIC 연계표 내려받는 중…")
    KSIC_XLSX.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(KSIC_XLSX_URL, headers={"User-Agent": USER_AGENT},
                     timeout=120)
    r.raise_for_status()
    KSIC_XLSX.write_bytes(r.content)
    return KSIC_XLSX


def load_ksic_lookup() -> pd.DataFrame:
    """업종명 → KSIC 세세분류코드·중분류코드 대조표.

    출처: 통계청 한국표준산업분류 제11차 (국세청 홈택스 『업종코드-11차
    표준산업분류 연계표』 게시본). 제11차 블록을 우선하고, 제11차에 없는
    구 분류 명칭만 보조로 쓴다. 한 이름이 둘 이상의 중분류에 걸리면 버린다.
    """
    d = pd.read_excel(ensure_ksic_table(), sheet_name="연계표",
                      header=None, skiprows=5)

    def norm_code(v) -> str:
        # 중분류 칸은 엑셀에서 수치로 읽혀 '94.0' 이 되기도 한다. 자릿수를 복원한다.
        s = str(v).strip()
        if re.fullmatch(r"\d+\.0", s):
            s = s[:-2]
        return s

    def block(code_col, name_col, mid_from_code, revision):
        b = d[[code_col, name_col]].dropna()
        b.columns = ["code", "name"]
        b["code"] = b["code"].map(norm_code)
        b["name"] = b["name"].astype(str).str.strip()
        b["ksic_mid"] = (b["code"].str[:2] if mid_from_code
                         else b["code"].str.zfill(2))
        b["ksic_code"] = b["code"] if mid_from_code else None
        b["key"] = b["name"].map(ksic_key)
        b["ksic_revision"] = revision
        uniq = b.groupby("key")["ksic_mid"].nunique()
        return b[b["key"].isin(uniq[uniq == 1].index)].drop_duplicates("key")

    new = block(13, 22, True, "KSIC 11차")
    old = block(5, 11, False, "KSIC 구분류")
    old = old[~old["key"].isin(new["key"])]
    cols = ["key", "name", "ksic_code", "ksic_mid", "ksic_revision"]
    return pd.concat([new[cols], old[cols]], ignore_index=True)


def is_manufacturing_mid(mid) -> bool | None:
    """KSIC 대분류 C(제조업) = 중분류 10~34. 미해결은 UNKNOWN 으로 남긴다."""
    if mid is None or (isinstance(mid, float) and math.isnan(mid)):
        return None
    try:
        return 10 <= int(mid) <= 34
    except (TypeError, ValueError):
        return None


# ═══════════════════════════════════════════════════════════════════════════
# 5. 기업 마스터 (PHASE 10)
# ═══════════════════════════════════════════════════════════════════════════
def load_company_master() -> pd.DataFrame:
    """창원시 공장등록현황을 공식 기업 마스터로 쓴다."""
    reg = pd.read_csv(FACTORY, encoding="utf-8-sig", dtype=str)
    reg = reg.rename(columns={
        "회사명": "company_official", "공장대표주소(도로명)": "factory_address",
        "업종명": "industry_name_official", "생산품": "products"})
    reg["company_official"] = reg["company_official"].astype(str).str.strip()
    reg["company_key"] = reg["company_official"].map(normalize_company)
    reg["company_key_alias"] = reg["company_official"].map(
        lambda s: normalize_company(_ENG_PAREN.sub("", _nfkc(s))))
    reg["industry_name_clean"] = (reg["industry_name_official"].astype(str)
                                  .str.strip().str.replace(_OIJONG, "", regex=True))
    reg["ksic_key"] = reg["industry_name_clean"].map(ksic_key)

    lut = load_ksic_lookup()
    reg = reg.merge(lut[["key", "ksic_code", "ksic_mid", "ksic_revision"]],
                    left_on="ksic_key", right_on="key", how="left")
    reg["is_mfg"] = reg["ksic_mid"].map(is_manufacturing_mid)
    return reg[reg["company_key"] != ""]


def match_companies(df: pd.DataFrame, reg: pd.DataFrame) -> pd.DataFrame:
    """정규화 키 완전일치만 인정한다. fuzzy match 로 자동확정하지 않는다."""
    long = pd.concat([
        reg.assign(_k=reg["company_key"]),
        reg.assign(_k=reg["company_key_alias"]),
    ]).drop_duplicates(subset=["_k", "company_official", "factory_address"])
    index = {}
    for key, g in long.groupby("_k"):
        mids = g["ksic_mid"].dropna().unique()
        index[key] = {
            "n_factories": len(g),
            "n_distinct_ksic_mid": len(mids),
            "ksic_code": (g["ksic_code"].dropna().iloc[0]
                          if len(mids) == 1 and g["ksic_code"].notna().any() else None),
            "ksic_mid": mids[0] if len(mids) == 1 else None,
            "ksic_name": (g["industry_name_clean"].iloc[0] if len(mids) == 1 else None),
            "ksic_revision": (g["ksic_revision"].dropna().iloc[0]
                              if len(mids) == 1 and g["ksic_revision"].notna().any()
                              else None),
            "address": g["factory_address"].iloc[0] if len(g) == 1 else None,
            "addresses": g["factory_address"].tolist(),
            "company_official": g["company_official"].iloc[0],
        }

    out = []
    for name in df["company_raw"]:
        keys = company_match_keys(name)
        if not keys:
            out.append({"company_match_status": "UNKNOWN"})
            continue
        hit = next((index[k] for k in keys if k in index), None)
        if hit is None:
            out.append({"company_match_status": "NO_MATCH"})
            continue
        if hit["n_distinct_ksic_mid"] > 1:
            # 같은 상호로 업종이 다른 공장이 여러 곳. 자동 선택하지 않는다.
            out.append({"company_match_status": "MULTI",
                        "company_official": hit["company_official"],
                        "n_factories_matched": hit["n_factories"]})
            continue
        out.append({
            "company_match_status": "MATCH",
            "company_official": hit["company_official"],
            "n_factories_matched": hit["n_factories"],
            "ksic_code": hit["ksic_code"], "ksic_mid": hit["ksic_mid"],
            "ksic_name": hit["ksic_name"], "ksic_revision": hit["ksic_revision"],
            "workplace_address_enriched": (hit["address"] if hit["n_factories"] == 1
                                           else None),
            "n_addresses": hit["n_factories"],
        })
    return pd.DataFrame(out, index=df.index)


# ═══════════════════════════════════════════════════════════════════════════
# 6. 산업단지 매칭 (PHASE 12)
# ═══════════════════════════════════════════════════════════════════════════
def load_dense_dongs() -> set[tuple[str, str]]:
    d = pd.read_csv(DONG_CONTEXT, encoding="utf-8-sig")
    d = d[d["is_dense"].astype(str).str.lower() == "true"]
    return set(zip(d["gu"].astype(str).str.strip(),
                   d["legal_dong"].astype(str).str.strip()))


_EUPMYEON = re.compile(r"(\S+[읍면])")
_DONG_RE = re.compile(r"(\S*?[가-힣]\d*동)")


def parse_dong(addr) -> tuple[str | None, str | None]:
    a = _nfkc(addr)
    gu = next((g for g in IN_SCOPE_GU if g in a), None)
    if gu is None:
        return None, None
    tail = a.split(gu, 1)[1]
    m = _EUPMYEON.search(tail) or _DONG_RE.search(tail)
    return (gu, m.group(1)) if m else (gu, None)


def match_industrial_complex(df: pd.DataFrame) -> pd.DataFrame:
    """창원국가산단 경계 polygon 은 미공표다. point-in-polygon 을 쓸 수 없다.

    대신 프로젝트가 이미 쓰는 제조업 집적 법정동(공장등록현황 기반, 산단 경계의
    **상한**)으로 POSSIBLE / NOT_MATCH 만 판정한다. 공식 경계가 없으므로
    MATCH 는 어떤 행에도 부여하지 않는다. 「성산구니까 산단」식 판정도 하지 않는다.
    """
    dense = load_dense_dongs()
    rows = []
    for addr, mfg in zip(df["workplace_address_enriched"], df["is_manufacturing"]):
        if not isinstance(addr, str) or not addr.strip():
            rows.append({"industrial_complex_match_status": "UNKNOWN",
                         "industrial_complex_match_method": "NO_RELIABLE_ADDRESS",
                         "address_legal_dong": None})
            continue
        gu, dong = parse_dong(addr)
        if gu is None or dong is None:
            rows.append({"industrial_complex_match_status": "UNKNOWN",
                         "industrial_complex_match_method": "ADDRESS_UNPARSED",
                         "address_legal_dong": dong})
            continue
        in_dense = (gu, dong) in dense
        rows.append({
            "industrial_complex_match_status": ("POSSIBLE" if in_dense and mfg is True
                                                else "NOT_MATCH" if not in_dense
                                                else "UNKNOWN"),
            "industrial_complex_match_method": "LEGAL_DONG_MFG_DENSITY_PROXY_UPPER_BOUND",
            "address_legal_dong": f"{gu} {dong}",
        })
    return pd.DataFrame(rows, index=df.index)


# ═══════════════════════════════════════════════════════════════════════════
# 7. KSIC → KICOX (PHASE 13)
# ═══════════════════════════════════════════════════════════════════════════
def load_kicox_map() -> dict[str, dict]:
    d = pd.read_csv(KSIC_TO_KICOX, encoding="utf-8-sig", dtype=str)
    return {str(r["source_code"]).strip().zfill(2): {
        "kicox_industry": r["target_kicox_industry"],
        "mapping_type": r["mapping_type"],
        "mapping_confidence": r["mapping_confidence"],
    } for _, r in d.iterrows()}


def map_kicox(df: pd.DataFrame) -> pd.DataFrame:
    """매핑 실패는 UNMAPPED 다. KICOX 의 실제 업종 '기타' 와 섞지 않는다."""
    m = load_kicox_map()
    rows = []
    for mid, mfg in zip(df["ksic_mid"], df["is_manufacturing"]):
        key = None if mid is None or pd.isna(mid) else str(mid).zfill(2)
        hit = m.get(key) if key else None
        if hit is None:
            rows.append({"kicox_industry": None,
                         "kicox_mapping_status": "UNMAPPED",
                         "kicox_mapping_confidence": None,
                         "kicox_mapping_note": (
                             "기업 미식별로 KSIC 미해결" if mfg is None
                             else "제조업이 아니어서 KICOX 업종 대상 아님" if mfg is False
                             else "KSIC 중분류가 crosswalk 에 없음")})
            continue
        rows.append({"kicox_industry": hit["kicox_industry"],
                     "kicox_mapping_status": "MAPPED",
                     "kicox_mapping_confidence": hit["mapping_confidence"],
                     "kicox_mapping_note": hit["mapping_type"]})
    return pd.DataFrame(rows, index=df.index)


# ═══════════════════════════════════════════════════════════════════════════
# 8. 재공고 후보 (PHASE 9)
# ═══════════════════════════════════════════════════════════════════════════
def flag_reposts(df: pd.DataFrame) -> pd.DataFrame:
    """자동 삭제하지 않는다. 후보 표시만 한다."""
    title_key = df["title_raw"].map(lambda s: _NONWORD.sub("", _nfkc(s)).upper())
    group = df["normalized_company"].fillna("") + "|" + title_key
    counts = group.value_counts()
    ids = {k: f"RG{i:05d}" for i, k in enumerate(counts[counts > 1].index, 1)}
    return pd.DataFrame({
        "duplicate_group_id": group.map(ids),
        "repost_candidate": group.map(lambda g: g in ids),
        "repost_reason": group.map(
            lambda g: "동일기업·동일공고명 복수 공고" if g in ids else None),
    }, index=df.index)


# ═══════════════════════════════════════════════════════════════════════════
# 9. build (PHASE 14~16)
# ═══════════════════════════════════════════════════════════════════════════
def latest_snapshot() -> Path:
    snaps = sorted(RAW_DIR.glob("work24_5gu_*.csv"))
    if not snaps:
        raise FileNotFoundError("5개 구 canonical RAW 가 없다. 먼저 collect 를 실행할 것.")
    return snaps[-1]


def load_gate_targets(stages: tuple[str, ...]) -> tuple[pd.DataFrame, str | None]:
    """Decision Gate 에서 추가 확인이 필요한 업종 (최신 분기 기준)."""
    if not GATE_SIGNALS.exists():
        return pd.DataFrame(columns=["industry", "stage", "state", "quarter"]), None
    d = pd.read_csv(GATE_SIGNALS, encoding="utf-8-sig", low_memory=False)
    last = d["quarter"].max()
    cur = d[d["quarter"] == last][["industry", "stage", "state", "quarter"]].copy()
    return cur[cur["stage"].isin(stages)].reset_index(drop=True), last


def build(stages: tuple[str, ...] = GATE_STAGES_DEFAULT) -> dict:
    snap = latest_snapshot()
    raw = pd.read_csv(snap, encoding="utf-8-sig", dtype=str)
    print(f"  RAW: {snap.name} ({len(raw):,}건)")

    df = raw.copy()
    df["gu"] = df["region_raw"].map(parse_gu)
    df["in_scope"] = df["gu"].isin(IN_SCOPE_GU)
    df["normalized_company"] = df["company_raw"].map(normalize_company)

    wage = pd.DataFrame(list(map(parse_wage, df["wage_raw"], df["wage_type_raw"])),
                        index=df.index)
    career = pd.DataFrame(list(map(parse_career, df["career_raw"])), index=df.index)
    reg_d = list(map(parse_date, df["reg_date_raw"]))
    due_d = list(map(parse_date, df["due_date_raw"]))
    df["reg_date"] = [x[0] for x in reg_d]
    df["reg_date_status"] = [x[1] for x in reg_d]
    df["due_date"] = [x[0] for x in due_d]
    df["due_date_status"] = [x[1] for x in due_d]
    df = pd.concat([df, wage, career, flag_reposts(df)], axis=1)

    # 기업 식별 → KSIC → 제조업
    reg = load_company_master()
    df = pd.concat([df, match_companies(df, reg)], axis=1)
    for col in ("company_official", "ksic_code", "ksic_mid", "ksic_name",
                "ksic_revision", "workplace_address_enriched", "n_factories_matched"):
        if col not in df.columns:
            df[col] = None
    df["is_manufacturing"] = df["ksic_mid"].map(is_manufacturing_mid)
    df["ksic_resolution_method"] = [
        "COMPANY_MASTER_EXACT" if s == "MATCH" and pd.notna(m) else "UNRESOLVED"
        for s, m in zip(df["company_match_status"], df["ksic_mid"])]
    df["ksic_source"] = df["ksic_resolution_method"].map(
        lambda v: "ENRICHED_FROM_FACTORY_REGISTER" if v == "COMPANY_MASTER_EXACT"
        else "NOT_COLLECTED_ACCESS_POLICY")

    # 목록에 없고 상세는 robots 비허용 → 만들지 않고 상태로 남긴다
    df["workplace_address_raw"] = None
    df["address_source"] = df["workplace_address_enriched"].map(
        lambda v: "ENRICHED_FROM_FACTORY_REGISTER" if isinstance(v, str) and v.strip()
        else "NOT_COLLECTED_ACCESS_POLICY")
    df["address_reference_date"] = df["address_source"].map(
        lambda v: "2024-12-31" if v == "ENRICHED_FROM_FACTORY_REGISTER" else None)
    df["recruitment_count"] = pd.NA
    df["recruitment_count_source"] = "NOT_COLLECTED_ACCESS_POLICY"
    df["occupation"] = pd.NA
    df["occupation_source"] = "NOT_PROVIDED_ON_LIST"

    df = pd.concat([df, match_industrial_complex(df), map_kicox(df)], axis=1)

    analysis = df[df["in_scope"]].copy()
    cols = [
        "snapshot_id", "crawl_timestamp", "source_center", "wanted_auth_no",
        "company_raw", "normalized_company", "company_official",
        "company_match_status", "n_factories_matched",
        "title_raw", "region_raw", "gu", "in_scope",
        "reg_date", "reg_date_raw", "reg_date_status",
        "due_date", "due_date_raw", "due_date_status",
        "wage_raw", "wage_type", "wage_min", "wage_max", "wage_unit",
        "wage_parse_status", "career_raw", "career_type", "career_min_months",
        "career_parse_status", "education_raw", "cert_raw",
        "recruitment_count", "recruitment_count_source",
        "occupation", "occupation_source",
        "workplace_address_raw", "workplace_address_enriched", "address_source",
        "address_reference_date",
        "ksic_code", "ksic_mid", "ksic_name", "ksic_revision",
        "ksic_resolution_method", "ksic_source", "is_manufacturing",
        "industrial_complex_match_status", "industrial_complex_match_method",
        "address_legal_dong",
        "kicox_industry", "kicox_mapping_status", "kicox_mapping_confidence",
        "kicox_mapping_note",
        "duplicate_group_id", "repost_candidate", "repost_reason", "source_url",
    ]
    analysis = analysis[[c for c in cols if c in analysis.columns]]
    atomic_write_csv(analysis, OUT_DIR / "work24_analysis_ready.csv")

    # Decision Gate evidence
    targets, gate_quarter = load_gate_targets(stages)
    ev = analysis[analysis["kicox_industry"].isin(targets["industry"])].copy()
    ev = ev.merge(targets.rename(columns={"industry": "kicox_industry",
                                          "stage": "q1_q3_stage",
                                          "state": "q1_q3_state",
                                          "quarter": "q1_q3_quarter"}),
                  on="kicox_industry", how="left")
    ev["q1_q3_industry"] = ev["kicox_industry"]
    ev["evidence_status"] = [
        "CONFIRMED_POSTING_COMPANY_IDENTIFIED" if s == "MATCH" else "COMPANY_UNIDENTIFIED"
        for s in ev["company_match_status"]]
    ev["evidence_notes"] = (
        "수집시점 공개 채용활동 확인. 공고 수는 모집인원·노동수요가 아니다. "
        "모집인원은 목록 미제공·상세 수집 비허용으로 미확보(NULL).")
    ev_cols = [
        "q1_q3_industry", "q1_q3_quarter", "q1_q3_stage", "q1_q3_state",
        "kicox_industry", "company_raw", "normalized_company", "company_official",
        "wanted_auth_no", "title_raw", "region_raw", "gu", "reg_date", "due_date",
        "recruitment_count", "recruitment_count_source",
        "occupation", "occupation_source",
        "career_type", "career_min_months", "wage_type", "wage_min", "wage_max",
        "ksic_code", "ksic_name", "ksic_resolution_method",
        "company_match_status", "is_manufacturing",
        "workplace_address_enriched", "address_source",
        "industrial_complex_match_status", "industrial_complex_match_method",
        "kicox_mapping_status", "kicox_mapping_confidence",
        "repost_candidate", "evidence_status", "evidence_notes", "source_url",
    ]
    ev = ev[[c for c in ev_cols if c in ev.columns]]
    atomic_write_csv(ev, OUT_DIR / "work24_decision_gate_evidence.csv")

    summary = build_quality_summary(snap, raw, df, analysis, ev, targets,
                                    gate_quarter, stages)
    atomic_write_text(OUT_DIR / "work24_quality_summary.json",
                      json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"  analysis-ready: {len(analysis):,}건 | evidence: {len(ev):,}건")
    return summary


def _pct(n, d) -> float:
    return round(100.0 * n / d, 2) if d else 0.0


def _cov(series, total) -> dict:
    """빈 문자열은 미확보로 센다(공백만 있는 값이 coverage 를 부풀리지 않게)."""
    n = int(series.fillna("").astype(str).str.strip().ne("").sum())
    return {"n": n, "pct": _pct(n, total)}


def build_quality_summary(snap, raw, df, analysis, ev, targets, gate_quarter,
                          stages) -> dict:
    meta = json.loads(snap.with_suffix(".metadata.json").read_text(encoding="utf-8"))
    n_raw, n = len(raw), len(analysis)
    hist_meta = HISTORICAL.with_suffix(".metadata.json")
    return {
        "generated_at": utcnow(),
        "purpose": ("고용24(work24) 공개 채용정보를 Decision Gate 후속 확인자료로 "
                    "쓰기 위한 품질요약. Q1~Q3 결과를 대체·수정하지 않는다."),
        "snapshot": {
            "snapshot_id": meta["snapshot_id"],
            "crawl_timestamp": meta["crawl_timestamp"],
            "file": snap.name,
            "file_sha256": meta["file_sha256"],
            "expected_total": meta["expected_total"],
            "collected_total": meta["collected_total"],
            "collected_vs_expected_diff": meta["collected_total"] - meta["expected_total"],
            "pages_requested": meta["pages_requested"],
            "pages_failed": meta["pages_failed"],
            "parse_failures": meta["parse_failures"],
            "robots_checked_at": meta["robots_checked_at"],
        },
        "historical_snapshot": (json.loads(hist_meta.read_text(encoding="utf-8"))
                                if hist_meta.exists() else None),
        "collection": {
            "raw_rows": n_raw,
            "in_scope_rows": n,
            "out_of_scope_rows": int((~df["in_scope"]).sum()),
            "region_unparsed": int(df["gu"].isna().sum()),
            "rows_by_gu": df["gu"].value_counts(dropna=False).rename(
                index=lambda x: "UNPARSED" if pd.isna(x) else x).to_dict(),
            "uiryeong_out_of_scope": int((df["gu"] == "의령군").sum()),
            "wanted_auth_no_unique": int(df["wanted_auth_no"].nunique()),
            "wanted_auth_no_duplicated": int(df["wanted_auth_no"].duplicated().sum()),
        },
        "core_field_coverage": {
            k: _cov(analysis[k], n) for k in
            ("wanted_auth_no", "company_raw", "title_raw", "region_raw",
             "reg_date", "due_date", "wage_raw", "career_raw", "education_raw")
        },
        "supplementary_field_coverage": {
            "recruitment_count": {
                "direct": {"n": 0, "pct": 0.0}, "enriched": {"n": 0, "pct": 0.0},
                "status": "NOT_COLLECTED_ACCESS_POLICY",
                "note": ("목록페이지에 모집인원이 없고 상세페이지는 robots.txt 에서 "
                         "수집이 허용되지 않는다. 미확보 행을 0명으로 처리하지 않는다."),
            },
            "workplace_address": {
                "direct": {"n": 0, "pct": 0.0},
                "enriched": _cov(analysis["workplace_address_enriched"], n),
                "enriched_source": "창원시 공장등록현황(2024-12-31)",
                "note": "기업 주소이며 공고의 실제 근무지와 동일하다고 가정하지 않는다.",
            },
            "ksic": {
                "direct": {"n": 0, "pct": 0.0},
                "enriched": {"n": int((analysis["ksic_resolution_method"]
                                       == "COMPANY_MASTER_EXACT").sum()),
                             "pct": _pct((analysis["ksic_resolution_method"]
                                          == "COMPANY_MASTER_EXACT").sum(), n)},
                "enriched_source": ("창원시 공장등록현황 업종명 → 통계청 KSIC 제11차 "
                                    "공식 연계표(국세청 홈택스 게시본)"),
            },
            "occupation": {"direct": {"n": 0, "pct": 0.0},
                           "status": "NOT_PROVIDED_ON_LIST"},
        },
        "company_matching": {
            "status_counts": analysis["company_match_status"].value_counts().to_dict(),
            "match_rate_pct": _pct((analysis["company_match_status"] == "MATCH").sum(), n),
            "note": "정규화 키 완전일치만 인정. fuzzy match 자동확정 없음. MULTI 자동선택 없음.",
        },
        "ksic_and_manufacturing": {
            "resolution_counts": analysis["ksic_resolution_method"].value_counts().to_dict(),
            "is_manufacturing_counts": {
                "True": int((analysis["is_manufacturing"] == True).sum()),      # noqa: E712
                "False": int((analysis["is_manufacturing"] == False).sum()),    # noqa: E712
                "UNKNOWN": int(analysis["is_manufacturing"].isna().sum()),
            },
            "note": "기업 미식별은 비제조업이 아니라 UNKNOWN 이다. 직무명으로 산업을 추정하지 않는다.",
        },
        "industrial_complex": {
            "status_counts": analysis["industrial_complex_match_status"]
                             .value_counts().to_dict(),
            "method": "LEGAL_DONG_MFG_DENSITY_PROXY_UPPER_BOUND",
            "match_status_blocked": True,
            "note": ("창원국가산단 경계 polygon 미공표로 point-in-polygon 불가. "
                     "MATCH 는 어떤 행에도 부여하지 않는다. 제조업 집적 법정동은 "
                     "산단 경계의 상한이므로 POSSIBLE 은 '산단 소재 확정'이 아니다."),
        },
        "kicox_mapping": {
            "status_counts": analysis["kicox_mapping_status"].value_counts().to_dict(),
            "industry_counts": analysis["kicox_industry"].value_counts().to_dict(),
            "note": "UNMAPPED 는 미분류이며 KICOX 실제 업종 '기타' 와 다르다.",
        },
        "reposts": {
            "duplicate_groups": int(analysis["duplicate_group_id"].nunique()),
            "repost_candidates": int(analysis["repost_candidate"].sum()),
            "note": "후보 표시만 하며 자동 삭제하지 않는다.",
        },
        "decision_gate_evidence": {
            "gate_quarter": gate_quarter,
            "target_stages": list(stages),
            "target_industries": targets["industry"].tolist(),
            "postings": int(len(ev)),
            "companies_identified": int(ev.loc[ev["company_match_status"] == "MATCH",
                                               "company_official"].nunique()),
            "postings_company_identified": int((ev["company_match_status"] == "MATCH").sum()),
            "recruitment_count_coverage_pct": 0.0,
            "level_a_available": True,
            "level_b_available": False,
            "level_b_blocked_reason": ("모집인원을 허용된 경로에서 확보할 수 없다. "
                                       "공고 수는 모집인원이 아니므로 Level B 집계를 하지 않는다."),
        },
        "interpretation_limits": [
            "공고 수는 모집인원이 아니다.",
            "공고 수는 노동수요가 아니다.",
            "공개공고는 전체 채용시장이 아니다.",
            "공고 수 증감으로 산업 성장·위기를 판단하지 않는다.",
            "이 자료로 Q1~Q3 의 S1~S4 상태를 바꾸지 않는다.",
            "현재 게시 중인 공고 위주의 단면이라 생존편향이 있다.",
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=["freeze", "collect", "build", "all"])
    ap.add_argument("--gate-stages", default=",".join(GATE_STAGES_DEFAULT),
                    help="Decision Gate 추가확인 대상 stage (쉼표 구분)")
    a = ap.parse_args(argv)
    stages = tuple(s.strip() for s in a.gate_stages.split(",") if s.strip())

    if a.command in ("freeze", "all"):
        print("[freeze] 기존 2026-09-18 부분 snapshot 동결")
        freeze_historical()
    if a.command in ("collect", "all"):
        print("[collect] 창원+마산 센터 동일시점 수집")
        collect()
    if a.command in ("build", "all"):
        print("[build] analysis-ready + Decision Gate evidence")
        build(stages)
    return 0


if __name__ == "__main__":
    sys.exit(main())
