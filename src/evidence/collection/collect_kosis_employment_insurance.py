# -*- coding: utf-8 -*-
"""KOSIS 고용 flow 수집 — 창원시 입직·이직·빈일자리·종사자.

무엇을 받았고 무엇을 못 받았나 (2026-09-19 실측)
    받은 것 : 고용노동부 『사업체노동력조사(지역편)』
              `행정구역(시군구)/산업별 고용` — 창원시 × 산업대분류 × 반기
              항목: 전체종사자, 입직자, 이직자, 빈일자리(+비율)
              DT_118N_MONA49 (2018상~2023하) + DT_118N_MONA59 (2024상~)
    못 받은 것 : 고용보험 DB 기반 『시군구 × 산업중분류 × 월 피보험자/취득/상실』.
              KOSIS 검색(고용보험·피보험자·자격취득·사업장)에서 고용노동부(118)
              통계표 17종을 확인했으나 해당 표가 없다. 경상남도 창원시(791)의
              지역통계 4종(산업별 피보험자수, 자격 취득·상실자수 등)은 통계표는
              존재하나 OpenAPI 조회 시 err=30(데이터 없음)이 반환된다.

해석 범위 — 반드시 지킬 것
    - 모집단이 다르다. 창원시 전역 사업체 표본조사이고 창원국가산단이 아니다.
    - 산업 분해가 `광업.제조업(BC)` 한 덩어리다. KICOX 10업종으로 나눌 수 없다.
      업종별 신호를 만들지 않는다(매핑등급 D).
    - 표본조사라 RSE(상대표준오차)가 함께 공표된다. 함께 저장한다.
    - 입직-이직 = KICOX 고용 증감이라고 가정하지 않는다. 개념·모집단이 다르다.
    - 역할은 FLOW_INTERPRETATION. 판정 입력이 아니다.

실행:  python src/evidence/collection/collect_kosis_employment_insurance.py
"""
from __future__ import annotations

import json
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from evidence.collection import secrets as S              # noqa: E402
from evidence.collection.http_client import fetch         # noqa: E402
from evidence.collection.metadata import (                # noqa: E402
    save_raw, sha256_bytes, utcnow, write_metadata,
)

DATA_ENDPOINT = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
SEARCH_ENDPOINT = "https://kosis.kr/openapi/statisticsSearch.do"
META_ENDPOINT = "https://kosis.kr/openapi/statisticsData.do"
ENV_KEY = "KOSIS_API_KEY"
SOURCE = "employment_insurance"

ORG_ID = "118"                                  # 고용노동부
# 기간은 반기 코드(YYYY0S)로 준다. 연도만 주면 KOSIS 가 마지막 반기를 잘라낸다
# (endPrdDe='2023' → 202202 까지만 반환되는 것을 실측 확인).
TABLES = [
    ("DT_118N_MONA49", "201801", "202302"),     # 구 계열
    ("DT_118N_MONA59", "202401", "202602"),     # 현 계열
]
PRD_SE = "S"                                    # 반기
REGIONS = {
    "ZONE2017A383811": "경상남도 창원시",
}
INDUSTRIES = {
    "IND201700": "전산업",
    "IND201701": "광업.제조업(BC)",
}
ITEMS = {
    "16118z1": "전체종사자",
    "16118z3": "빈일자리",
    "16118z4": "빈일자리(RSE)",
    "16118z5": "빈일자리율",
    "16118z7": "입직자",
    "16118z9": "입직률",
    "16118z11": "이직자",
    "16118z12": "이직자(RSE)",
    "16118z13": "이직률",
}
COLUMNS = ["table_id", "period", "region_code", "region_name", "industry_code",
           "industry_name", "item_id", "item_name", "value", "unit",
           "last_changed", "period_type"]


def _status(reason: str, **extra) -> int:
    d = ROOT / "data/raw/employment_insurance/_metadata"
    d.mkdir(parents=True, exist_ok=True)
    payload = dict(status="NOT_COLLECTED", reason=reason, checked_at=utcnow(),
                   data_endpoint=DATA_ENDPOINT, required_env=ENV_KEY)
    payload.update(extra)
    (d / "collection_status.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[skip] " + reason)
    return 0


def query(key: str, tbl: str, start: str, end: str, region: str) -> tuple[list, dict, str]:
    """한 통계표 × 한 지역을 조회한다. (rows, 기록용 파라미터, 마스킹된 URL)

    objL1='ALL' 로 전국 시군구를 한 번에 받으면 KOSIS 가 err=31
    (40,000셀 초과)을 반환한다. 지역을 지정해 셀 수를 줄인다.
    """
    params = dict(method="getList", apiKey=key, format="json", jsonVD="Y",
                  orgId=ORG_ID, tblId=tbl, itmId="ALL", objL1=region, objL2="ALL",
                  prdSe=PRD_SE, startPrdDe=start, endPrdDe=end)
    url = DATA_ENDPOINT + "?" + urllib.parse.urlencode(params)
    r = fetch(url, verify_tls=False, retries=2, timeout=90, delay=1.0)
    if not r.ok:
        return [], S.mask_params(params), r.url
    try:
        payload = json.loads(r.body.decode("utf-8"))
    except Exception:                                  # noqa: BLE001
        return [], S.mask_params(params), r.url
    if isinstance(payload, dict):                      # {"err": ...}
        return [], S.mask_params(params), r.url
    return payload, S.mask_params(params), r.url


def _collect(payload: list, rows: list) -> None:
    """관심 지역·산업·항목만 추려 담는다. 결측을 만들어 채우지 않는다."""
    for x in payload:
        if x.get("C1") not in REGIONS or x.get("C2") not in INDUSTRIES:
            continue
        if x.get("ITM_ID") not in ITEMS:
            continue
        rows.append(dict(
            table_id=x.get("TBL_ID"), period=x.get("PRD_DE"),
            region_code=x.get("C1"), region_name=x.get("C1_NM"),
            industry_code=x.get("C2"), industry_name=x.get("C2_NM"),
            item_id=x.get("ITM_ID"), item_name=x.get("ITM_NM"),
            value=x.get("DT"), unit=x.get("UNIT_NM"),
            last_changed=x.get("LST_CHN_DE"), period_type=x.get("PRD_SE")))


def main() -> int:
    S.load_env(ROOT)
    key = S.require(ENV_KEY)
    if not key:
        return _status(ENV_KEY + " 미설정 — KOSIS OpenAPI 는 인증키 없이 조회 불가.")

    rows, raw_payloads, errors, requests_log = [], {}, [], []
    for tbl, start, end in TABLES:
        for region in REGIONS:
            payload, safe_params, safe_url = query(key, tbl, start, end, region)
            requests_log.append(dict(table_id=tbl, region_code=region,
                                     endpoint=DATA_ENDPOINT,
                                     parameters_without_key=safe_params,
                                     returned_rows=len(payload)))
            if not payload:
                errors.append(dict(table_id=tbl, region_code=region,
                                   reason="응답 없음 또는 err 반환",
                                   masked_url=safe_url))
                continue
            raw_payloads[f"{tbl}:{region}"] = payload
            _collect(payload, rows)

    if not rows:
        return _status("창원시 해당 행이 없다.", errors=errors[:5])

    # 원본 응답(그대로) 저장 — 인증정보는 응답 본문에 포함되지 않는다.
    raw_json = json.dumps(raw_payloads, ensure_ascii=False, indent=2).encode("utf-8")
    S.assert_clean(raw_json.decode("utf-8"), "kosis raw payload")
    raw_path = save_raw(ROOT, SOURCE, "kosis_118_regional_labor_force_raw.json", raw_json)

    rows.sort(key=lambda r: (r["period"], r["industry_code"], r["item_id"]))
    body = (",".join(COLUMNS) + "\n" + "".join(
        ",".join('"' + str(r.get(c, "")).replace('"', '""') + '"' for c in COLUMNS) + "\n"
        for r in rows)).encode("utf-8-sig")
    S.assert_clean(body.decode("utf-8-sig"), "kosis csv")
    csv_path = save_raw(ROOT, SOURCE, "changwon_labor_force_flow_halfyear.csv", body)

    periods = sorted({r["period"] for r in rows})
    write_metadata(
        ROOT, SOURCE, "changwon_labor_force_flow_halfyear",
        dataset_name="고용노동부 사업체노동력조사(지역편) — 행정구역(시군구)/산업별 고용",
        institution="고용노동부 (KOSIS 수록)",
        source_url="https://kosis.kr/statHtml/statHtml.do?orgId=118&tblId=DT_118N_MONA59",
        api_endpoint=DATA_ENDPOINT, retrieved_at=utcnow(),
        observation_start=periods[0], observation_end=periods[-1],
        geography="경상남도 창원시(시군구). 창원국가산단이 아니다",
        industry_classification=("산업 대분류 5구분. 제조업은 '광업.제조업(BC)' 한 덩어리로 "
                                 "KICOX 10업종 분해 불가(매핑등급 D)"),
        frequency="반기", unit="명, %",
        original_filename="(KOSIS OpenAPI JSON 응답을 CSV 로 직렬화)",
        file_hash_sha256=sha256_bytes(body),
        api_parameters=dict(org_id=ORG_ID, tables=[t[0] for t in TABLES],
                            prd_se=PRD_SE, region_codes=list(REGIONS),
                            industry_codes=list(INDUSTRIES), item_ids=list(ITEMS),
                            requests=requests_log,
                            auth="KOSIS_API_KEY (환경변수, 기록에서 제외)"),
        pagination=("KOSIS 이 통계표는 페이지 분할 없이 기간범위로 일괄 반환한다. "
                    "startPrdDe/endPrdDe 로 전 구간을 덮었고 반환행수를 requests 에 기록했다."),
        revision_vintage="LST_CHN_DE 열에 통계표 최종변경일 보존. 과거치 개정 가능",
        terms_limitations=("KOSIS 이용약관. 표본조사이므로 RSE 동반. 시군구 단위이며 "
                           "산업단지 내부만 분리할 수 없다."),
        mapping_notes=("KICOX 10업종 매핑 불가(매핑등급 D). 제조업 총계 수준에서만 "
                       "방향 비교에 쓴다. 입직-이직을 KICOX 고용 증감과 같다고 보지 않는다."),
        role="FLOW_INTERPRETATION",
        limitations=("반기 빈도. 2018상~2025하. 업종별 분해 없음. "
                     "고용보험 DB 기반 피보험자/취득/상실 표는 KOSIS 에서 확인되지 않음."),
        notes=f"수집 {len(rows)}행 / 원본 응답 {raw_path.name}. 실패 {len(errors)}건.",
        collection_errors=errors,
        raw_response_file=raw_path.name,
        raw_response_sha256=sha256_bytes(raw_json),
    )
    print(f"[ok] {csv_path.relative_to(ROOT)} rows={len(rows)} "
          f"기간={periods[0]}~{periods[-1]} 실패={len(errors)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
