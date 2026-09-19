# -*- coding: utf-8 -*-
"""공공데이터포털 파일데이터 실수집.

대상 데이터셋 번호를 코드에 고정해 상세페이지(/data/<pk>/fileData.do)만 호출한다.
포털의 검색목록 경로(/tcs/dss/selectDataSetList.do)는 자동수집에 쓰지 않는다
(robots.txt 가 일부 수집기에 대해 해당 경로를 제한하고 있어 보수적으로 회피).

포털은 각 파일데이터의 '현재 공표본' 1개만 제공한다. 과거 월별 공표본은
포털에서 다시 받을 수 없으며, 이는 결과 문서에 한계로 기록한다.

실행:  python src/evidence/collection/collect_datagokr_files.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from evidence.collection import datagokr as dg          # noqa: E402
from evidence.collection.metadata import (               # noqa: E402
    save_raw, sha256_bytes, utcnow, write_metadata,
)

# (dataset_pk, 저장 source 디렉터리, 저장 파일명, 설명 필드)
TARGETS = [
    ("15085898", "kicox_datagokr", "kicox_industry_production_latest.csv",
     dict(dataset_name="한국산업단지공단_국가산업단지 산업동향정보_업종별 생산",
          industry_classification="KICOX 10업종(산업단지 산업동향 분류)", unit="백만원",
          frequency="분기(2024Q2 이후) / 이전 월별")),
    ("15085897", "kicox_datagokr", "kicox_industry_employment_latest.csv",
     dict(dataset_name="한국산업단지공단_국가산업단지 산업동향정보_업종별 고용현황",
          industry_classification="KICOX 10업종", unit="명",
          frequency="분기(2024Q2 이후) / 이전 월별")),
    ("15085895", "kicox_datagokr", "kicox_industry_op_rate_latest.csv",
     dict(dataset_name="한국산업단지공단_국가산업단지 산업동향정보_업종별 가동률",
          industry_classification="KICOX 10업종", unit="퍼센트", frequency="분기")),
    ("15085896", "kicox_datagokr", "kicox_industry_firms_op_latest.csv",
     dict(dataset_name="한국산업단지공단_국가산업단지 산업동향정보_업종별 가동업체 현황",
          industry_classification="KICOX 10업종", unit="개사", frequency="분기")),
    ("15085901", "kicox_datagokr", "kicox_industry_firms_in_latest.csv",
     dict(dataset_name="한국산업단지공단_국가산업단지 산업동향정보_업종별 입주업체 현황",
          industry_classification="KICOX 10업종", unit="개사", frequency="분기")),
    ("15085889", "kicox_datagokr", "kicox_complex_op_rate_latest.csv",
     dict(dataset_name="한국산업단지공단_국가산업단지 산업동향정보_가동률(단지 전체)",
          industry_classification="해당없음(단지 총계)", unit="퍼센트", frequency="분기")),
    ("15085874", "kicox_datagokr", "kicox_national_complex_status_latest.csv",
     dict(dataset_name="한국산업단지공단_전국산업단지현황통계_국가산업단지",
          industry_classification="해당없음(단지 단위)", unit="개사, 천㎡, %",
          frequency="분기",
          geography="전국 국가산업단지(단지별). 창원 행만 발췌해 사용",
          notes_role="단지 단위 입주·가동업체수의 별도 공표계열. KICOX 동일계열이므로 "
                     "독립검증이 아니라 공표 일관성 확인용")),
    ("3066436", "changwon_factory_registry", "changwon_factory_registry_20241231.csv",
     dict(dataset_name="경상남도 창원시_공장등록현황",
          institution="경상남도 창원시",
          industry_classification="KSIC 세세분류 업종명(문자열)", unit="공장 1건",
          frequency="비정기 스냅샷", geography="경상남도 창원시 전역(산업단지 내외 구분 없음)")),
]

DEFAULTS = dict(
    institution="한국산업단지공단",
    geography="전국 국가산업단지(창원 포함)",
    terms_limitations=("공공데이터포털 이용약관. 파일데이터는 현재 공표본 1개만 제공되며 "
                       "과거 공표본은 포털에서 재취득 불가. 로그인·CAPTCHA 우회 없이 수집."),
    revision_vintage="포털 제공 파일명에 표기된 공표 시점(연간보정 여부 포함)",
)


def main() -> int:
    log = []
    for pk, source, fname, fields in TARGETS:
        ds, page = dg.describe(pk)
        if ds is None or not ds.download_url:
            log.append(dict(pk=pk, status="NOT_AVAILABLE",
                            reason=page.error or "상세페이지에 파일 다운로드 URL 없음"))
            print(f"[skip] {pk}: {page.error or 'no download url'}")
            continue
        r = dg.download(ds)
        if not r.ok:
            log.append(dict(pk=pk, status="FAILED", reason=r.error, http_status=r.status))
            print(f"[fail] {pk}: {r.error}")
            continue
        p = save_raw(ROOT, source, fname, r.body)
        txt, enc = dg.decode_table(r.body)
        lines = txt.splitlines()
        meta = dict(DEFAULTS)
        meta.update(fields)
        meta.update(
            source_url=ds.page_url,
            api_endpoint=ds.download_url,
            retrieved_at=utcnow(),
            original_filename=r.filename(),
            file_hash_sha256=sha256_bytes(r.body),
            api_parameters=dict(dataset_pk=pk, method="GET", auth="none (public file download)"),
            notes=(f"포털 공표 제목: {ds.title}. 인코딩 {enc}, 행 수 {len(lines) - 1}, "
                   f"헤더: {lines[0][:300] if lines else ''}"),
        )
        meta.setdefault("observation_start", None)
        meta.setdefault("observation_end", None)
        write_metadata(ROOT, source, Path(fname).stem, **meta)
        log.append(dict(pk=pk, status="COLLECTED", path=str(p.relative_to(ROOT)),
                        bytes=len(r.body), rows=len(lines) - 1,
                        original_filename=r.filename()))
        print(f"[ok]   {pk} -> {p.relative_to(ROOT)} ({len(r.body):,} bytes, {len(lines) - 1} rows)")
    out = ROOT / "data/raw/kicox/datagokr/_collection_log_datagokr.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(run_at=utcnow(), results=log), ensure_ascii=False, indent=2),
                   encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
