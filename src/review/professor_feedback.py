# -*- coding: utf-8 -*-
"""교수 검토 피드백용 재현 가능한 표·그림을 생성한다.

계산은 이 Python 모듈에만 둔다. 최종 노트북은 여기서 저장한 결과를 읽어 표시한다.
Triage 단계는 ``src.triage`` 정본을 그대로 사용하며 이 모듈은 단계를 재계산하거나
ELECTRE 결과로 교체하지 않는다.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from handoff import delivery
from triage import triage_rule as tr

OUT = ROOT / "outputs/final_model/06_report_assets/professor_feedback"
TABLES = OUT / "tables"
FIGURES = OUT / "figures"


def _as_bool(value: object) -> bool:
    """CSV의 bool/object 혼합 열을 문자열 truthiness 없이 안전하게 읽는다."""
    if pd.isna(value):
        return False
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value).strip().lower() in {"true", "1", "yes"}


def _save(df: pd.DataFrame, name: str) -> pd.DataFrame:
    TABLES.mkdir(parents=True, exist_ok=True)
    df.to_csv(TABLES / name, index=False, encoding="utf-8-sig")
    return df


def _full_levels() -> pd.DataFrame:
    """분석기간 이전(2018Q1~)까지 포함한 업종×분기 고용·생산 수준값(정본 master)."""
    master = pd.read_csv(ROOT / "data/processed/kicox/changwon_industry_master.csv")
    return master[["industry", "quarter", "employment", "production"]]


def build_panel() -> pd.DataFrame:
    master = pd.read_csv(ROOT / "data/processed/kicox/changwon_industry_master.csv")
    state = pd.read_csv(ROOT / "data/processed/kicox/changwon_state_panel.csv")
    axes = tr.compute_axes(master)
    keep = [
        "industry", "quarter", "state", "run_length", "transition_type", "previous_state",
        "production_yoy_reason", "production_current_missing", "production_lag4_missing",
        "employment_yoy_reason",
    ]
    merged = axes.merge(state[keep], on=["industry", "quarter"], how="left", validate="one_to_one")
    panel = tr.add_routing(tr.apply_rule(merged))
    panel = delivery.trace_columns(panel)
    return panel[panel.quarter.between("2022Q1", "2026Q2")].sort_values(["quarter", "industry"])


def qa_cases(panel: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "industry", "quarter", "employment_lag1", "employment", "emp_qoq_pct",
        "production_lag1", "production", "production_qoq_pct", "firms_op_lag1", "firms_op",
        "firms_op_qoq_delta", "qa_emp_qoq_abs_p95", "qa_production_qoq_abs_p95",
        "qa_firms_op_abs_median", "qa_level_shift_flag", "qa_level_shift_reason", "stage",
    ]
    return _save(panel.loc[panel.qa_level_shift_flag, cols], "qa_level_shift_cases.csv")


def boundary_cases(panel: pd.DataFrame) -> pd.DataFrame:
    focus = panel[(panel.industry == "목재종이") & panel.quarter.isin(["2026Q1", "2026Q2"])].copy()
    focus["loss_if_one_fewer"] = (-focus.emp_delta).clip(lower=0) - 1
    focus["E_if_one_fewer_loss"] = focus.loss_if_one_fewer / focus.employment_lag4 * 100
    cols = [
        "industry", "quarter", "employment_lag4", "employment", "emp_delta", "E", "E_up",
        "E_upper_margin_pp", "E_upper_boundary_loss_exact", "E_upper_boundary_loss_min_int",
        "E_upper_headcount_margin", "E_upper_headcount_to_flip", "loss_if_one_fewer",
        "E_if_one_fewer_loss", "stage",
    ]
    return _save(focus[cols], "wood_paper_boundary_margin.csv")


def machine_interpretation(panel: pd.DataFrame) -> pd.DataFrame:
    row = panel[(panel.industry == "기계") & (panel.quarter == "2026Q2")].iloc[0]
    qoq = pd.read_csv(ROOT / "outputs/final_model/01_core/tables/qoq_yoy_comparison.csv")
    qoq_row = qoq[(qoq.industry == "기계") & (qoq.quarter == "2026Q2")].iloc[0]
    recent = qoq[(qoq.industry == "기계") & qoq.quarter.between("2023Q1", "2026Q2")]
    peak = recent.loc[recent.employment.idxmax()]
    result = pd.DataFrame([{
        "industry": "기계", "quarter": "2026Q2", "employment_2025Q2": row.employment_lag4,
        "employment_2026Q1": row.employment_lag1, "employment_2026Q2": row.employment,
        "yoy_change": row.emp_delta, "qoq_change": row.emp_qoq_delta,
        "yoy_pct": row.e_yoy, "qoq_pct": row.emp_qoq_pct,
        "qoq_recovery_while_yoy_below": _as_bool(qoq_row.qoq_recovery_while_yoy_below),
        "peak_since_2023_quarter": peak.quarter, "peak_since_2023_employment": peak.employment,
        "comparison_is_peak_since_2023": bool(
            row.employment_lag4 == peak.employment and peak.quarter == "2025Q2"),
        "manufacturing_yoy_change": row.mfg_emp_delta, "contribution_pct": row.contribution_pct,
        "interpretation": (
            "전년동기 대비 감소는 크지만 최근 전분기 감소는 상대적으로 작다. "
            "비교기준 고점 이후 조정, 최근 안정화, 기업 단위 감원 지속 여부를 현장에서 구분해야 한다."
        ),
        "trend_check_question": row.trend_check_question,
    }])
    return _save(result, "machine_yoy_qoq_interpretation.csv")


def level_shift_decomposition(panel: pd.DataFrame, industry: str = "목재종이") -> pd.DataFrame:
    """[1] 전년동기 변화를 'QA 급변 분기의 한 분기 변화'와 '그 밖의 변화'로 정확히 분해한다.

    YoY 차이 = 직전 4개 분기의 QoQ 차이 합이다. 비교창 안에 QA 수준변화 분기가 있으면 그 분기의
    QoQ 차이를 수준변화 성분으로, 나머지를 그 밖의 변화로 둔다. 비교창에 결측이 있으면 분해하지 않는다.
    '수준변화 제외 방향'은 기저효과 해석용 참고값이며 국면·단계를 재분류하지 않는다.
    """
    d = panel[panel.industry.eq(industry)].sort_values("quarter").set_index("quarter")
    # 비교창의 QoQ는 분석기간 이전 분기(2021년)까지 필요하므로 원자료 전체 이력의 수준값을 쓴다
    levels = _full_levels()
    levels = levels[levels.industry.eq(industry)].set_index("quarter")
    shift_quarters = [q for q in d.index if _as_bool(d.at[q, "qa_level_shift_flag"])]
    rows = []
    for quarter in d.index:
        periods = pd.Period(quarter, freq="Q")
        window = [str(periods - k) for k in range(4)]
        in_window = [q for q in shift_quarters if q in window]
        if not in_window:
            continue
        row = {"industry": industry, "quarter": quarter, "shift_quarters_in_window": ",".join(in_window),
               "q1_state": d.at[quarter, "state"], "stage": d.at[quarter, "stage"]}
        for var, lag4, label in (("employment", "employment_lag4", "emp"), ("production", "production_lag4", "prod")):
            deltas = []
            for q in window:
                prev = str(pd.Period(q, freq="Q") - 1)
                cur_v = levels[var].get(q, np.nan)
                prev_v = levels[var].get(prev, np.nan)
                deltas.append((q, cur_v - prev_v if pd.notna(cur_v) and pd.notna(prev_v) else np.nan))
            base = d.at[quarter, lag4]
            yoy_delta = d.at[quarter, var] - base if pd.notna(base) else np.nan
            complete = all(pd.notna(v) for _, v in deltas) and pd.notna(yoy_delta)
            shift = sum(v for q, v in deltas if q in in_window) if complete else np.nan
            other = yoy_delta - shift if complete else np.nan
            row.update({
                f"{label}_yoy_delta": yoy_delta,
                f"{label}_yoy_pct": yoy_delta / base * 100 if complete and base else np.nan,
                f"{label}_level_shift_component": shift,
                f"{label}_other_component": other,
                f"{label}_yoy_pct_excluding_shift": other / base * 100 if complete and base else np.nan,
            })
        def sign(v):
            return np.nan if pd.isna(v) else ("↑" if v > 0 else "↓" if v < 0 else "0")
        row["direction_excluding_shift"] = (
            f"생산{sign(row['prod_other_component'])}·고용{sign(row['emp_other_component'])}"
            if pd.notna(row["prod_other_component"]) and pd.notna(row["emp_other_component"]) else "분해 불가(결측)")
        row["note"] = "수준변화 분기의 QoQ를 분리한 참고 분해 — 국면·단계를 재분류하지 않음"
        rows.append(row)
    return _save(pd.DataFrame(rows), "wood_paper_level_shift_decomposition.csv")


def base_peak_check(panel: pd.DataFrame) -> pd.DataFrame:
    """[2] 우선점검 행마다 비교기준 분기(4분기 전)가 직전 고점이었는지와 최근 1분기 변화의 몫을 본다."""
    levels = _full_levels()
    rows = []
    for r in panel[panel.stage.eq("우선점검")].sort_values(["industry", "quarter"]).itertuples(index=False):
        base_q = str(pd.Period(r.quarter, freq="Q") - 4)
        hist = levels[(levels.industry == r.industry) & levels.quarter.between(
            str(pd.Period(base_q, freq="Q") - 4), str(pd.Period(r.quarter, freq="Q") - 1))]
        prior_max = hist.employment.max()
        rows.append({
            "industry": r.industry, "quarter": r.quarter, "base_quarter": base_q,
            "base_employment": r.employment_lag4, "employment": r.employment,
            "yoy_delta": r.emp_delta, "qoq_delta": r.emp_qoq_delta,
            "latest_quarter_share_of_yoy_pct": (
                r.emp_qoq_delta / r.emp_delta * 100 + 0.0 if r.emp_delta and pd.notna(r.emp_qoq_delta) else np.nan),
            "max_employment_prior_8q": prior_max,
            "base_is_prior_8q_peak": bool(pd.notna(prior_max) and r.employment_lag4 >= prior_max),
            "reading": ("비교기준이 직전 고점 — 고점 이후 조정이 YoY에 누적 반영"
                        if pd.notna(prior_max) and r.employment_lag4 >= prior_max else "비교기준이 고점 아님"),
        })
    return _save(pd.DataFrame(rows), "priority_base_peak_check.csv")


def ratio_boundary_headcount(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """[3] 고용감소율(E) 경계(5%·10%)의 통과 여부가 몇 명 차이로 바뀌는지 업종 규모별로 요약한다.

    한 행의 '최소 전환 인원'은 E 진입(5%)·상위(10%) 충족 여부 중 하나라도 바뀌는 데 필요한
    최소 감소인원 변화다. 판정은 바꾸지 않고, 비율 경계의 인원 민감도만 기술한다.
    """
    d = panel[panel.employment_lag4.notna() & panel.employment.notna()].copy()
    loss = (-d.emp_delta).clip(lower=0)
    flips = []
    for boundary in (tr.LEVEL_ENTRY, tr.LEVEL_UP):
        min_int = (d.employment_lag4 * boundary / 100).map(lambda x: math.ceil(x - tr.COMPARISON_ATOL))
        now = tr.reached(d.E.fillna(0), boundary)
        flips.append(np.where(now, loss - (min_int - 1), min_int - loss))
        d[f"loss_at_E{int(boundary)}"] = min_int
    d["persons_per_E_1pp"] = d.employment_lag4 / 100
    d["min_headcount_to_flip_E_status"] = np.minimum(*flips)
    d["size_group"] = np.where(d.employment.ge(tr.SCALE_MIN), f"{tr.SCALE_MIN}인 이상", f"{tr.SCALE_MIN}인 미만")
    d["flip_within_2"] = d.min_headcount_to_flip_E_status.le(2)
    summary = (d.groupby("size_group")
               .agg(rows=("industry", "size"),
                    median_employment=("employment", "median"),
                    median_persons_per_E_1pp=("persons_per_E_1pp", "median"),
                    rows_flip_within_2=("flip_within_2", "sum"),
                    share_flip_within_2_pct=("flip_within_2", lambda s: s.mean() * 100))
               .reset_index())
    summary["reading"] = "E 경계 충족 여부가 2명 이내 변화로 바뀌는 행의 비중 — 비율 경계의 인원 민감도"
    _save(summary, "ratio_boundary_headcount_summary.csv")
    latest = d[d.quarter.eq(d.quarter.max())][
        ["industry", "quarter", "employment_lag4", "employment", "emp_delta", "E", "persons_per_E_1pp",
         "loss_at_E5", "loss_at_E10", "min_headcount_to_flip_E_status", "size_group", "stage"]
    ].sort_values("employment_lag4")
    _save(latest, "ratio_boundary_headcount_latest.csv")
    return summary, latest


def validation_followup() -> tuple[pd.DataFrame, pd.DataFrame]:
    base = ROOT / "logs/validation/outputs/rolling_backtest"
    pred = pd.read_csv(base / "predictions_long.csv")
    out = pd.read_csv(base / "outcomes_long.csv")
    triage = pred[pred.model.eq("triage_final")][["industry", "quarter", "stage"]].drop_duplicates()
    primary = out[(out.outcome.eq("primary")) & out.outcome_valid.astype(bool)].copy()
    primary["recovery"] = primary.u_E.gt(0)
    h1 = primary[primary.horizon.eq(1)][["industry", "quarter", "recovery"]].rename(
        columns={"recovery": "recovery_1q"})
    h2 = primary[primary.horizon.eq(2)][["industry", "quarter", "recovery", "label"]].rename(
        columns={"recovery": "recovery_2q", "label": "additional_contraction_2q"})
    joined = triage.merge(h1, on=["industry", "quarter"]).merge(h2, on=["industry", "quarter"])
    order = ["우선점검", "추가확인", "관찰"]
    summary = (joined.groupby("stage", observed=True)
               .agg(N=("industry", "size"), recovery_rate_1q=("recovery_1q", "mean"),
                    recovery_rate_2q=("recovery_2q", "mean"),
                    additional_contraction_rate_2q=("additional_contraction_2q", "mean"))
               .reindex(order).reset_index())
    summary["definition"] = (
        "회복률: 원점 대비 미래 고용 증가(u_E>0); 2분기 추가수축률: 미래 고용도 감소하고 "
        "전년동기 경로도 더 악화(u_E<0 and d_E<0)"
    )
    _save(summary, "signal_followup_summary.csv")

    metrics = pd.read_csv(base / "metrics_long.csv")
    selected = metrics[
        metrics.record_type.eq("model_metrics") & metrics.experiment.eq("MAIN")
        & metrics.outcome.eq("primary") & metrics.horizon.eq(2) & metrics["groupby"].eq("pooled")
        & metrics.model.isin(["triage_final", "electre_fixed"])
    ][["model", "N", "positives", "negatives", "recall", "precision", "FPR", "balanced_accuracy",
       "alert_count", "alert_rate", "evidence_status"]]
    selected["model_role"] = selected.model.map({
        "triage_final": "주모형", "electre_fixed": "보조 비교모형",
    })
    selected["interpretation"] = (
        "균형정확도는 기술통계적 비교값이며 표본·사전등록 제약 때문에 우월성·정책효과를 뜻하지 않는다."
    )
    _save(selected, "validation_model_comparison.csv")
    return summary, selected


CCI_DIR = ROOT / "data/raw/changwon_chamber"
CCI_INDUSTRY = {"기계": "기계", "운송장비": "운송장비", "전기·전자": "전기전자", "철강": "철강",
                "음식료": "음식료", "석유·화학": "석유화학"}  # '기타'는 목재종이 등을 합친 값이라 대조하지 않는다


def _read_cci() -> pd.DataFrame:
    frames = []
    for path in sorted(CCI_DIR.glob("창원국가산단_업종별현황_*.csv")):
        quarter = path.stem.rsplit("_", 1)[-1]
        text = path.read_text(encoding="utf-8-sig").splitlines()
        lines = [ln for ln in text if not ln.startswith('"#')]
        frame = pd.read_csv(pd.io.common.StringIO("\n".join(lines)))
        frame["quarter"] = quarter
        frame["source_file"] = path.name
        # 전사본 머리말의 출처(보고서명·발간월·원문 URL)를 결과표에 남긴다 — data/raw는 저장소에 올리지 않는다
        frame["source_note"] = (text[0].strip('"').removeprefix("# 출처: ")
                                if text and text[0].startswith('"#') else "")
        frames.append(frame)
    cci = pd.concat(frames, ignore_index=True)
    cci = cci[cci["업종"].isin(CCI_INDUSTRY)].copy()
    cci["industry"] = cci["업종"].map(CCI_INDUSTRY)
    return cci.rename(columns={"고용_전년동기대비(%)": "cci_emp_yoy", "생산_전년동기대비(%)": "cci_prod_yoy",
                               "수출_전년동기대비(%)": "cci_export_yoy", "고용(명)": "cci_employment"})


def cci_concurrent_check(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """[4] 동시점 타당성: 판정 패널(KICOX 연간보정본)과 같은 분기 창원상공회의소 공표값(KICOX 속보치 인용)의
    전년동기 방향을 대조한다. 창원상의 값은 Triage 입력이 아니며 단계를 재계산하지 않는다."""
    cci = _read_cci()
    cols = ["industry", "quarter", "stage", "employment", "e_yoy", "production_yoy"]
    joined = cci.merge(panel[cols], on=["industry", "quarter"], how="inner", validate="one_to_one")

    def agree(a, b):
        return np.where(a.isna() | b.isna(), None, np.sign(a.round(6)) == np.sign(b.round(6)))
    joined["emp_direction_agree"] = agree(joined.e_yoy, joined.cci_emp_yoy)
    joined["prod_direction_agree"] = agree(joined.production_yoy, joined.cci_prod_yoy)
    joined["emp_yoy_gap_pp"] = joined.e_yoy - joined.cci_emp_yoy
    rows = joined[["industry", "quarter", "stage", "employment", "cci_employment", "e_yoy", "cci_emp_yoy",
                   "emp_direction_agree", "emp_yoy_gap_pp", "production_yoy", "cci_prod_yoy",
                   "prod_direction_agree", "cci_export_yoy", "source_file", "source_note"]].sort_values(["industry", "quarter"])
    _save(rows, "cci_concurrent_check.csv")

    def rate(s):
        s = s.dropna()
        return f"{int(s.sum())}/{len(s)}" if len(s) else "—"
    groups = [("전체 대조 행", rows), ("우선점검 행", rows[rows.stage.eq("우선점검")]),
              ("기계 2023Q1~2024Q1", rows[rows.industry.eq("기계") & rows.quarter.between("2023Q1", "2024Q1")])]
    summary = pd.DataFrame([{
        "group": name, "rows": len(g), "emp_direction_agree": rate(g.emp_direction_agree.astype("object")),
        "prod_direction_agree": rate(g.prod_direction_agree.astype("object")),
        "median_abs_emp_gap_pp": g.emp_yoy_gap_pp.abs().median(),
    } for name, g in groups])
    summary["note"] = ("창원상의 표는 KICOX 속보치를 인용하고 판정 패널은 연간보정본이다. "
                       "방향 일치는 동시점 정합성 점검이며 판정 입력이 아니다.")
    _save(summary, "cci_concurrent_summary.csv")
    return rows, summary


PRESS_SOURCES = OUT / "sources/press_concurrent_sources.csv"


def press_concurrent_check(panel: pd.DataFrame) -> pd.DataFrame:
    """[4] 언론·기관 발표와 같은 시기 판정의 대조. 근거 문장·URL은 수기 근거표(sources/)에 두고,
    판정 패널의 단계·고용 증감률을 옆에 붙인다. 일치 판단은 근거표의 assessment(모집단 차이 설명 포함)를 그대로 쓴다."""
    src = pd.read_csv(PRESS_SOURCES, encoding="utf-8")
    rows = []
    for r in src.itertuples(index=False):
        qs = r.quarters.split(";")
        sub = panel[(panel.industry == r.industry) & panel.quarter.isin(qs)].sort_values("quarter")
        rows.append({
            "case_id": r.case_id, "industry": r.industry, "quarters": r.quarters,
            "panel_stages": " · ".join(f"{q} {s}" for q, s in zip(sub.quarter, sub.stage)),
            "panel_emp_yoy_range": (f"{sub.e_yoy.min():.2f}% ~ {sub.e_yoy.max():.2f}%"
                                    if sub.e_yoy.notna().any() else "—"),
            "outlet": r.outlet, "published": r.published, "indicator": r.indicator,
            "population": r.population, "evidence": r.evidence, "assessment": r.assessment,
            "assessment_note": r.assessment_note, "url": r.url,
        })
    return _save(pd.DataFrame(rows), "press_concurrent_cases.csv")


def mean_reversion_diagnosis() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """[4] 평균회귀 가설의 정밀 점검(사후 진단 — 사전등록 주평가를 대체하지 않는다).

    주평가 양성 = 2분기 뒤 고용 수준 감소(u_E<0) AND 전년동기 대비 이동 악화(d_E<0).
    두 조건을 나눠 보면, Triage가 고르는 '이미 전년동기 감소가 큰 행'에서 고용 수준 감소는 이어지는데
    증감률만 평균 쪽으로 되돌아와(d_E>0) 양성이 되지 않는지 확인할 수 있다.
    """
    base = ROOT / "logs/validation/outputs/rolling_backtest"
    pred = pd.read_csv(base / "predictions_long.csv")
    out = pd.read_csv(base / "outcomes_long.csv")
    tri = pred[pred.model.eq("triage_final")][["industry", "quarter", "stage", "e_yoy"]].drop_duplicates()
    h2 = out[out.outcome.eq("primary") & out.horizon.eq(2) & out.outcome_valid.astype(bool)]
    d = tri.merge(h2[["industry", "quarter", "u_E", "d_E", "label"]], on=["industry", "quarter"])
    d["level_down"] = d.u_E.lt(0)
    d["yoy_worse"] = d.d_E.lt(0)
    d["label"] = d.label.astype(bool)

    order = ["우선점검", "추가확인", "관찰"]
    by_stage = (d.groupby("stage").agg(N=("industry", "size"), level_down_rate=("level_down", "mean"),
                                       yoy_worse_rate=("yoy_worse", "mean"),
                                       primary_positive_rate=("label", "mean"),
                                       median_d_E_pp=("d_E", "median"))
                .reindex(order).reset_index())
    by_stage["reading"] = "level_down=2분기 뒤 고용 수준 감소 · yoy_worse=전년동기 대비 이동 악화 · primary=둘 다"
    _save(by_stage, "mean_reversion_by_stage.csv")

    groups = pd.cut(d.e_yoy, [-np.inf, -10, -5, 0, 5, np.inf],
                    labels=["≤-10%", "-10~-5%", "-5~0%", "0~5%", ">5%"])
    by_yoy = (d.groupby(groups, observed=True).agg(N=("industry", "size"), median_d_E_pp=("d_E", "median"),
                                                   yoy_worse_rate=("yoy_worse", "mean"),
                                                   level_down_rate=("level_down", "mean"),
                                                   primary_positive_rate=("label", "mean"))
              .reset_index().rename(columns={"e_yoy": "current_emp_yoy_group"}))
    _save(by_yoy, "mean_reversion_by_current_yoy.csv")

    def balanced_accuracy(y: pd.Series, alert: pd.Series) -> float:
        tp, fn = (alert & y).sum(), (~alert & y).sum()
        tn, fp = (~alert & ~y).sum(), (alert & ~y).sum()
        return float(((tp / (tp + fn)) + (tn / (tn + fp))) / 2)

    alert = d.stage.isin(["우선점검", "추가확인"])  # 사전등록 선별 기준(단계≥추가확인)
    rho = d[["e_yoy", "d_E"]].corr(method="spearman").iloc[0, 1]
    summary = pd.DataFrame([
        {"item": "현재 고용 증감률과 2분기 뒤 증감률 변화의 순위상관(Spearman)", "value": rho,
         "note": "음수면 현재 증감률이 나쁠수록 이후 되돌아옴(증감률의 평균회귀)"},
        {"item": "주평가 균형정확도(수준↓ AND 증감률 악화, 사전등록)", "value": balanced_accuracy(d.label, alert),
         "note": "사전등록 결과 — 이 표의 다른 값으로 대체하지 않음"},
        {"item": "탐색: 고용 수준 감소 지속만 양성으로 본 균형정확도(단계≥추가확인)",
         "value": balanced_accuracy(d.level_down, alert), "note": "사후 탐색 — 성능 주장에 쓰지 않음"},
        {"item": "탐색: 고용 수준 감소 지속만 양성으로 본 균형정확도(우선점검만 경보)",
         "value": balanced_accuracy(d.level_down, d.stage.eq("우선점검")), "note": "사후 탐색 — 성능 주장에 쓰지 않음"},
        {"item": "평가 행 수(h=2 primary 유효·Triage 판정 결합)", "value": float(len(d)),
         "note": "업종·연속 분기로 서로 독립이 아님"},
    ])
    _save(summary, "mean_reversion_summary.csv")
    return by_stage, by_yoy, summary


def purpose_aligned_validation(n_boot: int = 2000, seed: int = 20260928) -> tuple[pd.DataFrame, pd.DataFrame]:
    """[4] 보강(사후) 검증: Triage 목적(지금 감소가 큰 업종을 먼저 확인)에 맞춘 기준으로 부가가치를 본다.

    사전등록 주평가(추가 위축)는 그대로 두고 함께 표시한다. 보강 기준 '신호 지속' = 2분기 뒤 고용 전년동기
    감소율이 E 진입경계(5%) 이상 유지. 비교 대상은 같은 행의 단순 규칙(현재 고용 YoY<0)과 ELECTRE.
    판정 분기 단위 묶음 부트스트랩으로 정밀도·오경보율 차이의 구간을 낸다(업종·분기 의존성 때문).
    """
    base = ROOT / "logs/validation/outputs/rolling_backtest"
    pred = pd.read_csv(base / "predictions_long.csv")
    out = pd.read_csv(base / "outcomes_long.csv")
    h2 = out[out.outcome.eq("primary") & out.horizon.eq(2) & out.outcome_valid.astype(bool)].copy()
    h2["signal_persist"] = ((h2.E_future / h2.E_future_lag4 - 1) * 100).le(-tr.LEVEL_ENTRY)
    h2["primary"] = h2.label.astype(bool)
    models = {"triage_final": "Triage(주모형)", "current_negative_e_yoy": "단순 규칙(현재 고용 YoY<0)",
              "electre_fixed": "ELECTRE(보조모형)"}
    frames = {}
    for model in models:
        d = pred[pred.model.eq(model)][["industry", "quarter", "stage_code"]].merge(
            h2[["industry", "quarter", "primary", "signal_persist"]], on=["industry", "quarter"])
        d["alert"] = d.stage_code.fillna(0).ge(1)  # 사전등록과 같은 선별 기준(단계≥추가확인)
        frames[model] = d

    def metrics(d: pd.DataFrame, y: str) -> dict:
        a, t = d.alert, d[y]
        tp, fp, fn, tn = (a & t).sum(), (a & ~t).sum(), (~a & t).sum(), (~a & ~t).sum()
        return {"alerts": int(a.sum()), "positives": int(t.sum()), "TP": int(tp),
                "precision": tp / (tp + fp) if tp + fp else np.nan, "recall": tp / (tp + fn) if tp + fn else np.nan,
                "false_alarm_rate": fp / (fp + tn) if fp + tn else np.nan,
                "balanced_accuracy": ((tp / (tp + fn)) + (tn / (tn + fp))) / 2 if (tp + fn) and (tn + fp) else np.nan,
                "lift_vs_base_rate": (tp / (tp + fp)) / t.mean() if tp + fp and t.mean() else np.nan}
    rows = []
    for y, role in (("primary", "사전등록 주평가(추가 위축)"), ("signal_persist", "보강: 신호 지속(2분기 뒤 E≥5%)")):
        for model, label in models.items():
            rows.append({"outcome": role, "model": label, **metrics(frames[model], y)})
    table = _save(pd.DataFrame(rows), "purpose_aligned_validation.csv")

    rng = np.random.default_rng(seed)
    quarters = frames["triage_final"].quarter.unique()
    diffs = []
    for _ in range(n_boot):
        pick = rng.choice(quarters, size=len(quarters), replace=True)
        sample = {m: pd.concat([f[f.quarter.eq(q)] for q in pick]) for m, f in frames.items()}
        tri, naive = metrics(sample["triage_final"], "signal_persist"), metrics(sample["current_negative_e_yoy"], "signal_persist")
        diffs.append((tri["precision"] - naive["precision"], tri["false_alarm_rate"] - naive["false_alarm_rate"],
                      tri["recall"] - naive["recall"]))
    diffs = pd.DataFrame(diffs, columns=["precision", "false_alarm_rate", "recall"]).dropna()
    point_t, point_n = metrics(frames["triage_final"], "signal_persist"), metrics(frames["current_negative_e_yoy"], "signal_persist")
    boot = pd.DataFrame([{
        "metric": k, "triage_minus_simple_rule": point_t[k] - point_n[k],
        "ci95_low": diffs[k].quantile(.025), "ci95_high": diffs[k].quantile(.975),
        "share_triage_better": (diffs[k] > 0).mean() if k != "false_alarm_rate" else (diffs[k] < 0).mean(),
        "note": f"판정 분기 단위 묶음 부트스트랩 {n_boot}회(seed {seed}) — 사후 보강 분석",
    } for k in ("precision", "false_alarm_rate", "recall")])
    _save(boot, "purpose_aligned_bootstrap.csv")
    return table, boot


def external_cases() -> pd.DataFrame:
    ext = pd.read_csv(ROOT / "outputs/final_model/04_external_evidence/external_evidence_panel.csv")
    ext["adverse_bsi"] = ext.bsi_industry_business.lt(100) & ext.bsi_industry_business.notna()
    ext["adverse_export"] = ext.trade_export_yoy.lt(0) & ext.trade_export_yoy.notna()
    ext["adverse_labor_flow"] = ext.mfg_flow_net.lt(0) & ext.mfg_flow_net.notna()
    ext["adverse_eis"] = ext.insured_yoy.lt(0) & ext.insured_yoy.notna()
    flags = ["adverse_bsi", "adverse_export", "adverse_labor_flow", "adverse_eis"]
    ext["concurrent_adverse_count"] = ext[flags].sum(axis=1)
    triage_order = ext.stage.map({"우선점검": 0, "추가확인": 1, "관찰": 2}).fillna(3)
    ext = ext.assign(_stage_order=triage_order)
    chosen = ext.sort_values(
        ["concurrent_adverse_count", "_stage_order", "quarter", "industry"],
        ascending=[False, True, False, True],
    ).head(3).copy()
    chosen["role_note"] = "동시기 맥락·해석 보강 전용; Triage 단계 재산정에 사용하지 않음"
    cols = ["industry", "quarter", "stage", "concurrent_adverse_count", "bsi_industry_business",
            "trade_export_yoy", "mfg_flow_net", "insured_yoy", *flags, "role_note"]
    return _save(chosen[cols], "external_contemporaneous_cases.csv")


def wood_source_audit(panel: pd.DataFrame) -> pd.DataFrame:
    focus_quarters = ["2022Q4", "2023Q1", "2023Q2", "2023Q3", "2024Q4", "2025Q1", "2026Q2"]
    focus = panel[(panel.industry == "목재종이") & panel.quarter.isin(focus_quarters)].copy()
    rows = []
    for r in focus.itertuples(index=False):
        if r.quarter == "2025Q1":
            audit_focus = "2024Q4→2025Q1 고용·생산 수준 급증 및 2025년 S1 기저효과 가능성"
        elif r.quarter in {"2022Q4", "2023Q1", "2023Q2", "2023Q3"}:
            audit_focus = "2022Q4 생산 급감 및 2022Q4~2023Q3 생산감소 경로"
        elif r.quarter == "2026Q2":
            audit_focus = "44개 가동업체·428명 규모에서 48명 YoY 감소의 기업 집중 가능성"
        else:
            audit_focus = "급변 직전 기준 수준"
        rows.append({
            "industry": r.industry, "quarter": r.quarter, "employment": r.employment,
            "employment_lag1": r.employment_lag1, "emp_qoq_pct": r.emp_qoq_pct,
            "production": r.production, "production_lag1": r.production_lag1,
            "production_qoq_pct": r.production_qoq_pct, "production_yoy": r.production_yoy,
            "firms_in": r.firms_in, "firms_op": r.firms_op, "firms_op_lag1": r.firms_op_lag1,
            "audit_focus": audit_focus,
            "directly_verified": "정본 값·원천구분·분류단절 플래그",
            "possible_explanation": "집계 개정, 업종분류 또는 사업체 구성 변화 가능성",
            "not_confirmed": (
                "저장소 내 공식 주석만으로 급변 원인, 특정 대형 사업체 편입 여부, "
                "2026Q2 감소가 한두 기업에 집중됐는지 확인 불가"
            ),
            "employment_source": getattr(r, "employment_source", None),
            "employment_note": getattr(r, "employment_note", None),
            "classification_break": getattr(r, "classification_break", None),
        })
    return _save(pd.DataFrame(rows), "wood_paper_source_audit.csv")


def stage_grid(panel: pd.DataFrame) -> Path:
    """정본 단계표에서 재현 가능한 표준 통계 그림을 그린다."""
    from PIL import Image, ImageDraw, ImageFont

    FIGURES.mkdir(parents=True, exist_ok=True)
    grid = panel.pivot(index="industry", columns="quarter", values="stage")
    order = ["관찰", "추가확인", "우선점검", "자료확인"]
    colors = ["#2E8B76", "#E3A72F", "#C95862", "#AAB4BC"]
    regular = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 17)
    small = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 13)
    left, top, cw, ch = 112, 76, 66, 42
    image = Image.new("RGB", (left + cw * len(grid.columns) + 2,
                              top + ch * len(grid.index) + 52), "white")
    draw = ImageDraw.Draw(image)
    draw.text((8, 5), "업종×분기 선제점검 단계", fill="#111111", font=regular)
    for i, label in enumerate(order):
        x = 8 + i * 130
        draw.rectangle((x, 33, x + 16, 49), fill=colors[i])
        draw.text((x + 22, 31), label, fill="#222222", font=small)
    for j, quarter in enumerate(grid.columns):
        draw.text((left + j * cw + 5, 56), quarter, fill="#222222", font=small)
    for i, industry in enumerate(grid.index):
        y = top + i * ch
        draw.text((8, y + 11), str(industry), fill="#222222", font=regular)
        for j, quarter in enumerate(grid.columns):
            x = left + j * cw
            stage = grid.loc[industry, quarter]
            color = colors[order.index(stage)] if stage in order else "#FFFFFF"
            draw.rectangle((x, y, x + cw, y + ch), fill=color, outline="#FFFFFF", width=2)
    draw.text((8, top + ch * len(grid.index) + 12),
              "자료: KICOX 업종별 분기자료 · src/review/professor_feedback.py", fill="#444444", font=small)
    path = FIGURES / "F10_Triage_단계격자.png"
    image.save(path, dpi=(180, 180))
    return path


def write_summary(panel: pd.DataFrame, validation: pd.DataFrame) -> None:
    wood = pd.read_csv(TABLES / "wood_paper_boundary_margin.csv")
    machine = pd.read_csv(TABLES / "machine_yoy_qoq_interpretation.csv").iloc[0]
    ba = validation.set_index("model").balanced_accuracy
    text = f"""# 교수 검토 피드백 반영 결과

- Triage는 주모형이며 ELECTRE/SMAA는 보조 비교·재검토 수단이다. 단계 산식은 변경하지 않았다.
- 목재종이 2026Q2 E는 {wood.loc[wood.quarter.eq('2026Q2'), 'E'].iloc[0]:.3f}%이고, 전년동기 고용 {wood.loc[wood.quarter.eq('2026Q2'), 'employment_lag4'].iloc[0]:.0f}명 기준 48명 감소다. 47명 감소라면 {wood.loc[wood.quarter.eq('2026Q2'), 'E_if_one_fewer_loss'].iloc[0]:.3f}%여서 상위경계를 이탈한다.
- 기계 2026Q2는 전년동기 대비 {machine.yoy_change:,.0f}명, 최근 전분기 대비 {machine.qoq_change:,.0f}명 변화이며 제조업 순감소 기여율은 {machine.contribution_pct:.2f}%다.
- 2분기 주평가 균형정확도는 Triage {ba['triage_final']:.3f}, ELECTRE {ba['electre_fixed']:.3f}이다. 이는 기술통계이며 일반적 우월성이나 정책효과를 의미하지 않는다.
- 자료 급변 QA, 경계여유, 후속성과, 외부 동시기 사례는 `{TABLES.relative_to(ROOT)}`에 저장했다.
"""
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "README.md").write_text(text, encoding="utf-8")


def main() -> None:
    panel = build_panel()
    qa_cases(panel)
    boundary_cases(panel)
    machine_interpretation(panel)
    level_shift_decomposition(panel)
    base_peak_check(panel)
    ratio_boundary_headcount(panel)
    _, validation = validation_followup()
    mean_reversion_diagnosis()
    purpose_aligned_validation()
    external_cases()
    press_concurrent_check(panel)
    if any(CCI_DIR.glob("창원국가산단_업종별현황_*.csv")):
        cci_concurrent_check(panel)
    else:  # 원자료(data/raw)는 저장소 제외 — 없으면 저장된 대조표를 그대로 둔다
        print("창원상의 전사본(data/raw/changwon_chamber) 없음: cci_concurrent_* 저장본 유지")
    wood_source_audit(panel)
    stage_grid(panel)
    write_summary(panel, validation)
    metadata = {
        "rule_version": tr.RULE_VERSION,
        "stage_unchanged": True,
        "qa_changes_stage": False,
        "generated_tables": sorted(p.name for p in TABLES.glob("*.csv")),
    }
    (OUT / "run_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
