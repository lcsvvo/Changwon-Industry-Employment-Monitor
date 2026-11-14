"""Work24 정규화 결과를 모형과 분리된 append-only External Evidence로 등록한다."""
from __future__ import annotations

import csv
import hashlib
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import select

from workflow import models as M

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "data/processed/work24/work24_analysis_ready.csv"
DERIVATION_VERSION = "recruitment-context/1.0.0"
# cert_raw 는 센터 목록의 ``[인증]`` 표식일 뿐 자격면허 텍스트가 아니다.
# 현행 상세 보강이 붙기 전에는 제목과 실제 직종명만 기술 텍스트로 사용한다.
TEXT_FIELDS = ("title_raw", "occupation")

# 공고 제목의 채용 관용어와 목록 화면 표식을 기술수요로 오인하지 않는다.
STOPWORDS = {
    "모집", "채용", "구인", "사원", "직원", "신입", "경력", "경력직", "정규직", "계약직",
    "업무", "담당", "관련", "가능", "무관", "우대", "급구", "긴급", "공고", "재공고",
    "주식회사", "유한회사", "창원", "창원시", "경남", "이상", "이하", "및", "에서",
    "생산", "현장", "관리", "작업", "지원", "주간", "야간", "교대", "인증",
}
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#.-]{1,}|[가-힣]{2,}")


def _display_term(term: str) -> str:
    return term.upper() if re.fullmatch(r"[a-z][a-z0-9+#.-]*", term) else term


def _tokens(row: dict) -> list[str]:
    text = " ".join(str(row.get(field) or "") for field in TEXT_FIELDS)
    # 제목 앞 회사명이 키워드가 되지 않도록 확인 가능한 회사 표기만 제거한다.
    for field in ("company_raw", "company_official", "normalized_company"):
        company = str(row.get(field) or "").strip()
        if company:
            text = text.replace(company, " ")
    text = re.sub(r"\[[^]]*]", " ", text)
    terms = []
    for match in TOKEN_RE.finditer(text.lower()):
        token = match.group(0).strip(".-")
        if (len(token) < 2 or token in STOPWORDS or token.isdigit()
                or token.startswith(("모집", "채용", "구인"))
                or token.endswith(("합니다", "하세요", "바랍니다"))):
            continue
        terms.append(token)
    return terms


def extract_recruitment_keywords(rows: list[dict], top_n: int = 20) -> list[dict]:
    """실제 목록 텍스트의 재현 가능한 unigram/bigram 빈도 순위.

    형태소 분석을 가장한 추정은 하지 않는다. 한 공고 안의 중복은 한 번만 세고,
    빈도 동률은 문자열 순으로 고정해 같은 입력에서 결과가 항상 같다.
    """
    counts: Counter[str] = Counter()
    documents: Counter[str] = Counter()
    for row in rows:
        tokens = _tokens(row)
        candidates = list(tokens)
        candidates.extend(f"{a} {b}" for a, b in zip(tokens, tokens[1:]) if a != b)
        counts.update(candidates)
        documents.update(set(candidates))
    ranked = []
    total_docs = max(1, len(rows))
    for term, count in counts.items():
        # 한 번만 나타난 긴 꼬리표현은 Top-N 기술수요로 올리지 않는다.
        if count < 2:
            continue
        doc_count = documents[term]
        score = count * (1.0 + math.log((total_docs + 1) / (doc_count + 1)))
        ranked.append({
            "term": _display_term(term), "count": int(count),
            "document_count": int(doc_count), "score": round(score, 6),
        })
    ranked.sort(key=lambda item: (-item["score"], -item["count"], item["term"]))
    return ranked[:top_n]


def _career_distribution(rows: list[dict]) -> dict:
    values = Counter((row.get("career_type") or "UNKNOWN").strip() or "UNKNOWN" for row in rows)
    return dict(sorted(values.items()))


def _quarter(date: str) -> str:
    year, month = int(date[:4]), int(date[5:7])
    return f"{year}Q{(month - 1) // 3 + 1}"


def register_work24_snapshot(Session, source_path: Path = DEFAULT_SOURCE) -> dict:
    """새 원자료 해시만 추가한다. 기존 스냅샷 행은 수정·삭제하지 않는다."""
    source_path = Path(source_path)
    raw = source_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("Work24 분석 입력이 비어 있습니다.")
    base_id = rows[0]["snapshot_id"]
    # 원자료 해시와 파생계약을 함께 식별한다. 파생 로직이 바뀌어도 이전 스냅샷은 덮어쓰지 않는다.
    snapshot_id = f"{base_id}@{digest[:12]}-rc1"
    collected = {r["crawl_timestamp"] for r in rows}
    quarters = {_quarter(r["reg_date"]) for r in rows if r.get("reg_date")}
    if len(collected) != 1 or len(quarters) != 1:
        raise ValueError("단일 수집시각·등록분기 스냅샷만 등록할 수 있습니다.")
    collected_at, quarter = next(iter(collected)), next(iter(quarters))
    with Session() as s:
        existing = s.scalar(select(M.Work24EvidenceSnapshot).where(
            M.Work24EvidenceSnapshot.snapshot_id == snapshot_id).limit(1))
        if existing:
            return {"snapshot_id": snapshot_id, "status": "EXISTS", "rows": len(rows),
                    "quarter": quarter, "company_matches": sum(r.get("company_match_status") == "MATCH" for r in rows),
                    "kicox_mapped": sum(bool(r.get("kicox_industry")) for r in rows),
                    "headcount_coverage_pct": 0.0, "model_input_allowed": False}

    grouped = defaultdict(list)
    for row in rows:
        grouped[row.get("kicox_industry") or "UNMAPPED"].append(row)
    source_ref = source_path.relative_to(ROOT).as_posix() if source_path.is_relative_to(ROOT) else str(source_path)
    with Session.begin() as s:
        for industry, records in sorted(grouped.items()):
            companies = {r.get("normalized_company") for r in records if r.get("normalized_company")}
            districts = Counter(r.get("gu") or "UNKNOWN" for r in records)
            titles = Counter(r.get("title_raw") or "UNKNOWN" for r in records)
            keywords = extract_recruitment_keywords(records)
            latest_registration_date = max((r.get("reg_date") or "" for r in records), default="") or None
            available_text_fields = [
                field for field in TEXT_FIELDS if any((r.get(field) or "").strip() for r in records)
            ]
            s.add(M.Work24EvidenceSnapshot(
                snapshot_id=snapshot_id, quarter=quarter, collected_at=collected_at,
                source="Work24 공개 채용공고(사후 채용시장 맥락)", source_file=source_ref,
                data_hash=digest, industry=industry, posting_count=len(records),
                unique_company_count=len(companies),
                new_posting_count=sum(r.get("posting_status") == "NEW" for r in records),
                active_posting_count=len(records), headcount=None,
                district_distribution=dict(sorted(districts.items())),
                title_distribution=dict(titles.most_common(20)),
                skill_keyword_distribution={item["term"]: item["count"] for item in keywords},
                latest_registration_date=latest_registration_date,
                career_distribution=_career_distribution(records),
                keyword_method="normalized unigram/bigram frequency; per-posting de-duplication",
                source_text_fields=available_text_fields,
                derivation_version=DERIVATION_VERSION,
                model_input_allowed=False))
        for row in rows:
            s.add(M.Work24EvidenceItem(
                snapshot_id=snapshot_id, posting_id=row["wanted_auth_no"],
                company=row.get("company_official") or row.get("company_raw") or None,
                district=row.get("gu") or None, industry=row.get("kicox_industry") or None,
                title=row.get("title_raw") or "", registered_date=row.get("reg_date") or None,
                closing_date=row.get("due_date") or None, collected_at=collected_at,
                source=row.get("source_url") or "Work24"))
    return {"snapshot_id": snapshot_id, "status": "CREATED", "rows": len(rows),
            "industries": len(grouped), "quarter": quarter, "headcount": None,
            "company_matches": sum(r.get("company_match_status") == "MATCH" for r in rows),
            "kicox_mapped": sum(bool(r.get("kicox_industry")) for r in rows),
            "headcount_coverage_pct": 0.0,
            "model_input_allowed": False}
