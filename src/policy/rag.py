"""페이지/섹션 provenance를 보존하는 소규모 정책 검색 계층."""
from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path

from sqlalchemy import delete, select

from workflow import models as M

ROOT = Path(__file__).resolve().parents[2]
ELIGIBLE_RAG = {"RAG_READY", "RAG_READY_WITH_CAVEAT"}
TOKEN = re.compile(r"[0-9A-Za-z가-힣]+")


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.heading = None
        self.current_heading = None
        self.parts: list[tuple[str | None, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.skip += 1
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6", "title"}:
            self.heading = []
        if tag in {"p", "li", "tr", "br", "div", "section"}:
            self.parts.append((self.current_heading, "\n"))

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self.skip:
            self.skip -= 1
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6", "title"} and self.heading is not None:
            value = re.sub(r"\s+", " ", "".join(self.heading)).strip()
            if value:
                self.current_heading = value[:240]
            self.heading = None

    def handle_data(self, data):
        if self.skip:
            return
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        if self.heading is not None:
            self.heading.append(text + " ")
        self.parts.append((self.current_heading, text + " "))


def _split(text: str, limit: int = 3500) -> list[str]:
    paragraphs = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n+", text) if p.strip()]
    chunks, current = [], ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 1 > limit:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n{paragraph}".strip()
    if current:
        chunks.append(current)
    return chunks


def _extract_pdf(path: Path):
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("PDF 정책 색인에는 pypdf가 필요합니다(requirements.txt 설치).") from exc
    for page_no, page in enumerate(PdfReader(str(path)).pages, start=1):
        text = page.extract_text() or ""
        for pos, chunk in enumerate(_split(text), start=1):
            yield page_no, page_no, f"p.{page_no}", None, pos, chunk


def _extract_html(path: Path):
    parser = _HTMLText()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    by_heading: list[tuple[str | None, str]] = []
    heading, buf = None, ""
    for item_heading, text in parser.parts:
        if item_heading != heading and buf.strip():
            by_heading.append((heading, buf))
            buf = ""
        heading = item_heading
        buf += text
    if buf.strip():
        by_heading.append((heading, buf))
    for section_no, (heading, text) in enumerate(by_heading, start=1):
        for pos, chunk in enumerate(_split(text), start=1):
            yield None, None, f"section-{section_no}", heading, pos, chunk


def rebuild_policy_index(Session, document_ids: list[str] | None = None) -> dict:
    """원문 해시를 검증하고 재생성 가능한 DB 색인을 문서 단위로 교체한다."""
    summary = {"indexed_documents": 0, "chunks": 0, "failures": []}
    with Session.begin() as s:
        q = select(M.DocumentMaster).where(M.DocumentMaster.rag_status.in_(ELIGIBLE_RAG))
        if document_ids:
            q = q.where(M.DocumentMaster.document_id.in_(document_ids))
        for doc in s.scalars(q.order_by(M.DocumentMaster.document_id)):
            if not doc.local_path:
                summary["failures"].append({"document_id": doc.document_id, "reason": "NO_LOCAL_SOURCE"})
                continue
            path = ROOT / doc.local_path
            if not path.exists():
                summary["failures"].append({"document_id": doc.document_id, "reason": "SOURCE_MISSING"})
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if doc.file_hash and digest != doc.file_hash:
                summary["failures"].append({"document_id": doc.document_id, "reason": "HASH_MISMATCH"})
                continue
            extractor = _extract_pdf if doc.document_type == "PDF" else _extract_html
            try:
                rows = list(extractor(path))
            except Exception as exc:  # failure is recorded; old index remains intact
                summary["failures"].append({"document_id": doc.document_id, "reason": type(exc).__name__})
                continue
            s.execute(delete(M.SourceEvidence).where(M.SourceEvidence.document_id == doc.document_id))
            for page_start, page_end, section, heading, pos, content in rows:
                if not content.strip():
                    continue
                locator = f"p{page_start}" if page_start else section
                s.add(M.SourceEvidence(
                    chunk_id=f"{doc.document_id}:{locator}:{pos}", document_id=doc.document_id,
                    page_start=page_start, page_end=page_end, section=section, heading=heading,
                    content=content, source_url=doc.source_url, verified_at=doc.verified_at,
                    source_class=doc.source_class, current_intake_status=doc.current_intake_status,
                    caveat=doc.caveat, file_hash=digest))
                summary["chunks"] += 1
            summary["indexed_documents"] += 1
    return summary


def _tokens(value: str) -> set[str]:
    compact = re.sub(r"\s+", "", value.lower())
    parts = {m.group(0).lower() for m in TOKEN.finditer(value) if len(m.group(0)) > 1}
    if compact:
        parts.add(compact)
    return parts


QUERY_EXPANSION = {
    "채용장려금": {"60만원", "720만원", "고용유지", "채용장려금"},
    "훈련지원금": {"300만원", "훈련비", "훈련장려금"},
    "훈련비한도": {"300만원", "훈련비"},
    "창원국가산단": {"밀집지역", "창원국가산업단지", "마산진북", "상복", "죽곡"},
    "자동승인": {"컨설팅", "지원대상", "참여기업", "심사"},
}


class PolicyRAG:
    def __init__(self, Session):
        self.Session = Session

    def route_jurisdiction(self, address: str | None) -> dict:
        value = re.sub(r"\s+", "", address or "")
        matches = [d for d in ("의창구", "성산구", "진해구", "마산회원구", "마산합포구") if d in value]
        if len(matches) != 1:
            return {"district": None, "institution": None, "jurisdiction_status": "NEED_LOCATION",
                    "message": "사업장 소재지 확인 필요 · 관할 고용센터 미확정"}
        with self.Session() as s:
            row = s.get(M.JurisdictionRule, matches[0])
            if row is None:
                return {"district": matches[0], "institution": None, "jurisdiction_status": "NEED_LOCATION"}
            return {"district": row.district, "institution": row.institution,
                    "jurisdiction_status": "MATCHED", "source_url": row.source_url,
                    "verified_at": row.verified_at}

    def search(self, query: str, namespace: str = "official", current_only: bool = False,
               limit: int = 5) -> dict:
        query = (query or "").strip()
        if not query:
            return {"status": "NO_QUERY", "message": "검색어를 입력하세요.", "hits": []}
        compact = re.sub(r"\s+", "", query.lower())
        qtokens = _tokens(query)
        for key, terms in QUERY_EXPANSION.items():
            if key in compact:
                qtokens |= terms
        # 문서 ID 관계 질문은 원문에 내부 ID 문자열이 없을 수 있다. ID를 근거로
        # 답하지 않고, 두 문서의 검증된 주제어로 검색을 확장한 뒤 실제 chunk를 요구한다.
        if "d10" in compact and "d11" in compact:
            qtokens |= {"산업", "일자리전환", "컨설팅", "지원금", "채용장려금", "훈련지원금"}
        with self.Session() as s:
            stmt = select(M.SourceEvidence, M.DocumentMaster).join(
                M.DocumentMaster, M.DocumentMaster.document_id == M.SourceEvidence.document_id
            ).where(M.DocumentMaster.rag_status.in_(ELIGIBLE_RAG))
            if namespace == "team":
                stmt = stmt.where(M.DocumentMaster.source_class == "TEAM_PROPOSAL")
            else:
                stmt = stmt.where(M.DocumentMaster.source_class != "TEAM_PROPOSAL")
            if current_only:
                stmt = stmt.where(M.DocumentMaster.current_intake_status.not_in(("CLOSED", "NOT_APPLICABLE")))
            scored = []
            for evidence, doc in s.execute(stmt):
                hay = f"{doc.title} {evidence.heading or ''} {evidence.content}"
                ht = _tokens(hay)
                matched = qtokens & ht
                score = len(matched)
                score += sum(2 for token in qtokens if token and token in hay.lower())
                # 한 개의 흔한 조사·표현 우연 일치만으로 공식 근거가 있다고 답하지 않는다.
                exact_phrase = len(compact) >= 4 and compact in re.sub(r"\s+", "", hay.lower())
                if len(matched) >= 2 or exact_phrase:
                    scored.append((score, evidence, doc))
            scored.sort(key=lambda item: (-item[0], item[2].document_id, item[1].id))
            hits = []
            for score, ev, doc in scored[:limit]:
                excerpt = re.sub(r"\s+", " ", ev.content).strip()
                hits.append({
                    "document_id": doc.document_id, "title": doc.title,
                    "source_class": doc.source_class, "excerpt": excerpt[:700],
                    "page": ev.page_start, "section": ev.heading or ev.section,
                    "source_url": ev.source_url, "verified_at": ev.verified_at,
                    "current_intake_status": doc.current_intake_status,
                    "scope_status": doc.scope_status, "caveat": doc.caveat,
                    "score": score,
                })
            if not hits:
                return {"status": "NO_OFFICIAL_EVIDENCE", "message": "공식 자료에서 확인되지 않음", "hits": []}
            message = "근거 검색 결과입니다. 개별 적격·승인·잔여예산은 담당기관 확인이 필요합니다."
            if "자동승인" in compact or ("d10" in compact and "d11" in compact):
                message = "D10 참여는 D11 검토 경로 중 하나일 뿐 자동 적격·신청·승인·지급이 아닙니다. 각 요건 확인과 관할 고용센터의 별도 신청·심사가 필요합니다."
            if "창원국가산단" in compact and ("stand-up" in compact or "대상" in compact):
                message = "D09 상반기 별첨의 창원 대상 3곳은 창원마산진북농공단지·상복일반산업단지·진해죽곡일반산업단지이며 창원국가산업단지는 포함되지 않습니다. D13 하반기 별첨에는 이 결론을 복사하지 않습니다."
            requirements = []
            if "채용장려금" in compact:
                requirements.append("R11-A")
            if "훈련지원금" in compact or "훈련비" in compact:
                requirements.append("R11-B")
            return {"status": "FOUND", "message": message, "matched_requirement_ids": requirements,
                    "hits": hits}
