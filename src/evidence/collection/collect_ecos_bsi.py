# -*- coding: utf-8 -*-
"""한국은행 ECOS 기업경기조사(BSI) — 지역·업종 경기심리 context.

인증
    ECOS_API_KEY (환경변수). 이전에 쓰던 공개 sample 키는 더 이상 쓰지 않는다.

수집 대상 (2026-09-19 실측으로 확인)
    512Y019  지역별 기업경기조사(실적, 2013.01~)  — 지역 21개 중 `Z22 경남` 존재.
             제조업 업황·생산·신규수주·가동률·인력사정 BSI 를 월별로 제공.
    512Y007  업종별 기업경기실사지수(실적, 2009.08~) — 전국이지만 KSIC 중분류
             수준(식료품·섬유·비금속·1차금속·기타기계장비·자동차·조선 등)으로 세분.

지역 우선순위(창원 → 경남 → 전국)에 따른 결과
    창원 단위 BSI 는 ECOS 에 없다. 경남(Z22)이 확보 가능한 가장 좁은 단위다.
    업종 세분은 전국 단위에서만 가능하다. 두 계열은 범위가 다르므로 섞지 않는다.

해석 범위
    BSI 는 Triage stage 를 바꾸지 않는다. 업종별 자동판정에도 쓰지 않는다.
    역할은 CONTEXT / BUSINESS_SENTIMENT 이며, 카드·보고서의 거시 배경으로만 쓴다.
    전국 업종 BSI 를 창원국가산단 개별 업종의 신호라고 부르지 않는다.

실행:  python src/evidence/collection/collect_ecos_bsi.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from evidence.collection import secrets as S              # noqa: E402
from evidence.collection.http_client import fetch         # noqa: E402
from evidence.collection.metadata import (                # noqa: E402
    save_raw, sha256_bytes, utcnow, write_metadata,
)

BASE = "https://ecos.bok.or.kr/api"
ENV_KEY = "ECOS_API_KEY"
SOURCE = "ecos"
START, END = "202101", "202608"
PAGE = 1000

BSI_CODES = {
    "AA": "업황BSI",
    "AC": "생산BSI",
    "AD": "신규수주BSI",
    "AK": "가동률BSI",
    "AJ": "인력사정BSI",
}
# 512Y019 지역별 — 경남만. 항목명이 '제조업…BSI' 로 이미 제조업 한정이다.
REGION_TABLE = "512Y019"
REGIONS = {"Z22": "경남"}
# 512Y007 업종별(전국) — KICOX 10업종에 대응시킬 수 있는 KSIC 중분류만.
INDUSTRY_TABLE = "512Y007"
INDUSTRY_CODES = {
    "C0000": "제조업", "C1000": "식료품", "C1100": "음료", "C1300": "섬유",
    "C1400": "의복모피", "C1600": "목재·나무", "C1700": "펄프·종이",
    "C1900": "석유정제·코크스", "C2000": "화학물질·제품", "C2200": "고무·플라스틱",
    "C2300": "비금속광물", "C2400": "1차금속", "C2500": "금속가공",
    "C2600": "전자·영상·통신장비", "C2800": "전기장비", "C2900": "기타기계·장비",
    "C3000": "자동차", "C3100": "조선·기타운수",
}
COLUMNS = ["period", "scope", "region_or_industry_code", "region_or_industry_name",
           "bsi_code", "bsi_name", "value", "stat_code", "unit"]


def _status(reason: str, **extra) -> int:
    d = ROOT / "data/raw/ecos/api/_metadata"
    d.mkdir(parents=True, exist_ok=True)
    payload = dict(status="NOT_COLLECTED", reason=reason, checked_at=utcnow(),
                   api_base=BASE, required_env=ENV_KEY)
    payload.update(extra)
    (d / "collection_status.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[skip] " + reason)
    return 0


def series(key: str, stat: str, code1: str, code2: str) -> tuple[list, dict]:
    """월별 시계열 하나. ECOS 는 페이지 범위를 경로에 넣는다.

    두 통계표 모두 분류축 순서가 (BSI코드, 지역/업종코드) 다. 반대로 주면
    INFO-200(해당 데이터 없음)이 돌아온다 — 실측 확인.
    """
    url = f"{BASE}/StatisticSearch/{key}/json/kr/1/{PAGE}/{stat}/M/{START}/{END}/{code1}/{code2}"
    r = fetch(url, verify_tls=False, retries=2, timeout=60, delay=0.7)
    check = dict(stat_code=stat, item1=code1, item2=code2,
                 http_status=r.status, error=r.error, masked_url=r.url)
    if not r.ok:
        return [], check
    try:
        payload = json.loads(r.body.decode("utf-8"))
    except Exception as e:                             # noqa: BLE001
        check["error"] = f"json: {e}"
        return [], check
    if "StatisticSearch" not in payload:
        check["error"] = payload.get("RESULT", payload)
        return [], check
    rows = payload["StatisticSearch"].get("row", [])
    total = payload["StatisticSearch"].get("list_total_count")
    check.update(list_total_count=total, returned=len(rows),
                 pagination_complete=(total is not None and int(total) == len(rows)))
    return rows, check


def main() -> int:
    S.load_env(ROOT)
    key = S.require(ENV_KEY)
    if not key:
        return _status(ENV_KEY + " 미설정 — ECOS OpenAPI 는 인증키가 필요하다.")

    rows, checks, raw = [], [], {}
    jobs = ([(REGION_TABLE, c, n, "경남(지역)") for c, n in REGIONS.items()]
            + [(INDUSTRY_TABLE, c, n, "전국(업종)") for c, n in INDUSTRY_CODES.items()])
    for stat, code1, name1, scope in jobs:
        for bsi, bsi_name in BSI_CODES.items():
            # 분류축 순서: BSI코드 먼저, 그다음 지역/업종코드
            data, check = series(key, stat, bsi, code1)
            check["scope"] = scope
            checks.append(check)
            if not data:
                continue
            raw[f"{stat}_{code1}_{bsi}"] = data
            for x in data:
                rows.append(dict(
                    period=x.get("TIME"), scope=scope,
                    region_or_industry_code=code1, region_or_industry_name=name1,
                    bsi_code=bsi, bsi_name=bsi_name, value=x.get("DATA_VALUE"),
                    stat_code=stat, unit=x.get("UNIT_NAME") or "지수(기준 100)"))

    if not rows:
        return _status("ECOS 응답 없음", checks=checks[:5])

    raw_json = json.dumps(raw, ensure_ascii=False, indent=2).encode("utf-8")
    S.assert_clean(raw_json.decode("utf-8"), "ecos raw")
    raw_path = save_raw(ROOT, SOURCE, "ecos_bsi_raw_responses.json", raw_json)

    rows.sort(key=lambda r: (r["scope"], r["region_or_industry_code"],
                             r["bsi_code"], r["period"]))
    body = (",".join(COLUMNS) + "\n" + "".join(
        ",".join('"' + str(r.get(c, "")).replace('"', '""') + '"' for c in COLUMNS) + "\n"
        for r in rows)).encode("utf-8-sig")
    S.assert_clean(body.decode("utf-8-sig"), "ecos csv")
    csv_path = save_raw(ROOT, SOURCE, "bsi_gyeongnam_and_industry_monthly.csv", body)

    periods = sorted({r["period"] for r in rows})
    incomplete = [c for c in checks if c.get("error") or not c.get("pagination_complete")]
    write_metadata(
        ROOT, SOURCE, "bsi_gyeongnam_and_industry_monthly",
        dataset_name=("한국은행 ECOS 기업경기조사 — 지역별(512Y019, 경남) 및 "
                      "업종별(512Y007, 전국) 실적 BSI"),
        institution="한국은행",
        source_url="https://ecos.bok.or.kr/api/#/DevGuide/StatisticalCodeSearch",
        api_endpoint=f"{BASE}/StatisticSearch/{{API_KEY}}/json/kr/1/{PAGE}/{{stat}}/M/{{start}}/{{end}}/{{item1}}/{{item2}}",
        retrieved_at=utcnow(),
        observation_start=periods[0], observation_end=periods[-1],
        geography=("두 범위가 섞여 있다. 512Y019=경상남도(Z22), 512Y007=전국. "
                   "창원 단위 BSI 는 ECOS 에 존재하지 않는다."),
        industry_classification=("512Y019 는 제조업 총계. 512Y007 은 KSIC 중분류"
                                 "(식료품·섬유·비금속·1차금속·기타기계장비·자동차·조선 등)"),
        frequency="월", unit="지수(기준 100)",
        original_filename="(ECOS OpenAPI JSON 응답을 CSV 로 직렬화)",
        file_hash_sha256=sha256_bytes(body),
        api_parameters=dict(stat_codes=[REGION_TABLE, INDUSTRY_TABLE],
                            cycle="M", start=START, end=END,
                            region_codes=list(REGIONS),
                            industry_codes=list(INDUSTRY_CODES),
                            bsi_codes=list(BSI_CODES),
                            auth="ECOS_API_KEY (환경변수, 기록에서 제외)"),
        pagination=dict(method="경로에 1/{PAGE} 범위를 넣어 호출하고 list_total_count 와 대조",
                        page_size=PAGE, checks=checks, incomplete_calls=len(incomplete)),
        revision_vintage="한국은행 공표 시점 기준. 과거치 개정 가능",
        terms_limitations="한국은행 ECOS OpenAPI 이용약관. 창원 단위 미제공.",
        mapping_notes=("512Y007 의 KSIC 중분류를 KICOX 10업종에 대응시키는 표는 "
                       "data/processed/final_model/reference/industry_crosswalk/ecos_bsi_to_kicox.csv 에 둔다. "
                       "전국 심리지수이므로 업종별 판정·신호 생성에 쓰지 않는다."),
        role="CONTEXT / BUSINESS_SENTIMENT",
        limitations=("경남 계열은 제조업 총계뿐이고, 업종 세분 계열은 전국이다. "
                     "창원국가산단 개별 업종의 신호로 해석하지 않는다."),
        notes=f"수집 {len(rows)}행, 호출 {len(checks)}건, 불완전 {len(incomplete)}건.",
        raw_response_file=raw_path.name,
        raw_response_sha256=sha256_bytes(raw_json),
    )
    print(f"[ok] {csv_path.relative_to(ROOT)} rows={len(rows)} "
          f"기간={periods[0]}~{periods[-1]} 호출={len(checks)} 불완전={len(incomplete)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
