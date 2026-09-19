# -*- coding: utf-8 -*-
"""한국전력 전력데이터 개방포털 — 창원시 전력사용 보조지표 수집.

상태: **VERIFIED** (명세·실호출 확인). 데이터 완전성은 dataset 별로 다르다 — 아래 참조.

명세는 어디서 왔나 (2026-09-19 확인)
    이전 실행은 "endpoint 를 알 수 없다"며 PARTIAL 로 멈춰 있었다. 그 판단의 근거였던
    공식 매뉴얼(`kepco_open_api_manual.pptx`)은 실제로 URL·파라미터를 싣지 않는다.
    이번에는 **로그인한 브라우저로 포털의 `OPEN API 소개` 화면을 직접 열어**
    (데이터공개 > OPEN API > OPEN API 소개, `cmsmain.do?scode=S01&pcode=000493`)
    각 API 가이드의 요청 URL·인자·응답 필드를 화면 그대로 옮겨 적었다.
    로그인 우회는 하지 않았다. 사용자 본인 계정의 화면을 읽었을 뿐이다.

    이전 기록의 오판 하나를 바로잡는다. `powerUsage/industryType.do` 가 돌려준
    `errCd=404` 를 "업무명이 틀렸다"로 읽었지만, 포털 상태코드표는
    **404 = 요청자료 찾을 수 없음**이다. 경로는 처음부터 맞았고 인자가 문제였다.

수집 대상 3종
    1. businessType  `powerUsage/businessType.do`
       한전 자체 업종분류(38종) × 창원 5개 구 × 월. **1순위.**
       KICOX 10업종과 대응 가능한 유일한 KEPCO 자료다.
    2. industryType  `powerUsage/industryType.do`
       KSIC 대분류 × 창원시(구 분해 없음) × 월. 제조업 총량 macro check 용.
    3. custNumChange `change/custNum/industryType.do`
       KSIC 대분류 × 창원 × 월 신설·증설·해지 KWH. 공식 화면도 각 필드를
       KWH로 표시하며 상세 산식은 설명하지 않는다. 고객·계약 '건수'가 아니다.

실측으로 확인한 제약 (2026-09-19)
    1. **인증은 query parameter `apiKey`** 다. 헤더가 아니다.
    2. **지역코드 체계가 두 벌**이다. `commonCode.do?codeTy=metroCd` 는 한전 코드
       (경남=38)를, `codeTy=lglDngMetroCd` 는 법정동 코드(경남=48)를 준다.
       전력사용량 API 들은 **법정동 코드**를 받는다(38 을 주면 404).
       창원 법정동 시군구코드: 120 창원시 / 121 의창 / 123 성산 / 125 마산합포 /
       127 마산회원 / 129 진해.
    3. `businessType.do` 는 코드가 아니라 **이름**(`metro`,`city`)을 받는다.
       `city=창원시` 로 주면 **5개 구가 모두** 돌아온다(전방일치). 그래서
       구별로 5번 부르지 않고 **월 1회 호출로 창원 전체**를 받는다.
    4. `bizType` 문자열에는 **내부 공백이 여러 칸** 들어 있다("1차   금속",
       "섬      유"). 한 칸으로 줄여 조회하면 404 다. 그래서 개별 bizType 조회를
       쓰지 않고 미지정 전체조회만 쓴다(호출 수도 이쪽이 적다).
    5. `industryType.do` 의 `cityCd` 는 **2024년부터 404** 다(2023년까지는 120 이
       동작한다). 원인은 알 수 없다. 그래서 `metroCd=48` 만 주고 경남 전체를 받아
       `city == '창원시'` 를 골라낸다. 호출 수는 같다.
    6. **pagination 이 없다.** 응답에 totalCount·페이지 인자가 없고, 문서에도 없다.
       대신 매 호출에서 돌아온 구(city) 집합을 세어 잘림 여부를 확인한다.
    7. **호출 제한이 공표돼 있지 않다.** 포털 어느 화면에도 일일·분당 한도가 없다.
       한도가 없다고 단정할 수 없으므로 호출 간격을 두고, 429 를 만나면 즉시
       멈추고 이어받는다. 수집 중 2021-07 에서 **일시적 401** 을 한 번 관측했다
       (재시도로 해소). 그래서 401 도 즉시 실패로 보지 않고 제한적으로 재시도한다.

원자료 결함 — 추정이 아니라 관측이다
    `businessType.do` 는 **2020-11 ~ 2022-01 (15개월)** 구간에서 창원 5개 구 중
    2개 구만, 8~10행만, 총 5천~4만 kWh 만 돌려준다. 정상 월은 163~166행,
    약 9억 kWh 다. 즉 자료가 **공급측에서 비어 있다.** 수집 실패가 아니다.
    이 구간을 `SOURCE_DEGENERATE` 로 기록하고 분기집계에서 제외한다.
    같은 구간에 `industryType.do` 는 정상값을 준다 — 두 자료의 결함이 다르다.

실행:  python src/evidence/collection/collect_kepco_power.py
        (이미 받은 월은 건너뛴다. 처음부터 다시 받으려면 --refresh)
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from evidence.collection import secrets as S              # noqa: E402
from evidence.collection.http_client import fetch         # noqa: E402
from evidence.collection.metadata import (                # noqa: E402
    save_raw, sha256_bytes, utcnow, write_metadata,
)

BASE = "https://bigdata.kepco.co.kr/openapi/v1"
PORTAL_GUIDE = "https://bigdata.kepco.co.kr/cmsmain.do?scode=S01&pcode=000493"
ENV_KEY = "KEPCO_API_KEY"
SOURCE = "kepco"

# 분석기간 2022Q1~2026Q2 의 YoY 기준연도까지 포함한다.
PERIOD_START, PERIOD_END = (2021, 1), (2026, 6)

LGL_METRO_GYEONGNAM = "48"          # 법정동 시도코드. 한전코드 38 이 아니다.
CHANGWON_GU = ("창원시 의창구", "창원시 성산구", "창원시 마산합포구",
               "창원시 마산회원구", "창원시 진해구")

DELAY_SEC = 1.2
MAX_401 = 5                          # 일시적 401 허용 한도. 넘으면 인증문제로 보고 중단.
BACKOFF_BASE_SEC = 4.0               # 지수 백오프 기준. 4 → 8 → 16초.
MAX_ATTEMPTS = 4                    # 최초 1회 + 재시도 3회(4 → 8 → 16초).

RAW_DIR = ROOT / "data/raw/kepco/api"
RAW_STORE = RAW_DIR / "kepco_raw_responses.json"
META_DIR = RAW_DIR / "_metadata"


def months(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[str, str]]:
    y, m = start
    out = []
    while (y, m) <= end:
        out.append((f"{y:04d}", f"{m:02d}"))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


MONTHS = months(PERIOD_START, PERIOD_END)


# ---------------------------------------------------------------- dataset 정의
def _biz_params(y: str, m: str) -> dict:
    return dict(year=y, month=m, metro="경상남도", city="창원시")


def _ind_params(y: str, m: str) -> dict:
    # cityCd 는 2024년부터 404 다. metroCd 만 주고 창원시 행을 골라낸다.
    return dict(year=y, month=m, metroCd=LGL_METRO_GYEONGNAM)


DATASETS = {
    "business_type": dict(
        path="powerUsage/businessType.do",
        params=_biz_params,
        keep=lambda r: str(r.get("city", "")).strip() in CHANGWON_GU,
        csv_name="changwon_business_type_power_monthly.csv",
        title="한국전력공사_업종별 전력사용량 (창원시 5개 구)",
        industry_field="bizType",
        value_fields=("custCnt", "powerUsage", "cntrPwr"),
        unit="전력사용량 kWh, 고객호수 호, 계약전력 kW",
        classification="한국전력 자체 업종분류(38종). KSIC 아님",
    ),
    "industry_type": dict(
        path="powerUsage/industryType.do",
        params=_ind_params,
        keep=lambda r: str(r.get("city", "")).strip() == "창원시",
        csv_name="changwon_industry_type_power_monthly.csv",
        title="한국전력공사_산업분류별 전력사용량 (창원시)",
        industry_field="biz",
        value_fields=("custCnt", "powerUsage", "bill", "unitCost"),
        unit="전력사용량 kWh, 고객호수 호, 전기요금 원, 평균단가 원/kWh",
        classification="KSIC 대분류(21종). 제조업은 C 한 칸",
    ),
    "custnum_change": dict(
        path="change/custNum/industryType.do",
        params=_ind_params,
        keep=lambda r: str(r.get("city", "")).strip().startswith("창원"),
        csv_name="changwon_custnum_change_monthly.csv",
        title="한국전력공사_산업분류별 전기사용고객 증감 (창원시)",
        industry_field="biz",
        value_fields=("new", "expansion", "cancel"),
        unit="KWH (공식 화면 표기; 상세 산식 미공표)",
        classification="KSIC 대분류(21종)",
    ),
}


class RateLimited(Exception):
    """429. 즉시 멈추고 다음 실행에서 이어받는다."""


class AuthFailed(Exception):
    """401 이 반복된다. 키 문제로 보고 멈춘다."""


# ---------------------------------------------------------------- 호출
def backoff_seconds(retry_index: int) -> float:
    """0부터 시작하는 재시도 번호에 대해 4, 8, 16…초를 반환한다."""
    return BACKOFF_BASE_SEC * (2 ** retry_index)


def should_request(previous: dict | None, *, refresh: bool = False) -> bool:
    """캐시 이어받기 규칙. 성공·NO_DATA·공급측 결함은 중복 호출하지 않는다."""
    return bool(refresh or not previous
                or previous.get("completeness") == "REQUEST_FAILED")


def call(path: str, params: dict, key: str, state: dict) -> dict:
    """호출 후 판정 결과를 반환한다. 401·통신오류·5xx는 지수 백오프한다.

    403 은 재시도하지 않는다. 접근이 거부된 요청을 같은 키로 다시 보내도 결과가
    달라지지 않고, 서버에 불필요한 부하만 준다. 다만 **원인을 단정하지 않는다** —
    인증상품 등록범위·권한·차단 중 무엇인지 공식 근거가 없으므로 횟수만 기록한다.
    """
    q = urllib.parse.urlencode(dict(params, apiKey=key, returnType="json"))
    url = f"{BASE}/{path}?{q}"
    for attempt in range(MAX_ATTEMPTS):
        # 재시도·대기 정책을 이 함수 한 곳에서 통제한다.
        r = fetch(url, verify_tls=True, retries=0, timeout=90, delay=DELAY_SEC)
        if r.status == 429:
            raise RateLimited(f"{path} {params.get('year')}-{params.get('month')}")
        if r.status == 403:
            state["n403"] = state.get("n403", 0) + 1
            break                      # 재시도하지 않는다. 원인은 단정하지 않는다.
        if r.status == 401:
            state["n401"] = state.get("n401", 0) + 1
            if state["n401"] > MAX_401 or attempt == MAX_ATTEMPTS - 1:
                raise AuthFailed(f"401 이 {state['n401']}회. 인증키를 확인한다.")
            time.sleep(backoff_seconds(attempt))
            continue
        if (r.status == 0 or 500 <= r.status < 600) and attempt < MAX_ATTEMPTS - 1:
            time.sleep(backoff_seconds(attempt))
            continue
        break
    text = r.body.decode("utf-8", "replace")
    try:
        j = json.loads(text)
    except Exception:                                  # noqa: BLE001
        return dict(http=r.status, outcome="REQUEST_FAILED",
                    error=S.mask(f"non-json ({r.error or ''}) {text[:120]}"), rows=[])
    if isinstance(j, dict) and j.get("errCd"):
        # 404 = 요청자료 없음. endpoint 오류가 아니다(포털 상태코드표).
        out = "NO_DATA" if str(j["errCd"]) == "404" else "REQUEST_FAILED"
        return dict(http=r.status, outcome=out,
                    error=f"errCd={j.get('errCd')} errMsg={j.get('errMsg')}", rows=[])
    if not r.ok:
        note = (" (403 — 인증상품 범위 또는 권한 문제 가능성. 호출 한도로 단정하지 않는다)"
                if r.status == 403 else "")
        return dict(http=r.status, outcome="REQUEST_FAILED",
                    error=S.mask((r.error or f"HTTP {r.status}") + note), rows=[])
    rows = j.get("data") or j.get("totData") or []
    if not isinstance(rows, list):
        rows = [rows]
    return dict(http=r.status, outcome="OK", error=None, rows=rows)


def classify(name: str, rows: list, outcome: str) -> str:
    """월 단위 완전성 판정. '자료 없음'과 '수집 실패'를 절대 섞지 않는다."""
    if outcome in ("REQUEST_FAILED", "NO_DATA"):
        return outcome
    if not rows:
        return "NO_DATA"
    if name == "business_type":
        # 정상월은 창원 5개 구가 모두 온다. 2020-11~2022-01 은 2개 구뿐이다.
        cities = {str(r.get("city", "")).strip() for r in rows}
        if len(cities & set(CHANGWON_GU)) < len(CHANGWON_GU):
            return "SOURCE_DEGENERATE"
    return "COMPLETE"


# ---------------------------------------------------------------- 저장
def load_store() -> dict:
    if RAW_STORE.exists():
        return json.loads(RAW_STORE.read_text(encoding="utf-8"))
    return {}


def save_store(store: dict) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    body = json.dumps(store, ensure_ascii=False, indent=1)
    S.assert_clean(body, "kepco raw store")
    RAW_STORE.write_text(body, encoding="utf-8")


def to_csv(name: str, spec: dict, store: dict) -> bytes:
    """월별 응답을 하나의 CSV 로 직렬화한다. 결측월은 행을 만들지 않는다."""
    ind = spec["industry_field"]
    vals = spec["value_fields"]
    cols = ["ym", "year", "month", "metro", "city", "industry_raw", "industry"] + list(vals)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    n = 0
    for ym in sorted(store.get(name, {})):
        rec = store[name][ym]
        if rec.get("completeness") == "REQUEST_FAILED":
            continue
        for r in rec.get("rows", []):
            raw = str(r.get(ind, ""))
            w.writerow([ym, r.get("year"), r.get("month"), r.get("metro"), r.get("city"),
                        raw, " ".join(raw.split())] + [r.get(v) for v in vals])
            n += 1
    body = buf.getvalue().encode("utf-8-sig")
    S.assert_clean(body.decode("utf-8-sig"), f"kepco {name} csv")
    return body


# ---------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="이미 받은 월도 다시 받는다")
    ap.add_argument("--only", choices=sorted(DATASETS), help="한 dataset 만 수집")
    args = ap.parse_args(argv)

    S.load_env(ROOT)
    key = S.require(ENV_KEY)
    if not key:
        print(f"[skip] {ENV_KEY} 미설정.")
        return 1

    store = {} if args.refresh else load_store()
    failures: list[dict] = []
    state: dict = {}
    n_calls = 0
    stopped: str | None = None

    targets = [args.only] if args.only else list(DATASETS)
    try:
        for name in targets:
            spec = DATASETS[name]
            store.setdefault(name, {})
            for y, m in MONTHS:
                ym = f"{y}-{m}"
                prev = store[name].get(ym)
                # 이미 판정한 월은 건너뛰어 중복 요청을 막는다(이어받기).
                if not should_request(prev, refresh=args.refresh):
                    continue
                res = call(spec["path"], spec["params"](y, m), key, state)
                n_calls += 1
                rows = [r for r in res["rows"] if spec["keep"](r)]
                comp = classify(name, rows, res["outcome"])
                store[name][ym] = dict(
                    http=res["http"], completeness=comp, n_rows=len(rows),
                    n_rows_response=len(res["rows"]), error=res["error"],
                    retrieved_at=utcnow(), rows=rows,
                )
                if comp == "REQUEST_FAILED":
                    failures.append(dict(dataset=name, ym=ym, http=res["http"],
                                         error=res["error"]))
                print(f"  {name:15s} {ym} HTTP{res['http']:3d} n={len(rows):4d} {comp}")
    except RateLimited as e:
        stopped = f"429 호출제한 — {e}. 이미 받은 분까지 저장하고 멈춘다."
        print("[stop] " + stopped)
    except AuthFailed as e:
        stopped = f"401 인증실패 — {e}"
        print("[stop] " + stopped)
    except KeyboardInterrupt:
        stopped = "사용자 중단"
        print("[stop] " + stopped)

    save_store(store)

    # ------------------------------------------------ CSV + metadata
    summary = {}
    for name in targets:
        spec = DATASETS[name]
        body = to_csv(name, spec, store)
        p = save_raw(ROOT, SOURCE, spec["csv_name"], body)
        months_by = {}
        for ym, rec in store.get(name, {}).items():
            months_by.setdefault(rec["completeness"], []).append(ym)
        n_rows = sum(len(r.get("rows", [])) for r in store.get(name, {}).values()
                     if r.get("completeness") != "REQUEST_FAILED")
        covered = sorted(months_by.get("COMPLETE", []))
        summary[name] = dict(
            rows=n_rows, months_total=len(MONTHS),
            months_complete=len(covered),
            months_source_degenerate=sorted(months_by.get("SOURCE_DEGENERATE", [])),
            months_no_data=sorted(months_by.get("NO_DATA", [])),
            months_request_failed=sorted(months_by.get("REQUEST_FAILED", [])),
            first_complete=covered[0] if covered else None,
            last_complete=covered[-1] if covered else None,
        )
        write_metadata(
            ROOT, SOURCE, spec["csv_name"].replace(".csv", ""),
            dataset_name=spec["title"], institution="한국전력공사",
            source_url=PORTAL_GUIDE, api_endpoint=f"{BASE}/{spec['path']}",
            retrieved_at=utcnow(),
            observation_start=f"{MONTHS[0][0]}-{MONTHS[0][1]}",
            observation_end=f"{MONTHS[-1][0]}-{MONTHS[-1][1]}",
            geography=("경상남도 창원시 5개 구(의창·성산·마산합포·마산회원·진해). "
                       "창원국가산단 경계와 다르다"
                       if name == "business_type" else
                       "경상남도 창원시(구 분해 없음). 창원국가산단 경계와 다르다"),
            industry_classification=spec["classification"],
            frequency="월", unit=spec["unit"],
            original_filename="(API JSON 응답을 CSV 로 직렬화)",
            file_hash_sha256=sha256_bytes(body),
            api_parameters=dict(S.mask_params(spec["params"]("YYYY", "MM")),
                                returnType="json",
                                note="apiKey 는 query parameter. 값은 기록하지 않는다"),
            pagination=("없음. 응답에 totalCount·페이지 인자가 없고 문서에도 없다. "
                        "대신 월별 반환 구(city) 집합으로 잘림을 확인한다"),
            mapping_notes=("창원시 전력을 창원국가산단 10업종에 복제하지 않는다. "
                           "KEPCO 업종↔KICOX 대응은 공식 crosswalk 가 아니다 — "
                           "data/processed/final_model/reference/industry_crosswalk/kepco_biztype_to_kicox.csv"),
            role="CONTEXT / ACTIVITY (보조·강건성)",
            revision_vintage="한전 공표 시점 기준",
            terms_limitations="전력데이터개방포털 이용약관. 산단 경계 단위 미제공",
            limitations=("공간단위가 행정구까지다. 전력사용량은 조업강도의 proxy 일 뿐 "
                         "생산량이 아니다. 전력집약도·설비교체·자가발전·계절성에 좌우된다"),
            notes=json.dumps(summary[name], ensure_ascii=False),
            completeness_by_month={ym: rec["completeness"]
                                   for ym, rec in sorted(store.get(name, {}).items())},
        )
        print(f"[ok] {p.relative_to(ROOT)} rows={n_rows} "
              f"complete={summary[name]['months_complete']}/{len(MONTHS)}")

    # ------------------------------------------------ 수집 상태
    # 두 가지를 따로 적는다. 명세·호출이 확인됐는지(spec)와, 분석기간이 다 찼는지
    # (dataset 별 완전성). 전자가 참이어도 후자가 거짓이면 전체는 PARTIAL 이다.
    no_failure = all(not summary[n]["months_request_failed"] for n in targets)
    spec_status = "VERIFIED" if (no_failure and not stopped) else "PARTIAL"
    per_dataset = {
        n: ("USABLE" if summary[n]["months_complete"] == len(MONTHS)
            else "PARTIAL" if summary[n]["months_complete"] else "NOT_AVAILABLE")
        for n in targets
    }
    status = spec_status if all(v == "USABLE" for v in per_dataset.values()) else "PARTIAL"
    META_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(
        status=status, spec_verification=spec_status, dataset_status=per_dataset,
        checked_at=utcnow(), required_env=ENV_KEY,
        key_present=True, portal_base=BASE, portal_guide=PORTAL_GUIDE,
        spec_source=("로그인한 브라우저로 포털 'OPEN API 소개' 화면을 직접 열어 확인 "
                     "(2026-09-19). 로그인 우회 없음"),
        endpoints={n: f"{BASE}/{DATASETS[n]['path']}" for n in DATASETS},
        n_calls_this_run=n_calls, stopped_reason=stopped,
        request_failures=failures[:50], summary=summary,
        known_source_defect=("businessType.do 는 2020-11~2022-01 에 창원 5개 구 중 "
                             "2개 구만 반환한다(8~10행, 5천~4만 kWh). 정상월은 163~166행, "
                             "약 9억 kWh. 공급측 결함이며 수집 실패가 아니다"),
        rate_limit=("공표되지 않음. 429 미관측. 일시적 401 1회 관측(재시도로 해소). "
                    "재시도는 4·8·16초 지수 백오프, 최대 4회"),
        http_403=dict(
            n_observed=state.get("n403", 0),
            handling="재시도하지 않고 REQUEST_FAILED 로 기록한다",
            cause=("미확정. 인증상품 등록범위 또는 권한 문제 가능성이 있으나 "
                   "공식 근거를 확보하지 못했다. 호출 한도로 단정하지 않는다")),
        role="CONTEXT / ACTIVITY (보조·강건성). Triage 판정변수 아님",
    )
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    S.assert_clean(body, "kepco collection_status")
    (META_DIR / "collection_status.json").write_text(body, encoding="utf-8")
    (META_DIR / "request_failures.json").write_text(
        json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[status] {status}  calls={n_calls}  failures={len(failures)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
