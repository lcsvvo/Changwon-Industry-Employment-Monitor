# -*- coding: utf-8 -*-
"""해석층·신뢰도층 산출 (Triage 판정은 건드리지 않는다).

이 스크립트는 `src/run_triage_rule.py` 의 산출물을 읽기만 하고 다시 쓰지 않는다.
stage / stage_reason / E / R / A / P / 규모 게이트는 재계산하지 않는다.

산출
    data/processed/<source>/*.csv     출처별 보조패널 (Triage 에 join 하지 않는다)
    outputs/final_model/04_external_evidence/*

실행:  python src/build_context_layer.py
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from evidence.modules import cross_source as cs               # noqa: E402
from evidence.modules import external_panels as xp            # noqa: E402
from evidence.modules import external_signals as xs           # noqa: E402
from evidence.modules import firm_activity as fa              # noqa: E402
from evidence.modules import monthly_panel as mp              # noqa: E402
from evidence.modules import ppi_adjusted as pa               # noqa: E402
from evidence.modules import questions as qs                  # noqa: E402
from evidence.modules import quality as ql                    # noqa: E402
from evidence.modules import signals as sg                    # noqa: E402
from evidence.modules.config import WINDOW                    # noqa: E402
from triage import triage_rule as tr                          # noqa: E402

TRIAGE_PANEL = ROOT / "outputs/final_model/02_triage/tables/triage_panel.csv"
MASTER = ROOT / "data/processed/kicox/changwon_industry_master.csv"
PROC = ROOT / "data/processed"
FINAL_PROC = PROC / "final_model"
OUT = ROOT / "outputs/final_model/04_external_evidence"
HANDOFF_OUT = ROOT / "outputs/final_model/05_handoff/tables"
VALIDATION_OUT = ROOT / "logs/validation/context_layer"
QA_OUT = ROOT / "outputs/final_model/06_report_assets/qa"

# Triage 가 결정하고 해석층이 절대 바꾸지 않는 열
FROZEN = ["stage", "stage_reason", "E", "R", "A", "P", "scale_ok", "persist",
          "E_entry", "E_up", "R_entry", "R_up", "A_entry", "A_up", "P_support"]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(df: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def build() -> dict:
    triage = pd.read_csv(TRIAGE_PANEL)
    triage.columns = [c.lstrip("﻿") for c in triage.columns]
    if len(triage) != 180:
        raise ValueError(f"Triage 패널이 180행이 아니다: {len(triage)}")
    frozen_before = triage[["industry", "quarter"] + FROZEN].copy()

    master = pd.read_csv(MASTER)

    # ---------------------------------------------------------------- 3-1 교차확인
    cross = cs.build_crosscheck_panel(ROOT, triage)

    # ---------------------------------------------------------------- 3-2 월별 지속성
    monthly = mp.build_monthly_panel(ROOT)
    monthly_yoy = mp.add_monthly_yoy(monthly)
    persistence = mp.quarterly_persistence(monthly_yoy)

    # ---------------------------------------------------------------- 3-3 PPI 조정 생산
    ppi_cand = pa.build_ppi_adjusted_panel(ROOT, triage)
    ppi_sum = pa.collapse_to_industry_quarter(ppi_cand)

    # ---------------------------------------------------------------- 3-4 업체·가동률·소규모
    firm = fa.add_small_industry_track(fa.build_firm_activity_panel(master), tr.SCALE_MIN)
    firm = firm[firm["quarter"].between(*WINDOW)]

    # ---------------------------------------------------------------- 결합 (판정 열은 그대로)
    keep_triage = ["industry", "quarter", "stage", "stage_reason", "state", "run_length",
                   "e_yoy", "p_yoy", "emp_delta", "employment", "production",
                   "employment_share_pct", "E", "R", "A", "P", "scale_ok", "persist",
                   "data_quality_core_missing", "data_quality_production_missing",
                   "check_question", "first_owner"]
    d = triage[keep_triage].copy()
    d = d.merge(firm[["industry", "quarter", "firms_op", "firms_in", "firms_op_lag4",
                      "firms_op_change_count", "firms_op_yoy", "firms_in_yoy",
                      "op_rate", "op_rate_yoy", "op_rate_yoy_pp", "op_rate_basis",
                      "op_rate_definition_break", "op_rate_definition_break_note",
                      "employment_level", "firms_op_level", "small_industry_flag",
                      "small_base_warning", "track", "firms_op_change_display",
                      "small_track_note"]
                 + [c for c in firm.columns if c.endswith("_is_revised")]],
                on=["industry", "quarter"], how="left", validate="one_to_one")
    d = d.merge(ppi_sum, on=["industry", "quarter"], how="left", validate="one_to_one")
    d = d.merge(cross[["industry", "quarter", "eis_manufacturing_yoy", "mfg_emp_yoy",
                       "aggregate_direction", "aggregate_yoy_gap_pp", "source_category",
                       "insured_level", "insured_yoy", "industry_direction",
                       "industry_yoy_gap_pp", "mapping_confidence",
                       "industry_mapping_uncertain", "cross_source_available",
                       "employment_cross_source_agreement",
                       "employment_cross_source_disagreement",
                       "cross_source_population_note"]],
                on=["industry", "quarter"], how="left", validate="one_to_one")
    pcols = ["industry", "quarter"] + [c for c in persistence.columns
                                       if c not in ("industry", "quarter")]
    d = d.merge(persistence[pcols], on=["industry", "quarter"], how="left",
                validate="one_to_one")

    # ---------------------------------------------------------------- 외부 수집자료
    # 역할이 서로 다른 세 자료. 판정 입력이 아니라 해석·맥락으로만 붙인다.
    flow_panel = xp.build_employment_flow_panel(ROOT)
    trade_panel = xp.build_trade_context_panel(ROOT)
    bsi_panel = xp.build_business_sentiment_panel(ROOT)
    power_panel = xp.build_electricity_activity_panel(ROOT)
    trade_coverage = xp.trade_industry_coverage(ROOT)
    d = xs.add_trade_signals(d, trade_panel, trade_coverage)
    d = xs.add_flow_signals(d, flow_panel)
    d = xs.add_power_signals(d, power_panel)
    d = xs.add_bsi_signals(d, bsi_panel)
    # 수출은 유지·확대인데 고용은 감소하는 조합(원인 확정이 아니라 확인 대상)
    d["trade_export_up_employment_down"] = (
        (d["trade_export_yoy"] > 0) & (d["e_yoy"] < 0)
    ).astype("boolean").where(d["trade_export_yoy"].notna() & d["e_yoy"].notna())

    # ---------------------------------------------------------------- 해석층·신뢰도층
    sig = sg.compute_signals(d)
    d = pd.concat([d, sig], axis=1)
    quality = ql.build_quality_flags(d)
    # 신뢰도층은 원본 열(결측 포함)을 결측 없는 플래그로 다시 낸다. 중복 열은
    # 플래그 쪽을 남겨 카드·요약이 한 가지 정의만 쓰게 한다.
    qcols = [c for c in quality.columns if c not in ("industry", "quarter")]
    d = pd.concat([d.drop(columns=[c for c in qcols if c in d.columns]),
                   quality[qcols]], axis=1)
    d = pd.concat([d, qs.build_questions(d)], axis=1)
    d = d.sort_values(["quarter", "industry"]).reset_index(drop=True)

    sens_detail, sens_summary = sg.sensitivity(d)

    # ---------------------------------------------------------------- 불변성 확인
    frozen_after = d[["industry", "quarter"] + [c for c in FROZEN if c in d.columns]]
    merged = frozen_before.merge(frozen_after, on=["industry", "quarter"],
                                 suffixes=("_before", "_after"))
    changed = [c for c in FROZEN if c in d.columns
               and not merged[c + "_before"].equals(merged[c + "_after"])]
    if changed:
        raise AssertionError(f"해석층이 Triage 판정 열을 바꿨다: {changed}")

    # ---------------------------------------------------------------- 저장
    for path in [FINAL_PROC, PROC / "eis", PROC / "ppi", PROC / "employment_insurance",
                 PROC / "customs", PROC / "kepco", PROC / "ecos"]:
        path.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    VALIDATION_OUT.mkdir(parents=True, exist_ok=True)
    HANDOFF_OUT.mkdir(parents=True, exist_ok=True)
    save(cross, PROC / "eis/employment_crosscheck_panel.csv")
    save(monthly_yoy, FINAL_PROC / "monthly_persistence_panel.csv")
    save(ppi_cand, PROC / "ppi/ppi_adjusted_production_panel.csv")
    save(d, FINAL_PROC / "industry_context_signals.csv")
    save(quality, FINAL_PROC / "data_quality_panel.csv")
    if not flow_panel.empty:
        save(flow_panel, PROC / "employment_insurance/employment_flow_panel.csv")
    if not trade_panel.empty:
        save(trade_panel, PROC / "customs/trade_context_panel.csv")
    if not trade_coverage.empty:
        save(trade_coverage, PROC / "customs/trade_coverage_by_industry.csv")
    if not power_panel.empty:
        save(power_panel, PROC / "kepco/electricity_activity_panel.csv")
    if not bsi_panel.empty:
        save(bsi_panel, PROC / "ecos/business_sentiment_panel.csv")

    latest = d[d["quarter"] == d["quarter"].max()].copy()
    save(_context_signal_summary(d), OUT / "external_signal_summary.csv")
    save(cs.crosscheck_summary(cross), OUT / "cross_source_summary.csv")
    save(pa.disagreement_rows(ppi_sum), OUT / "ppi/nominal_real_disagreement.csv")
    save(sens_summary, VALIDATION_OUT / "signal_threshold_sensitivity.csv")
    save(sens_detail, VALIDATION_OUT / "signal_threshold_sensitivity_changed_rows.csv")
    save(_small_track(d), OUT / "kicox/small_industry_track.csv")
    save(_card_preview(d, latest), HANDOFF_OUT / "external_evidence_card_preview.csv")

    return dict(panel=d, latest=latest, cross=cross, ppi=ppi_sum,
                persistence=persistence, sens_summary=sens_summary,
                sens_detail=sens_detail, monthly_yoy=monthly_yoy)


def _context_signal_summary(d: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for col, label in sg.SIGNAL_LABELS.items():
        s = d[col]
        rows.append(dict(signal=col, signal_label=label,
                         n_true=int(s.eq(True).sum()), n_false=int(s.eq(False).sum()),
                         n_not_determinable=int(s.isna().sum()),
                         industries_with_signal=int(d.loc[s.eq(True), "industry"].nunique()),
                         quarters_with_signal=int(d.loc[s.eq(True), "quarter"].nunique())))
    return pd.DataFrame(rows)


def _small_track(d: pd.DataFrame) -> pd.DataFrame:
    cols = ["industry", "quarter", "track", "stage", "employment_level", "firms_op_level",
            "firms_op_change_count", "firms_op_yoy", "firms_op_change_display",
            "small_industry_flag", "small_base_warning", "signal_profile",
            "representative_signal", "small_track_note"]
    out = d.loc[d["small_base_warning"].fillna(False), cols]
    return out.sort_values(["quarter", "industry"]).reset_index(drop=True)


def _card_preview(panel: pd.DataFrame, latest: pd.DataFrame) -> pd.DataFrame:
    """진단카드에 덧붙일 블록만 모은 preview (판정 블록은 Triage 값 그대로)."""
    c = latest.copy()
    c["card_판정"] = c["stage"] + " — " + c["stage_reason"].astype(str)
    c["card_현재상태"] = (
        "Q1 " + c["state"].astype(str)
        + " / Q3 상태 지속 " + c["run_length"].fillna(0).astype(int).astype(str) + "분기"
        + " / 반복 고용진입신호 " + c["persist"].astype(str))
    c["card_확인신호프로필"] = c["signal_profile"]
    c["card_대표확인신호"] = c["representative_signal"]
    c["card_교차확인"] = (
        "고용보험 방향: " + c["industry_direction"].fillna("비교자료 없음")
        + " / 월별 지속성: " + np.where(
            c["employment_months_observed"].notna(),
            c["employment_negative_months"].fillna(0).astype("Int64").astype(str) + "/"
            + c["employment_months_observed"].fillna(0).astype("Int64").astype(str) + "개월",
            "월별 원자료 미제공")
        + " / 명목·PPI조정 생산 방향: " + np.where(
            c["sign_agreement"].eq(True).fillna(False), "일치",
            np.where(c["sign_agreement"].eq(False).fillna(False), "불일치", "판단 보류")))
    c["card_고용flow"] = np.where(
        c["mfg_flow_data_available"].fillna(False),
        "창원시 제조업(" + c["mfg_flow_period"].astype(str) + ", 반기): 종사자 "
        + c["mfg_flow_workers_yoy"].round(1).astype(str) + "% / 입직 "
        + c["mfg_flow_acquisition_yoy"].round(1).astype(str) + "% / 이직 "
        + c["mfg_flow_loss_yoy"].round(1).astype(str) + "% [업종 공통 배경]",
        "고용 flow 자료 없음")
    inc = c.get("n_hs6_incomplete", pd.Series(0, index=c.index)).fillna(0).astype(int)
    c["card_수출"] = np.where(
        c["trade_data_available"].fillna(False),
        "HS6 " + c["trade_n_items"].fillna(0).astype(int).astype(str) + "개 합계 수출 YoY "
        + c["trade_export_yoy"].round(1).astype(str) + "% (매핑 "
        + c["trade_mapping_grade"].astype(str) + ", 업종 총액 아님)"
        + np.where(inc > 0,
                   " [주의: " + inc.astype(str) + "개 품목은 호출한도로 미확보, 집계 제외]",
                   ""),
        "수출 자료 없음 — " + c["trade_unavailable_reason"].fillna("사유 미기록").astype(str))
    c["card_경기심리"] = np.where(
        c["bsi_data_available"].fillna(False),
        "경남 제조업 업황BSI " + c["bsi_region_business"].round(1).astype(str)
        + np.where(c["bsi_industry_business"].notna(),
                   " / 전국 동업종 업황BSI " + c["bsi_industry_business"].round(1).astype(str),
                   " / 전국 동업종 BSI 없음") + " [거시 배경]",
        "BSI 자료 없음")
    c["card_전력"] = np.where(
        c["power_data_available"].fillna(False),
        "창원시 제조업 전력사용량 YoY " + c["power_usage_yoy"].round(1).astype(str)
        + "% / 고객호수 " + c["power_customers"].fillna(0).astype(int).astype(str)
        + "호 [업종 공통 배경 · 시 전체 제조업]",
        "전력사용량 자료 없음")
    c["card_자료품질"] = c["quality_flag_list"]
    c["card_확인질문"] = c["check_questions_context"]
    c["card_인계검토"] = c["handoff_review_functions"] + " — " + c["handoff_note"]
    cols = ["industry", "quarter", "card_판정", "card_현재상태", "card_확인신호프로필",
            "card_대표확인신호", "representative_signal_note", "card_교차확인",
            "card_고용flow", "card_수출", "card_경기심리", "card_전력",
            "card_자료품질", "card_확인질문", "card_인계검토",
            "nominal_production_yoy", "ppi_adjusted_production_yoy",
            "ppi_mapping_grade", "ppi_adjusted_production_decline_band",
            "firms_op_change_display", "track"]
    order = {"우선점검": 0, "추가확인": 1, "관찰": 2, "자료확인": 3}
    c["_o"] = c["stage"].map(order).fillna(9)
    return c.sort_values(["_o", "industry"])[cols].reset_index(drop=True)


def main() -> int:
    res = build()
    d = res["panel"]
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                         capture_output=True, text=True)
    meta = dict(
        layer="context-interpretation/1.0.0",
        run_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        window=list(WINDOW), rows=len(d),
        triage_rule_version=tr.RULE_VERSION,
        triage_untouched=True,
        frozen_columns=FROZEN,
        git_head=git.stdout.strip(),
        inputs={str(p.relative_to(ROOT)): sha(p) for p in
                [TRIAGE_PANEL, MASTER,
                 ROOT / "data/processed/ppi/ppi_industry_panel.csv",
                 ROOT / "data/raw/eis/eis_changwon_insured_2022M03_2026M06.csv",
                 ROOT / "data/raw/changwon_chamber/창원시_업종별_고용보험피보험자_동향.csv"]},
        code_sha256={str(p.relative_to(ROOT)): sha(p) for p in
                     sorted((ROOT / "src/evidence/modules").glob("*.py")) + [Path(__file__)]},
        thresholds_are_own=True,
        note=("해석층은 Triage stage 를 바꾸지 않는다. 새 자료는 판정 입력이 아니라 "
              "해석·교차확인·자료품질 표시에 쓰인다."),
        python=sys.version, pandas=pd.__version__, numpy=np.__version__,
    )
    QA_OUT.mkdir(parents=True, exist_ok=True)
    (QA_OUT / "external_evidence_run_metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"rows={len(d)}  (Triage stage 불변 확인됨)")
    print(_context_signal_summary(d).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
