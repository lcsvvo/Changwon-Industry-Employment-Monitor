"""고용24 채용공고 상세 HTML 정제본을 검색하는 소규모 RAG 계층.

수집기가 상세 HTML에서 추출·정제한 필드는 최신 ``work24_recruitment_layer_*.csv``에
보존된다. 이 모듈은 그 가운데 상세 검증이 끝난 공고만 읽고, 선택 업종 안에서
직무·기술·자격·경력 문맥을 검색한다. 결과는 설명용 근거이며 CORE/Triage 입력이 아니다.
"""
from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "processed" / "work24"
TOKEN = re.compile(r"[0-9A-Za-z가-힣+#.-]+")
STOPWORDS = {
    "최근", "채용", "채용공고", "구인", "공고", "모집", "직무", "신호", "어떤가요",
    "알려줘", "알려주세요", "보여줘", "무엇", "어떤", "관련", "업종", "창원", "고용24",
}


def _true(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _tokens(value: str) -> set[str]:
    return {
        token.lower().strip(".-")
        for token in TOKEN.findall(value or "")
        if len(token.strip(".-")) >= 2 and token.lower().strip(".-") not in STOPWORDS
    }


@lru_cache(maxsize=4)
def _read(path_text: str, modified_ns: int) -> tuple[dict, ...]:
    del modified_ns
    with Path(path_text).open("r", encoding="utf-8-sig", newline="") as handle:
        return tuple(csv.DictReader(handle))


def _latest_source() -> Path | None:
    files = sorted(DATA_DIR.glob("work24_recruitment_layer_*.csv"))
    return files[-1] if files else None


def _excerpt(row: dict, limit: int = 520) -> str:
    fields = [
        ("공고", row.get("posting_title")),
        ("직종", row.get("occupation_raw")),
        ("업무", row.get("job_description_clean")),
        ("자격", row.get("certificate_raw")),
        ("경력", row.get("career")),
        ("학력", row.get("education")),
        ("고용형태", row.get("employment_type")),
        ("임금", row.get("wage")),
    ]
    text = " · ".join(f"{label}: {re.sub(r'\s+', ' ', str(value)).strip()}"
                      for label, value in fields if str(value or "").strip())
    return text[:limit]


class RecruitmentRAG:
    """재현 가능한 토큰 검색. 외부 호출이나 LLM 판단 없이 근거 공고만 고른다."""

    @property
    def available(self) -> bool:
        return _latest_source() is not None

    @property
    def source_name(self) -> str | None:
        path = _latest_source()
        return path.name if path else None

    def search(self, query: str, *, industry: str, limit: int = 5) -> dict:
        path = _latest_source()
        if path is None:
            return {"status": "NO_SOURCE", "message": "고용24 채용공고 검색 자료가 없습니다.", "hits": []}
        rows = [
            row for row in _read(str(path), path.stat().st_mtime_ns)
            if row.get("kicox_industry") == industry and _true(row.get("detail_verified"))
        ]
        if not rows:
            return {
                "status": "NO_VERIFIED_DETAIL",
                "message": f"{industry} 업종에서 상세 HTML 검증이 끝난 고용24 채용공고가 없습니다.",
                "hits": [], "source_file": path.name,
            }

        qtokens = _tokens(query)
        scored = []
        for row in rows:
            title = str(row.get("posting_title") or "")
            detail = " ".join(str(row.get(field) or "") for field in (
                "occupation_raw", "occupation_keywords", "job_description_clean", "certificate_raw",
                "career", "education", "employment_type", "wage", "preference_raw",
            ))
            title_tokens, detail_tokens = _tokens(title), _tokens(detail)
            matched = qtokens & (title_tokens | detail_tokens)
            score = 4 * len(qtokens & title_tokens) + 2 * len(qtokens & detail_tokens)
            # 일반적인 '최근 채용 신호' 질문은 질의어 일치가 없어도 선택 업종의 최신 상세검증 공고를 보여 준다.
            scored.append((score, row.get("registration_date") or "", row, sorted(matched)))
        # 질의어 일치 점수가 높은 공고를 우선하고, 같은 점수에서는 최근 등록일을 먼저 둔다.
        scored.sort(key=lambda item: (item[0], item[1], item[2].get("wanted_auth_no") or ""), reverse=True)

        hits = []
        for score, _registered, row, matched in scored[:limit]:
            url = row.get("detail_source_url") or row.get("list_source_url") or ""
            hits.append({
                "document_id": f"WORK24:{row.get('wanted_auth_no')}",
                "posting_id": row.get("wanted_auth_no"),
                "title": row.get("posting_title") or "고용24 채용공고",
                "company": row.get("company_official_name") or row.get("company_name"),
                "industry": industry,
                "excerpt": _excerpt(row),
                "source_url": url,
                "checked_at": row.get("detail_checked_at") or row.get("source_snapshot_date"),
                "registered_at": row.get("registration_date"),
                "closing_at": row.get("detail_closing_date") or row.get("due_date"),
                "activity_status": row.get("posting_activity_status"),
                "matched_terms": matched,
                "score": score,
                "source_class": "WORK24_RECRUITMENT_HTML",
            })
        return {
            "status": "FOUND", "message": "고용24 채용공고 상세 HTML 정제본 검색 결과입니다.",
            "hits": hits, "source_file": path.name, "verified_detail_count": len(rows),
            "query_terms": sorted(qtokens),
        }
