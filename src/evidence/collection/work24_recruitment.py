"""Work24 목록·공식 산단·공고상태·상세 직무 Gate를 분리한 Recruitment Layer.

네트워크 요청은 수행하지 않는다. 기존 Work24 목록 2,045건, 저장된 상세 10건,
한국산업단지공단 공식 FactoryOn snapshot을 결합한다.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import kicox_factory as factory
from . import work24_current as current

ROOT = Path(__file__).resolve().parents[3]
FACTORY_METADATA = (ROOT / "data/raw/changwon_factory_registry/_metadata/"
                    "changwon_factory_registry_20241231.json")
DIAGNOSTIC_HISTORY = (ROOT / "data/processed/final_model/reference/triage_history/"
                      "original_v3_stages.csv")

JOB_CLASSES = ("CORE_INDUSTRIAL", "INDUSTRIAL_SUPPORT",
               "GENERAL_NONCORE", "UNKNOWN")
COMPLEX_STATUSES = ("CONFIRMED", "POSSIBLE", "UNKNOWN", "NOT_MATCHED")
JOB_RULES = {
    "CORE_INDUSTRIAL": (
        ("production", r"생산(?:직|기술|관리)?"),
        ("machining", r"가공|공작기계|CNC|MCT|연삭|사상"),
        ("assembly", r"조립|용접|취부"),
        ("quality", r"품질(?:관리|보증)?|제품\s*검사|검사원"),
        ("engineering", r"설계|설비|자동화|공정|정비|캐드|CAD"),
        ("manufacturing", r"제조\s*(?:분야|관련|종사|업무)"),
    ),
    "INDUSTRIAL_SUPPORT": (
        ("materials", r"자재|구매|창고"),
        ("logistics", r"물류|출하|공급망"),
        ("delivery", r"납품|배송"),
    ),
    "GENERAL_NONCORE": (
        ("promotion", r"광고|홍보|마케팅"),
        ("general_office", r"일반\s*사무|사무원|총무|행정"),
        ("accounting", r"회계|경리"),
    ),
}
FIELD_WEIGHTS = {"occupation_raw": 5, "occupation_keywords": 4,
                 "job_description_clean": 2, "title": 2, "certificate_raw": 1}
JOB_KEYWORD_RULES = {
    "생산": r"생산|제조", "가공": r"가공|절삭|선반|밀링|연삭|사상",
    "조립": r"조립", "용접": r"용접|취부", "품질·검사": r"품질|검사|검수",
    "설비·정비": r"설비|정비|보전", "설계": r"설계|캐드|CAD",
    "물류·납품": r"물류|출하|납품|배송", "자재": r"자재|구매|창고",
    "사무": r"사무|총무|행정", "회계": r"회계|경리", "홍보·마케팅": r"홍보|마케팅|광고",
}
SKILL_KEYWORD_RULES = {
    "H-MCT": r"H\s*[- ]?MCT", "MCT": r"(?<!H)(?<!H-)(?<!H )MCT", "CNC": r"CNC",
    "CAD/CAM": r"CAD\s*/\s*CAM|CAD|CAM", "PLC": r"PLC",
    "지게차": r"지게차", "전기": r"전기|전장", "도면": r"도면|제도",
    "프레스": r"프레스", "선반": r"선반", "밀링": r"밀링", "용접": r"용접",
}


def _matched_keywords(value: str | None, rules: dict[str, str]) -> str:
    text = value or ""
    return "|".join(label for label, pattern in rules.items()
                    if re.search(pattern, text, re.I))


def _qualification_keywords(value: str | None) -> str:
    text = value or ""
    terms = {match.group(0).strip() for match in re.finditer(
        r"[가-힣A-Za-z0-9·]{0,24}(?:기능사|산업기사|기사|면허|자격증)[가-힣0-9]{0,12}",
        text,
    )}
    return "|".join(sorted(term for term in terms if term))


def _diagnostic_index() -> dict[tuple[str, str], str]:
    if not DIAGNOSTIC_HISTORY.exists():
        raise FileNotFoundError(f"saved diagnostic history missing: {DIAGNOSTIC_HISTORY}")
    rows = _read_csv(DIAGNOSTIC_HISTORY)
    return {(row["industry"], row["quarter"]): row["stage"] for row in rows}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict], fieldnames: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def proxy_complex_gate(row: dict[str, str]) -> tuple[str, str, bool]:
    """창원시 주소 프록시를 공식 확인과 분리한다."""
    status = (row.get("industrial_complex_match_status") or "").strip()
    method = (row.get("industrial_complex_match_method") or "").strip()
    if status == "POSSIBLE":
        return "POSSIBLE", f"기존 {method or '주소 프록시'} 상한 판정", False
    if status in {"NOT_MATCH", "NOT_MATCHED"}:
        return "NOT_MATCHED", f"기존 {method or '주소 프록시'} 비매치", False
    return "UNKNOWN", "기존 주소 근거 부족", False


def normalized_complex_gate(
    row: dict[str, str], official_match: dict | None = None,
) -> tuple[str, str, bool]:
    """공식 exact 회사명+주소만 CONFIRMED, 없으면 공식 결과/프록시를 분리."""
    if official_match:
        return (str(official_match["status"]), str(official_match["basis"]),
                bool(official_match["official_evidence"]))
    return proxy_complex_gate(row)


def classify_job_relevance(detail: dict[str, str] | None) -> dict:
    if not detail or detail.get("request_status") != "SUCCESS":
        return {"job_relevance_class": "UNKNOWN",
                "job_relevance_basis":
                    "DETAIL_NOT_VERIFIED; 목록 공고명만으로 직무를 확정하지 않음",
                "job_relevance_rule_status": "NO_VERIFIED_DETAIL",
                "job_relevance_manual_review": True}
    scores = {name: 0 for name in JOB_RULES}
    evidence: dict[str, list[str]] = {name: [] for name in JOB_RULES}
    field_categories: dict[str, set[str]] = {}
    for field, weight in FIELD_WEIGHTS.items():
        value = detail.get(field) or ""
        for category, rules in JOB_RULES.items():
            for label, pattern in rules:
                if re.search(pattern, value, re.I):
                    scores[category] += weight
                    evidence[category].append(f"{field}:{label}")
                    field_categories.setdefault(field, set()).add(category)
    ranked = sorted(scores, key=scores.get, reverse=True)
    first, second = ranked[0], ranked[1]
    if scores[first] == 0 or scores[first] == scores[second]:
        return {"job_relevance_class": "UNKNOWN",
                "job_relevance_basis": "RULE_V1_AMBIGUOUS; " + "; ".join(
                    f"{name}={scores[name]}" for name in scores),
                "job_relevance_rule_status": "AMBIGUOUS",
                "job_relevance_manual_review": True}
    supporting_fields = {item.split(":", 1)[0] for item in evidence[first]}
    manual_review = (len(supporting_fields) < 2 or
                     len(field_categories.get("occupation_raw", set())) > 1)
    return {"job_relevance_class": first,
            "job_relevance_basis": (
                "RULE_V1_MULTI_FIELD; "
                f"scores={','.join(f'{name}:{scores[name]}' for name in scores)}; "
                f"matched={','.join(evidence[first])}"),
            "job_relevance_rule_status": "MATCHED_REVIEW" if manual_review else "MATCHED",
            "job_relevance_manual_review": manual_review}


def industry_mapping_source(row: dict[str, str]) -> str:
    if row.get("kicox_mapping_status") != "MAPPED":
        return "NO_EXISTING_KICOX_MAPPING"
    parts = [row.get("ksic_source"), row.get("ksic_resolution_method"),
             row.get("kicox_mapping_note")]
    return " | ".join(str(value) for value in parts if value) or "EXISTING_MAPPING"


def posting_activity(row: dict[str, str], as_of: dt.date) -> tuple[str, str]:
    """보유 목록 마감일만으로 현재 유효 여부를 보수적으로 판정한다."""
    due = (row.get("due_date") or "").strip()
    if not due:
        return "ACTIVE_UNKNOWN", "LIST_DUE_DATE_MISSING"
    try:
        due_date = dt.date.fromisoformat(due[:10])
    except ValueError:
        return "ACTIVE_UNKNOWN", "LIST_DUE_DATE_UNPARSEABLE"
    if due_date >= as_of:
        return "ACTIVE", f"LIST_DUE_DATE_ON_OR_AFTER_{as_of.isoformat()}"
    return "EXPIRED", f"LIST_DUE_DATE_BEFORE_{as_of.isoformat()}"


def _official_company_matches(base_rows: list[dict[str, str]],
                              official_rows: list[dict[str, str]]) -> dict[str, dict]:
    companies: dict[str, dict[str, object]] = {}
    for row in base_rows:
        if not (row.get("kicox_mapping_status") == "MAPPED" and
                row.get("kicox_industry") in current.KICOX_INDUSTRIES):
            continue
        key = factory.normalize_company(row.get("company_raw"))
        if not key:
            continue
        entry = companies.setdefault(key, {"name": row.get("company_raw") or "",
                                           "addresses": set()})
        for field in ("workplace_address_enriched", "workplace_address_raw"):
            if row.get(field):
                entry["addresses"].add(row[field])
    return {
        key: factory.match_company(str(entry["name"]), sorted(entry["addresses"]),
                                   official_rows)
        for key, entry in companies.items()
    }


def _title_key(value: str | None) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", value or "").casefold()


def _priority_industries() -> list[str]:
    # current 함수가 최신 triage_latest.csv의 decision_stage를 읽는다.
    return list(current.current_priority_industries())


def aggregate_industries(rows: list[dict]) -> dict[str, dict[str, int]]:
    result = {}
    for industry in current.KICOX_INDUSTRIES:
        subset = [row for row in rows if row["kicox_industry"] == industry]
        confirmed = [row for row in subset
                     if row["industrial_complex_match_status"] == "CONFIRMED"]
        result[industry] = {
            "mapped_postings": len(subset),
            "unique_companies": len({factory.normalize_company(row["company_name"])
                                     for row in subset}),
            "official_confirmed_postings": len(confirmed),
            "official_confirmed_companies": len({
                factory.normalize_company(row["company_name"]) for row in confirmed}),
        }
    return result


def build_recruitment_layer(
    date_stamp: str = "20260923", *, shared_raw_root: Path | None = None,
) -> dict:
    if not re.fullmatch(r"\d{8}", date_stamp):
        raise ValueError("date_stamp must use YYYYMMDD")
    as_of = dt.datetime.strptime(date_stamp, "%Y%m%d").date()
    base_path = current.EXISTING_DATA
    raw_root = Path(shared_raw_root) if shared_raw_root else ROOT / "data/raw"
    detail_path = (raw_root / "work24" /
                   f"work24_priority_industry_detail_{date_stamp}.csv")
    official_path = (raw_root / "kicox/datagokr" /
                     f"kicox_factory_changwon_national_{date_stamp}.csv")
    official_meta_path = (official_path.parent / "_metadata" /
                          f"kicox_factory_changwon_national_{date_stamp}.json")
    output_path = current.PROCESSED_WORK24_DIR / f"work24_recruitment_layer_{date_stamp}.csv"
    queue_path = current.PROCESSED_WORK24_DIR / f"work24_detail_collection_queue_{date_stamp}.csv"
    quality_path = current.PROCESSED_WORK24_DIR / f"work24_recruitment_layer_quality_{date_stamp}.json"
    if not official_path.exists():
        raise FileNotFoundError(f"official KICOX snapshot missing: {official_path}")

    base_rows = _read_csv(base_path)
    detail_rows = _read_csv(detail_path) if detail_path.exists() else []
    official_rows = _read_csv(official_path)
    detail_by_id = {row["wanted_auth_no"]: row for row in detail_rows}
    if len(detail_by_id) != len(detail_rows):
        raise RuntimeError("detail snapshot contains duplicate wanted_auth_no")
    company_matches = _official_company_matches(base_rows, official_rows)
    priority_industries = set(_priority_industries())
    diagnostic_stages = _diagnostic_index()
    diagnostic_quarter = "2026Q2"

    rows: list[dict] = []
    base_by_id = {row["wanted_auth_no"]: row for row in base_rows}
    for base in base_rows:
        wanted = base["wanted_auth_no"]
        detail = detail_by_id.get(wanted)
        mapped = (base.get("kicox_mapping_status") == "MAPPED" and
                  base.get("kicox_industry") in current.KICOX_INDUSTRIES)
        proxy_status, proxy_basis, _ = proxy_complex_gate(base)
        official_match = company_matches.get(factory.normalize_company(base.get("company_raw"))) \
            if mapped else None
        complex_status, complex_basis, official = normalized_complex_gate(
            base, official_match)
        relevance = classify_job_relevance(detail)
        detail_status = detail.get("request_status") if detail else "NOT_REQUESTED"
        detail_verified = detail_status == "SUCCESS"
        detail_access_status = (
            "accessible" if detail_verified else
            "unknown" if detail_status == "FAILED" else "unknown")
        detail_access_reason = (
            "SAVED_DETAIL_PARSE_SUCCESS" if detail_verified else
            (detail.get("error") or "NO_DETAIL_REQUEST_RECORDED") if detail else "")
        activity_status, activity_basis = posting_activity(base, as_of)
        priority_industry = bool(mapped and base.get("kicox_industry") in priority_industries)
        industry = base.get("kicox_industry") if mapped else ""
        row = {
            "wanted_auth_no": wanted,
            "company_name": base.get("company_raw"),
            "company_official_name": base.get("company_official"),
            "company_match_status": base.get("company_match_status"),
            "posting_title": base.get("title_raw"),
            "source_snapshot_id": base.get("snapshot_id"),
            "source_snapshot_date": (base.get("crawl_timestamp", "")[:10]
                                     if base.get("crawl_timestamp") else ""),
            "registration_date": base.get("reg_date"),
            "due_date": base.get("due_date"),
            "posting_activity_status": activity_status,
            "posting_activity_basis": activity_basis,
            "list_posting_status": base.get("posting_status"),
            "list_region": base.get("region_raw"),
            "list_district": base.get("gu"),
            "list_workplace_address": (base.get("workplace_address_enriched") or
                                       base.get("workplace_address_raw")),
            "kicox_industry": base.get("kicox_industry"),
            "industry_mapping_status": "MAPPED" if mapped else "UNMAPPED",
            "industry_mapping_source": industry_mapping_source(base),
            "ksic_code": base.get("ksic_code"),
            "ksic_name": base.get("ksic_name"),
            "ksic_revision": base.get("ksic_revision"),
            "ksic_resolution_method": base.get("ksic_resolution_method"),
            "diagnostic_quarter": diagnostic_quarter if mapped else "",
            "diagnostic_industry": industry,
            "diagnostic_stage": diagnostic_stages.get((industry, diagnostic_quarter), ""),
            "diagnostic_q1_stage": diagnostic_stages.get((industry, "2026Q1"), ""),
            "diagnostic_q2_stage": diagnostic_stages.get((industry, "2026Q2"), ""),
            "diagnostic_q3_stage": diagnostic_stages.get((industry, "2026Q3"), ""),
            "priority_industry": priority_industry,
            "industrial_complex_proxy_status": proxy_status,
            "industrial_complex_proxy_basis": proxy_basis,
            "industrial_complex_match_status": complex_status,
            "industrial_complex_match_basis": complex_basis,
            "industrial_complex_official_evidence": official,
            "industrial_complex_official_source": (
                official_match.get("official_source", "") if official_match else ""),
            "industrial_complex_factory_id": (
                official_match.get("factory_ids", "") if official_match else ""),
            "industrial_complex_name": (
                official_match.get("industrial_complex_name", "") if official_match else ""),
            **relevance,
            "detail_collection_status": detail_status,
            "detail_verified": detail_verified,
            "detailed_validation_target": False,
            "detail_access_status": detail_access_status,
            "detail_access_reason": detail_access_reason,
            "source_duplicate_group_id": base.get("duplicate_group_id"),
            "source_repost_candidate": base.get("repost_candidate"),
            "source_repost_reason": base.get("repost_reason"),
            "regional_core_metric_eligible": bool(
                mapped and detail_verified and relevance["job_relevance_class"] == "CORE_INDUSTRIAL"),
            "regional_support_metric_eligible": bool(
                mapped and detail_verified and relevance["job_relevance_class"] == "INDUSTRIAL_SUPPORT"),
            "national_complex_core_metric_eligible": bool(
                mapped and official and detail_verified and
                relevance["job_relevance_class"] == "CORE_INDUSTRIAL"),
            "recruitment_count_raw": detail.get("recruitment_count_raw") if detail else None,
            "recruitment_count": detail.get("recruitment_count") if detail else None,
            "occupation_raw": detail.get("occupation_raw") if detail else None,
            "list_occupation_raw": base.get("occupation"),
            "list_cert_marker": base.get("cert_raw"),
            "occupation_keywords": detail.get("occupation_keywords") if detail else None,
            "title_job_keyword": _matched_keywords(base.get("title_raw"), JOB_KEYWORD_RULES),
            "title_skill_keyword": _matched_keywords(base.get("title_raw"), SKILL_KEYWORD_RULES),
            "occupation_job_keyword": _matched_keywords(base.get("occupation"), JOB_KEYWORD_RULES),
            "detail_job_keyword": _matched_keywords(
                " ".join((detail.get("occupation_raw") or "", detail.get("job_description_clean") or ""))
                if detail else "", JOB_KEYWORD_RULES),
            "detail_skill_keyword": _matched_keywords(
                " ".join((detail.get("occupation_raw") or "", detail.get("job_description_clean") or ""))
                if detail else "", SKILL_KEYWORD_RULES),
            "detail_qualification_keyword": _qualification_keywords(
                detail.get("certificate_raw") if detail else ""),
            "job_description_raw": detail.get("job_description_raw") if detail else None,
            "job_description_clean": detail.get("job_description_clean") if detail else None,
            "career": detail.get("career") if detail else None,
            "education": detail.get("education") if detail else None,
            "certificate_raw": detail.get("certificate_raw") if detail else None,
            "employment_type": detail.get("employment_type") if detail else None,
            "wage": detail.get("wage") if detail else None,
            "workplace_address": detail.get("workplace_address") if detail else None,
            "detail_district": detail.get("district") if detail else None,
            "detail_registered_at": detail.get("registered_at") if detail else None,
            "detail_closing_date": detail.get("closing_date") if detail else None,
            "list_source_url": base.get("source_url"),
            "detail_source_url": (detail.get("source_url") if detail else
                                  current.current_detail_url(wanted)),
        }
        rows.append(row)

    # Exact same company/title/registration-date만 중복으로 접고, repost 후보는 접지 않는다.
    eligible_groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        eligible = (row["industry_mapping_status"] == "MAPPED" and
                    row["industrial_complex_match_status"] == "CONFIRMED" and
                    row["priority_industry"] and
                    row["posting_activity_status"] == "ACTIVE")
        row["detail_candidate_before_dedup"] = eligible
        row["detail_needed"] = False
        row["detail_needed_reason"] = "OUTSIDE_CONFIRMED_PRIORITY_ACTIVE_FUNNEL"
        if eligible:
            key = (factory.normalize_company(row["company_name"]),
                   _title_key(row["posting_title"]), row["registration_date"] or "")
            eligible_groups[key].append(row)
    exact_duplicate_groups = 0
    exact_duplicate_rows_removed = 0
    for group in eligible_groups.values():
        verified = [row for row in group if row["detail_collection_status"] == "SUCCESS"]
        if len(group) > 1:
            exact_duplicate_groups += 1
            exact_duplicate_rows_removed += len(group) - 1
        if verified:
            for row in group:
                row["detail_needed_reason"] = "EXACT_NATURAL_KEY_ALREADY_DETAIL_VERIFIED"
            continue
        representative = sorted(group, key=lambda row: row["wanted_auth_no"])[0]
        representative["detail_needed"] = True
        representative["detailed_validation_target"] = True
        representative["detail_access_status"] = "list_only"
        representative["detail_access_reason"] = (
            "NOT_REQUESTED_PENDING_KEIS_COORDINATION_FOR_BULK_OR_SPECIAL_USE")
        representative["detail_needed_reason"] = "CONFIRMED_PRIORITY_ACTIVE_MINIMUM_CANDIDATE"
        for row in group[1:]:
            row["detail_needed_reason"] = "EXACT_NATURAL_KEY_DUPLICATE_OF_MINIMUM_CANDIDATE"

    _write_csv(output_path, rows, tuple(rows[0].keys()))

    queue_rows = []
    for row in rows:
        if row["industry_mapping_status"] != "MAPPED":
            continue
        if row["detail_needed"]:
            priority, reason = "P1", row["detail_needed_reason"]
        elif row["detail_candidate_before_dedup"]:
            priority, reason = "P2", row["detail_needed_reason"]
        elif (row["industrial_complex_match_status"] == "CONFIRMED" and
              row["priority_industry"]):
            priority = "P3"
            reason = f"CONFIRMED_PRIORITY_BUT_{row['posting_activity_status']}"
        elif row["priority_industry"]:
            priority, reason = "P4", "PRIORITY_INDUSTRY_OFFICIAL_COMPLEX_UNCONFIRMED"
        else:
            priority, reason = "P5", "NON_PRIORITY_KICOX_MAPPING"
        queue_rows.append({
            "wanted_auth_no": row["wanted_auth_no"],
            "kicox_industry": row["kicox_industry"],
            "industrial_complex_match_status": row["industrial_complex_match_status"],
            "priority_industry": row["priority_industry"],
            "posting_activity_status": row["posting_activity_status"],
            "job_relevance_class": row["job_relevance_class"],
            "detail_collection_status": row["detail_collection_status"],
            "detailed_validation_target": row["detailed_validation_target"],
            "detail_access_status": row["detail_access_status"],
            "detail_access_reason": row["detail_access_reason"],
            "detail_needed": row["detail_needed"],
            "detail_priority": priority,
            "duplicate_group_id": row["source_duplicate_group_id"],
            "repost_candidate": row["source_repost_candidate"],
            "reason": reason,
            "http_collection_authorized": False,
        })
    order = {name: index for index, name in enumerate(current.KICOX_INDUSTRIES)}
    queue_rows.sort(key=lambda row: (
        row["detail_priority"], order[row["kicox_industry"]], row["wanted_auth_no"]))
    _write_csv(queue_path, queue_rows, tuple(queue_rows[0].keys()))

    mapped_rows = [row for row in rows if row["industry_mapping_status"] == "MAPPED"]
    confirmed = [row for row in mapped_rows
                 if row["industrial_complex_match_status"] == "CONFIRMED"]
    confirmed_priority = [row for row in confirmed if row["priority_industry"]]
    confirmed_priority_active = [row for row in confirmed_priority
                                 if row["posting_activity_status"] == "ACTIVE"]
    detail_needed = [row for row in rows if row["detail_needed"]]
    validation_targets = [row for row in rows if row["detailed_validation_target"]]
    company_identifiable = [row for row in base_rows
                            if row.get("company_match_status") in {"MATCH", "MULTI"}]
    ksic_resolved = [row for row in base_rows
                     if row.get("ksic_resolution_method") == "COMPANY_MASTER_EXACT"]
    diagnostic_joined = [row for row in mapped_rows
                         if row.get("diagnostic_stage")]
    detail_sample = [row for row in mapped_rows if row["detail_verified"]]

    def terms_count(records: list[dict], field: str) -> dict[str, int]:
        counts: Counter[str] = Counter()
        for record in records:
            counts.update({term for term in (record.get(field) or "").split("|") if term})
        return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))

    detail_observations = {}
    for industry in current.KICOX_INDUSTRIES:
        sample = [row for row in detail_sample if row["kicox_industry"] == industry]
        detail_observations[industry] = {
            "verified_postings": len(sample),
            "job_relevance_classes": dict(Counter(row["job_relevance_class"] for row in sample)),
            "detail_job_keywords": terms_count(sample, "detail_job_keyword"),
            "detail_skill_keywords": terms_count(sample, "detail_skill_keyword"),
            "detail_qualification_keywords": terms_count(sample, "detail_qualification_keyword"),
            "career_observed": sum(bool(row.get("career")) for row in sample),
            "wage_observed": sum(bool(row.get("wage")) for row in sample),
            "recruitment_count_observed": sum(bool(row.get("recruitment_count")) for row in sample),
        }
    complex_counts = Counter(row["industrial_complex_match_status"] for row in mapped_rows)
    complex_status_summary = {
        status: {
            "postings": complex_counts.get(status, 0),
            "unique_companies": len({
                factory.normalize_company(row["company_name"])
                for row in mapped_rows
                if row["industrial_complex_match_status"] == status
            }),
        }
        for status in COMPLEX_STATUSES
    }
    proxy_crosstab = {
        status: {
            "official_confirmed": sum(
                row["industrial_complex_proxy_status"] == status and
                row["industrial_complex_match_status"] == "CONFIRMED"
                for row in mapped_rows),
            "official_unconfirmed": sum(
                row["industrial_complex_proxy_status"] == status and
                row["industrial_complex_match_status"] != "CONFIRMED"
                for row in mapped_rows),
        }
        for status in ("POSSIBLE", "UNKNOWN", "NOT_MATCHED")
    }
    industry_stats = aggregate_industries(mapped_rows)
    priority_summary = {
        industry: {
            **industry_stats[industry],
            "official_confirmed_active_postings": sum(
                row["kicox_industry"] == industry
                and row["industrial_complex_match_status"] == "CONFIRMED"
                and row["posting_activity_status"] == "ACTIVE"
                for row in mapped_rows),
            "final_detail_needed": sum(
                row["kicox_industry"] == industry and row["detail_needed"]
                for row in mapped_rows),
        }
        for industry in sorted(priority_industries)
    }
    serialized = "\n".join(str(value) for row in rows for value in row.values()
                           if value not in (None, ""))
    official_meta = json.loads(official_meta_path.read_text(encoding="utf-8"))
    quality = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "inputs": {
            "list_dataset": base_path.relative_to(ROOT).as_posix(),
            "detail_snapshot": f"data/raw/work24/{detail_path.name}",
            "official_factory_snapshot": f"data/raw/kicox/datagokr/{official_path.name}",
            "official_factory_metadata": (
                f"data/raw/kicox/datagokr/_metadata/{official_meta_path.name}"),
            "shared_raw_root_used": bool(shared_raw_root),
        },
        "priority_industries": sorted(priority_industries),
        "priority_industry_summary": priority_summary,
        "industry_counts": industry_stats,
        "validation": {
            "list_total": len(rows), "mapped_total": len(mapped_rows),
            "industry_count_sum": sum(v["mapped_postings"] for v in industry_stats.values()),
            "all_ten_industries_present_in_axis": len(industry_stats) == 10,
            "wanted_auth_no_duplicates": len(rows) - len({r["wanted_auth_no"] for r in rows}),
            "detail_verified_total": sum(row["detail_verified"] for row in rows),
            "privacy_phone_hits": len(current.PHONE_RE.findall(serialized)),
            "privacy_email_hits": len(current.EMAIL_RE.findall(serialized)),
            "work24_detail_http_requests_this_run": 0,
            "official_factory_rows": len(official_rows),
            "official_factory_unique_ids": len({r["factory_id"] for r in official_rows}),
            "official_factory_exact_complex_rows": sum(
                r["industrial_complex_name"] == factory.OFFICIAL_COMPLEX_NAME
                for r in official_rows),
            "api_key_exposed": False,
        },
        "industrial_complex_gate": {
            "status_counts_mapped_only": {name: complex_counts.get(name, 0)
                                           for name in COMPLEX_STATUSES},
            "status_summary_mapped_only": complex_status_summary,
            "confirmed_definition":
                "official factory registration in Changwon National Industrial Complex",
            "official_source": factory.SOURCE_ID,
            "official_snapshot": {key: official_meta.get(key) for key in (
                "collected_at", "api_total_count", "rows", "unique_factories",
                "unique_companies", "operation", "query_parameter", "query_value")},
            "proxy_crosstab": proxy_crosstab,
        },
        "job_relevance_gate": {
            "status_counts_mapped_only": dict(Counter(
                row["job_relevance_class"] for row in mapped_rows)),
            "classified_detail_only": True,
            "list_title_only_classification_disabled": True,
        },
        "posting_activity": {
            "as_of": as_of.isoformat(),
            "status_counts_mapped_only": dict(Counter(
                row["posting_activity_status"] for row in mapped_rows)),
            "basis": "stored Work24 list due_date only; no additional detail request",
        },
        "detail_target_funnel": {
            "A_kicox_mapped": len(mapped_rows),
            "B_official_complex_confirmed": len(confirmed),
            "C_latest_priority_industries": len(confirmed_priority),
            "D_currently_active": len(confirmed_priority_active),
            "M_final_validation_targets_requiring_detail_check": len(validation_targets),
            "E_remaining_detail_needed": len(detail_needed),
            "already_detail_verified_excluded_from_M": sum(
                row["detail_verified"] for row in confirmed_priority_active),
            "exact_natural_key_duplicate_groups": exact_duplicate_groups,
            "exact_natural_key_rows_removed": exact_duplicate_rows_removed,
            "existing_detail_success_removed": sum(
                row["detail_collection_status"] == "SUCCESS"
                for row in confirmed_priority_active),
            "repost_candidate_not_auto_collapsed": sum(
                str(row["source_repost_candidate"]).lower() == "true"
                for row in confirmed_priority_active),
        },
        "data_funnel": [
            {"stage": "all_changwon_list_postings", "start": len(base_rows),
             "remain": len(base_rows), "excluded": 0, "reason": "기존 5개 구 processed 목록"},
            {"stage": "company_identifiable", "start": len(base_rows),
             "remain": len(company_identifiable),
             "excluded": len(base_rows) - len(company_identifiable),
             "reason": "회사 마스터 MATCH/MULTI 외 NO_MATCH"},
            {"stage": "exact_ksic", "start": len(company_identifiable),
             "remain": len(ksic_resolved),
             "excluded": len(company_identifiable) - len(ksic_resolved),
             "reason": "사업체 마스터 COMPANY_MASTER_EXACT만 포함"},
            {"stage": "kicox_industry_mapped", "start": len(ksic_resolved),
             "remain": len(mapped_rows), "excluded": len(ksic_resolved) - len(mapped_rows),
             "reason": "KSIC→KICOX 공식 crosswalk 미연결"},
            {"stage": "official_national_complex_confirmed", "start": len(mapped_rows),
             "remain": len(confirmed), "excluded": len(mapped_rows) - len(confirmed),
             "reason": "POSSIBLE 79, UNKNOWN 327; 공식 일치 근거만 CONFIRMED"},
            {"stage": "saved_diagnostic_join_2026Q2", "start": len(mapped_rows),
             "remain": len(diagnostic_joined), "excluded": len(mapped_rows) - len(diagnostic_joined),
             "reason": "기존 진단 stage를 산업코드로 조인; 판정 재계산 없음"},
            {"stage": "latest_priority_industries", "start": len(confirmed),
             "remain": len(confirmed_priority),
             "excluded": len(confirmed) - len(confirmed_priority),
             "reason": "최신 저장 진단의 기계·목재종이만"},
            {"stage": "active_as_of_snapshot", "start": len(confirmed_priority),
             "remain": len(confirmed_priority_active),
             "excluded": len(confirmed_priority) - len(confirmed_priority_active),
             "reason": "목록 마감일이 2026-09-23 이후인 공고"},
            {"stage": "final_validation_targets_M", "start": len(confirmed_priority_active),
             "remain": len(validation_targets),
             "excluded": len(confirmed_priority_active) - len(validation_targets),
             "reason": "이미 상세검증된 1건 제외; 중복 0건, 재공고 후보 자동병합 없음"},
        ],
        "diagnostic_join": {
            "quarter": diagnostic_quarter,
            "industry_joined_postings": len(diagnostic_joined),
            "stage_counts": dict(Counter(row["diagnostic_stage"] for row in diagnostic_joined)),
            "priority_industries": sorted(priority_industries),
            "q1_q2_states_attached": True,
            "q3_state_available": any(row.get("diagnostic_q3_stage") for row in mapped_rows),
        },
        "detail_access_status_in_M": dict(Counter(
            row["detail_access_status"] for row in validation_targets)),
        "detail_request_gate": {
            "additional_requests_made": 0,
            "additional_requests_authorized": False,
            "reason": ("Existing official terms reserve mass/special use for separate agreement; "
                       "clarify KEIS coordination before making further automated detail requests. "
                       "list_only means not requested, not a server denial."),
        },
        "keyword_provenance": {
            "title_job_skill_source": "title_raw only",
            "occupation_job_source": "list occupation only; null when absent",
            "detail_job_skill_source": "verified detail occupation_raw + job_description_clean only",
            "detail_qualification_source": "verified detail certificate_raw only",
            "list_cert_raw_semantics": "[인증] listing marker; not qualification text",
            "detail_sample_size": len(detail_sample),
            "title_job_keyword_counts": terms_count(rows, "title_job_keyword"),
            "title_skill_keyword_counts": terms_count(rows, "title_skill_keyword"),
            "occupation_job_keyword_counts": terms_count(rows, "occupation_job_keyword"),
        },
        "detail_sample_observations_by_industry": detail_observations,
        "queue": {
            "rows": len(queue_rows),
            "detail_needed": len(detail_needed),
            "priority_counts": dict(Counter(r["detail_priority"] for r in queue_rows)),
            "http_collection_authorized": False,
            "note": "detail_priority is analysis ordering, not HTTP permission",
        },
        "artifacts": {
            "recruitment_layer": output_path.relative_to(ROOT).as_posix(),
            "detail_queue": queue_path.relative_to(ROOT).as_posix(),
            "quality": quality_path.relative_to(ROOT).as_posix(),
        },
    }
    quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    return quality


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--date-stamp", default="20260923")
    parser.add_argument("--shared-raw-root", type=Path,
                        help="기존 저장소의 data/raw 경로를 읽기 전용으로 재사용")
    args = parser.parse_args(argv)
    print(json.dumps(build_recruitment_layer(args.date_stamp,
                                             shared_raw_root=args.shared_raw_root),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
