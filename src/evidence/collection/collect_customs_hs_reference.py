# -*- coding: utf-8 -*-
"""관세청 HS부호 기준자료 수집 — 유효 HS6 목록과 공식 성질분류.

왜 필요한가
    `시군구별 품목별 수출입실적` API 는 HsSgn(HS 6단위)을 필수로 요구한다.
    HS6 목록을 추정으로 만들면 안 되므로, 관세청이 공표한 HS부호 원본을 받아
    **유효 HS6 모집단**을 만든다.

받는 것
    15049722 관세청_HS부호            HSK 10단위 12,469행. 적용기간·품목명·성질통합분류코드 포함
    15049720 관세청_HSK별 신성질별·성질별 분류   성질분류 코드 해설

이 데이터셋들은 상세페이지에 contentUrl 이 없는 '원문파일등록' 형식이라
`datagokr.resolve_registered_file()` 로 첨부파일 id 를 먼저 얻어야 한다.

HS → KICOX 매핑에 대하여
    이 수집기는 매핑을 만들지 않는다. 원본을 그대로 저장할 뿐이다.
    매핑은 `src/evidence/build_hs6_universe.py` 에서 공식 근거(HS 류, 관세청 성질통합분류코드)가
    있는 범위에서만 수행한다.

실행:  python src/evidence/collection/collect_customs_hs_reference.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from evidence.collection import datagokr as dg            # noqa: E402
from evidence.collection import secrets as S              # noqa: E402
from evidence.collection.metadata import (                # noqa: E402
    save_raw, sha256_bytes, utcnow, write_metadata,
)

SOURCE = "customs_reference"
TARGETS = [
    dict(pk="15049722",
         detail_pk="uddi:a51a7d76-0b1c-4efe-a0f9-a10dcdf12669",
         filename="customs_hs_code_20260101.xlsx",
         name="관세청_HS부호",
         desc=("우리나라 2026년 기준 HS부호(HSK 10단위). 적용시작·종료일자, 한글·영문 품목명, "
               "수출입 성질코드, 성질통합분류코드/명 포함"),
         industry_classification="HS(HSK 10단위) + 관세청 성질통합분류코드"),
    dict(pk="15049720",
         detail_pk=None,
         filename="customs_hsk_nature_classification_20260101.xlsx",
         name="관세청_HSK별 신성질별_성질별 분류",
         desc="HSK 별 신성질별·성질별 분류표. 성질통합분류코드의 계층 해설",
         industry_classification="관세청 성질(신성질) 분류"),
]


def _detail_pk(pk: str) -> str | None:
    """상세페이지에서 publicDataDetailPk 를 읽는다."""
    from evidence.collection.http_client import fetch
    import re
    r = fetch(f"https://www.data.go.kr/data/{pk}/fileData.do", timeout=60)
    if not r.ok:
        return None
    m = re.search(r'name="publicDataDetailPk"[^>]*value="([^"]+)"',
                  r.body.decode("utf-8", "replace"))
    return m.group(1) if m else None


def main() -> int:
    S.load_env(ROOT)
    results = []
    for t in TARGETS:
        pk = t["pk"]
        detail_pk = t["detail_pk"] or _detail_pk(pk)
        if not detail_pk:
            results.append(dict(pk=pk, status="FAILED", reason="publicDataDetailPk 미확인"))
            print(f"[fail] {pk}: publicDataDetailPk 미확인")
            continue
        atch, sn = dg.resolve_registered_file(pk, detail_pk)
        if not atch:
            results.append(dict(pk=pk, status="FAILED", reason="atchFileId 미확인"))
            print(f"[fail] {pk}: atchFileId 미확인")
            continue
        r = dg.download_by_file_id(pk, atch, sn)
        if not r.ok or len(r.body) < 1000:
            results.append(dict(pk=pk, status="FAILED", reason=r.error or "본문 없음",
                                http_status=r.status))
            print(f"[fail] {pk}: {r.error or 'empty'}")
            continue
        p = save_raw(ROOT, SOURCE, t["filename"], r.body)
        write_metadata(
            ROOT, SOURCE, Path(t["filename"]).stem,
            dataset_name=t["name"], institution="관세청",
            source_url=f"https://www.data.go.kr/data/{pk}/fileData.do",
            api_endpoint="https://www.data.go.kr/cmm/cmm/fileDownload.do (원문파일등록)",
            retrieved_at=utcnow(),
            observation_start="2026-01-01", observation_end="2026-12-31",
            geography="전국(품목 코드 체계 — 지역 개념 없음)",
            industry_classification=t["industry_classification"],
            frequency="연 1회 갱신(코드 개정 시)", unit="코드",
            original_filename=r.filename(),
            file_hash_sha256=sha256_bytes(r.body),
            api_parameters=dict(publicDataPk=pk, publicDataDetailPk=detail_pk,
                                fileDetailSn=sn, publicDataTyCode="PR0051",
                                auth="none (공개 파일데이터)"),
            pagination="단일 파일. 분할 없음.",
            mapping_notes=("이 파일 자체는 매핑을 포함하지 않는다. KICOX 업종 대응은 "
                           "HS 류와 관세청 성질통합분류코드를 근거로 별도 스크립트에서 만든다."),
            role="REFERENCE / CODE_UNIVERSE",
            revision_vintage="2026-01-01 적용 기준본",
            terms_limitations="공공데이터포털 이용약관.",
            limitations="코드 체계일 뿐 거래실적이 아니다.",
            notes=f"{len(r.body):,} bytes. {t['desc']}",
        )
        results.append(dict(pk=pk, status="COLLECTED",
                            path=str(p.relative_to(ROOT)), bytes=len(r.body),
                            original_filename=r.filename()))
        print(f"[ok]   {pk} -> {p.relative_to(ROOT)} ({len(r.body):,} bytes)")

    out = ROOT / "data/raw/customs/reference/_metadata/collection_log.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(run_at=utcnow(), results=results),
                              ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
