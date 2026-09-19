# -*- coding: utf-8 -*-
"""창원 법정동 단위 제조업 집적도 ↔ KEPCO 법정동 전력 결합.

무엇을 푸는 문제인가
    KEPCO 공간단위는 행정구(업종별 API)까지다. 「성산구 = 창원국가산단」으로
    바꿔 읽는 오류를 막으려면, **성산구 안에서도 제조업이 어디에 몰려 있고
    전력이 어디서 쓰이는지**를 수치로 보여야 한다.

무엇을 하지 않는가
    이 스크립트는 **창원국가산단 경계를 복원하지 않는다.** 산단 경계 polygon 은
    공표돼 있지 않다. 여기서 만드는 것은 공장등록현황(공식)에서 뽑은
    **제조업 집적 법정동**이고, 이는 산단 경계의 **상한(upper bound)** 이다 —
    법정동은 산단보다 넓고, 산단 밖 공장도 함께 들어간다.
    원자료의 metadata 도 "산업단지 내외 구분 없음"이라고 명시한다.

입력 (둘 다 공식자료)
    data/raw/changwon_factory_registry/changwon_factory_registry_20241231.csv
        경상남도 창원시_공장등록현황 (공공데이터포털 3066436)
    data/processed/kepco/kepco_2021_legal_dong_changwon.csv
        KEPCO 『2021 산업분류-법정동별 전력사용량』 창원 발췌
        (verify_kepco_legal_dong_2021.py 산출. 복원된 월만 들어 있다)

실행:  python src/evidence/build_changwon_legal_dong_context.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
FACTORY = (ROOT / "data/raw/changwon_factory_registry"
           / "changwon_factory_registry_20241231.csv")
KEPCO_DONG = ROOT / "data/processed/kepco/kepco_2021_legal_dong_changwon.csv"
OUT_REF = ROOT / "data/processed/kepco/reference/spatial"
OUT = ROOT / "logs/validation/outputs/kepco_robustness"

GU = ("의창구", "성산구", "마산합포구", "마산회원구", "진해구")
# 제조업 집적 법정동으로 볼 최소 공장 수. 한 두 곳짜리 산발 입지를 집적으로
# 부르지 않기 위한 문턱이며, 민감도는 결과에 함께 싣는다.
DENSE_MIN_FACTORIES = 30

_PAREN = re.compile(r"\(([^)]*)\)")
_EUPMYEON = re.compile(r"(\S+[읍면])\b")
_DONG = re.compile(r"(\S*?[가-힣]\d*동)\b")


def parse_unit(addr: str) -> tuple[str | None, str | None]:
    """주소 → (구, KEPCO 읍면동 단위). 확실하지 않으면 None 을 돌린다."""
    a = str(addr)
    gu = next((g for g in GU if g in a), None)
    if gu is None:
        return None, None
    tail = a.split(gu, 1)[1]
    # 1) 읍·면 지역은 KEPCO 도 읍·면 이름을 쓴다.
    m = _EUPMYEON.search(tail)
    if m:
        return gu, m.group(1)
    # 2) 도로명주소는 괄호 안 첫 토큰이 법정동이다.
    for inner in _PAREN.findall(tail):
        head = inner.split(",")[0].strip()
        if head.endswith("동"):
            return gu, head
    # 3) 지번주소는 도로명이 나오기 전 '○○동' 이 법정동이다.
    m = _DONG.search(tail.split("(")[0])
    if m and not re.search(r"(로|길)\s*$", m.group(1)):
        return gu, m.group(1)
    return gu, None


def main() -> int:
    if not FACTORY.exists():
        print(f"[skip] 공장등록현황이 없다: {FACTORY}")
        return 1
    if not KEPCO_DONG.exists():
        print("[skip] KEPCO 법정동 발췌가 없다. verify_kepco_legal_dong_2021.py 먼저 실행")
        return 1

    # ------------------------------------------------ 1. 공장 → 법정동
    f = pd.read_csv(FACTORY, encoding="utf-8-sig")
    addr_col = next(c for c in f.columns if "주소" in c)
    parsed = f[addr_col].map(parse_unit)
    f["gu"] = [p[0] for p in parsed]
    f["legal_dong"] = [p[1] for p in parsed]
    n_total = len(f)
    matched = f["legal_dong"].notna() & f["gu"].notna()
    print(f"[공장] {n_total:,}건 중 법정동 해석 {int(matched.sum()):,}건 "
          f"({100 * matched.mean():.1f}%)")

    # ------------------------------------------------ 2. KEPCO 법정동 집합과 대조
    k = pd.read_csv(KEPCO_DONG, encoding="utf-8-sig")
    k["sigungu_gu"] = k["sigungu"].str.replace("창원시 ", "", regex=False)
    kepco_keys = set(zip(k["sigungu_gu"], k["legal_dong"]))

    fm = f[matched].copy()
    fm["in_kepco"] = [(g, d) in kepco_keys for g, d in zip(fm["gu"], fm["legal_dong"])]
    print(f"[대조] 해석된 공장 중 KEPCO 법정동 목록과 일치 "
          f"{int(fm['in_kepco'].sum()):,}건 ({100 * fm['in_kepco'].mean():.1f}%)")

    dong = (fm[fm["in_kepco"]].groupby(["gu", "legal_dong"], as_index=False)
            .size().rename(columns={"size": "n_factories"})
            .sort_values("n_factories", ascending=False))
    dong["is_dense"] = dong["n_factories"] >= DENSE_MIN_FACTORIES
    dong["factory_share_pct"] = (100 * dong["n_factories"]
                                 / dong["n_factories"].sum()).round(2)

    # ------------------------------------------------ 3. KEPCO 제조업(C) 전력
    kc = k[k["ksic_major_code"] == "C"].copy()
    kc["sales_kwh"] = pd.to_numeric(kc["sales_kwh"], errors="coerce")
    power = (kc.groupby(["sigungu_gu", "legal_dong"], as_index=False)["sales_kwh"]
             .sum().rename(columns={"sigungu_gu": "gu",
                                    "sales_kwh": "mfg_power_kwh_2021_recovered"}))
    masked_n = (kc.groupby(["sigungu_gu", "legal_dong"], as_index=False)["masked"]
                .sum().rename(columns={"sigungu_gu": "gu", "masked": "masked_rows"}))

    ref = (power.merge(masked_n, on=["gu", "legal_dong"], how="outer")
                .merge(dong[["gu", "legal_dong", "n_factories", "is_dense"]],
                       on=["gu", "legal_dong"], how="outer"))
    ref["n_factories"] = ref["n_factories"].fillna(0).astype(int)
    ref["is_dense"] = ref["is_dense"].fillna(False).astype(bool)
    ref = ref.sort_values(["gu", "mfg_power_kwh_2021_recovered"],
                          ascending=[True, False])
    OUT_REF.mkdir(parents=True, exist_ok=True)
    ref.to_csv(OUT_REF / "changwon_legal_dong_manufacturing_context.csv",
               index=False, encoding="utf-8-sig")

    # ------------------------------------------------ 4. 「성산구 = 산단」 오류 정량화
    def share(sub: pd.DataFrame, whole: pd.DataFrame, col: str) -> float | None:
        w = whole[col].sum()
        return round(100 * sub[col].sum() / w, 2) if w else None

    cw = ref
    ss = ref[ref["gu"] == "성산구"]
    res = dict(
        method=("공장등록현황(공식)에서 법정동을 추출해 제조업 집적 법정동을 정의하고, "
                "KEPCO 2021 법정동 전력과 결합했다. 산단 경계가 아니라 상한이다"),
        boundary_polygon_available=False,
        dense_threshold_factories=DENSE_MIN_FACTORIES,
        factories_total=int(n_total),
        factories_parsed=int(matched.sum()),
        factories_parsed_pct=round(100 * float(matched.mean()), 1),
        factories_matched_kepco_dong=int(fm["in_kepco"].sum()),
        factories_matched_pct=round(100 * float(fm["in_kepco"].mean()), 1),
        changwon_dong_total=int(len(ref)),
        dense_dong_count=int(ref["is_dense"].sum()),
        dense_dong_list=sorted(f"{g} {d}" for g, d in
                               ref.loc[ref["is_dense"], ["gu", "legal_dong"]].values),
        seongsan_dong_total=int(len(ss)),
        seongsan_dense_dong_count=int(ss["is_dense"].sum()),
        # 핵심 수치들
        dense_share_of_changwon_mfg_power_pct=share(
            ref[ref["is_dense"]], cw, "mfg_power_kwh_2021_recovered"),
        seongsan_share_of_changwon_mfg_power_pct=share(
            ss, cw, "mfg_power_kwh_2021_recovered"),
        seongsan_dense_share_of_seongsan_mfg_power_pct=share(
            ss[ss["is_dense"]], ss, "mfg_power_kwh_2021_recovered"),
        dense_share_of_changwon_factories_pct=share(
            ref[ref["is_dense"]], cw, "n_factories"),
        masked_rows_total=int(kc["masked"].sum()),
        masked_rows_pct=round(100 * float(kc["masked"].mean()), 1),
        caveat=("법정동은 산단보다 넓고 산단 밖 공장·수요를 포함한다. 따라서 이 비중은 "
                "산단 전력의 **상한**이며 산단 전력 자체가 아니다. "
                "또한 2021년 복원된 월만 반영한다"),
        forbidden_reading=["성산구 = 창원국가산단",
                           "집적 법정동 전력 = 창원국가산단 전력",
                           "창원시 제조업 = 창원국가산단 제조업"],
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "spatial_context_legal_dong.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[집적] 창원 법정동 {res['changwon_dong_total']}개 중 "
          f"{res['dense_dong_count']}개가 공장 {DENSE_MIN_FACTORIES}건 이상")
    print(f"[전력] 집적 법정동이 창원 제조업 전력의 "
          f"{res['dense_share_of_changwon_mfg_power_pct']}%")
    print(f"[전력] 성산구 전체가 창원 제조업 전력의 "
          f"{res['seongsan_share_of_changwon_mfg_power_pct']}%")
    print(f"[전력] 성산구 안에서 집적 법정동 비중 "
          f"{res['seongsan_dense_share_of_seongsan_mfg_power_pct']}%")
    print(f"[ok] {(OUT_REF / 'changwon_legal_dong_manufacturing_context.csv').relative_to(ROOT)}")
    print(f"[ok] {(OUT / 'spatial_context_legal_dong.json').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
