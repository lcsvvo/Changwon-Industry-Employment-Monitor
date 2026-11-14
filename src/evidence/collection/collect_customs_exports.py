# -*- coding: utf-8 -*-
"""관세청 시군구별 품목별 수출입실적 — 창원시 외부수요 context.

공공데이터포털 OpenAPI 15134343
    endpoint : https://apis.data.go.kr/1220000/sigunguperprlstperacrs/getSigunguPerPrlstPerAcrs
    파라미터 : serviceKey, strtYymm, endYymm, HsSgn(HS 6단위, 필수), sidoCd(시도코드)

실측으로 확인한 제약 (2026-09-19)
    1. serviceKey 는 포털이 준 Encoding 형태를 **그대로** 붙여야 한다.
       urlencode 로 다시 인코딩하면 SERVICE_KEY_IS_NOT_REGISTERED_ERROR(403) 다.
    2. HsSgn 은 6자리 필수다. 2·4자리를 주면
       "품목코드는 6자리로 입력해야 합니다" 가 돌아온다 → 류/호 단위 집계 불가.
    3. 조회기간은 1년 이내만 허용된다
       ("시작과 종료의 조회기간은 1년이내 기간만 가능합니다"). 연 단위로 잘라 호출한다.
    3-1. **호출량 한도가 있다.** 2026-09-19 수집에서 6,393회째 부근(4,904번째 호출)부터
       HTTP 429 가 반환됐다. 포털 OpenAPI 는 일일 호출한도를 두므로 한 번에 전 구간을
       받지 못할 수 있다. 그래서 이 수집기는 (a) 429 를 만나면 즉시 중단하고
       (b) 다음 실행에서 이미 받은 HS6×연도창을 건너뛴다(이어받기).
    4. 응답에 totalCount 가 있고 items 수와 같다. 페이지 분할이 없다
       (numOfRows/pageNo 를 붙여도 동일 결과). 그래도 매 호출에서 대조한다.
    5. 같은 인증키로 `시도별 품목별`(15101641), `품목별`(15101609),
       `HS부호`(15049722) 는 403 이다. 포털 OpenAPI 는 API 별로 활용신청이 필요하며
       이 키는 15134343 에만 등록되어 있다.

그래서 무엇을 수집하는가 (2026-09-19 개정)
    HS6 목록은 더 이상 추정하지 않는다. 관세청이 공표한 HS부호 원본에서
    유효 HS6 모집단을 만들고(`src/evidence/build_hs6_universe.py`),
    KICOX 업종에 귀속할 공식 근거가 있는 류(72·73·84·85·87·89) 1,248개를 대상으로 한다.

    2단계로 호출한다.
      1) 탐색  : 대상 HS6 전체 × 최근 1년 → 창원시 행이 돌아오는 코드를 가려낸다.
      2) 본수집: 가려낸 코드 × 연도별 창(2021~2026) 전체.

    그래도 '창원 수출 총액' 은 아니다. 근거 없는 류(비철 74~81, 광학·의료 90 등)를
    의도적으로 제외했기 때문이다. coverage_flag 로 계속 표시한다.

실행:  python src/evidence/collection/collect_customs_exports.py
"""
from __future__ import annotations

import csv
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from evidence.collection import secrets as S              # noqa: E402
from evidence.collection.http_client import fetch         # noqa: E402
from evidence.collection.metadata import (                # noqa: E402
    save_raw, sha256_bytes, utcnow, write_metadata,
)

ENDPOINT = ("https://apis.data.go.kr/1220000/sigunguperprlstperacrs/"
            "getSigunguPerPrlstPerAcrs")
ENV_KEY = "DATA_GO_KR_SERVICE_KEY"
SOURCE = "customs_trade"
SIDO_GYEONGNAM = "48"
TARGET = "창원"
START, END = "202101", "202606"
# 1년 이내 제약 때문에 연 단위 창으로 나눈다.
WINDOWS = [("202101", "202112"), ("202201", "202212"), ("202301", "202312"),
           ("202401", "202412"), ("202501", "202512"), ("202601", "202606")]

UNIVERSE = ROOT / "data/processed/final_model/reference/industry_crosswalk/hs6_universe_customs.csv"
DISCOVERY_WINDOW = ("202501", "202512")     # 탐색에 쓰는 최근 1년
COVERAGE = ROOT / "data/raw/customs/trade/_metadata/coverage_manifest.json"
# 호출별 검증기록은 실행마다 덮어쓰지 않고 쌓는다. 이어받기로 여러 번 나눠 받으면
# 마지막 실행의 기록만 남아 이전 실행의 페이지 검증 이력이 사라지기 때문이다.
CHECKLOG = ROOT / "data/raw/customs/trade/_metadata/pagination_checks.json"
COLUMNS = ["period", "sigungu", "hs6", "hs_chapter", "chapter_name_ko", "item_name_ko",
           "export_usd", "import_usd", "export_count", "import_count",
           "trade_balance", "mapped_kicox_industry", "mapping_grade",
           "mapping_rationale", "coverage_flag"]


def _status(reason: str, **extra) -> int:
    d = ROOT / "data/raw/customs/trade/_metadata"
    d.mkdir(parents=True, exist_ok=True)
    payload = dict(status="NOT_COLLECTED", reason=reason, checked_at=utcnow(),
                   endpoint=ENDPOINT, required_env=ENV_KEY)
    payload.update(extra)
    (d / "collection_status.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[skip] " + reason)
    return 0


def _num(text: str | None) -> str:
    return (text or "").strip().replace(",", "")


def fetch_hs6(key: str, hs6: str, start: str, end: str) -> tuple[list[ET.Element], dict, bytes]:
    """한 HS6 × 한 연도창을 받는다. (items, 검증정보, 원본 바이트)"""
    # serviceKey 는 재인코딩하지 않는다 (위 제약 1).
    url = (f"{ENDPOINT}?serviceKey={key}&strtYymm={start}&endYymm={end}"
           f"&HsSgn={hs6}&sidoCd={SIDO_GYEONGNAM}")
    r = fetch(url, retries=2, timeout=120, delay=1.0)
    check = dict(hs6=hs6, window=[start, end], http_status=r.status, error=r.error,
                 # 429 일 때 서버가 재시도 시점을 알려주면 그대로 보존한다.
                 # 이 API 는 2026-09-19 실측에서 이 헤더를 주지 않았다.
                 retry_after=r.headers.get("Retry-After"))
    if not r.ok:
        return [], check, r.body
    try:
        root = ET.fromstring(r.body)
    except ET.ParseError as e:
        check["error"] = f"xml parse: {e}"
        return [], check, r.body
    items = root.findall(".//item")
    total = root.findtext(".//totalCount")
    check.update(result_msg=root.findtext(".//resultMsg"),
                 total_count=total, returned_items=len(items),
                 pagination_complete=(total is not None
                                      and str(total).strip() == str(len(items))))
    return items, check, r.body


def load_coverage() -> dict:
    """이미 성공한 HS6×연도창 기록. 이어받기의 기준이 된다."""
    if not COVERAGE.exists():
        return {"completed": {}, "runs": []}
    return json.loads(COVERAGE.read_text(encoding="utf-8"))


def append_checks(new_checks: list, rate_limited: bool) -> dict:
    """호출별 검증기록을 누적 저장하고 누적 요약을 돌려준다."""
    hist = {"runs": []}
    if CHECKLOG.exists():
        try:
            hist = json.loads(CHECKLOG.read_text(encoding="utf-8"))
        except Exception:                                # noqa: BLE001
            hist = {"runs": []}
    answered = [c for c in new_checks if c.get("http_status") == 200]
    hist["runs"].append(dict(
        run_at=utcnow(), calls=len(new_checks), answered=len(answered),
        pagination_mismatch=sum(1 for c in answered
                                if not c.get("pagination_complete")),
        rate_limited_calls=sum(1 for c in new_checks
                               if c.get("http_status") == 429),
        rate_limited=rate_limited, checks=new_checks))
    runs = hist["runs"]
    hist["cumulative"] = dict(
        runs=len(runs), calls=sum(r["calls"] for r in runs),
        answered=sum(r["answered"] for r in runs),
        pagination_mismatch=sum(r["pagination_mismatch"] for r in runs),
        rate_limited_calls=sum(r["rate_limited_calls"] for r in runs))
    CHECKLOG.parent.mkdir(parents=True, exist_ok=True)
    CHECKLOG.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")
    return hist["cumulative"]


def save_coverage(cov: dict) -> None:
    COVERAGE.parent.mkdir(parents=True, exist_ok=True)
    COVERAGE.write_text(json.dumps(cov, ensure_ascii=False, indent=2), encoding="utf-8")


def load_existing_rows() -> list[dict]:
    """이전 실행에서 받아 둔 행. 이어받기 시 합쳐서 다시 쓴다."""
    p = ROOT / "data/raw/customs/trade/changwon_hs6_trade_monthly.csv"
    if not p.exists():
        return []
    with p.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_universe() -> list[dict]:
    """관세청 원본에서 만든 유효 HS6 모집단. 없으면 수집하지 않는다."""
    if not UNIVERSE.exists():
        return []
    with UNIVERSE.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _harvest(items, meta: dict, rows: list) -> None:
    """창원시 행만 추린다. 다른 시군구는 저장하지 않는다."""
    for it in items:
        sgg = (it.findtext("sggNm") or "").strip()
        if TARGET not in sgg:
            continue
        rows.append(dict(
            period=(it.findtext("priodTitle") or "").strip(),
            sigungu=sgg, hs6=meta["hs6"], hs_chapter=meta["hs_chapter"],
            chapter_name_ko=meta.get("chapter_name_ko", ""),
            item_name_ko=(it.findtext("korePrlstNm") or "").strip(),
            export_usd=_num(it.findtext("expUsdAmt")),
            import_usd=_num(it.findtext("impUsdAmt")),
            export_count=_num(it.findtext("expCnt")),
            import_count=_num(it.findtext("impCnt")),
            trade_balance=_num(it.findtext("cmtrBlncAmt")),
            mapped_kicox_industry=meta["target_kicox_industry"],
            mapping_grade=meta["mapping_confidence"],
            mapping_rationale=meta["rationale"],
            coverage_flag="mapped_chapters_only"))


def collect(limit: int | None = None, quiet: bool = False) -> dict:
    """남은 조합만 이어받는다.

    limit 를 주면 그만큼만 새로 호출하고 멈춘다(=probe 용도). probe 로 받은 응답도
    일반 수집과 똑같이 저장되므로 호출을 버리지 않는다.

    반환: dict(status, rate_limited, new_calls, remaining, rows, ...)
    """
    def say(*a):
        if not quiet:
            print(*a)

    S.load_env(ROOT)
    key = S.require(ENV_KEY)
    if not key:
        _status(ENV_KEY + " 미설정 — API 인증키 없이 조회할 수 없다.")
        return dict(status="NO_KEY", rate_limited=False, new_calls=0,
                    remaining=None, rows=0)

    universe = load_universe()
    if not universe:
        _status("HS6 모집단 파일이 없다 — src/evidence/build_hs6_universe.py 먼저 실행",
                universe_path=str(UNIVERSE.relative_to(ROOT)))
        return dict(status="NO_UNIVERSE", rate_limited=False, new_calls=0,
                    remaining=None, rows=0)

    cov = load_coverage()
    done: dict[str, set] = {k: set(map(tuple, v)) for k, v in cov["completed"].items()}
    rows = [dict(r) for r in load_existing_rows()]
    checks, raw_parts, incomplete = [], {}, []
    rate_limited = False
    new_calls = 0

    def _call(meta: dict, start: str, end: str, phase: str) -> bool:
        """한 번 호출. 429 를 만나면 False 를 돌려 전체 중단 신호로 쓴다."""
        nonlocal rate_limited, new_calls
        if (start, end) in done.get(meta["hs6"], set()):
            return True                                  # 이미 받은 조합은 건너뛴다
        if limit is not None and new_calls >= limit:
            return False                                 # probe 한도 도달 — 정상 중단
        new_calls += 1
        items, check, raw = fetch_hs6(key, meta["hs6"], start, end)
        check["phase"] = phase
        checks.append(check)
        if check.get("http_status") == 429:
            rate_limited = True
            incomplete.append(check)
            return False                                 # 호출한도 — 즉시 중단
        if check.get("error") or not check.get("pagination_complete", False):
            incomplete.append(check)
            return True
        raw_parts[f'{meta["hs6"]}_{start}_{end}'] = raw.decode("utf-8", "replace")
        _harvest(items, meta, rows)
        done.setdefault(meta["hs6"], set()).add((start, end))
        return True

    # 1단계 — 탐색. 최근 1년으로 창원시 거래가 있는 HS6 를 가려낸다.
    pending_discovery = [m for m in universe
                         if DISCOVERY_WINDOW not in done.get(m["hs6"], set())]
    say(f"[1/2] 탐색: 남은 HS6 {len(pending_discovery):,}개 / 전체 {len(universe):,}개")
    for i, meta in enumerate(pending_discovery, 1):
        if not _call(meta, *DISCOVERY_WINDOW, "discovery"):
            break
        if i % 100 == 0:
            say(f"      {i:,}/{len(pending_discovery):,} 탐색")

    # 창원 거래가 확인된 HS6 = 탐색창이 성공했고 실제 행이 남은 코드
    hs_with_rows = {r["hs6"] for r in rows}
    found = [m for m in universe if m["hs6"] in hs_with_rows]

    # 2단계 — 본수집. 탐색에서 걸린 코드만 나머지 연도창으로 채운다.
    rest = [w for w in WINDOWS if w != DISCOVERY_WINDOW]
    # found = 창원시 행이 있는 코드. 거래가 없던 코드는 더 부르지 않는다.
    todo = [(m, w) for m in found for w in rest if w not in done.get(m["hs6"], set())]
    say(f"[2/2] 본수집: 남은 조합 {len(todo):,}개 "
        f"({len(found):,}개 HS6 × {len(rest)}개 창 기준)")
    if not rate_limited:
        for j, (meta, (start, end)) in enumerate(todo, 1):
            if not _call(meta, start, end, "backfill"):
                break
            if j % 200 == 0:
                say(f"      {j:,}/{len(todo):,} 본수집 · 누적 {len(rows):,}행")

    if rate_limited:
        say("      [중단] HTTP 429 — 포털 호출한도에 도달했다. "
            "받은 만큼만 저장하고 종료한다. 다음 실행에서 이어받는다.")

    if not rows:
        _status("창원시 행이 없다.", checks=checks[:5])
        return dict(status="NO_ROWS", rate_limited=rate_limited,
                    new_calls=new_calls, remaining=None, rows=0)

    raw_json = json.dumps(raw_parts, ensure_ascii=False, indent=2).encode("utf-8")
    S.assert_clean(raw_json.decode("utf-8"), "customs raw xml")
    raw_path = save_raw(ROOT, SOURCE, "changwon_hs6_trade_raw_responses.json", raw_json)

    rows.sort(key=lambda r: (r["period"], r["hs6"]))
    body = (",".join(COLUMNS) + "\n" + "".join(
        ",".join('"' + str(r.get(c, "")).replace('"', '""') + '"' for c in COLUMNS) + "\n"
        for r in rows)).encode("utf-8-sig")
    S.assert_clean(body.decode("utf-8-sig"), "customs csv")
    csv_path = save_raw(ROOT, SOURCE, "changwon_hs6_trade_monthly.csv", body)

    periods = sorted({r["period"] for r in rows})
    cumulative = append_checks(checks, rate_limited)
    # 창원시 행이 실제로 나온 코드만 '더 받을 것이 있는' 대상이다.
    # 탐색에서 거래가 없던 코드까지 partial 로 세면 결손이 부풀려지고,
    # 이어받기가 받을 것도 없는 조합을 호출하게 된다.
    hs_with_rows = {r["hs6"] for r in rows}
    full = sorted(h for h in hs_with_rows if len(done.get(h, ())) == len(WINDOWS))
    partial = sorted(h for h in hs_with_rows if 0 < len(done.get(h, ())) < len(WINDOWS))
    no_trade = sorted(h for h in done if h not in hs_with_rows)
    cov = dict(
        completed={h: sorted(map(list, ws)) for h, ws in done.items()},
        windows=[list(w) for w in WINDOWS],
        hs6_complete=full, hs6_partial=partial,
        hs6_no_changwon_trade=no_trade,
        n_hs6_complete=len(full), n_hs6_partial=len(partial),
        n_hs6_no_changwon_trade=len(no_trade),
        missing_combinations=sum(len(WINDOWS) - len(done[h]) for h in partial),
        rate_limited_last_run=rate_limited,
        runs=(cov.get("runs") or []) + [dict(
            run_at=utcnow(), calls=len(checks), incomplete=len(incomplete),
            rate_limited=rate_limited, rows_after=len(rows))],
        note=("업종×분기 집계는 hs6_complete 에 있는 코드만 써야 한다. "
              "일부 연도창이 빠진 코드를 섞으면 연도별 합계가 과소집계되어 "
              "YoY 가 왜곡된다."))
    save_coverage(cov)

    write_metadata(
        ROOT, SOURCE, "changwon_hs6_trade_monthly",
        dataset_name="관세청_시군구별 품목별 수출입실적 (창원시, 근거 있는 류의 HS6)",
        institution="관세청",
        source_url="https://www.data.go.kr/data/15134343/openapi.do",
        api_endpoint=ENDPOINT, retrieved_at=utcnow(),
        observation_start=periods[0], observation_end=periods[-1],
        geography="경상남도 창원시(시군구). 창원국가산단 경계가 아니다",
        industry_classification=("HS 6단위. 관세청 공표 HS부호 원본에서 만든 유효 HS6 "
                                 "모집단 중 류 단위로 KICOX 업종 귀속 근거가 있는 것만. "
                                 "등급 A(72·73·87·89류) / B(84·85류)"),
        frequency="월",
        unit="API 문서상 '수출미화금액'(단위 표기 없음). 값 크기는 천 달러 단위로 보이나 단정하지 않는다",
        original_filename="(API XML 응답을 CSV 로 직렬화)",
        file_hash_sha256=sha256_bytes(body),
        api_parameters=dict(sidoCd=SIDO_GYEONGNAM, strtYymm=START, endYymm=END,
                            discovery_window=list(DISCOVERY_WINDOW),
                            windows=[list(w) for w in WINDOWS],
                            hs6_universe_file=str(UNIVERSE.relative_to(ROOT)),
                            HsSgn_count=len(universe), HsSgn_discovered=len(found),
                            hs6_complete=len(full), hs6_partial=len(partial),
                            rate_limited=rate_limited,
                            auth="DATA_GO_KR_SERVICE_KEY (Encoding 형태 그대로 전달)",
                            note="serviceKey 재인코딩 금지"),
        pagination=dict(
            method=("이 API 는 페이지 분할이 없다. 호출마다 totalCount 와 반환 item 수를 "
                    "대조했다. 호출별 기록은 실행마다 누적 저장한다."),
            check_log=str(CHECKLOG.relative_to(ROOT)),
            cumulative=cumulative,
            this_run=dict(calls=len(checks), incomplete=len(incomplete),
                          rate_limited=rate_limited),
            incomplete_calls=cumulative["rate_limited_calls"]),
        revision_vintage="관세청 확정·잠정 구분이 응답에 없다. 최근월은 잠정치일 수 있다",
        terms_limitations=("2026.7.1 전후 시군구코드 체계가 다르다는 제공기관 안내가 있다. "
                           "시군구 단위이며 산업단지 내부만 분리할 수 없다."),
        mapping_notes=("HS6 목록은 관세청 HS부호 원본(15049722) 파일다운로드로 확보했다"
                       "(OpenAPI 는 이 키에 미등록이라 파일 경로를 썼다). 업종 대응은 "
                       "HS 류와 관세청 공표 세번2단위품명만 근거로 했고, 신성질별 분류"
                       "(소비재/원자재/자본재)는 용도 분류라 근거로 쓰지 않았다. "
                       "비철(74~81)·광학의료(90) 등 귀속 근거가 없는 류는 제외했으므로 "
                       "창원 수출 총액이 아니다."),
        role="CONTEXT / EXTERNAL_DEMAND",
        limitations=("귀속 근거가 있는 류만 포함(mapped_chapters_only). 업종 수출 총액이 "
                     "아니다. 탐색은 최근 1년 기준이라 그 해에 거래가 없던 품목은 "
                     "빠질 수 있다. 창원시 전역이며 산단 한정이 아니다. "
                     "등급 B(84·85류)는 맥락으로만 쓴다."),
        coverage_manifest=str(COVERAGE.relative_to(ROOT)),
        notes=(f"수집 {len(rows)}행. 탐색 대상 HS6 {len(universe)}개 중 "
               f"{len(found)}개에서 창원시 거래 확인. 이번 실행 호출 {len(checks)}회, "
               f"불완전 {len(incomplete)}건(429 포함). "
               f"6개 연도창 전부 확보 {len(full)}개 / 일부만 확보 {len(partial)}개."),
        raw_response_file=raw_path.name,
        raw_response_sha256=sha256_bytes(raw_json),
    )
    remaining = sum(len(WINDOWS) - len(done.get(h, ())) for h in partial)
    say(f"[ok] {csv_path.relative_to(ROOT)} rows={len(rows):,} "
        f"기간={periods[0]}~{periods[-1]} 품목={len(found):,}/{len(universe):,}")
    say(f"     연도창 완전 {len(full):,}개 / 부분 {len(partial):,}개 "
        f"(빠진 조합 {cov['missing_combinations']:,})")
    say(f"     이번 실행 호출 {len(checks):,} · 불완전 {len(incomplete):,} "
        f"· 호출한도 도달 {rate_limited}")
    return dict(status="RATE_LIMITED" if rate_limited else "OK",
                rate_limited=rate_limited, new_calls=new_calls,
                remaining=remaining, rows=len(rows),
                hs6_complete=len(full), hs6_partial=len(partial),
                missing_combinations=cov["missing_combinations"])


def main() -> int:
    r = collect()
    return 0 if r["status"] in ("OK", "RATE_LIMITED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
