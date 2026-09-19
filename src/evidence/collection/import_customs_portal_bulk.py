# -*- coding: utf-8 -*-
"""관세청 무역통계 포털의 지역별 실적 CSV로 API 429 결손을 보완한다.

OpenAPI는 HS6 한 건과 최대 1년을 한 번에만 조회할 수 있어 일일 한도에
걸렸지만, 관세청 무역통계 화면은 여러 HS4를 선택하고 하위품목(HS6)을
한 CSV로 내려받을 수 있다. 이 스크립트는 그 공식 CSV 6개를 검증한 뒤
기존 API 결과의 미수집 연도창만 채운다.

금액/무역수지는 API와 포털의 중복 검증행에서 전부 일치했다. 반면 신고
건수는 두 경로의 정의 또는 개정 시점 차이가 있어, 포털로 새로 보완하는
행의 건수 필드는 공란으로 둔다. 원래 건수는 portal_bulk 원본에 보존된다.
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RAW_DIR = ROOT / "data/raw/customs/trade"
BULK_DIR = RAW_DIR / "portal_bulk"
DATA_FILE = RAW_DIR / "changwon_hs6_trade_monthly.csv"
COVERAGE_FILE = RAW_DIR / "_metadata/coverage_manifest.json"
DATA_METADATA_FILE = RAW_DIR / "_metadata/changwon_hs6_trade_monthly.json"
PORTAL_METADATA_FILE = BULK_DIR / "_metadata.json"
UNIVERSE_FILE = ROOT / "data/processed/final_model/reference/industry_crosswalk/hs6_universe_customs.csv"

WINDOWS = [
    ("202101", "202112"),
    ("202201", "202212"),
    ("202301", "202312"),
    ("202401", "202412"),
    ("202501", "202512"),
    ("202601", "202606"),
]
FILES = {
    "changwon_hs6_2021.csv": WINDOWS[0],
    "changwon_hs6_2022.csv": WINDOWS[1],
    "changwon_hs6_2023.csv": WINDOWS[2],
    "changwon_hs6_2024.csv": WINDOWS[3],
    "changwon_hs6_2025.csv": WINDOWS[4],
    "changwon_hs6_2026H1.csv": WINDOWS[5],
}
PORTAL_COLUMNS = [
    "기간",
    "지역",
    "HS코드",
    "품목명",
    "수출 건수",
    "수출 금액",
    "수입 건수",
    "수입 금액",
    "무역수지",
]
OUTPUT_COLUMNS = [
    "period",
    "sigungu",
    "hs6",
    "hs_chapter",
    "chapter_name_ko",
    "item_name_ko",
    "export_usd",
    "import_usd",
    "export_count",
    "import_count",
    "trade_balance",
    "mapped_kicox_industry",
    "mapping_grade",
    "mapping_rationale",
    "coverage_flag",
]


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def window_for_period(period: str) -> tuple[str, str]:
    yyyymm = period.replace(".", "").replace("-", "")
    for window in WINDOWS:
        if window[0] <= yyyymm <= window[1]:
            return window
    raise ValueError(f"수집 범위 밖 기간: {period}")


def main() -> None:
    required = [DATA_FILE, COVERAGE_FILE, DATA_METADATA_FILE, UNIVERSE_FILE]
    required.extend(BULK_DIR / name for name in FILES)
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("필수 파일 없음:\n" + "\n".join(missing))

    coverage = json.loads(COVERAGE_FILE.read_text(encoding="utf-8"))
    target_codes = set(coverage.get("hs6_partial", []))
    if not target_codes:
        # 성공 후 다시 실행해도 실패하거나 데이터를 중복 추가하지 않는다.
        if PORTAL_METADATA_FILE.exists():
            current_meta = json.loads(DATA_METADATA_FILE.read_text(encoding="utf-8"))
            already_done = (
                coverage.get("missing_combinations") == 0
                and current_meta.get("portal_bulk_metadata")
                and sha256(DATA_FILE) == current_meta.get("file_hash_sha256")
            )
            if already_done:
                print(json.dumps({"status": "ALREADY_IMPORTED"}, ensure_ascii=False))
                return
        raise RuntimeError("coverage_manifest에 보완할 hs6_partial이 없다")

    universe_rows = read_csv(UNIVERSE_FILE)
    universe = {row["hs6"].zfill(6): row for row in universe_rows}
    unknown = sorted(target_codes - set(universe))
    if unknown:
        raise RuntimeError(f"HS6 모집단에 없는 보완 코드: {unknown[:10]}")

    existing = read_csv(DATA_FILE)
    existing_by_key = {(r["period"], r["hs6"].zfill(6)): r for r in existing}
    if len(existing_by_key) != len(existing):
        raise RuntimeError("기존 정규화 데이터에 period+hs6 중복이 있다")

    portal_rows: list[dict[str, str]] = []
    file_stats: list[dict[str, object]] = []
    for filename, expected_window in FILES.items():
        path = BULK_DIR / filename
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames != PORTAL_COLUMNS:
                raise RuntimeError(
                    f"{filename} 열 불일치: {reader.fieldnames!r}"
                )
            raw = list(reader)

        detail = [r for r in raw if (r.get("HS코드") or "").strip()]
        for row in detail:
            period = row["기간"].strip()
            hs6 = row["HS코드"].strip().zfill(6)
            if window_for_period(period) != expected_window:
                raise RuntimeError(f"{filename}에 예상 밖 기간: {period}")
            row["HS코드"] = hs6
            row["기간"] = period.replace("-", ".")
            portal_rows.append(row)

        file_stats.append(
            {
                "file": filename,
                "window": list(expected_window),
                "detail_rows": len(detail),
                "sha256": sha256(path),
            }
        )

    portal_by_key: dict[tuple[str, str], dict[str, str]] = {}
    for row in portal_rows:
        key = (row["기간"], row["HS코드"])
        if key in portal_by_key:
            raise RuntimeError(f"포털 CSV period+hs6 중복: {key}")
        portal_by_key[key] = row

    seen_target_codes = {r["HS코드"] for r in portal_rows if r["HS코드"] in target_codes}
    unseen = sorted(target_codes - seen_target_codes)
    if unseen:
        raise RuntimeError(f"포털 CSV에서 한 번도 관측되지 않은 대상 HS6: {unseen[:10]}")

    overlap = 0
    amount_mismatches = 0
    balance_mismatches = 0
    export_count_mismatches = 0
    import_count_mismatches = 0
    for key, portal in portal_by_key.items():
        api = existing_by_key.get(key)
        if api is None or key[1] not in target_codes:
            continue
        overlap += 1
        if api["export_usd"] != portal["수출 금액"] or api["import_usd"] != portal["수입 금액"]:
            amount_mismatches += 1
        if api["trade_balance"] != portal["무역수지"]:
            balance_mismatches += 1
        if api["export_count"] != portal["수출 건수"]:
            export_count_mismatches += 1
        if api["import_count"] != portal["수입 건수"]:
            import_count_mismatches += 1
    if amount_mismatches or balance_mismatches:
        raise RuntimeError(
            "API/포털 중복구간 금액 불일치: "
            f"amount={amount_mismatches}, balance={balance_mismatches}"
        )

    added: list[dict[str, str]] = []
    for portal in portal_rows:
        hs6 = portal["HS코드"]
        if hs6 not in target_codes:
            continue
        key = (portal["기간"], hs6)
        if key in existing_by_key:
            continue
        meta = universe[hs6]
        added.append(
            {
                "period": portal["기간"],
                "sigungu": portal["지역"].strip(),
                "hs6": hs6,
                "hs_chapter": meta["hs_chapter"],
                "chapter_name_ko": meta.get("chapter_name_ko", ""),
                "item_name_ko": portal["품목명"].strip(),
                "export_usd": portal["수출 금액"].strip(),
                "import_usd": portal["수입 금액"].strip(),
                "export_count": "",
                "import_count": "",
                "trade_balance": portal["무역수지"].strip(),
                "mapped_kicox_industry": meta["target_kicox_industry"],
                "mapping_grade": meta["mapping_confidence"],
                "mapping_rationale": meta["rationale"],
                "coverage_flag": "mapped_chapters_only",
            }
        )

    merged = existing + added
    merged.sort(key=lambda r: (r["period"], r["hs6"].zfill(6)))
    merged_keys = {(r["period"], r["hs6"].zfill(6)) for r in merged}
    if len(merged_keys) != len(merged):
        raise RuntimeError("병합 결과에 period+hs6 중복이 있다")

    done = {
        code: {tuple(window) for window in windows}
        for code, windows in coverage["completed"].items()
    }
    for hs6 in target_codes:
        done.setdefault(hs6, set()).update(WINDOWS)

    no_trade = set(coverage.get("hs6_no_changwon_trade", []))
    observed = {r["hs6"].zfill(6) for r in merged}
    complete = sorted(code for code in observed if set(WINDOWS) <= done.get(code, set()))
    partial = sorted(code for code in observed if code not in complete)
    if partial:
        raise RuntimeError(f"포털 보완 뒤에도 일부 연도창만 있는 코드: {partial[:10]}")
    if set(complete) & no_trade:
        raise RuntimeError("complete와 no_trade 코드가 겹친다")

    now = utcnow()
    coverage["completed"] = {
        code: [list(window) for window in sorted(windows)]
        for code, windows in sorted(done.items())
    }
    coverage["windows"] = [list(window) for window in WINDOWS]
    coverage["hs6_complete"] = complete
    coverage["hs6_partial"] = partial
    coverage["n_hs6_complete"] = len(complete)
    coverage["n_hs6_partial"] = len(partial)
    coverage["missing_combinations"] = 0
    coverage["rate_limited_last_run"] = False
    coverage["note"] = (
        "OpenAPI 429로 남았던 HS6×연도창을 관세청 무역통계 지역별 실적 "
        "CSV 6회 일괄조회로 보완했다. 집계에는 hs6_complete만 사용한다."
    )
    coverage.setdefault("runs", []).append(
        {
            "run_at": now,
            "method": "tradedata_portal_bulk_csv",
            "queries": len(FILES),
            "target_hs6": len(target_codes),
            "rows_added": len(added),
            "incomplete": 0,
            "rate_limited": False,
            "rows_after": len(merged),
        }
    )

    write_csv(DATA_FILE, merged)
    COVERAGE_FILE.write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    portal_metadata = {
        "dataset_name": "관세청 무역통계 지역별 실적(품목별) 포털 일괄 보완본",
        "institution": "관세청",
        "source_url": "https://tradedata.go.kr/cts/index.do",
        "retrieved_at": now,
        "query": {
            "region": "경상남도 창원시",
            "period": "2021.01~2026.06 (연도별 6회)",
            "selected_hs4_count": 61,
            "include_descendants": True,
            "result_granularity": "HS6×월",
            "target_partial_hs6_count": len(target_codes),
        },
        "files": file_stats,
        "validation": {
            "portal_detail_rows": len(portal_rows),
            "portal_unique_period_hs6": len(portal_by_key),
            "target_hs6_seen": len(seen_target_codes),
            "api_overlap_rows": overlap,
            "export_import_amount_mismatches": amount_mismatches,
            "trade_balance_mismatches": balance_mismatches,
            "export_count_mismatches": export_count_mismatches,
            "import_count_mismatches": import_count_mismatches,
            "normalized_rows_added": len(added),
            "normalized_rows_after": len(merged),
        },
        "unit": "건, 천 달러 (관세청 무역통계 화면 표기)",
        "count_policy": (
            "API와 포털의 중복행에서 신고 건수가 달라 포털 보완행의 export_count/"
            "import_count는 공란 처리했다. 원시 건수는 이 폴더 CSV에 보존된다."
        ),
    }
    PORTAL_METADATA_FILE.write_text(
        json.dumps(portal_metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    metadata = json.loads(DATA_METADATA_FILE.read_text(encoding="utf-8"))
    params = metadata.setdefault("api_parameters", {})
    params["hs6_complete"] = len(complete)
    params["hs6_partial"] = 0
    params["rate_limited"] = False
    metadata["retrieved_at"] = now
    metadata["unit"] = "금액: 천 달러, 신고 건수: 건 (관세청 무역통계 화면 표기)"
    metadata["file_hash_sha256"] = sha256(DATA_FILE)
    metadata["collection_methods"] = [
        {
            "method": "data_go_kr_openapi",
            "role": "초기 HS6×연도창 수집",
            "historical_rate_limit": True,
        },
        {
            "method": "tradedata_portal_bulk_csv",
            "role": "OpenAPI 429 결손 보완",
            "queries": len(FILES),
            "metadata": str(PORTAL_METADATA_FILE.relative_to(ROOT)),
        },
    ]
    pagination = metadata.setdefault("pagination", {})
    pagination["incomplete_calls"] = 0
    pagination["note"] = (
        "누적 API 기록에는 과거 HTTP 429가 남아 있다. 해당 1,489개 결손 조합은 "
        "관세청 무역통계 포털 CSV 일괄조회로 전부 보완했으며 현재 결손은 0이다."
    )
    metadata["limitations"] = (
        "귀속 근거가 있는 류만 포함(mapped_chapters_only)하므로 업종 수출 총액이 아니다. "
        "창원시 전역이며 산단 한정이 아니다. 등급 B(84·85류)는 맥락으로만 쓴다. "
        "포털 보완행의 신고 건수는 API와 정의/개정시점이 달라 공란이다."
    )
    metadata["notes"] = (
        f"수집 {len(merged)}행. 탐색 대상 HS6 1248개 중 {len(complete)}개에서 창원시 "
        f"거래 확인, 6개 연도창 전부 확보 {len(complete)}개 / 일부 확보 0개. "
        f"OpenAPI 429 결손은 포털 일괄조회 6회로 {len(added)}행 보완했다."
    )
    metadata["portal_bulk_metadata"] = str(PORTAL_METADATA_FILE.relative_to(ROOT))
    DATA_METADATA_FILE.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "status": "OK",
                "target_hs6": len(target_codes),
                "portal_rows": len(portal_rows),
                "api_overlap_rows": overlap,
                "rows_added": len(added),
                "rows_after": len(merged),
                "hs6_complete": len(complete),
                "hs6_partial": len(partial),
                "missing_combinations": 0,
                "count_mismatches": {
                    "export": export_count_mismatches,
                    "import": import_count_mismatches,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
