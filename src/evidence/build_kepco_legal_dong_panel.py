# -*- coding: utf-8 -*-
"""Build KEPCO legal-dong x KSIC monthly/quarterly panels (offline only).

Reads only ``data/raw/kepco``.  It never downloads or modifies source files.
The 18 legal dongs are taken verbatim from the existing spatial reference where
``is_dense == True``; they are described as a Changwon manufacturing-concentration
legal-dong proxy, not as the Changwon National Industrial Complex boundary.

Outputs
-------
data/processed/kepco/legal_dong_ksic_monthly_panel.csv
data/processed/kepco/legal_dong_ksic_quarterly_panel.csv
outputs/final_model/04_external_evidence/kepco/quality/* (inventory, QA and report)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data/raw/kepco"
OUT_DATA = ROOT / "data/processed/kepco"
OUT_QA = ROOT / "outputs/final_model/04_external_evidence/kepco/quality"
SPATIAL = ROOT / "data/processed/kepco/reference/spatial/changwon_legal_dong_manufacturing_context.csv"
CROSSWALK = ROOT / "data/processed/final_model/reference/industry_crosswalk/ksic_to_kicox.csv"
DECISION = ROOT / "outputs/final_model/02_triage/tables/triage_panel.csv"
BUSINESS_MONTHLY = ROOT / "data/processed/kepco/kepco_power_monthly_panel.csv"
BUSINESS_QUARTERLY = ROOT / "data/processed/kepco/kepco_power_quarterly_panel.csv"

START_PERIOD = "2022-04"
KICOX_ORDER = [
    "음식료", "섬유의복", "목재종이", "석유화학", "비금속",
    "철강", "기계", "전기전자", "운송장비", "기타",
]
CHANGWON_DISTRICTS = ["의창구", "성산구", "마산합포구", "마산회원구", "진해구"]

HEADER_ALIASES = {
    "year": ("년도", "연도"),
    "month": ("월",),
    "sido": ("시도",),
    "sigungu": ("시군구",),
    "legal_dong": ("읍면동(법정동)리단위X", "읍면동", "법정동"),
    "ksic_major_code": ("산업분류코드(대)", "대분류코드"),
    "ksic_major_name": ("산업분류명(대)", "산업분류(대)", "대분류명"),
    "ksic_mid_code": ("산업분류코드(중)", "중분류코드"),
    "ksic_mid_name": ("산업분류명(중)", "산업분류(중)", "중분류명"),
    "customer_count": ("고객호수", "호수"),
    "power_usage": ("판매량", "전력사용량"),
    "charge_won": ("판매요금", "전기요금"),
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def stable_hash(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def norm_text(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip()
    return re.sub(r"\s+", "", text)


def display_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value)).strip())


def resolve_headers(values: tuple[Any, ...]) -> dict[str, int]:
    normalized = [norm_text(x) for x in values]
    result: dict[str, int] = {}
    used: set[int] = set()
    for standard, aliases in HEADER_ALIASES.items():
        needles = [norm_text(x) for x in aliases]
        for idx, text in enumerate(normalized):
            if idx not in used and text in needles:
                result[standard] = idx
                used.add(idx)
                break
        if standard in result:
            continue
        for idx, text in enumerate(normalized):
            if idx not in used and any(n and n in text for n in needles):
                result[standard] = idx
                used.add(idx)
                break
    return result


def parse_period(year: Any, month: Any) -> str | None:
    try:
        y = int(float(str(year).strip()))
        m = int(float(str(month).strip()))
    except (TypeError, ValueError):
        return None
    if 1900 <= y <= 2100 and 1 <= m <= 12:
        return f"{y:04d}-{m:02d}"
    return None


def normalize_code(value: Any, width: int | None = None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = display_text(value)
    if re.fullmatch(r"\d+(?:\.0+)?", text):
        text = str(int(float(text)))
    return text.zfill(width) if width and text.isdigit() else text


def numeric(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)
    text = display_text(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def is_suppression(value: Any) -> bool:
    text = norm_text(value).lower()
    if not text:
        return False
    return any(token in text for token in (
        "5호미만", "비식별", "비공개", "suppressed", "masked", "제거"
    ))


def expected_months(first: str, last: str) -> list[str]:
    start = pd.Period(first, freq="M")
    end = pd.Period(last, freq="M")
    return [str(x) for x in pd.period_range(start, end, freq="M")]


def quarter_of(period: str) -> str:
    return str(pd.Period(period, freq="M").asfreq("Q"))


def json_cell(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def json_default(value: Any) -> Any:
    """Convert NumPy/Pandas scalar values without stringifying booleans/numbers."""
    item = getattr(value, "item", None)
    if callable(item):
        return item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def read_baseline() -> dict[str, Any]:
    decision = pd.read_csv(DECISION, dtype=str, encoding="utf-8-sig")
    business_hashes = {
        str(p.relative_to(ROOT)): sha256_file(p)
        for p in (BUSINESS_MONTHLY, BUSINESS_QUARTERLY) if p.exists()
    }
    raw_hashes = {
        str(p.relative_to(ROOT)): sha256_file(p)
        for p in sorted(RAW.rglob("*")) if p.is_file()
    }
    return {
        "raw_hashes": raw_hashes,
        "decision_hash": sha256_file(DECISION),
        "decision_rows": int(len(decision)),
        "stage_counts": {str(k): int(v) for k, v in decision["stage"].value_counts().to_dict().items()},
        "business_hashes": business_hashes,
    }


def load_targets() -> tuple[set[tuple[str, str]], pd.DataFrame, str]:
    spatial = pd.read_csv(SPATIAL, dtype=str, encoding="utf-8-sig")
    dense = spatial[spatial["is_dense"].str.lower().eq("true")].copy()
    dense["gu_norm"] = dense["gu"].map(norm_text)
    dense["dong_norm"] = dense["legal_dong"].map(norm_text)
    targets = set(zip(dense["gu_norm"], dense["dong_norm"]))
    if len(targets) != 18:
        raise RuntimeError(f"Expected 18 existing proxy legal dongs, found {len(targets)}")
    key_hash = stable_hash(sorted(f"{g}|{d}" for g, d in targets))
    return targets, dense, key_hash


def load_crosswalk() -> tuple[dict[str, dict[str, str]], pd.DataFrame, str]:
    cw = pd.read_csv(CROSSWALK, dtype=str, encoding="utf-8-sig").fillna("")
    cw = cw[cw["source_scheme"].eq("KSIC 중분류")].copy()
    mapping: dict[str, dict[str, str]] = {}
    for row in cw.to_dict("records"):
        code = normalize_code(row["source_code"], 2)
        if code in mapping and mapping[code] != row:
            raise RuntimeError(f"Conflicting existing crosswalk rows for KSIC {code}")
        mapping[code] = row
    return mapping, cw, sha256_file(CROSSWALK)


def strict_district(value: Any) -> str | None:
    text = norm_text(value)
    accepted = {norm_text(x): x for x in CHANGWON_DISTRICTS}
    accepted.update({norm_text(f"창원시 {x}"): x for x in CHANGWON_DISTRICTS})
    accepted.update({norm_text(f"경상남도 창원시 {x}"): x for x in CHANGWON_DISTRICTS})
    return accepted.get(text)


def scan_workbooks(targets: set[tuple[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], Counter]:
    file_inventory: list[dict[str, Any]] = []
    sheet_inventory: list[dict[str, Any]] = []
    extracted: list[dict[str, Any]] = []
    nonnumeric_tokens: Counter = Counter()

    for path in sorted(RAW.rglob("*")):
        if not path.is_file():
            continue
        stat = path.stat()
        meta: dict[str, Any] = {
            "file_name": path.name,
            "relative_path": str(path.relative_to(ROOT)),
            "extension": path.suffix.lower(),
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
            "sha256": sha256_file(path),
            "expected_periods_from_name": "",
            "internal_periods": "",
            "sheet_names": "",
            "actual_data_rows": 0,
            "actual_columns": "",
            "read_success": False,
            "corruption_status": "UNTESTED",
            "duplicate_file": False,
            "in_scope": True,
            "error": "",
        }
        name_periods = re.findall(r"(?<!\d)(\d{2})(\d{2})(?!\d)", path.stem)
        meta["expected_periods_from_name"] = "|".join(f"20{y}-{m}" for y, m in name_periods if 1 <= int(m) <= 12)
        if "2021" in path.stem and "2022" not in path.stem:
            meta["in_scope"] = False
            meta["read_success"] = None
            meta["corruption_status"] = "NOT_INSPECTED_OUT_OF_SCOPE"
            meta["error"] = "2021 is outside the requested 2022-04+ period; skipped at user direction"
            file_inventory.append(meta)
            print(f"[skip] {path.name}: outside requested period", flush=True)
            continue
        if path.suffix.lower() != ".xlsx":
            # The source-oriented raw/kepco directory also contains the API CSV,
            # response JSON, and collection metadata used by other KEPCO builders.
            # They belong in the inventory, but not in this XLSX-only QA universe.
            meta["in_scope"] = False
            meta["read_success"] = None
            meta["corruption_status"] = "NOT_INSPECTED_OTHER_SERIES"
            meta["error"] = "Not an XLSX input for the legal-dong series"
            file_inventory.append(meta)
            continue

        try:
            with zipfile.ZipFile(path) as archive:
                bad_member = archive.testzip()
            meta["corruption_status"] = "CORRUPT" if bad_member else "OK"
            if bad_member:
                meta["error"] = f"CRC failure: {bad_member}"

            workbook = load_workbook(path, read_only=True, data_only=True)
            meta["sheet_names"] = "|".join(workbook.sheetnames)
            file_periods: set[str] = set()
            file_columns: list[str] = []
            file_rows = 0

            for ws in workbook.worksheets:
                iterator = ws.iter_rows(values_only=True)
                header = next(iterator, tuple())
                headers = [display_text(x) for x in header]
                cols = resolve_headers(header)
                required = {"year", "month", "sido", "sigungu", "legal_dong",
                            "ksic_major_code", "ksic_major_name", "ksic_mid_code",
                            "ksic_mid_name", "customer_count", "power_usage", "charge_won"}
                missing_columns = sorted(required - set(cols))
                sheet_periods: set[str] = set()
                data_rows = 0
                target_rows = 0

                for values in iterator:
                    if not values or not any(v is not None and display_text(v) != "" for v in values):
                        continue
                    data_rows += 1
                    if missing_columns:
                        continue
                    period = parse_period(values[cols["year"]], values[cols["month"]])
                    if period:
                        sheet_periods.add(period)
                        file_periods.add(period)

                    district = strict_district(values[cols["sigungu"]])
                    dong = display_text(values[cols["legal_dong"]])
                    key = (norm_text(district), norm_text(dong)) if district else None
                    if not period or period < START_PERIOD or key not in targets:
                        continue

                    raw_customer = values[cols["customer_count"]]
                    raw_power = values[cols["power_usage"]]
                    raw_charge = values[cols["charge_won"]]
                    major_code_raw = values[cols["ksic_major_code"]]
                    major_name_raw = values[cols["ksic_major_name"]]
                    mid_code_raw = values[cols["ksic_mid_code"]]
                    mid_name_raw = values[cols["ksic_mid_name"]]
                    # Some 2022 files label code/name columns in the opposite
                    # order from their actual values. Detect by value shape,
                    # never by filename or fuzzy industry-name matching.
                    if (not re.fullmatch(r"[A-Z]", display_text(major_code_raw))
                            and re.fullmatch(r"[A-Z]", display_text(major_name_raw))):
                        major_code_raw, major_name_raw = major_name_raw, major_code_raw
                    if (not re.fullmatch(r"\d{1,3}", display_text(mid_code_raw))
                            and re.fullmatch(r"\d{1,3}", display_text(mid_name_raw))):
                        mid_code_raw, mid_name_raw = mid_name_raw, mid_code_raw
                    for field, raw in (("customer_count", raw_customer),
                                       ("power_usage", raw_power), ("charge_won", raw_charge)):
                        if display_text(raw) and numeric(raw) is None:
                            nonnumeric_tokens[(field, display_text(raw))] += 1

                    suppression = any(is_suppression(x) for x in (raw_customer, raw_power, raw_charge))
                    customer = numeric(raw_customer)
                    power = numeric(raw_power)
                    charge = numeric(raw_charge)
                    missing = (customer is None or power is None) and not suppression
                    coverage = "SUPPRESSED" if suppression else ("MISSING_VALUE" if missing else "COMPLETE")
                    extracted.append({
                        "period": period,
                        "district": district,
                        "legal_dong": dong,
                        "ksic_major_code": normalize_code(major_code_raw),
                        "ksic_major_name": display_text(major_name_raw),
                        "ksic_mid_code": normalize_code(mid_code_raw, 2),
                        "ksic_mid_name": display_text(mid_name_raw),
                        "customer_count": customer,
                        "power_usage": power,
                        "charge_won": charge,
                        "suppression_flag": int(suppression),
                        "missing_flag": int(missing),
                        "coverage_flag": coverage,
                        "source_file": path.name,
                        "source_sheet": ws.title,
                    })
                    target_rows += 1

                file_rows += data_rows
                file_columns = file_columns or headers
                sheet_inventory.append({
                    "file_name": path.name,
                    "sheet_name": ws.title,
                    "actual_data_rows": data_rows,
                    "actual_column_count": len([x for x in headers if x]),
                    "actual_columns": json_cell(headers),
                    "resolved_columns": json_cell(cols),
                    "missing_required_columns": "|".join(missing_columns),
                    "internal_periods": "|".join(sorted(sheet_periods)),
                    "target_proxy_rows": target_rows,
                    "read_success": not missing_columns,
                })

            workbook.close()
            meta["actual_data_rows"] = file_rows
            meta["actual_columns"] = json_cell(file_columns)
            meta["internal_periods"] = "|".join(sorted(file_periods))
            meta["read_success"] = bool(workbook.sheetnames) and all(
                x["read_success"] for x in sheet_inventory if x["file_name"] == path.name
            )
        except Exception as exc:  # inventory must retain failed/corrupt files
            meta["corruption_status"] = "CORRUPT_OR_UNREADABLE"
            meta["error"] = f"{type(exc).__name__}: {exc}"
        file_inventory.append(meta)
        print(f"[scan] {path.name}: rows={meta['actual_data_rows']:,} "
              f"months={meta['internal_periods'] or '-'} status={meta['corruption_status']}", flush=True)

    hashes = Counter(x["sha256"] for x in file_inventory)
    for row in file_inventory:
        row["duplicate_file"] = hashes[row["sha256"]] > 1
    return file_inventory, sheet_inventory, extracted, nonnumeric_tokens


def choose_month_sources(file_inventory: list[dict[str, Any]], extracted: list[dict[str, Any]]) -> tuple[dict[str, str], pd.DataFrame, list[dict[str, Any]]]:
    month_files: dict[str, list[str]] = defaultdict(list)
    file_meta = {x["file_name"]: x for x in file_inventory}
    for row in file_inventory:
        if not row["read_success"]:
            continue
        for period in filter(None, row["internal_periods"].split("|")):
            if period >= START_PERIOD:
                month_files[period].append(row["file_name"])

    extracted_df = pd.DataFrame(extracted)
    counts = (extracted_df.groupby(["period", "source_file"]).size().to_dict()
              if not extracted_df.empty else {})
    source_choice: dict[str, str] = {}
    month_audit: list[dict[str, Any]] = []
    latest = max(month_files) if month_files else START_PERIOD
    expected = expected_months(START_PERIOD, latest)

    for period in expected:
        candidates = sorted(set(month_files.get(period, [])))
        healthy = [f for f in candidates if file_meta[f]["corruption_status"] == "OK"]
        pool = healthy or candidates
        selected = ""
        if pool:
            selected = max(pool, key=lambda f: (
                counts.get((period, f), 0),
                int(file_meta[f]["actual_data_rows"]),
                file_meta[f]["modified_at"],
                f,
            ))
            source_choice[period] = selected

        status = "AVAILABLE"
        if not candidates:
            status = "MISSING"
        elif not healthy:
            status = "CORRUPT"
        elif len(candidates) > 1:
            status = "DUPLICATE_RESOLVED"
        month_audit.append({
            "period": period,
            "expected": True,
            "status": status,
            "source_candidates": "|".join(candidates),
            "selected_source": selected,
            "candidate_count": len(candidates),
            "selected_proxy_rows": counts.get((period, selected), 0) if selected else 0,
        })

    if extracted_df.empty:
        panel = extracted_df
    else:
        panel = extracted_df[
            extracted_df.apply(lambda r: source_choice.get(r["period"]) == r["source_file"], axis=1)
        ].copy()
    return source_choice, panel, month_audit


def attach_mapping(panel: pd.DataFrame, mapping: dict[str, dict[str, str]]) -> pd.DataFrame:
    panel = panel.copy()
    panel["kicox_industry"] = panel["ksic_mid_code"].map(
        lambda x: mapping.get(x, {}).get("target_kicox_industry", ""))
    panel["mapping_grade"] = panel["ksic_mid_code"].map(
        lambda x: mapping.get(x, {}).get("mapping_confidence", "D"))
    panel["mapping_type"] = panel["ksic_mid_code"].map(
        lambda x: mapping.get(x, {}).get("mapping_type", "unavailable"))
    panel["mapping_rationale"] = panel["ksic_mid_code"].map(
        lambda x: mapping.get(x, {}).get("rationale", "기존 crosswalk에 중분류 코드 없음; 강제 배정하지 않음"))
    return panel


def validate_and_dedupe_monthly(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    key = ["period", "district", "legal_dong", "ksic_major_code", "ksic_mid_code"]
    exact_dups = int(panel.duplicated(keep="first").sum())
    panel = panel.drop_duplicates().copy()
    conflicts = panel[panel.duplicated(key, keep=False)].sort_values(key)
    conflict_keys = int(conflicts[key].drop_duplicates().shape[0])
    panel["source_row_count"] = 1
    if not conflicts.empty:
        conflict_path = OUT_QA / "conflicting_duplicate_rows.csv"
        conflicts.to_csv(conflict_path, index=False, encoding="utf-8-sig")
        keep = panel[~panel.duplicated(key, keep=False)].copy()
        resolved: list[dict[str, Any]] = []
        for _, group in conflicts.groupby(key, dropna=False, sort=True):
            rec = group.iloc[0].to_dict()
            suppressed = bool(group["suppression_flag"].astype(bool).any())
            missing = bool(group["missing_flag"].astype(bool).any())
            # The source exposes no dimension that distinguishes these rows.
            # If any component is suppressed/missing, the desired-grain total is
            # unknowable: retain null rather than a visible lower bound or zero.
            if suppressed or missing:
                rec["customer_count"] = None
                rec["power_usage"] = None
                rec["charge_won"] = None
            else:
                rec["customer_count"] = float(group["customer_count"].sum())
                rec["power_usage"] = float(group["power_usage"].sum())
                rec["charge_won"] = float(group["charge_won"].sum())
            rec["suppression_flag"] = int(suppressed)
            rec["missing_flag"] = int(missing and not suppressed)
            rec["coverage_flag"] = "SUPPRESSED" if suppressed else (
                "MISSING_VALUE" if missing else "COMPLETE")
            rec["source_file"] = "|".join(sorted(group["source_file"].unique()))
            rec["source_sheet"] = "|".join(sorted(group["source_sheet"].unique()))
            rec["source_row_count"] = int(len(group))
            resolved.append(rec)
        panel = pd.concat([keep, pd.DataFrame(resolved)], ignore_index=True)
    panel = panel.sort_values(key).reset_index(drop=True)
    return panel, {"exact_duplicate_rows_removed": exact_dups,
                   "conflicting_duplicate_source_rows": int(len(conflicts)),
                   "conflicting_duplicate_keys_resolved_as_incomplete": conflict_keys}


def build_quarterly(monthly: pd.DataFrame) -> pd.DataFrame:
    work = monthly.copy()
    work["quarter"] = work["period"].map(quarter_of)
    keys = ["quarter", "district", "legal_dong", "ksic_major_code", "ksic_major_name",
            "ksic_mid_code", "ksic_mid_name", "kicox_industry", "mapping_grade",
            "mapping_type", "mapping_rationale"]
    rows: list[dict[str, Any]] = []
    for group_key, g in work.groupby(keys, dropna=False, sort=True):
        g = g.sort_values("period")
        periods = sorted(g["period"].unique())
        numeric_power = g["power_usage"].notna()
        numeric_customer = g["customer_count"].notna()
        complete = (len(periods) == 3 and numeric_power.all()
                    and not g["suppression_flag"].astype(bool).any()
                    and not g["missing_flag"].astype(bool).any())
        q_last = str(pd.Period(group_key[0], freq="Q").asfreq("M", "end"))
        qe = g.loc[g["period"].eq(q_last), "customer_count"]
        customer_qe = float(qe.iloc[-1]) if len(qe) and pd.notna(qe.iloc[-1]) else None
        customer_mean = float(g["customer_count"].mean()) if (len(periods) == 3 and numeric_customer.all()) else None
        rec = dict(zip(keys, group_key))
        rec.update({
            "period": group_key[0],
            "months_observed": len(periods),
            "months": "|".join(periods),
            "power_usage": float(g["power_usage"].sum()) if complete else None,
            "customer_count_qe": customer_qe,
            "customer_count_mean": customer_mean,
            "suppression_flag": int(g["suppression_flag"].astype(bool).any()),
            "missing_flag": int(not complete),
            "coverage_flag": "COMPLETE" if complete else (
                "SUPPRESSED" if g["suppression_flag"].astype(bool).any() else "INCOMPLETE"),
            "source_file": "|".join(sorted(g["source_file"].unique())),
        })
        rows.append(rec)
    columns = ["period", "district", "legal_dong", "ksic_major_code", "ksic_major_name",
               "ksic_mid_code", "ksic_mid_name", "kicox_industry", "mapping_grade",
               "mapping_type", "mapping_rationale", "months_observed", "months",
               "power_usage", "customer_count_qe", "customer_count_mean",
               "suppression_flag", "missing_flag", "coverage_flag", "source_file"]
    return pd.DataFrame(rows)[columns].sort_values(
        ["period", "district", "legal_dong", "ksic_major_code", "ksic_mid_code"]
    ).reset_index(drop=True)


def suppression_tables(monthly: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    def summarize(cols: list[str]) -> pd.DataFrame:
        return (monthly.groupby(cols, dropna=False)
                .agg(rows=("period", "size"), suppressed_rows=("suppression_flag", "sum"),
                     missing_rows=("missing_flag", "sum"))
                .reset_index()
                .assign(suppression_rate=lambda x: x["suppressed_rows"] / x["rows"],
                        missing_rate=lambda x: x["missing_rows"] / x["rows"]))
    return summarize(["period"]), summarize(["ksic_mid_code", "ksic_mid_name"]), summarize(["district", "legal_dong"])


def kicox_coverage(monthly: pd.DataFrame, quarterly: pd.DataFrame, mapping: dict[str, dict[str, str]]) -> pd.DataFrame:
    grade_order = {"A": 1, "B": 2, "C": 3, "D": 4}
    rows = []
    for industry in KICOX_ORDER:
        codes = sorted((code, x["mapping_confidence"]) for code, x in mapping.items()
                       if x.get("target_kicox_industry") == industry)
        m = monthly[monthly["kicox_industry"].eq(industry)].copy()
        q = quarterly[quarterly["kicox_industry"].eq(industry)].copy()
        monthly_status: dict[str, bool] = {}
        for period, g in m.groupby("period"):
            monthly_status[period] = bool(len(g) and g["power_usage"].notna().all()
                                          and not g["suppression_flag"].astype(bool).any()
                                          and not g["missing_flag"].astype(bool).any())
        complete_quarters = 0
        for quarter in sorted({quarter_of(x) for x in monthly_status}):
            months = [str(x) for x in pd.period_range(pd.Period(quarter, freq="Q").start_time,
                                                       periods=3, freq="M")]
            if all(monthly_status.get(x, False) for x in months):
                complete_quarters += 1
        worst = max((g for _, g in codes), key=lambda x: grade_order.get(x, 9), default="D")
        q2 = ["2026-04", "2026-05", "2026-06"]
        rows.append({
            "kicox_industry": industry,
            "ksic_mid_codes": "|".join(f"{c}({g})" for c, g in codes),
            "mapping_grade": worst,
            "first_observed_month": m["period"].min() if len(m) else "",
            "last_observed_month": m["period"].max() if len(m) else "",
            "available_month_count": int(m["period"].nunique()),
            "complete_quarter_count": complete_quarters,
            "missing_rate": float(m["missing_flag"].mean()) if len(m) else None,
            "suppression_rate": float(m["suppression_flag"].mean()) if len(m) else None,
            "proxy_legal_dong_coverage": int(m[["district", "legal_dong"]].drop_duplicates().shape[0]),
            "proxy_legal_dong_coverage_label": f"{m[['district', 'legal_dong']].drop_duplicates().shape[0]}/18",
            "available_2026Q2": all(monthly_status.get(x, False) for x in q2),
            "quarterly_complete_row_share": float(q["coverage_flag"].eq("COMPLETE").mean()) if len(q) else None,
        })
    return pd.DataFrame(rows)


def business_comparison(monthly: pd.DataFrame, kicox: pd.DataFrame) -> pd.DataFrame:
    old = pd.read_csv(BUSINESS_MONTHLY, low_memory=False, encoding="utf-8-sig")
    old_period_col = "ym" if "ym" in old.columns else "period"
    old_first = str(old[old_period_col].min())
    old_last = str(old[old_period_col].max())
    old_missing = float(pd.to_numeric(old.get("power_usage_kwh"), errors="coerce").isna().mean())
    old_kicox_count = (old.loc[old["kicox_industry"].isin(KICOX_ORDER), "kicox_industry"].nunique()
                       if "kicox_industry" in old else "확인불가")
    new_first = str(monthly["period"].min())
    new_last = str(monthly["period"].max())
    return pd.DataFrame([
        {"aspect": "업종 정의", "legal_dong_ksic": "공식 KSIC 중분류 코드", "business_type": "KEPCO 비공식 businessType 명칭", "assessment": "법정동×KSIC 개선"},
        {"aspect": "KICOX 매핑 신뢰도", "legal_dong_ksic": "기존 코드 crosswalk A/B/C/D 유지; fuzzy matching 없음", "business_type": "업종명→KSIC→KICOX 간접 대응", "assessment": "법정동×KSIC 개선"},
        {"aspect": "공간단위", "legal_dong_ksic": "창원 제조업 집적 법정동 proxy 18개", "business_type": "기존 창원시 집계", "assessment": "법정동×KSIC가 세밀하지만 산단 경계는 아님"},
        {"aspect": "기간 coverage", "legal_dong_ksic": f"{new_first}~{new_last}", "business_type": f"{old_first}~{old_last}", "assessment": "서로 기간·자료계열이 다름"},
        {"aspect": "비식별률", "legal_dong_ksic": f"{monthly['suppression_flag'].mean():.4%}", "business_type": "별도 suppression_flag 없음", "assessment": "신규 자료는 비식별을 명시"},
        {"aspect": "결측률", "legal_dong_ksic": f"{monthly['missing_flag'].mean():.4%}", "business_type": f"{old_missing:.4%}", "assessment": "정의 차이로 단순 우열 해석 금지"},
        {"aspect": "10업종 coverage", "legal_dong_ksic": f"{int((kicox['available_month_count'] > 0).sum())}/10", "business_type": f"{old_kicox_count}/10", "assessment": "신규 자료는 코드별 근거 추적 가능"},
    ])


def write_report(stats: dict[str, Any], kicox: pd.DataFrame, comparison: pd.DataFrame,
                 inventory: pd.DataFrame, month_audit: pd.DataFrame, qa: dict[str, Any]) -> None:
    status = stats["candidate_status"]
    improved = stats["one_line_conclusion"]
    k_lines = []
    for row in kicox.to_dict("records"):
        k_lines.append(
            f"| {row['kicox_industry']} | {row['ksic_mid_codes']} | {row['mapping_grade']} | "
            f"{row['first_observed_month']}~{row['last_observed_month']} | "
            f"{row['complete_quarter_count']} | {row['suppression_rate']:.2%} | "
            f"{'가능' if row['available_2026Q2'] else '불가'} |"
        )
    comp_lines = [
        f"| {r['aspect']} | {r['legal_dong_ksic']} | {r['business_type']} | {r['assessment']} |"
        for r in comparison.to_dict("records")
    ]
    failed = [name for name, item in qa["checks"].items() if not item["pass"]]
    in_scope_inventory = inventory[inventory["in_scope"].eq(True)]
    corrupt = in_scope_inventory[in_scope_inventory["corruption_status"].ne("OK")]["file_name"].tolist()
    schema_path = OUT_QA / "schema_anomalies.csv"
    if schema_path.exists():
        schema = pd.read_csv(schema_path, encoding="utf-8-sig")
        schema_note = "; ".join(
            f"{r['affected_periods']} ({int(r['affected_rows']):,}행): {r['resolution']}"
            for r in schema.to_dict("records")
        )
    else:
        schema_note = "없음"
    missing = month_audit[month_audit["status"].eq("MISSING")]["period"].tolist()
    duplicate = month_audit[month_audit["status"].eq("DUPLICATE_RESOLVED")]["period"].tolist()
    report = f"""# KEPCO 법정동×KSIC 전력자료 QA 보고서

## 1. 한 줄 결론

{improved}

최종 후보 지위: **{status}**

## 2. 로컬 원자료 inventory

- 파일 수: {len(inventory)}개
- 범위 내 읽기 성공: {int(in_scope_inventory['read_success'].fillna(False).sum())}개 / 실패: {int((~in_scope_inventory['read_success'].fillna(False)).sum())}개
- 2021 파일: 사용자 지시에 따라 범위 제외·미검사
- 손상·비정상 파일: {', '.join(corrupt) if corrupt else '없음'}
- 동일 SHA-256 중복 파일: {int(inventory['duplicate_file'].sum())}개
- 헤더-값 스키마 이상 및 처리: {schema_note}
- 상세: `raw_file_inventory.csv`, `raw_sheet_inventory.csv`

## 3. 수집 가능한 실제 기간

- 최초월: {stats['first_month']}
- 최종월: {stats['last_month']}
- expected / available / missing: {stats['expected_months']} / {stats['available_months']} / {stats['missing_months']}
- 누락월: {', '.join(missing) if missing else '없음'}
- 원자료 중복월(정상 파일 우선·행수 기준으로 1개 선택): {', '.join(duplicate) if duplicate else '없음'}
- 최종 월 패널은 월별 source를 하나만 선택했으며, 자료가 없는 월을 0으로 만들지 않았다.

## 4. 18개 제조업 집적 법정동 패널

이 공간범위는 **창원 제조업 집적 법정동 proxy**이며 창원국가산단 경계가 아니다.

- 월 패널: {stats['monthly_rows']:,}행
- 분기 패널: {stats['quarterly_rows']:,}행
- 비식별률: {stats['suppression_rate']:.2%}
- 일반 결측률(비식별 제외): {stats['missing_rate']:.2%}
- 관측 법정동: {stats['observed_proxy_dongs']}/18
- 분기 `power_usage`는 3개월이 모두 숫자이고 비식별·결측이 없을 때만 합계했다.
- `customer_count`는 합계하지 않고 분기말값과 3개월 평균을 분리했다.

## 5. KICOX 10업종 매핑

| KICOX 업종 | 대응 KSIC(등급) | 종합 grade | 기간 | COMPLETE 분기 | 비식별률 | 2026Q2 사용가능 |
|---|---|---|---|---:|---:|---|
{chr(10).join(k_lines)}

`COMPLETE 분기`는 해당 KICOX 업종의 관측 행에서 세 달 모두 전력값이 숫자이고 비식별·일반결측이 없는 분기다. 구조적으로 존재하지 않는 법정동×업종 조합을 0으로 보충하지 않았다.

## 6. businessType 대비 개선점/한계

| 비교축 | 법정동×KSIC | 기존 businessType | 판단 |
|---|---|---|---|
{chr(10).join(comp_lines)}

## 7. 신규 전력자료의 최종 후보 지위

**{status}**

KSIC 코드와 공간단위가 명확해 기존 businessType보다 매핑·공간 해석은 개선됐다. 다만 이 18개 법정동은 산단 경계가 아니고, B/C 등급 매핑·비식별·최신 분기 미확보 제약이 있어 현재 단계에서 핵심 판정기준으로 승격하지 않는다.

## 8. Triage 불변성

- 행 수: {qa['post']['decision_rows']}
- 관찰 / 추가확인 / 우선점검: {qa['post']['stage_counts'].get('관찰', 0)} / {qa['post']['stage_counts'].get('추가확인', 0)} / {qa['post']['stage_counts'].get('우선점검', 0)}
- decision_panel.csv SHA-256: `{qa['post']['decision_hash']}`
- 작업 전후 hash 동일: {'예' if qa['checks']['decision_panel_hash_unchanged']['pass'] else '아니오'}

## 9. 남은 한계

- 2026Q2(4~6월)는 원자료가 없어 사용할 수 없다.
- 비식별값은 0이나 추정치로 보완하지 않았으므로 업종 합계가 하한처럼 보일 수 있다.
- KSIC 18·21·25·32·33 등 C등급은 부분 대응 또는 복수 범위여서 단정형 업종 신호에 부적합하다.
- 법정동 proxy는 제조업 집적지역을 나타낼 뿐 창원국가산단 입주기업 모집단과 일치하지 않는다.
- 원자료에 법정동 코드가 없어 명칭 기반의 엄격한 정규화만 사용했다.

## 10. 생성·수정 파일

- `data/processed/kepco/legal_dong_ksic_monthly_panel.csv`
- `data/processed/kepco/legal_dong_ksic_quarterly_panel.csv`
- `outputs/final_model/04_external_evidence/kepco/quality/` 아래 inventory, coverage, mapping, 비식별률, QA, metadata, 본 보고서
- `src/evidence/build_kepco_legal_dong_panel.py`

QA 실패 항목: {', '.join(failed) if failed else '없음'}
"""
    (OUT_QA / "REPORT.md").write_text(report, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--finalize-existing", action="store_true",
                        help="Reuse already generated CSVs; do not rescan XLSX files")
    args = parser.parse_args(argv)

    OUT_QA.mkdir(parents=True, exist_ok=True)
    OUT_DATA.mkdir(parents=True, exist_ok=True)
    baseline = read_baseline()
    targets, dense, proxy_hash = load_targets()
    mapping, cw, crosswalk_hash = load_crosswalk()

    if args.finalize_existing:
        inventory_df = pd.read_csv(OUT_QA / "raw_file_inventory.csv", encoding="utf-8-sig")
        monthly = pd.read_csv(OUT_DATA / "legal_dong_ksic_monthly_panel.csv",
                              dtype={"ksic_major_code": str, "ksic_mid_code": str},
                              encoding="utf-8-sig", low_memory=False)
        quarterly = pd.read_csv(OUT_DATA / "legal_dong_ksic_quarterly_panel.csv",
                                dtype={"ksic_major_code": str, "ksic_mid_code": str},
                                encoding="utf-8-sig", low_memory=False)
        major_swap = (~monthly["ksic_major_code"].fillna("").str.fullmatch(r"[A-Z]")
                      & monthly["ksic_major_name"].fillna("").str.fullmatch(r"[A-Z]"))
        mid_swap = (~monthly["ksic_mid_code"].fillna("").str.fullmatch(r"\d{1,3}")
                    & monthly["ksic_mid_name"].fillna("").str.fullmatch(r"\d{1,3}"))
        swap_rows = int((major_swap | mid_swap).sum())
        if major_swap.any():
            old_code = monthly.loc[major_swap, "ksic_major_code"].copy()
            monthly.loc[major_swap, "ksic_major_code"] = monthly.loc[major_swap, "ksic_major_name"].values
            monthly.loc[major_swap, "ksic_major_name"] = old_code.values
        if mid_swap.any():
            old_code = monthly.loc[mid_swap, "ksic_mid_code"].copy()
            monthly.loc[mid_swap, "ksic_mid_code"] = monthly.loc[mid_swap, "ksic_mid_name"].values
            monthly.loc[mid_swap, "ksic_mid_name"] = old_code.values
        if swap_rows:
            monthly["ksic_mid_code"] = monthly["ksic_mid_code"].map(lambda x: normalize_code(x, 2))
            monthly = attach_mapping(monthly.drop(
                columns=["kicox_industry", "mapping_grade", "mapping_type", "mapping_rationale"]), mapping)
            monthly = monthly[list(pd.read_csv(
                OUT_DATA / "legal_dong_ksic_monthly_panel.csv", nrows=0,
                encoding="utf-8-sig").columns)]
            quarterly = build_quarterly(monthly)
            monthly.to_csv(OUT_DATA / "legal_dong_ksic_monthly_panel.csv",
                           index=False, encoding="utf-8-sig")
            quarterly.to_csv(OUT_DATA / "legal_dong_ksic_quarterly_panel.csv",
                             index=False, encoding="utf-8-sig")
            pd.DataFrame([{
                "issue": "header_value_code_name_order_mismatch",
                "affected_periods": "|".join(sorted(monthly.loc[major_swap | mid_swap, "period"].unique())),
                "affected_rows": swap_rows,
                "resolution": "swapped by code-value shape; raw files unchanged",
            }]).to_csv(OUT_QA / "schema_anomalies.csv", index=False, encoding="utf-8-sig")
            by_month, by_ksic, by_dong = suppression_tables(monthly)
            by_month.to_csv(OUT_QA / "suppression_by_month.csv", index=False, encoding="utf-8-sig")
            by_ksic.to_csv(OUT_QA / "suppression_by_ksic.csv", index=False, encoding="utf-8-sig")
            by_dong.to_csv(OUT_QA / "suppression_by_legal_dong.csv", index=False, encoding="utf-8-sig")
            kicox = kicox_coverage(monthly, quarterly, mapping)
            kicox.to_csv(OUT_QA / "kicox_coverage.csv", index=False, encoding="utf-8-sig")
            comparison = business_comparison(monthly, kicox)
            comparison.to_csv(OUT_QA / "business_type_comparison.csv", index=False, encoding="utf-8-sig")
        month_audit_df = pd.read_csv(OUT_QA / "month_coverage.csv", encoding="utf-8-sig")
        kicox = pd.read_csv(OUT_QA / "kicox_coverage.csv", encoding="utf-8-sig")
        comparison = pd.read_csv(OUT_QA / "business_type_comparison.csv", encoding="utf-8-sig")
        source_choice = dict(zip(month_audit_df["period"], month_audit_df["selected_source"].fillna("")))
        conflict_path = OUT_QA / "conflicting_duplicate_rows.csv"
        conflict_rows = pd.read_csv(conflict_path, encoding="utf-8-sig") if conflict_path.exists() else pd.DataFrame()
        conflict_key = ["period", "district", "legal_dong", "ksic_major_code", "ksic_mid_code"]
        duplicate_info = {
            "exact_duplicate_rows_removed": 0,
            "conflicting_duplicate_source_rows": int(len(conflict_rows)),
            "conflicting_duplicate_keys_resolved_as_incomplete": int(
                conflict_rows[conflict_key].drop_duplicates().shape[0]) if len(conflict_rows) else 0,
        }
        monthly_columns = list(monthly.columns)
    else:
        inventory, sheet_inventory, extracted, tokens = scan_workbooks(targets)
        inventory_df = pd.DataFrame(inventory)
        sheets_df = pd.DataFrame(sheet_inventory)
        inventory_df.to_csv(OUT_QA / "raw_file_inventory.csv", index=False, encoding="utf-8-sig")
        sheets_df.to_csv(OUT_QA / "raw_sheet_inventory.csv", index=False, encoding="utf-8-sig")
        pd.DataFrame([
            {"field": field, "token": token, "count": count}
            for (field, token), count in sorted(tokens.items())
        ]).to_csv(OUT_QA / "nonnumeric_tokens.csv", index=False, encoding="utf-8-sig")
        if args.inventory_only:
            return 0

        source_choice, monthly, month_audit = choose_month_sources(inventory, extracted)
        monthly = attach_mapping(monthly, mapping)
        monthly, duplicate_info = validate_and_dedupe_monthly(monthly)
        quarterly = build_quarterly(monthly)

        monthly_columns = ["period", "district", "legal_dong", "ksic_major_code", "ksic_major_name",
                           "ksic_mid_code", "ksic_mid_name", "kicox_industry", "mapping_grade",
                           "mapping_type", "mapping_rationale", "customer_count", "power_usage",
                           "charge_won", "suppression_flag", "missing_flag", "coverage_flag",
                           "source_file", "source_sheet", "source_row_count"]
        monthly[monthly_columns].to_csv(
            OUT_DATA / "legal_dong_ksic_monthly_panel.csv", index=False, encoding="utf-8-sig")
        quarterly.to_csv(
            OUT_DATA / "legal_dong_ksic_quarterly_panel.csv", index=False, encoding="utf-8-sig")

        month_audit_df = pd.DataFrame(month_audit)
        month_audit_df.to_csv(OUT_QA / "month_coverage.csv", index=False, encoding="utf-8-sig")
        by_month, by_ksic, by_dong = suppression_tables(monthly)
        by_month.to_csv(OUT_QA / "suppression_by_month.csv", index=False, encoding="utf-8-sig")
        by_ksic.to_csv(OUT_QA / "suppression_by_ksic.csv", index=False, encoding="utf-8-sig")
        by_dong.to_csv(OUT_QA / "suppression_by_legal_dong.csv", index=False, encoding="utf-8-sig")

        kicox = kicox_coverage(monthly, quarterly, mapping)
        kicox.to_csv(OUT_QA / "kicox_coverage.csv", index=False, encoding="utf-8-sig")
        comparison = business_comparison(monthly, kicox)
        comparison.to_csv(OUT_QA / "business_type_comparison.csv", index=False, encoding="utf-8-sig")
        dense[["gu", "legal_dong"]].sort_values(["gu", "legal_dong"]).to_csv(
            OUT_QA / "proxy_legal_dong_18.csv", index=False, encoding="utf-8-sig")

    post = read_baseline()
    intended_cols = set(monthly_columns) | set(quarterly.columns)
    triage_cols = {"stage", "E", "R", "A", "P"}
    raw_unchanged = baseline["raw_hashes"] == post["raw_hashes"]
    business_unchanged = baseline["business_hashes"] == post["business_hashes"]
    decision_unchanged = baseline["decision_hash"] == post["decision_hash"]
    counts_unchanged = (baseline["decision_rows"] == post["decision_rows"] == 180
                        and baseline["stage_counts"] == post["stage_counts"]
                        and post["stage_counts"] == {"관찰": 128, "추가확인": 35, "우선점검": 17})
    final_key_dups = int(monthly.duplicated(
        ["period", "district", "legal_dong", "ksic_major_code", "ksic_mid_code"]
    ).sum())
    suppression_zero_confusion = int(monthly.loc[monthly["suppression_flag"].eq(1), "power_usage"].eq(0).sum())
    q_complete = quarterly[quarterly["coverage_flag"].eq("COMPLETE")]
    monthly_lookup = monthly.assign(quarter=monthly["period"].map(quarter_of))
    monthly_sums = (monthly_lookup.groupby(
        ["quarter", "district", "legal_dong", "ksic_major_code", "ksic_mid_code"], dropna=False
    )["power_usage"].sum(min_count=3))
    flow_ok = True
    for row in q_complete.itertuples(index=False):
        key = (row.period, row.district, row.legal_dong, row.ksic_major_code, row.ksic_mid_code)
        value = monthly_sums.get(key)
        if pd.isna(value) or not math.isclose(float(value), float(row.power_usage), rel_tol=0, abs_tol=1e-8):
            flow_ok = False
            break
    xlsx_scope = inventory_df["in_scope"].eq(True) & inventory_df["extension"].eq(".xlsx")
    checks = {
        "raw_files_unchanged": {"pass": raw_unchanged, "detail": f"{len(post['raw_hashes'])} files"},
        "xlsx_files_readable": {"pass": bool(inventory_df.loc[xlsx_scope, "read_success"].fillna(False).all()), "detail": f"{int(inventory_df.loc[xlsx_scope, 'read_success'].fillna(False).sum())}/{int(xlsx_scope.sum())} in-scope XLSX files"},
        "final_month_source_unique": {"pass": monthly.groupby("period")["source_file"].nunique().le(1).all(), "detail": source_choice},
        "final_duplicate_rows_absent": {"pass": final_key_dups == 0, "detail": final_key_dups},
        "strict_legal_dong_normalization": {"pass": monthly[["district", "legal_dong"]].drop_duplicates().shape[0] <= 18 and set(zip(monthly["district"].map(norm_text), monthly["legal_dong"].map(norm_text))).issubset(targets), "detail": int(monthly[["district", "legal_dong"]].drop_duplicates().shape[0])},
        "suppression_not_zero": {"pass": suppression_zero_confusion == 0, "detail": suppression_zero_confusion},
        "quarterly_power_flow_sum": {"pass": flow_ok, "detail": f"checked {len(q_complete)} COMPLETE rows"},
        "customer_count_not_summed": {"pass": {"customer_count_qe", "customer_count_mean"}.issubset(quarterly.columns) and "customer_count" not in quarterly.columns, "detail": "quarter-end and mean only"},
        "crosswalk_version_recorded": {"pass": bool(crosswalk_hash), "detail": crosswalk_hash},
        "proxy_18_unchanged": {"pass": len(targets) == 18, "detail": proxy_hash},
        "triage_counts_unchanged": {"pass": counts_unchanged, "detail": post["stage_counts"]},
        "decision_panel_hash_unchanged": {"pass": decision_unchanged, "detail": post["decision_hash"]},
        "triage_columns_absent": {"pass": not bool(triage_cols & intended_cols), "detail": sorted(triage_cols & intended_cols)},
        "business_type_outputs_unchanged": {"pass": business_unchanged, "detail": post["business_hashes"]},
    }
    qa = {"pre": baseline, "post": post, "duplicate_resolution": duplicate_info, "checks": checks}
    (OUT_QA / "qa_results.json").write_text(
        json.dumps(qa, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")

    available = month_audit_df[month_audit_df["status"].isin(["AVAILABLE", "DUPLICATE_RESOLVED"])]
    all_kicox = int((kicox["available_month_count"] > 0).sum()) == 10
    any_complete = int(kicox["complete_quarter_count"].sum()) > 0
    q2_available = bool(kicox["available_2026Q2"].all())
    candidate_status = "SUPPLEMENTARY_CRITERION_CANDIDATE" if all_kicox and any_complete else "CONTEXT_ONLY"
    if all_kicox and any_complete and q2_available and not (kicox["mapping_grade"] == "C").any():
        candidate_status = "CORE_CRITERION_CANDIDATE"
    conclusion = (
        "법정동×KSIC 자료는 코드 기반 업종 정의와 공간 해상도에서 기존 businessType 방식보다 개선됐지만, "
        "18개 법정동 proxy·B/C등급 매핑·비식별·2026Q2 미확보 때문에 현재는 보조 기준 후보가 적절하다."
        if candidate_status == "SUPPLEMENTARY_CRITERION_CANDIDATE" else
        "법정동×KSIC 자료는 기존 businessType보다 업종 정의와 공간단위가 개선되고 10업종을 모두 관측하지만, 비식별 때문에 업종 합계 기준 COMPLETE 분기가 없어 현재는 맥락자료로만 적합하다."
    )
    stats = {
        "candidate_status": candidate_status,
        "one_line_conclusion": conclusion,
        "first_month": monthly["period"].min(),
        "last_month": monthly["period"].max(),
        "expected_months": len(month_audit_df),
        "available_months": len(available),
        "missing_months": int(month_audit_df["status"].eq("MISSING").sum()),
        "monthly_rows": len(monthly),
        "quarterly_rows": len(quarterly),
        "suppression_rate": float(monthly["suppression_flag"].mean()),
        "missing_rate": float(monthly["missing_flag"].mean()),
        "observed_proxy_dongs": int(monthly[["district", "legal_dong"]].drop_duplicates().shape[0]),
    }
    metadata = {
        "run_date": datetime.now().astimezone().isoformat(timespec="seconds"),
        "series": "KEPCO 산업분류별-법정동별 전력데이터",
        "source_directory": str(RAW.relative_to(ROOT)),
        "source_download_performed": False,
        "spatial_scope": "창원 제조업 집적 법정동 proxy 18개 (창원국가산단 경계 아님)",
        "spatial_reference": str(SPATIAL.relative_to(ROOT)),
        "spatial_reference_sha256": sha256_file(SPATIAL),
        "proxy_key_sha256": proxy_hash,
        "crosswalk": str(CROSSWALK.relative_to(ROOT)),
        "crosswalk_sha256": crosswalk_hash,
        "crosswalk_source_label": sorted(cw["source"].unique().tolist()),
        "period_selection": source_choice,
        "suppression_rule": "5호미만/비식별/비공개/제거 계열 토큰은 null+flag; 0 대체 없음",
        "quarter_rule": "power_usage: three numeric unsuppressed months sum; customer_count: quarter-end and three-month mean, never sum",
        "stats": stats,
    }
    (OUT_QA / "run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    write_report(stats, kicox, comparison, inventory_df, month_audit_df, qa)

    failed = [k for k, v in checks.items() if not v["pass"]]
    print(f"[ok] monthly={len(monthly):,} quarterly={len(quarterly):,} "
          f"period={stats['first_month']}..{stats['last_month']} status={candidate_status}")
    if failed:
        print(f"[qa-fail] {', '.join(failed)}")
        return 2
    print("[qa] all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
