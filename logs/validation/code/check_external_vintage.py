# -*- coding: utf-8 -*-
"""새로 내려받은 공공데이터포털 최신 공표본과 저장소 마스터 값 대조.

**이것은 외부검증이 아니다.** 내려받은 자료와 저장소 입력이 둘 다 한국산업단지공단
산업동향정보로 출처가 같다. 같은 기관이 같은 조사로 만든 값을 다시 받아 본 것이므로
독립 검증이 성립하지 않는다. 확인하는 것은 두 가지뿐이다.

    1. 값 개정(vintage)  — 같은 분기 값이 사후에 바뀌었는가
    2. 업종 구성 일치    — 공표본의 업종 열이 분석에 쓰는 KICOX 10업종과 같은가

차이가 있으면 `source_revision_warning` 해석에 쓴다.

실행:  python scripts/check_external_vintage.py
"""
from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/external/kicox_datagokr"
META = RAW / "_metadata"
MASTER = ROOT / "data/processed/kicox/changwon_industry_master.csv"
OUT = ROOT / "outputs/robustness_extension/source_vintage_check.csv"

INDUSTRIES = ["음식료", "섬유의복", "목재종이", "석유화학", "비금속",
              "철강", "기계", "전기전자", "운송장비", "기타"]
FILES = {
    "employment": "kicox_industry_employment_latest.csv",
    "production": "kicox_industry_production_latest.csv",
    "firms_op": "kicox_industry_firms_op_latest.csv",
    "firms_in": "kicox_industry_firms_in_latest.csv",
    "op_rate_official": "kicox_industry_op_rate_latest.csv",
}


def _read_changwon(path: Path) -> dict[str, float]:
    raw = path.read_bytes()
    for enc in ("cp949", "utf-8-sig", "utf-8"):
        try:
            rows = list(csv.reader(io.StringIO(raw.decode(enc))))
            break
        except UnicodeDecodeError:
            continue
    hdr = [str(h).split("(")[0].strip() for h in rows[0]]
    cw = next((r for r in rows[1:] if r and r[0].strip() == "창원"), None)
    if cw is None:
        return {}
    out = {}
    for i, h in enumerate(hdr):
        if h in INDUSTRIES and i < len(cw):
            s = cw[i].strip().replace(",", "")
            if s and s.upper() not in ("X", "×", "-"):
                try:
                    out[h] = float(s)
                except ValueError:
                    pass
    return out


def _period_from_filename(name: str) -> str | None:
    """포털 파일명의 '(2026.2분기)' 표기를 분기 코드로 바꾼다."""
    m = re.search(r"(\d{4})\.(\d)\s*분기", name)
    return f"{m.group(1)}Q{m.group(2)}" if m else None


def check_industry_composition() -> dict:
    """공표본의 업종 열이 분석에 쓰는 KICOX 10업종과 같은지 대조한다.

    업종이 늘거나 줄면 마스터 구축과 해석층 전체가 영향을 받으므로 따로 본다.
    """
    out = []
    for indicator, fname in FILES.items():
        p = RAW / fname
        if not p.exists():
            continue
        raw = p.read_bytes()
        for enc in ("cp949", "utf-8-sig", "utf-8"):
            try:
                header = raw.decode(enc).splitlines()[0]
                break
            except UnicodeDecodeError:
                continue
        cols = [str(h).split("(")[0].strip() for h in header.split(",")]
        published = [c for c in cols if c in INDUSTRIES]
        extra = [c for c in cols if c not in INDUSTRIES
                 and c not in ("산업단지", "구분", "계", "총계", "비제조", "")]
        out.append(dict(
            indicator=indicator,
            published_industries=published,
            n_published=len(published),
            matches_kicox_10=sorted(published) == sorted(INDUSTRIES),
            missing_from_published=[i for i in INDUSTRIES if i not in published],
            extra_columns=extra))
    return dict(expected_kicox_10=INDUSTRIES, per_indicator=out,
                all_match=all(x["matches_kicox_10"] for x in out) if out else None,
                note=("동일 KICOX 계열 자료다. 업종 구성 일치는 공표 일관성 확인이며 "
                      "외부검증이 아니다."))


def main() -> int:
    if not RAW.exists():
        print("[skip] 외부 수집물 없음 — collect_datagokr_files.py 먼저 실행")
        return 0
    master = pd.read_csv(MASTER)
    master.columns = [c.lstrip("﻿") for c in master.columns]
    rows = []
    for indicator, fname in FILES.items():
        p = RAW / fname
        mp_ = META / (Path(fname).stem + ".json")
        if not p.exists() or not mp_.exists():
            continue
        meta = json.loads(mp_.read_text(encoding="utf-8"))
        quarter = _period_from_filename(meta.get("original_filename") or "")
        vals = _read_changwon(p)
        for ind, portal_value in vals.items():
            sel = master[(master.industry == ind) & (master.quarter == quarter)]
            stored = sel[indicator].iloc[0] if (len(sel) == 1 and indicator in sel) else None
            diff = (None if stored is None or pd.isna(stored)
                    else round(float(portal_value) - float(stored), 6))
            rel = (None if not diff or stored in (None, 0) or pd.isna(stored)
                   else round(diff / float(stored) * 100, 4))
            rows.append(dict(
                indicator=indicator, industry=ind, quarter=quarter,
                portal_latest_value=portal_value,
                repository_master_value=(None if stored is None or pd.isna(stored)
                                         else float(stored)),
                absolute_difference=diff, relative_difference_pct=rel,
                identical=(diff == 0) if diff is not None else None,
                # 포털 CSV 는 소수점을 잘라 싣는 경우가 있어 값 자체의 개정과
                # 표기 자릿수 차이를 구분한다.
                difference_is_rounding_only=(
                    None if rel is None else abs(rel) < 1e-6),
                portal_filename=meta.get("original_filename"),
                portal_retrieved_at=meta.get("retrieved_at"),
                note=("같은 KICOX 계열 자료다. 독립 검증이 아니라 사후 개정 여부 확인이다."
                      if quarter else "파일명에서 분기를 확정하지 못해 대조 불가")))
    out = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False, encoding="utf-8-sig")

    comp = check_industry_composition()
    comp_path = OUT.parent / "kicox_industry_composition_check.json"
    comp_path.write_text(json.dumps(comp, ensure_ascii=False, indent=2), encoding="utf-8")
    comparable = out[out["identical"].notna()]
    print(f"[ok] {OUT.relative_to(ROOT)}  대조 {len(comparable)}건 / 전체 {len(out)}건")
    print(f"[ok] {comp_path.relative_to(ROOT)}  업종 구성 일치: {comp['all_match']}")
    for x in comp["per_indicator"]:
        mark = "일치" if x["matches_kicox_10"] else "불일치"
        print(f"     {x['indicator']:<18} 업종 {x['n_published']}개 {mark}"
              + (f" · 누락 {x['missing_from_published']}" if x["missing_from_published"] else "")
              + (f" · 추가열 {x['extra_columns']}" if x["extra_columns"] else ""))
    if len(comparable):
        n_same = int(comparable["identical"].sum())
        print(f"     동일 {n_same}건, 상이 {len(comparable) - n_same}건")
        diff = comparable[~comparable["identical"].astype(bool)
                          & ~comparable["difference_is_rounding_only"].fillna(False)]
        n_round = int((~comparable["identical"].astype(bool)
                       & comparable["difference_is_rounding_only"].fillna(False)).sum())
        print(f"     그중 표기 자릿수 차이만인 건 {n_round}건 (값 개정 아님)")
        if len(diff):
            print(diff[["indicator", "industry", "quarter", "portal_latest_value",
                        "repository_master_value", "relative_difference_pct"]]
                  .to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
