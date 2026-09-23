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
    이 모듈이 사용한 레거시 work.go.kr 의 `/empInfo/` 상세경로는 robots.txt 에서
    차단되어 수집하지 않는다. 센터 목록경로(`/changwon|masan/infoPlace/empInfo/`)
    는 그 접두사가 아니므로 허용된다. 현행 work24.go.kr 검색·상세 경로는 별도
    모듈 ``work24_current.py``에서 도메인별 robots를 다시 확인하고 다룬다.
    목록에 없는 필드는 이 원자료에 만들어 넣지 않는다.

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
REQUEST_DELAY_SEC = 2.0
REQUEST_TIMEOUT_SEC = 30
MAX_RETRIES = 3
USER_AGENT = (
    "Changwon-Industry-Employment-Monitor/1.0 (academic research; "
    "public job posting list pages; contact via repository)"
)


class AccessPolicyStop(RuntimeError):
    """403/429 등 명시적 차단 신호를 받으면 전체 수집을 즉시 중단한다."""
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

# 모집인원·직종·과거공고를 얻을 수 있는 공식 경로를 하나씩 확인한 기록 (2026-09-19).
# 검색 결과 설명이 아니라 실제 호출·조회 결과다. 추정 endpoint 는 호출하지 않았다.
EXTERNAL_SOURCE_INVESTIGATION = {
    "checked_at": "2026-09-19",
    "sources": [
        {"source": "한국고용정보원 워크넷 채용정보 API (data.go.kr 3038225)",
         "endpoint": "http://openapi.work.go.kr/opi/opi/opia/wantedApi.do",
         "auth": "전용 authKey (데이터셋별 활용신청, 자동승인)",
         "tested": True,
         "result": "보유한 DATA_GO_KR_SERVICE_KEY 로 호출 시 messageCd=002 "
                   "'유효하지 않은 인증키' — 현재 자격으로 사용 불가",
         "would_solve": "모집인원·직종코드 (단, 게시 중 공고 한정으로 과거이력은 별개)",
         "status": "NOT_AVAILABLE"},
        {"source": "KOSIS 워크넷 구인 통계",
         "endpoint": "https://kosis.kr/openapi/statisticsSearch.do",
         "auth": "KOSIS_API_KEY (보유)",
         "tested": True,
         "result": "'워크넷·구인배수·구인인원' 검색 결과 중 지역 구인 통계는 "
                   "DT_1YL1101 『구인배수(시도)』뿐. 시군구×산업 테이블 없음",
         "would_solve": "업종×월 구인인원 시계열",
         "status": "NOT_SUITABLE_GEOGRAPHY"},
        {"source": "공공데이터포털 파일데이터 (채용·구인·일자리정보)",
         "endpoint": "https://www.data.go.kr/tcs/dss/selectDataSetList.do?dType=FILE",
         "auth": "불필요",
         "tested": True,
         "result": "창원·경남 제조업 채용공고 파일데이터 없음. 검색결과는 타 지자체 "
                   "노인일자리·개별 공공기관 채용공고뿐",
         "would_solve": "과거 공고 이력",
         "status": "NOT_FOUND"},
        {"source": "고용24 상세페이지 (/empInfo/)",
         "endpoint": "https://www.work.go.kr/empInfo/...",
         "auth": "불필요",
         "tested": False,
         "result": "robots.txt 가 모든 UA 에 Disallow. 수집하지 않는다",
         "would_solve": "모집인원·직종·담당업무·요구기술·자격요건",
         "status": "BLOCKED_BY_ACCESS_POLICY"},
        {"source": "현행 고용24 공개 채용정보 상세",
         "endpoint": "https://www.work24.go.kr/wk/a/b/1500/empDetailAuthView.do",
         "auth": "비로그인 공개",
         "tested": True,
         "result": ("2026-09-23 robots.txt에서 /wk/a/b/1200·1500 허용 확인 후 "
                    "기존 구인인증번호 5건을 비로그인 검증. 모집인원·직종·직무내용·"
                    "자격면허·고용형태·근무예정지 확보, 5/5 ID join 성공. 전체 수집은 미실행"),
         "would_solve": "현행 공개 공고의 모집인원·직종·직무내용·자격요건 보강",
         "status": "SAMPLE_VALIDATED"},
        {"source": "창원시 공장등록현황 (data.go.kr 3066436)",
         "endpoint": "공공데이터포털 파일데이터",
         "auth": "불필요", "tested": True,
         "result": "확보·사용 중. 기업명·공장주소·업종명(KSIC 세세분류 명칭) 제공",
         "would_solve": "기업 식별·주소·KSIC",
         "status": "IN_USE"},
        {"source": "통계청 KSIC 제11차 연계표 (국세청 홈택스 게시본)",
         "endpoint": "https://teht.hometax.go.kr/doc/rn/a/a/업종코드-표준산업분류 연계표",
         "auth": "불필요", "tested": True,
         "result": "확보·사용 중. 업종명→세세분류코드·중분류코드 대조 99.5%",
         "would_solve": "KSIC 코드화·KICOX 매핑",
         "status": "IN_USE"},
    ],
    "conclusion": ("개인회원 OPEN-API는 사용할 수 없지만 현행 work24.go.kr 공개 상세는 "
                   "robots 허용·비로그인 접근을 5건 검증했다. 전체 요청 전 대량 이용 범위를 "
                   "별도 확인해야 하며, 게시 중 공고라 2021~2026 과거 분기 복원과는 별개다."),
}


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
                # 같은 화면이 시점에 따라 UTF-8/EUC-KR 선언을 사용한다. 강제 UTF-8은
                # 한글을 훼손하므로 응답 선언과 requests 감지를 존중한다.
                if not r.encoding or r.encoding.lower() in {"iso-8859-1", "ascii"}:
                    r.encoding = r.apparent_encoding or "utf-8"
                return r.text
            if r.status_code in (403, 429):        # 접근통제는 재시도하지 않는다
                failures.append({"center": center, "page_index": page_index,
                                 "status": r.status_code, "kind": "access_denied"})
                raise AccessPolicyStop(
                    f"work.go.kr access signal {r.status_code}; collection stopped")
            last = {"status": r.status_code, "kind": "http_error"}
        except requests.RequestException as e:
            last = {"status": 0, "kind": type(e).__name__}
        if attempt < MAX_RETRIES - 1:
            time.sleep(2.0 ** (attempt + 1))       # 2초, 4초 exponential backoff
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
            "이 레거시 센터 목록에는 모집인원·사업장 상세주소·KSIC·직종이 없다. "
            "work.go.kr 레거시 상세는 robots 비허용이며, 현행 work24.go.kr 상세 "
            "보강은 이 2026-09-19 snapshot에 적용하지 않았다.",
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
# 9. 필드 확보 상태 台帳
# ═══════════════════════════════════════════════════════════════════════════
# (필드, 상태, 실제 컬럼, 비고). 상태는 다음 다섯 가지만 쓴다.
#   DIRECT                  센터 공개 목록에서 그대로 수집
#   OFFICIAL_EXTERNAL_MATCH 공식 외부자료(공장등록현황·KSIC 연계표)로 결합
#   DERIVED                 위 둘에서 규칙으로 파생
#   TEXT_INFERENCE          텍스트 추정 — 이 파이프라인은 쓰지 않는다
#   UNAVAILABLE             허용된 경로에 없다
FIELD_INVENTORY: tuple[tuple[str, str, str | None, str], ...] = (
    # 공고 식별
    ("posting_id", "DIRECT", "wanted_auth_no", "공식 구인인증번호. 임의 생성 없음"),
    ("posting_url", "DIRECT", "source_url", "상세 링크. 상세페이지는 수집하지 않는다"),
    ("posting_title", "DIRECT", "title_raw", ""),
    ("registration_date", "DIRECT", "reg_date", ""),
    ("closing_date", "DIRECT", "due_date", ""),
    ("posting_status", "DERIVED", "posting_status",
     "스냅샷 2회 이상일 때만 NEW/CONTINUING 판정. 1회면 전 행 UNKNOWN_SINGLE_SNAPSHOT"),
    # 기업
    ("company_name", "DIRECT", "company_raw", ""),
    ("company_identifier", "UNAVAILABLE", None,
     "이 레거시 목록 snapshot에는 사업자등록번호가 없다"),
    ("workplace_name", "UNAVAILABLE", None, "목록은 기업명만 준다"),
    ("workplace_address", "OFFICIAL_EXTERNAL_MATCH", "workplace_address_enriched",
     "공장등록현황 공장주소. 공고의 실제 근무지와 같다고 가정하지 않는다"),
    ("headquarters_address", "UNAVAILABLE", None, ""),
    ("company_size", "UNAVAILABLE", None, "종사자 규모 미제공"),
    ("establishment_type", "UNAVAILABLE", None, ""),
    # 지역
    ("work_region", "DIRECT", "region_raw", "시·군·구까지만. 읍면동 없음"),
    ("sido", "DERIVED", "region_raw", "전 행 경상남도"),
    ("sigungu", "DERIVED", "gu", ""),
    ("eupmyeondong", "OFFICIAL_EXTERNAL_MATCH", "address_legal_dong",
     "공고가 아니라 결합된 공장주소의 법정동"),
    ("industrial_complex", "DERIVED", "industrial_complex_match_status",
     "공식 경계 미공표. POSSIBLE 상한판정만. MATCH 부여 안 함"),
    # 산업
    ("ksic_code", "OFFICIAL_EXTERNAL_MATCH", "ksic_code", "통계청 제11차 공식 연계표"),
    ("ksic_name", "OFFICIAL_EXTERNAL_MATCH", "ksic_name", ""),
    ("manufacturing", "DERIVED", "is_manufacturing", "KSIC 중분류 10~34. 미해결은 UNKNOWN"),
    ("kicox_industry", "DERIVED", "kicox_industry", "ksic_to_kicox.csv 재사용"),
    # 채용량
    ("recruitment_count", "UNAVAILABLE", "recruitment_count",
     "2026-09-19 레거시 목록 미제공. 전 행 NULL; 현행 work24 상세 보강은 별도 snapshot"),
    # 직무
    ("occupation_code", "UNAVAILABLE", None, "목록 미제공"),
    ("occupation_name", "UNAVAILABLE", None, "공고제목은 직종명이 아니다"),
    ("job_description", "UNAVAILABLE", None, "상세페이지 전용"),
    # 기술·자격
    ("required_skill", "UNAVAILABLE", None, "상세페이지 전용"),
    ("preferred_skill", "UNAVAILABLE", None, "상세페이지 전용"),
    ("certificate_required", "UNAVAILABLE", None,
     "cert_raw 는 자격증이 아니라 공고 인증배지이며 전 행 동일값이라 정보량 0"),
    # 채용조건
    ("experience", "DIRECT", "career_type", ""),
    ("education", "DIRECT", "education_raw", "script var hak 에서 취득"),
    ("employment_type", "UNAVAILABLE", None,
     "목록 미제공. comm_daily_clcd 필터는 수집시점에 결과를 바꾸지 않아 상용 단정 불가"),
    ("working_type", "UNAVAILABLE", None, ""),
    ("shift_work", "UNAVAILABLE", None, ""),
    ("working_hours", "UNAVAILABLE", None, "임금 단위 환산을 못 하는 직접 원인"),
    ("wage_type", "DIRECT", "wage_type", "em.ico_pay 클래스에서 취득"),
    ("wage", "DIRECT", "wage_min", "wage_min/wage_max/wage_unit"),
    ("preferred_condition", "UNAVAILABLE", None, ""),
    # 시계열·중복
    ("repost_identification", "DERIVED", "repost_candidate", "동일기업·동일공고명"),
    ("timeseries_key", "DIRECT", "snapshot_id", "snapshot_id + crawl_timestamp"),
)


def field_inventory_report(a: pd.DataFrame) -> dict:
    n = len(a)
    out = {}
    for field, status, col, note in FIELD_INVENTORY:
        entry = {"status": status, "column": col, "note": note}
        if col and col in a.columns:
            entry["coverage"] = _cov(a[col], n)
        else:
            entry["coverage"] = {"n": 0, "pct": 0.0}
        out[field] = entry
    counts = {}
    for _, status, _, _ in FIELD_INVENTORY:
        counts[status] = counts.get(status, 0) + 1
    return {"fields": out, "status_counts": counts,
            "total_fields": len(FIELD_INVENTORY)}


# ═══════════════════════════════════════════════════════════════════════════
# 10. 스냅샷 간 공고 상태 추적 (§22·§23)
# ═══════════════════════════════════════════════════════════════════════════
def _center_list_snapshots() -> list[Path]:
    """레거시 센터 목록 스냅샷만 반환하고 상세 보강 CSV는 제외한다."""
    candidates = list(RAW_DIR.glob("work24_5gu_*.csv"))
    historical = RAW_DIR / "20260918_partial_3gu.csv"
    if historical.exists():
        candidates.append(historical)
    return sorted(set(candidates))


def _snapshot_ids(path: Path) -> tuple[set[str], set[str]]:
    """(공고 ID 집합, 포함된 구 집합). 구 스키마(20260918)도 함께 읽는다."""
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
    region_col = "region_raw" if "region_raw" in df.columns else "region"
    gu = df[region_col].map(parse_gu)
    return set(df["wanted_auth_no"].dropna()), set(gu.dropna())


def snapshot_transitions() -> dict:
    """직전 스냅샷과 비교해 NEW / CONTINUING / CLOSED 를 센다.

    두 스냅샷의 수집범위가 다르면 **공통 구로 제한**해서만 비교한다. 그러지 않으면
    마산 2개 구가 통째로 NEW 로 잡혀 '신규 채용 급증'처럼 보인다.
    스냅샷이 하나뿐이면 과거 상태를 추정하지 않고 그대로 비워 둔다.
    """
    snaps = _center_list_snapshots()
    if len(snaps) < 2:
        return {"available": False,
                "reason": "스냅샷이 1개뿐이다. 과거 상태를 역산하지 않는다.",
                "snapshots": [p.name for p in snaps]}
    prev, cur = snaps[-2], snaps[-1]
    prev_ids, prev_gu = _snapshot_ids(prev)
    cur_ids, cur_gu = _snapshot_ids(cur)
    common = sorted(prev_gu & cur_gu)
    if prev_gu != cur_gu:
        prev_df = pd.read_csv(prev, encoding="utf-8-sig", dtype=str)
        cur_df = pd.read_csv(cur, encoding="utf-8-sig", dtype=str)
        pcol = "region_raw" if "region_raw" in prev_df.columns else "region"
        ccol = "region_raw" if "region_raw" in cur_df.columns else "region"
        prev_ids = set(prev_df[prev_df[pcol].map(parse_gu).isin(common)]["wanted_auth_no"])
        cur_ids = set(cur_df[cur_df[ccol].map(parse_gu).isin(common)]["wanted_auth_no"])
    return {
        "available": True,
        "previous_snapshot": prev.name, "current_snapshot": cur.name,
        "scope_restricted_to": common,
        "scope_differs": sorted(prev_gu) != sorted(cur_gu),
        "previous_rows_in_scope": len(prev_ids),
        "current_rows_in_scope": len(cur_ids),
        "continuing": len(prev_ids & cur_ids),
        "new": len(cur_ids - prev_ids),
        "closed": len(prev_ids - cur_ids),
        "note": ("공고 ID 기준 집합 비교. CLOSED 는 '마감'이 아니라 '목록에서 사라짐' "
                 "이다(마감·삭제·수정 재등록을 구분하지 못한다)."),
        "reposting_rate_available": False,
        "reposting_rate_status": "BLOCKED",
        "reposting_rate_note": (
            "상태추적으로 재공고율을 만들지 않는다. NEW/CONTINUING/CLOSED 는 **같은 "
            "posting ID** 의 존속 여부이고, 재공고는 **다른 posting ID 로 다시 올라온 "
            "같은 자리**다. 두 스냅샷이 있다고 해서 재공고율이 산출되지 않는다. "
            "동일기업·유사 공고명이 새 ID 로 재등장하는 규칙을 검증하기 전까지 BLOCKED."),
    }


def assign_posting_status(a: pd.DataFrame) -> pd.Series:
    """직전 스냅샷에 있던 공고면 CONTINUING, 없으면 NEW. 1회 수집이면 판정하지 않는다."""
    snaps = _center_list_snapshots()
    if len(snaps) < 2:
        return pd.Series("UNKNOWN_SINGLE_SNAPSHOT", index=a.index, dtype="object")
    prev_ids, prev_gu = _snapshot_ids(snaps[-2])
    in_prev_scope = a["gu"].isin(prev_gu)
    return pd.Series(
        [("CONTINUING" if i in prev_ids else "NEW") if scope
         else "OUT_OF_PREVIOUS_SCOPE"
         for i, scope in zip(a["wanted_auth_no"], in_prev_scope)],
        index=a.index, dtype="object")


# ═══════════════════════════════════════════════════════════════════════════
# 11. build (PHASE 14~16)
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

    # 이 레거시 목록 snapshot에 없던 값은 소급 생성하지 않고 상태로 남긴다.
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
    analysis["posting_status"] = assign_posting_status(analysis)
    cols = [
        "snapshot_id", "crawl_timestamp", "source_center", "wanted_auth_no",
        "company_raw", "normalized_company", "company_official",
        "company_match_status", "n_factories_matched",
        "title_raw", "region_raw", "gu", "in_scope",
        "reg_date", "reg_date_raw", "reg_date_status",
        "due_date", "due_date_raw", "due_date_status",
        "wage_raw", "wage_type", "wage_min", "wage_max", "wage_unit",
        "wage_parse_status", "career_raw", "career_type", "career_min_months",
        "career_parse_status", "education_raw", "cert_raw", "posting_status",
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


def selection_bias_report(a: pd.DataFrame) -> dict:
    """매칭군과 미매칭군이 관측 가능한 변수에서 체계적으로 다른지 본다.

    기업 마스터가 공장등록현황이므로 매칭 자체가 제조업·법인 쪽으로 기운다.
    이 편향은 고칠 수 있는 결함이 아니라 구조다. 따라서 업종·지역 간 **공고 수
    원값 비교**를 금지하는 근거로 쓴다.
    """
    m = a["company_match_status"].eq("MATCH")
    n = len(a)

    def share(col, value_filter=None):
        s = a[col]
        if value_filter is not None:
            s = s.where(s.isin(value_filter))
        t = pd.crosstab(s, m, normalize="columns").mul(100).round(1)
        return {str(k): {"unmatched_pct": float(v.get(False, 0.0)),
                         "matched_pct": float(v.get(True, 0.0))}
                for k, v in t.iterrows()}

    by_gu = a.groupby("gu").agg(postings=("gu", "size"),
                                matched=("company_match_status",
                                         lambda s: int((s == "MATCH").sum())))
    by_gu["match_rate_pct"] = (100 * by_gu["matched"] / by_gu["postings"]).round(1)
    rates = by_gu["match_rate_pct"]

    wage = a[a["wage_type"].eq("월급") & a["wage_min"].notna()]
    wage_med = wage.groupby(m.loc[wage.index])["wage_min"].median()

    has_corp = a["company_raw"].str.contains(r"주식회사|\(주\)|㈜|（주）", regex=True,
                                             na=False)
    mfg_kw = a["title_raw"].str.contains("생산|가공|용접|조립|품질|기계|설비|CNC|제조",
                                         na=False)
    return {
        "matched_n": int(m.sum()), "total_n": n,
        "match_rate_pct": _pct(int(m.sum()), n),
        "by_gu": by_gu.to_dict("index"),
        "gu_match_rate_spread_pp": round(float(rates.max() - rates.min()), 1),
        "gu_match_rate_ratio": round(float(rates.max() / rates.min()), 2)
        if rates.min() > 0 else None,
        "wage_type_share": share("wage_type"),
        "career_type_share": share("career_type"),
        "monthly_wage_median_won": {
            "unmatched": float(wage_med.get(False, float("nan"))),
            "matched": float(wage_med.get(True, float("nan"))),
        },
        "corporate_name_form_pct": {
            "unmatched": round(float(has_corp[~m].mean() * 100), 1),
            "matched": round(float(has_corp[m].mean() * 100), 1)},
        "manufacturing_keyword_title_pct": {
            "unmatched": round(float(mfg_kw[~m].mean() * 100), 1),
            "matched": round(float(mfg_kw[m].mean() * 100), 1)},
        "verdict": ("매칭군은 법인 표기·제조 직무·연봉제·고임금 쪽으로 체계적으로 치우친다. "
                    "매칭 표본은 업종 전체를 대표하지 않는다."),
        "consequences": [
            "구별 매칭률 격차가 커서 지역 간 공고 수 원값을 비교할 수 없다.",
            "업종별 매칭률이 다르므로 업종 간 공고 수 원값 비교도 할 수 없다.",
            "매칭 기반 업종별 공고 수는 하한(lower bound)으로만 읽는다.",
        ],
    }


def model_feasibility_report(a: pd.DataFrame, gate_quarter: str | None) -> dict:
    """§18 의 검증항목을 실제 데이터로 확인한다. 통과 못 하면 feature 를 만들지 않는다."""
    reg = pd.to_datetime(a["reg_date"], errors="coerce")
    due = pd.to_datetime(a["due_date"], errors="coerce")
    quarters = sorted(reg.dropna().dt.to_period("Q").astype(str).unique())
    months = reg.dropna().dt.to_period("M").value_counts().sort_index()
    duration = (due - reg).dt.days
    n_snapshots = len(_center_list_snapshots())

    mapped = a[a["kicox_mapping_status"].eq("MAPPED")]
    by_ind = mapped.groupby("kicox_industry").size()
    ind_match = (a[a["company_match_status"].eq("MATCH")]
                 .groupby("kicox_industry").size())

    checks = {
        "1_sufficient_period": {
            "pass": len(quarters) >= 8,
            "observed": f"등록일 기준 분기 {len(quarters)}개 ({', '.join(quarters)})",
            "detail": (f"등록일 범위 {reg.min().date()} ~ {reg.max().date()} "
                       f"({int((reg.max() - reg.min()).days)}일)"),
        },
        "2_quarterly_aggregation": {
            "pass": False,
            "observed": "분기 1개뿐이라 분기 시계열을 만들 수 없다.",
        },
        "3_industry_coverage_balance": {
            "pass": False,
            "observed": f"KICOX 매핑 업종 {len(by_ind)}개, 최소 {int(by_ind.min())}건 "
                        f"~ 최대 {int(by_ind.max())}건",
            "detail": "소수 업종은 한 자릿수라 분기 지표로 쓰면 분산이 지배한다.",
        },
        "4_matching_rate_distortion": {
            "pass": False,
            "observed": "업종별 매핑이 기업매칭에 전적으로 의존한다. "
                        "매칭률 차이가 업종 순위에 그대로 들어간다.",
        },
        "5_repost_domination": {
            "pass": True,
            "observed": f"재공고 후보 {int(a['repost_candidate'].sum())}건 "
                        f"({_pct(int(a['repost_candidate'].sum()), len(a))}%) — 지배적이지 않다",
        },
        "6_postings_vs_headcount": {
            "pass": False,
            "observed": "모집인원 0%. 공고 수를 인원으로 쓸 수 없다.",
        },
        "7_survivorship_bias": {
            "pass": False,
            "observed": "현재 게시 중 공고만 담긴 단면이다.",
            "evidence": {str(k): int(v) for k, v in months.items()},
            "detail": (f"게시기간 중앙값 {duration.median():.0f}일, "
                       f"{duration.eq(60).mean()*100:.1f}%가 정확히 60일. "
                       "과거 월로 갈수록 장기게시 공고만 남아 단조 감소한다."),
        },
        "8_redundancy_with_existing": {
            "pass": None,
            "observed": "빈일자리·입직(사업체노동력조사)이 이미 모형에 있다. "
                        "채용수요 축이 중복될 수 있으나 현 자료로는 검정 불가.",
        },
        "9_temporal_leakage": {
            "pass": False,
            "observed": f"수집시점 2026-09-19(2026Q3)은 모형 최종분기 "
                        f"{gate_quarter}보다 뒤다. 과거 판정에 넣으면 미래정보 유입이다.",
        },
        "10_electre_criterion_redundancy": {
            "pass": None,
            "observed": "분기 시계열이 없어 기준 추가 자체가 불가능하다.",
        },
        "11_decision_stability": {
            "pass": None,
            "observed": "단일 분기라 판정 안정성을 검정할 수 없다.",
        },
        "12_sensitivity_robustness": {
            "pass": None,
            "observed": "정의 변경에 대한 민감도를 볼 시점이 하나뿐이다.",
        },
    }
    blocking = [k for k, v in checks.items() if v["pass"] is False]
    return {
        "checks": checks,
        "blocking_checks": blocking,
        "n_blocking": len(blocking),
        "n_snapshots_available": n_snapshots,
        "registration_quarters": quarters,
        "model_quarter_overlap": [q for q in quarters if gate_quarter and q <= gate_quarter],
        "industry_posting_counts_matched_only": {k: int(v) for k, v in ind_match.items()
                                                 if pd.notna(k)},
        "verdict": "NOT_USABLE_AS_MODEL_INPUT",
        "verdict_reason": (
            "등록일이 전부 2026Q3 한 분기에 몰려 있고 그 분기조차 60일 게시창으로 "
            "잘려 있다. 모형 최종분기(2026Q2)와 겹치는 구간이 0이므로 업종×분기 "
            "변수를 만들 수 없고, 넣으면 미래정보가 과거 판정에 들어간다."),
    }


def model_role_table(feas: dict, bias: dict) -> list[dict]:
    """§29 역할표. '쓸 수 있으니 넣는다'가 아니라 검증 결과에 따라 배정한다.

    표현 주의: 현 수준은 '외적 타당성 검증'이 아니다. 2026Q2 판정 **이후 기간**의
    사후 교차확인(post-period corroboration)이며, 판정을 지지하거나 반박하는
    통계적 검정이 아니다.
    """
    D = "모형 직접입력"
    P = "모형 판정 이후 후속 Evidence"
    A = "모형 판정 이후 현장확인용"
    X = "사용불가"

    def row(item, role, reason):
        return {"item": item, "role": role,
                "model_input": role == D,
                "post_period_evidence": role == P,
                "post_model_field_check": role == A,
                "unusable": role == X, "reason": reason}

    return [
        row("Work24 파생 변수 일체의 최종모형 직접입력", X,
            "없음. 등록일이 2026Q3 한 분기뿐이고 모형기간(~2026Q2)과 겹침이 0이다"),
        row("업종×분기 정량 보조축", X,
            "성립하지 않는다. 분기 축 자체가 존재하지 않아 정량 보조축을 구성할 수 없다"),
        row("업종×분기 공고 수 / 고유 채용기업 수", X,
            "단일 분기 + 60일 롤링창 생존편향. 과거 분기 역산 불가"),
        row("모집인원 / 인원 기반 지표", X,
            "허용된 경로에 없어 0% 확보. 공고 수로 대체하지 않는다"),
        row("재공고율(reposting_rate)", X,
            "BLOCKED. NEW/CONTINUING/CLOSED 상태추적은 동일 posting ID 의 존속 여부일 "
            "뿐이고, 재공고는 '다른 posting ID 로 다시 올라온 같은 자리'다. 두 개념이 "
            "다르며 후자의 식별규칙이 아직 검증되지 않았다"),
        row("업종별·지역별 공고 수 원값의 상호 비교", X,
            f"기업매칭률이 구별 {bias['gu_match_rate_spread_pp']}%p"
            f"({bias['gu_match_rate_ratio']}배) 차이. 매칭률 차이가 순위에 직접 섞인다"),
        row("2026Q3 채용활동 '존재 여부'", P,
            "2026Q2 판정 이후 기간의 사후 교차확인으로만 제한적으로 사용. 수준 비교·"
            "순위 비교·판정 검증에는 쓰지 않는다"),
        row("기업 단위 채용 여부·공고·직무·지역", A,
            "우선점검 업종의 현장확인 대상 기업 목록으로 사용"),
        row("임금유형·임금수준·경력요건·학력요건", A,
            "확인된 공고 범위에서만. 업종 대표값으로 쓰지 않는다"),
        row("KSIC·KICOX 업종 귀속", A,
            "매칭 성공분(MATCH)에 한해서만 활용. 미매칭은 UNKNOWN 으로 남긴다"),
        row("산업단지 소재 여부", A,
            "POSSIBLE 은 MATCH 가 아니다. 해당 기업을 '산단 기업'이라고 표현하지 않는다"),
        row("향후 반복 snapshot 누적 시 채용시장 분기 보조축", X,
            "현재는 불가. 월 단위 재수집을 누적한 뒤에 재검토할 사항이며, 지금 "
            "보조축으로 예약해 두지 않는다"),
    ]


def build_quality_summary(snap, raw, df, analysis, ev, targets, gate_quarter,
                          stages) -> dict:
    meta = json.loads(snap.with_suffix(".metadata.json").read_text(encoding="utf-8"))
    n_raw, n = len(raw), len(analysis)
    bias = selection_bias_report(analysis)
    feas = model_feasibility_report(analysis, gate_quarter)
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
                "note": ("2026-09-19 레거시 목록에 모집인원이 없어 전 행 NULL이다. "
                         "2026-09-23 현행 work24 상세 5건에서 확보 가능성을 검증했지만 "
                         "이 snapshot을 소급 변경하지 않는다."),
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
            "scope": ("같은 스냅샷 안에서 동일기업·동일공고명이 중복 등장한 건수다. "
                      "스냅샷 사이의 재등장(재공고)과는 다른 개념이다."),
            "reposting_rate_status": "BLOCKED",
            "reposting_rate_reason": (
                "재공고 식별규칙(다른 posting ID·동일 기업·유사 공고명·등록일 간격)이 "
                "아직 검증되지 않았다. 상태추적(NEW/CONTINUING/CLOSED)으로 대체하지 "
                "않는다."),
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
            "level_b_blocked_reason": ("이 snapshot에는 모집인원이 없다. 현행 공개 상세 "
                                       "보강을 전체 범위에 검증·승인하기 전까지 공고 수를 "
                                       "모집인원으로 대체하지 않고 Level B를 계산하지 않는다."),
        },
        "field_inventory": field_inventory_report(analysis),
        "snapshot_transitions": snapshot_transitions(),
        "selection_bias": bias,
        "model_feasibility": feas,
        "role_assignment": model_role_table(feas, bias),
        "external_source_investigation": EXTERNAL_SOURCE_INVESTIGATION,
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
