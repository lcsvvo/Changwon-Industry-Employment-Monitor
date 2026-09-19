# -*- coding: utf-8 -*-
"""관세청 포털 일괄 보완 결과의 독립 QA.

pytest 설치 여부와 무관하게 실행할 수 있도록 표준 라이브러리만 쓴다.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/external/customs_trade"
NORMALIZED = RAW / "changwon_hs6_trade_monthly.csv"
COVERAGE = RAW / "_metadata/coverage_manifest.json"
METADATA = RAW / "_metadata/changwon_hs6_trade_monthly.json"
PORTAL_METADATA = RAW / "portal_bulk/_metadata.json"
UNIVERSE = ROOT / "data/reference/industry_crosswalk/hs6_universe_customs.csv"
TRADE_COVERAGE = ROOT / "data/processed/context/trade_coverage_by_industry.csv"
TRADE_PANEL = ROOT / "data/processed/context/trade_context_panel.csv"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    data = read_csv(NORMALIZED)
    coverage = json.loads(COVERAGE.read_text(encoding="utf-8"))
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    portal = json.loads(PORTAL_METADATA.read_text(encoding="utf-8"))
    universe = {r["hs6"] for r in read_csv(UNIVERSE)}

    keys = [(r["period"], r["hs6"]) for r in data]
    assert len(keys) == len(set(keys)), "정규화 데이터 period+hs6 중복"
    assert len(data) == portal["validation"]["normalized_rows_after"] == 46061
    assert not ({r["hs6"] for r in data} - universe), "공식 모집단 밖 HS6 존재"
    assert all("2021.01" <= r["period"] <= "2026.06" for r in data)
    assert all(r["export_usd"] != "" and r["import_usd"] != "" for r in data)

    complete = set(coverage["hs6_complete"])
    no_trade = set(coverage["hs6_no_changwon_trade"])
    expected_windows = {tuple(w) for w in coverage["windows"]}
    assert len(complete) == coverage["n_hs6_complete"] == 1029
    assert coverage["hs6_partial"] == []
    assert coverage["n_hs6_partial"] == 0
    assert coverage["missing_combinations"] == 0
    assert coverage["rate_limited_last_run"] is False
    assert len(no_trade) == coverage["n_hs6_no_changwon_trade"] == 219
    assert complete.isdisjoint(no_trade)
    assert complete | no_trade == universe
    for hs6 in complete:
        done = {tuple(w) for w in coverage["completed"][hs6]}
        assert expected_windows <= done, f"연도창 미완료: {hs6}"

    assert sha256(NORMALIZED) == metadata["file_hash_sha256"]
    assert metadata["api_parameters"]["hs6_complete"] == 1029
    assert metadata["api_parameters"]["hs6_partial"] == 0
    assert metadata["pagination"]["incomplete_calls"] == 0
    assert portal["validation"]["export_import_amount_mismatches"] == 0
    assert portal["validation"]["trade_balance_mismatches"] == 0
    assert portal["validation"]["normalized_rows_added"] == 11803
    for item in portal["files"]:
        path = RAW / "portal_bulk" / item["file"]
        assert sha256(path) == item["sha256"], f"포털 원본 해시 불일치: {path.name}"

    blank_count_rows = sum(
        not r["export_count"] and not r["import_count"] for r in data
    )
    assert blank_count_rows == 11803, "포털 보완행 건수 공란 정책 불일치"

    trade_cov = read_csv(TRADE_COVERAGE)
    assert all(r["trade_coverage_status"] != "collection_incomplete" for r in trade_cov)
    assert all(int(float(r["n_hs6_incomplete"])) == 0 for r in trade_cov)
    panel = read_csv(TRADE_PANEL)
    assert panel, "수출입 가공 패널이 비어 있음"
    assert all(int(float(r["n_hs6_excluded_incomplete"])) == 0 for r in panel)

    print(
        json.dumps(
            {
                "status": "OK",
                "normalized_rows": len(data),
                "unique_period_hs6": len(set(keys)),
                "hs6_complete": len(complete),
                "hs6_no_trade": len(no_trade),
                "missing_combinations": coverage["missing_combinations"],
                "portal_rows_added": portal["validation"]["normalized_rows_added"],
                "processed_trade_rows": len(panel),
                "incomplete_industries": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
