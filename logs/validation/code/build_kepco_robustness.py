# -*- coding: utf-8 -*-
"""KEPCO 전력사용량 강건성 분석 (Triage 판정은 건드리지 않는다).

이 스크립트는 `outputs/decision_support_final/decision_panel.csv` 를 **읽기만** 한다.
stage / stage_reason / E / R / A / P 를 다시 계산하지도, 덮어쓰지도 않는다.
산출물도 기존 경로와 겹치지 않는 곳에만 쓴다.

산출
    data/processed/kepco/*.csv        월·분기 보조패널
    outputs/kepco_robustness/*        비교표·상관·REPORT

실행:  python src/build_kepco_robustness.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from context import kepco_power as kp                 # noqa: E402
from context import kepco_report as kr                # noqa: E402

TRIAGE_PANEL = ROOT / "outputs/decision_support_final/decision_panel.csv"
PROC = ROOT / "data/processed/kepco"
OUT = ROOT / "outputs/kepco_robustness"

# Triage 가 결정하고 이 스크립트가 절대 바꾸지 않는 열
FROZEN = ["stage", "stage_reason", "E", "R", "A", "P"]

LEGAL_DONG_VERIFY = (ROOT
                     / "data/raw/external/kepco/legal_dong/_metadata"
                     / "legal_dong_2021_verification.json")
PORTAL_VERIFY = (ROOT / "data/raw/external/kepco/_metadata"
                 / "portal_verification_20260919.json")
SPATIAL_CONTEXT = ROOT / "outputs/kepco_robustness/spatial_context_legal_dong.json"

MIN_N_CORR = 8          # 이보다 표본이 적으면 상관을 내지 않는다
DEADBAND_PCT = 1.0      # 방향 일치율 민감도용 무반응대

# Triage 가 확정한 값. 이 스크립트 실행 전후로 반드시 같아야 한다.
EXPECTED_STAGES = {"관찰": 128, "추가확인": 35, "우선점검": 17}
EXPECTED_ROWS = 180


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def check_triage_invariant(stage: str) -> dict:
    """decision_panel.csv 의 행수·판정분포를 확인한다. 어긋나면 즉시 멈춘다."""
    d = pd.read_csv(TRIAGE_PANEL, encoding="utf-8-sig")
    counts = d["stage"].value_counts().to_dict()
    if len(d) != EXPECTED_ROWS or counts != EXPECTED_STAGES:
        raise AssertionError(
            f"[{stage}] Triage 불변성 위반 — 행 {len(d)}(기대 {EXPECTED_ROWS}), "
            f"판정 {counts}(기대 {EXPECTED_STAGES})")
    return dict(stage=stage, rows=len(d), stages=counts,
                sha256=sha256_file(TRIAGE_PANEL))


def spearman(a: pd.Series, b: pd.Series) -> tuple[float, float, int]:
    m = a.notna() & b.notna()
    n = int(m.sum())
    if n < MIN_N_CORR:
        return np.nan, np.nan, n
    from scipy import stats
    r = stats.spearmanr(a[m], b[m])
    return float(r.statistic), float(r.pvalue), n


def agree(a: pd.Series, b: pd.Series, deadband: float = 0.0) -> dict:
    """방향 일치. 무반응대 안의 관측치는 '판정보류' 로 빼고 센다."""
    m = a.notna() & b.notna()
    if deadband > 0:
        m &= (a.abs() >= deadband) & (b.abs() >= deadband)
    n = int(m.sum())
    if n == 0:
        return dict(n=0, agree=np.nan, agree_pct=np.nan)
    same = int((np.sign(a[m]) == np.sign(b[m])).sum())
    return dict(n=n, agree=same, agree_pct=round(100 * same / n, 1))


def main() -> int:
    PROC.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    triage_before = check_triage_invariant("before")

    # ---------------------------------------------------------- 패널
    monthly = kp.build_monthly_panel(ROOT)
    if monthly.empty:
        print("[skip] KEPCO 원자료가 없다. 먼저 collect_kepco_power.py 를 실행한다.")
        return 1
    quarterly = kp.build_quarterly_panel(monthly)
    mfg = kp.build_manufacturing_total(ROOT)
    cust = kp.build_custnum_panel(ROOT)

    monthly.to_csv(PROC / "kepco_power_monthly_panel.csv", index=False, encoding="utf-8-sig")
    quarterly.to_csv(PROC / "kepco_power_quarterly_panel.csv", index=False, encoding="utf-8-sig")
    mfg.to_csv(PROC / "kepco_manufacturing_total_quarterly.csv", index=False, encoding="utf-8-sig")
    cust.to_csv(PROC / "kepco_custnum_change_quarterly.csv", index=False, encoding="utf-8-sig")

    # ---------------------------------------------------------- Triage 결합 (읽기 전용)
    tri = pd.read_csv(TRIAGE_PANEL, encoding="utf-8-sig")
    keep = ["quarter", "industry", "production_yoy", "employment_yoy",
            "production_yoy_valid", "employment_yoy_valid", "state", "stage"]
    tri = tri[[c for c in keep if c in tri.columns]].copy()
    tri_hash_before = pd.util.hash_pandas_object(tri, index=True).sum()

    q = quarterly[quarterly["kicox_mapped"]].copy()
    dup = q.duplicated(["quarter", "kicox_industry"]).sum()
    if dup:
        raise ValueError(f"보조패널에 (분기, 업종) 중복 {dup}건 — 결합 시 Triage 행이 늘어난다")
    j = tri.merge(q, left_on=["quarter", "industry"],
                  right_on=["quarter", "kicox_industry"], how="left")
    if len(j) != len(tri):
        raise ValueError(f"결합 후 행수 변화 {len(tri)} → {len(j)}. 전력자료가 Triage 행을 늘렸다")
    for c in ("production_yoy", "employment_yoy"):
        j[c] = pd.to_numeric(j[c], errors="coerce")
    # YoY 유효성 플래그를 존중한다. 무효 YoY 로는 비교하지 않는다.
    for c, v in (("production_yoy", "production_yoy_valid"),
                 ("employment_yoy", "employment_yoy_valid")):
        if v in j.columns:
            j.loc[j[v].astype(str).str.lower() != "true", c] = np.nan
    j = j.rename(columns={"power_usage_kwh_yoy": "power_yoy",
                          "power_usage_kwh_B_yoy": "power_yoy_Bonly",
                          "cust_cnt_yoy": "power_custcnt_yoy",
                          "cntr_pwr_kw_yoy": "cntr_pwr_yoy"})
    # 상관을 '쓸모 있음/없음' 판정으로 바꾸지 않는다. 각 지표가 던지는 후속 질문을
    # 행 단위로 남겨, 생산·고용과 다른 방향일 때도 진단 단서로 사용한다.
    j["diagnostic_total_power"] = np.where(
        j["power_yoy"].isna(), "판단불가(완전한 전년동기 자료 없음)",
        np.where(j["power_yoy"] < 0, "총 전력수요 감소 원인은 무엇인가?",
                 "총 전력수요 증가가 생산·가동 증가와 일치하는가?"))
    j["diagnostic_per_customer"] = np.where(
        j["power_usage_per_customer_yoy"].isna(), "판단불가(0·결측 분모 또는 불완전 분기)",
        np.where(j["power_usage_per_customer_yoy"] < 0,
                 "고객당 사용량 감소가 가동률·효율·구성 변화 중 무엇 때문인가?",
                 "고객당 사용량 증가가 집중 가동 또는 전력집약도 변화인가?"))
    j["diagnostic_contract_utilization"] = np.where(
        j["power_usage_per_contract_power_yoy"].isna(),
        "판단불가(0·결측 분모 또는 불완전 분기)",
        np.where(j["power_usage_per_contract_power_yoy"] < 0,
                 "계약전력 대비 사용량 감소가 유휴설비 증가를 시사하는가?",
                 "계약전력 대비 사용량 증가가 설비 활용도 상승을 시사하는가?"))
    _pers = j["monthly_signal_consistency"]
    j["diagnostic_monthly_persistence"] = np.select(
        [_pers == "PERSISTENT", _pers == "MAJORITY", _pers == "WEAK", _pers == "NONE"],
        ["3개월 모두 감소: 분기평균의 일시변동이 아닌 지속 원인 확인",
         "3개월 중 2개월 감소: 다수월 신호 확인",
         "3개월 중 1개월 감소: 일시 충격 여부 확인",
         "감소월 없음"],
        default="판단불가(월별 YoY 3개월 미확보)")
    j["comparable"] = j["power_yoy"].notna() & (
        j["production_yoy"].notna() | j["employment_yoy"].notna())
    j.to_csv(OUT / "kepco_vs_production_employment.csv", index=False, encoding="utf-8-sig")

    assert pd.util.hash_pandas_object(tri, index=True).sum() == tri_hash_before, \
        "Triage 입력이 변형됐다"

    # ---------------------------------------------------------- 요약
    res: dict = {}
    cmp_ = j[j["comparable"]]
    res["n_rows_joined"] = int(len(j))
    res["n_comparable"] = int(len(cmp_))
    res["quarters_with_power_yoy"] = sorted(j.loc[j["power_yoy"].notna(), "quarter"].unique())

    res["pooled"] = {
        "production_vs_power": dict(
            **agree(cmp_["production_yoy"], cmp_["power_yoy"]),
            **dict(zip(("spearman_rho", "p_value", "n_corr"),
                       spearman(cmp_["production_yoy"], cmp_["power_yoy"])))),
        "employment_vs_power": dict(
            **agree(cmp_["employment_yoy"], cmp_["power_yoy"]),
            **dict(zip(("spearman_rho", "p_value", "n_corr"),
                       spearman(cmp_["employment_yoy"], cmp_["power_yoy"])))),
    }
    res["pooled_deadband_1pct"] = {
        "production_vs_power": agree(cmp_["production_yoy"], cmp_["power_yoy"], DEADBAND_PCT),
        "employment_vs_power": agree(cmp_["employment_yoy"], cmp_["power_yoy"], DEADBAND_PCT),
    }
    res["sensitivity_B_grade_only"] = {
        "production_vs_power": agree(cmp_["production_yoy"], cmp_["power_yoy_Bonly"]),
        "employment_vs_power": agree(cmp_["employment_yoy"], cmp_["power_yoy_Bonly"]),
    }

    # 업종별. 규모를 함께 싣는다 — 전력량이 작은 업종의 YoY 는 잡음이 크다.
    scale = (quarterly[quarterly["completeness"] == "COMPLETE"]
             .groupby("kicox_industry", as_index=False)["power_usage_kwh"].mean()
             .rename(columns={"power_usage_kwh": "power_kwh_qmean"}))
    scale["power_share_pct"] = (100 * scale["power_kwh_qmean"]
                                / scale["power_kwh_qmean"].sum()).round(2)
    by_ind = []
    for ind, g in cmp_.groupby("industry"):
        pa, ea = agree(g["production_yoy"], g["power_yoy"]), agree(g["employment_yoy"], g["power_yoy"])
        pr, pp, pn = spearman(g["production_yoy"], g["power_yoy"])
        er, ep, en = spearman(g["employment_yoy"], g["power_yoy"])
        by_ind.append(dict(
            industry=ind, evidence_level=g["evidence_level"].max(),
            biz_types=g["biz_types"].iloc[0], n=len(g),
            prod_agree_n=pa["n"], prod_agree_pct=pa["agree_pct"],
            emp_agree_n=ea["n"], emp_agree_pct=ea["agree_pct"],
            prod_spearman=pr, prod_p=pp, prod_n_corr=pn,
            emp_spearman=er, emp_p=ep, emp_n_corr=en,
            power_yoy_mean=round(float(g["power_yoy"].mean()), 2),
            production_yoy_mean=round(float(g["production_yoy"].mean()), 2),
            employment_yoy_mean=round(float(g["employment_yoy"].mean()), 2)))
    by_ind = pd.DataFrame(by_ind).merge(
        scale.rename(columns={"kicox_industry": "industry"}), on="industry", how="left")

    # 다중검정 보정. 업종 10개 × (생산·고용) 2개 = 20회 검정이다.
    # 보정 없이 p<0.05 를 세면 우연히 1개쯤은 나온다.
    pv = pd.concat([by_ind["prod_p"], by_ind["emp_p"]]).to_numpy(dtype=float)
    ok = ~np.isnan(pv)
    qv = np.full_like(pv, np.nan)
    if ok.sum():
        from scipy import stats as _st
        qv[ok] = _st.false_discovery_control(pv[ok], method="bh")
    k = len(by_ind)
    by_ind["prod_q_bh"] = np.round(qv[:k], 4)
    by_ind["emp_q_bh"] = np.round(qv[k:], 4)
    by_ind = by_ind.sort_values("power_share_pct", ascending=False)
    by_ind.to_csv(OUT / "agreement_by_industry.csv", index=False, encoding="utf-8-sig")
    res["multiple_testing"] = dict(
        n_tests=int(ok.sum()),
        n_p_below_05=int((pv[ok] < 0.05).sum()),
        n_q_below_05_bh=int((qv[ok] < 0.05).sum()),
        note=("업종 10 × (생산·고용) 2 = 20회 검정. Benjamini-Hochberg FDR 보정 후 "
              "몇 개가 남는지로 판단한다"))

    # 상태(S1~S4)별 전력 신호
    if "state" in cmp_.columns:
        by_state = (cmp_.groupby("state")
                    .agg(n=("power_yoy", "size"),
                         power_yoy_median=("power_yoy", "median"),
                         power_yoy_mean=("power_yoy", "mean"),
                         n_negative=("power_yoy", lambda s: int((s < 0).sum())))
                    .reset_index())
        by_state["pct_negative"] = (100 * by_state["n_negative"] / by_state["n"]).round(1)
        by_state.to_csv(OUT / "power_by_state.csv", index=False, encoding="utf-8-sig")
        res["by_state"] = json.loads(by_state.to_json(orient="records"))

    # stage 별 (판정에 쓰지 않는다 — 사후 관찰일 뿐)
    if "stage" in cmp_.columns:
        by_stage = (cmp_.groupby("stage")
                    .agg(n=("power_yoy", "size"),
                         power_yoy_median=("power_yoy", "median"))
                    .reset_index())
        by_stage.to_csv(OUT / "power_by_stage.csv", index=False, encoding="utf-8-sig")
        res["by_stage"] = json.loads(by_stage.to_json(orient="records"))

    # lead/lag — 표본이 작다. 탐색적으로만.
    ll = []
    for k in (-2, -1, 0, 1, 2):
        s = cmp_.copy()
        shifted = (quarterly.assign(
            qi=quarterly["quarter"].str[:4].astype(int) * 4
               + quarterly["quarter"].str[5].astype(int) - 1)
            [["kicox_industry", "qi", "power_usage_kwh_yoy"]].copy())
        shifted["qi"] += k
        s["qi"] = s["quarter"].str[:4].astype(int) * 4 + s["quarter"].str[5].astype(int) - 1
        s = s.merge(shifted.rename(columns={"power_usage_kwh_yoy": "power_shift"}),
                    left_on=["industry", "qi"], right_on=["kicox_industry", "qi"],
                    how="left", suffixes=("", "_y"))
        pr, pp, pn = spearman(s["production_yoy"], s["power_shift"])
        er, ep, en = spearman(s["employment_yoy"], s["power_shift"])
        ll.append(dict(power_lag_quarters=k, prod_spearman=pr, prod_p=pp, prod_n=pn,
                       emp_spearman=er, emp_p=ep, emp_n=en))
    ll = pd.DataFrame(ll)
    ll.to_csv(OUT / "lead_lag_exploratory.csv", index=False, encoding="utf-8-sig")
    res["lead_lag_exploratory"] = json.loads(ll.to_json(orient="records"))

    # macro check: 업종합 vs 제조업 총량
    mapped_q = (quarterly[quarterly["kicox_mapped"] & (quarterly["completeness"] == "COMPLETE")]
                .groupby("quarter", as_index=False)["power_usage_kwh"].sum()
                .rename(columns={"power_usage_kwh": "kicox_mapped_sum_kwh"}))
    if mfg.empty:
        raise ValueError("산업분류별(제조업 총량) 원자료가 없다 — macro check 를 만들 수 없다")
    macro = mfg[["quarter", "completeness", "power_usage_kwh", "power_usage_kwh_yoy"]].rename(
        columns={"power_usage_kwh": "ksic_C_total_kwh",
                 "power_usage_kwh_yoy": "ksic_C_total_yoy",
                 "completeness": "ksic_C_completeness"})
    macro = macro.merge(mapped_q, on="quarter", how="left")
    macro["ratio_mapped_over_C"] = (macro["kicox_mapped_sum_kwh"]
                                    / macro["ksic_C_total_kwh"]).round(4)
    # 두 API 는 서로 다른 분류·엔드포인트다. 제조업 총량이 일치하면
    # crosswalk 의 '제조업 범위' 가 실증적으로 확인된 것이다(가정이 아니다).
    # 위치 기준 shift(4) 는 분기가 하나라도 비면 엉뚱한 분기를 전년동기로 쓴다.
    # 달력 분기 인덱스로 결합한다.
    macro["qi"] = (macro["quarter"].str[:4].astype(int) * 4
                   + macro["quarter"].str[5].astype(int) - 1)
    _lag = macro[["qi", "kicox_mapped_sum_kwh"]].copy()
    _lag["qi"] += 4
    _lag = _lag.rename(columns={"kicox_mapped_sum_kwh": "kicox_mapped_sum_kwh_lag4"})
    macro = macro.merge(_lag, on="qi", how="left")
    _base = macro["kicox_mapped_sum_kwh_lag4"]
    macro["mapped_sum_yoy"] = ((macro["kicox_mapped_sum_kwh"] / _base - 1) * 100).where(
        _base.notna() & (_base > 0))
    macro = macro.drop(columns=["qi"])
    both = macro.dropna(subset=["ksic_C_total_yoy", "mapped_sum_yoy"])
    macro.to_csv(OUT / "macro_check_vs_ksic_manufacturing.csv", index=False,
                 encoding="utf-8-sig")
    r_ = macro["ratio_mapped_over_C"]
    res["macro_check"] = dict(
        ratio_median=float(r_.median(skipna=True)) if r_.notna().any() else None,
        ratio_min=float(r_.min(skipna=True)) if r_.notna().any() else None,
        ratio_max=float(r_.max(skipna=True)) if r_.notna().any() else None,
        yoy_pearson=(round(float(both["ksic_C_total_yoy"].corr(both["mapped_sum_yoy"])), 4)
                     if len(both) >= MIN_N_CORR else None),
        yoy_mean_abs_diff_pp=(round(float((both["ksic_C_total_yoy"]
                                           - both["mapped_sum_yoy"]).abs().mean()), 3)
                              if len(both) else None),
        n=int(len(both)),
        interpretation=("업종별 API 의 제조업 업종 합계와 산업분류별 API 의 KSIC C "
                        "제조업이 일치하면, KEPCO 업종↔KSIC 제조업 '범위' 대응이 "
                        "실증 확인된 것이다. 단 이는 총량 수준의 확인이며 "
                        "KICOX 10업종 배분의 정확성을 보증하지 않는다"))

    # 공식 화면은 신설·증설·해지 모두 KWH로 표시한다. 'custNum'이라는 경로명만
    # 보고 고객/계약 건수로 바꾸지 않는다. 상세 산식이 없어 분석 입력에서는 제외한다.
    res["custnum_assessment"] = dict(
        status="NOT_SUITABLE",
        official_display_unit="KWH",
        reason=("공식 화면에 신설(KWH)·증설(KWH)·해지(KWH)로 표시되지만 "
                "상세 산식·모집단 정의가 공표되지 않아 고객수나 계약 건수로 해석할 수 없음"),
        retained_for="원값 보존과 API 응답 진단만",
    )

    # 완전성 요약
    comp = (quarterly.groupby(["kicox_industry", "completeness"]).size()
            .unstack(fill_value=0).reset_index())
    comp.to_csv(OUT / "quarterly_completeness.csv", index=False, encoding="utf-8-sig")
    res["completeness_by_quarter"] = json.loads(
        quarterly[quarterly["kicox_mapped"]]
        .groupby("quarter")["completeness"].agg(lambda s: s.mode()[0])
        .reset_index().to_json(orient="records"))
    res["diagnostic_questions"] = [
        "총 전력수요 변화가 생산 변화와 같은 방향인가?",
        "고객당 사용량 변화는 가동률·효율·업체 구성 중 무엇을 반영하는가?",
        "계약전력 대비 사용량 변화는 설비 활용도의 변화인가?",
        "고객호수와 계약전력 변화가 총사용량 변화보다 먼저 나타나는가?",
        "분기 신호가 세 달 모두 지속되는가, 다수월인가, 한 달짜리인가?",
    ]
    xw = kp.load_crosswalk(ROOT)
    for grade in ("B", "C", "D"):
        res[f"_xwalk_{grade}"] = int((xw["evidence_level"] == grade).sum())

    # ---------------------------------------------------------- 정규화 보조지표
    qm = quarterly[quarterly["kicox_mapped"]]
    res["normalized_indicators"] = {}
    for col, formula in (
        ("total_power_usage_yoy", "분기 powerUsage 합계의 전년동기비(%)"),
        ("power_usage_per_customer", "powerUsage / custCnt (분기말 고객호수)"),
        ("power_usage_per_customer_yoy", "위 비율의 전년동기비(%)"),
        ("power_usage_per_contract_power", "powerUsage / cntrPwr (분기말 계약전력)"),
        ("power_usage_per_contract_power_yoy", "위 비율의 전년동기비(%)"),
        ("customer_count_yoy", "분기말 custCnt 의 전년동기비(%)"),
        ("contract_power_yoy", "분기말 cntrPwr 의 전년동기비(%)"),
    ):
        v = pd.to_numeric(qm[col], errors="coerce")
        res["normalized_indicators"][col] = dict(
            definition=formula, n_valid=int(v.notna().sum()),
            n_rows=int(len(qm)),
            median=(round(float(v.median()), 3) if v.notna().any() else None),
            n_negative=int((v < 0).sum()),
        )

    # ---------------------------------------------------------- 월별 지속성
    pers = qm[qm["completeness"] == "COMPLETE"]["monthly_signal_consistency"]
    res["monthly_persistence"] = dict(
        definition=("monthly_negative_months = 분기 내 power_usage_yoy<0 인 월 수. "
                    "PERSISTENT 3/3 · MAJORITY 2/3 · WEAK 1/3 · NONE 0/3 · "
                    "INCOMPLETE 월별 YoY 3개 미확보"),
        caveat=("같은 분기 안에서 신호가 반복되는지를 보는 보조지표다. "
                "표본수 증가도, 예측력 향상도 아니다"),
        distribution={k: int(v) for k, v in pers.value_counts().items()},
    )

    # ---------------------------------------------------------- 2021 대체자료
    if LEGAL_DONG_VERIFY.exists():
        ld = json.loads(LEGAL_DONG_VERIFY.read_text(encoding="utf-8"))
        res["legal_dong_2021"] = {k: ld[k] for k in (
            "integrity", "months_recoverable", "months_declared",
            "sheets_unrecoverable", "header_actual", "changwon_sigungu",
            "changwon_legal_dong_count", "ksic_major_count",
            "ksic_mid_count_manufacturing", "masking_token", "masked_share_pct",
            "legal_dong_code_present", "spatial_note",
            "substitution_verdict", "substitution_reason") if k in ld}
    else:
        res["legal_dong_2021"] = dict(
            substitution_verdict="STRUCTURALLY_UNAVAILABLE",
            substitution_reason="검증 파일이 없다. verify_kepco_legal_dong_2021.py 를 먼저 실행한다")

    # ---------------------------------------------------------- 포털 재확인 (로그인 화면)
    if PORTAL_VERIFY.exists():
        pv = json.loads(PORTAL_VERIFY.read_text(encoding="utf-8"))
        res["portal_verification"] = pv
        res["http_403_assessment"] = pv["http_403_investigation"]
    # ---------------------------------------------------------- 공간 context
    if SPATIAL_CONTEXT.exists():
        res["spatial_context"] = json.loads(SPATIAL_CONTEXT.read_text(encoding="utf-8"))

    res["custnum_assessment"]["status"] = "NOT_SUITABLE"
    res["final_kepco_status"] = "PARTIAL_CONTEXT"
    res["role"] = "CONTEXT / ACTIVITY only; Triage inputs unchanged"

    # ---------------------------------------------------------- Triage 불변성
    triage_after = check_triage_invariant("after")
    if triage_before["sha256"] != triage_after["sha256"]:
        raise AssertionError("decision_panel.csv 바이트가 변했다 — 읽기 전용 위반")
    res["triage_invariance"] = dict(before=triage_before, after=triage_after,
                                    unchanged=True)

    (OUT / "results_summary.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (OUT / "REPORT.md").write_text(
        kr.build(res, monthly, quarterly, j), encoding="utf-8")

    print(f"[ok] monthly={len(monthly)} quarterly={len(quarterly)} "
          f"joined={len(j)} comparable={len(cmp_)}")
    print(f"[ok] {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
