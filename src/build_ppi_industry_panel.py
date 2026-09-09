# -*- coding: utf-8 -*-
"""
build_ppi_industry_panel.py
KICOX 10개 업종 대응 PPI 업종별 분기 지수 패널 생성 (오프라인, 읽기 전용)

목적
    PPI 보조분석의 목적은 실질 생산 증감률을 '추정'하는 것이 아니라,
    국면(S1~S4)의 **생산 방향 부호가 가격효과로 뒤집히는지**만 확인하는 것이다.
    S1~S4는 생산 YoY의 부호로만 결정되므로 점추정이 아니라 부호 안전성 판정이면 충분하고,
    그래서 임의 가중치가 필요 없다.

매핑 등급
    A  1:1 대응이 가능해 점추정 가능
    B  대분류가 범위 과대여서 하위(lv4) 항목으로 정밀화 — 점추정 가능
    C  단일 PPI 항목으로 대응 불가. **가중치를 부여하지 않고** 후보 지수를 각각 적용해
       밴드(min~max)로만 제시한다
    D  정의가 이질적이어서 보조분석에서 제외

    confirmed(본분석 반영 승인)와 aux_usable(보조분석 사용 가능)은 별개 축이다.
    이 스크립트는 본분석 국면 판정을 바꾸지 않으며, 승인 여부와 무관하게 보조 검증만 지원한다.

산출물
    data/processed/ppi/ppi_industry_panel.csv          (업종 x 분기 x PPI후보, long)
    data/processed/ppi/ppi_industry_mapping_resolved.csv (등급 확정 매핑표)

주의
    ppi_industry_mapping_candidates.csv(승인 대기 후보표)는 건드리지 않는다.
"""
from __future__ import annotations

import os
import sys

import pandas as pd

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P_PPI_RAW = os.path.join(BASE, "data", "raw", "ppi", "ppi_raw.csv")
DIR_OUT = os.path.join(BASE, "data", "processed", "ppi")

# (등급, PPI 계층, [(component_id, PPI 항목명)], 판단 근거)
MAPPING = {
    "기계":    ("A", "lv3", [("", "기계및장비")], "대분류 직접 대응"),
    "운송장비": ("A", "lv3", [("", "운송장비")], "대분류 직접 대응(자동차+기타운송장비)"),
    "비금속":  ("A", "lv3", [("", "비금속광물제품")], "시멘트·유리·요업 등 매칭 양호"),
    "음식료":  ("A", "lv3", [("", "음식료품")], "대분류 직접 대응"),
    "목재종이": ("A", "lv3", [("", "목재및종이제품")],
                "대분류에 목재+종이가 이미 통합 존재 — 후보표의 '2개 합산 필요'는 불성립"),
    "섬유의복": ("A", "lv4", [("", "섬유및의복")],
                "lv3 '섬유및가죽제품'은 가죽 포함으로 범위 과대 → lv4로 정밀화"),
    "철강":    ("B", "lv4", [("", "철강1차제품")],
                "lv3 '1차금속제품'은 비철금속 포함으로 범위 과대(2026Q2 +14.4% vs +5.9%) → lv4로 정밀화"),
    "석유화학": ("C", "lv3", [("c1", "화학제품"), ("c2", "석탄및석유제품")],
                "상위 통합 항목 없음. 가중치 근거가 없어 밴드로만 제시"),
    "전기전자": ("C", "lv3", [("c1", "전기장비"), ("c2", "컴퓨터전자및광학기기")],
                "상위 통합 항목 없음. 가중치 근거가 없어 밴드로만 제시"),
    "기타":    ("D", "", [], "PPI '기타제조업제품'과 정의 이질 — 보조분석 제외(고용비중 0.15%)"),
}

NOTE = ("전국 단위 KOSIS 생산자물가지수(기본분류) 월 지수를 분기 평균한 값. "
        "국면 부호 안전성 판정 전용이며 본분석 생산 YoY(명목)를 대체하지 않는다.")


def load_ppi() -> pd.DataFrame:
    d = pd.read_csv(P_PPI_RAW, encoding="utf-8-sig")
    d.columns = [str(c).strip() for c in d.columns]
    d["code"] = d["C1"].str.extract(r"ACC_CD\.(.+)AA")[0]
    d["lv"] = "lv" + d["code"].str.len().astype("Int64").astype(str)
    d["PRD_DE"] = d["PRD_DE"].astype(str)
    d["quarter"] = d.PRD_DE.str[:4] + "Q" + ((d.PRD_DE.str[4:6].astype(int) - 1) // 3 + 1).astype(str)
    # 기준연도가 다른 항목이 섞여 있으면 같은 항목 안에서만 YoY를 계산하므로 문제 없으나,
    # 한 항목이 두 기준을 함께 가지면 연결 단절이 되므로 확인한다.
    mixed = d.groupby("C1_NM").UNIT_NM.nunique()
    bad = mixed[mixed > 1].index.tolist()
    if bad:
        raise ValueError(f"기준연도가 혼재된 항목: {bad}")
    return d


def build_panel(d: pd.DataFrame) -> pd.DataFrame:
    q = (d.groupby(["C1_NM", "lv", "quarter"])
         .agg(ppi_index=("DT", "mean"), ppi_index_n_months=("DT", "size"))
         .reset_index())
    q["ppi_index_complete_quarter"] = q.ppi_index_n_months == 3
    # 같은 항목명이 여러 계층(lv)에 존재하므로 반드시 (C1_NM, lv)로 그룹을 잡는다.
    # C1_NM만으로 묶으면 서로 다른 계층의 계열이 섞여 shift(4)가 잘못된 값을 참조한다.
    q = q.sort_values(["C1_NM", "lv", "quarter"]).reset_index(drop=True)
    gk = ["C1_NM", "lv"]
    q["ppi_index_yoy_pct"] = q.groupby(gk).ppi_index.transform(
        lambda s: (s / s.shift(4) - 1) * 100)
    # 당분기 또는 4분기 전이 불완전하면 YoY 무효
    cq = q.ppi_index_complete_quarter.astype(bool)
    prev_ok = q.groupby(gk).ppi_index_complete_quarter.shift(4).astype("boolean").fillna(False)
    q.loc[~(cq & prev_ok.astype(bool)), "ppi_index_yoy_pct"] = pd.NA

    rows = []
    for ind, (grade, lv, items, _basis) in MAPPING.items():
        if grade == "D":
            continue
        for comp, item in items:
            sub = q[(q.C1_NM == item) & (q.lv == lv)]
            if sub.empty:
                raise ValueError(f"PPI 항목을 찾지 못함: {ind} -> {item} ({lv})")
            for _, r in sub.iterrows():
                rows.append(dict(
                    quarter=r.quarter, kicox_industry=ind, grade=grade, ppi_level=lv,
                    component_id=comp, ppi_item=item,
                    ppi_index=round(float(r.ppi_index), 6),
                    ppi_index_n_months=int(r.ppi_index_n_months),
                    ppi_index_complete_quarter=bool(r.ppi_index_complete_quarter),
                    ppi_index_yoy_pct=(None if pd.isna(r.ppi_index_yoy_pct)
                                       else round(float(r.ppi_index_yoy_pct), 6)),
                    note=NOTE))
    return pd.DataFrame(rows).sort_values(["quarter", "kicox_industry", "component_id"])


def build_resolved_mapping() -> pd.DataFrame:
    rows = []
    for ind, (grade, lv, items, basis) in MAPPING.items():
        if grade == "D":
            rows.append(dict(kicox_industry=ind, grade=grade, ppi_level="", component_id="",
                             ppi_item="", aux_usable=False, confirmed=False, basis=basis))
            continue
        for comp, item in items:
            rows.append(dict(kicox_industry=ind, grade=grade, ppi_level=lv, component_id=comp,
                             ppi_item=item, aux_usable=True, confirmed=False, basis=basis))
    return pd.DataFrame(rows)


def main() -> None:
    os.makedirs(DIR_OUT, exist_ok=True)
    d = load_ppi()
    print(f"[PPI] 원자료 {len(d):,}행, {d.PRD_DE.min()}~{d.PRD_DE.max()} "
          f"({d.PRD_DE.nunique()}개월), 항목 {d.C1_NM.nunique()}개")

    panel = build_panel(d)
    p1 = os.path.join(DIR_OUT, "ppi_industry_panel.csv")
    panel.to_csv(p1, index=False, encoding="utf-8-sig")
    ok = panel[panel.ppi_index_yoy_pct.notna()]
    print(f"[PPI] ppi_industry_panel.csv 저장 ({len(panel)}행, "
          f"YoY 유효 {len(ok)}행, {ok.quarter.min()}~{ok.quarter.max()})")

    mp = build_resolved_mapping()
    p2 = os.path.join(DIR_OUT, "ppi_industry_mapping_resolved.csv")
    mp.to_csv(p2, index=False, encoding="utf-8-sig")
    print(f"[PPI] ppi_industry_mapping_resolved.csv 저장 ({len(mp)}행)")
    print(mp.to_string(index=False))
    print("\n주의: confirmed=False(본분석 미반영)를 유지한다. aux_usable은 보조분석 사용 가능 여부로 별개 축이다.")


if __name__ == "__main__":
    main()
