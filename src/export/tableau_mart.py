# -*- coding: utf-8 -*-
"""
창원국가산단 제조업종 대시보드 — Tableau 데이터 마트 생성 스크립트

tableau_build_guide.md 가 요구하는 CSV 4개를 data/ 폴더에서 만들어 낸다.

    outputs/final_model/07_tableau/
      ├─ dm_total_quarter.csv     (34행, 10개 제조업종 합계)
      ├─ dm_industry_quarter.csv  (340행, 업종 10 × 분기 34)
      ├─ dm_reference.csv         (외부 참고, long format)
      ├─ dm_meta.csv              (1행)
      └─ qa_report.json           (가이드 10-1 값 검증 결과)

실행 (저장소 루트에서):
    pip install pandas numpy
    python src/export/tableau_mart.py
    python src/export/tableau_mart.py --data-dir ./data --out-dir ./outputs/final_model/07_tableau

입력 파일
    data/processed/kicox/changwon_state_reference_panel.csv  (2018Q1~, 340행)  → 값·YoY·표시용 필드
    data/processed/kicox/changwon_state_panel.csv            (2022Q1~, 180행)  → 국면·지속기간(점검 단계)
    data/processed/kicox/changwon_industry_master.csv        (해시 기록용)
    data/processed/kicox/changwon_total_master.csv           (해시 기록용, 합계에는 쓰지 않음)
    data/processed/ppi/ppi_industry_panel.csv                → PPI 보정 생산 YoY
    data/processed/eis/eis_validation_panel.csv              → EIS 제조업 YoY
    data/raw/cci_report/*_YYYYQn.csv                         → 업종별 수출 YoY(창원상의 전사본)
    data/external/<indicator_id>.csv  (선택)                 → BSI·입직자·전력 등 zip에 없는 지표

주의
    * 합계는 업종 10개 원값의 합으로만 만든다(changwon_total_master = 산단 전체 총계와 다름).
    * 점검 단계(stage) 판정 규칙 원문은 zip에 없어서 STAGE_RULE 로 재구성했다.
      가이드 2026Q2 검증값(우선점검 = 기계·목재종이, 나머지 관찰, 추가확인 없음)과 일치하도록
      맞췄지만, 팀에서 확정한 규칙이 있으면 stage_from_state() 한 곳만 고치면 된다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# ─────────────────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────────────────
SNAPSHOT_VERSION = "v3"
RULE_VERSION = "stage_rule_reconstructed_v1"
INDEX_BASE_YEAR = "2022"
INDEX_BASE_LABEL = "2022년 평균 = 100"
SCOPE_LABEL = "10개 제조업종 합계"
NOTE_SCOPE = "10개 제조업종 합계는 산단 전체 총계와 다름"
MAIN_START = "2022Q1"
INDUSTRIES = ["기계", "기타", "목재종이", "비금속", "석유화학",
              "섬유의복", "운송장비", "음식료", "전기전자", "철강"]
CONTRIB_MIN_TOTAL_YOY = 0.5   # 합계 고용 YoY 절댓값이 이보다 작으면 기여율 NULL(표시 조건 미충족)

STAGE_ORDER = {"우선점검": 1, "추가확인": 2, "관찰": 3}


def stage_from_state(state, run_length):
    """국면(S1~S4, N, INVALID)과 지속 분기 수 → 점검 단계.

    S1 생산↑ 고용↑ / S2 생산↑ 고용↓ / S3 생산↓ 고용↑ / S4 생산↓ 고용↓ / N 보합
    재구성 규칙:
      우선점검 : S4(동반 감소)가 2분기 이상 지속
      추가확인 : S4가 이번 분기 처음 나타남, 또는 S3(생산 감소)가 2분기 이상 지속
      관찰     : 그 외 유효 국면(S1, S2, S3 1분기, N)
      INVALID  : NULL(판정 불가)
    """
    if pd.isna(state) or state == "INVALID":
        return None
    rl = 0 if pd.isna(run_length) else int(run_length)
    if state == "S4" and rl >= 2:
        return "우선점검"
    if (state == "S4" and rl == 1) or (state == "S3" and rl >= 2):
        return "추가확인"
    return "관찰"


# ─────────────────────────────────────────────────────────────
# 공통 유틸
# ─────────────────────────────────────────────────────────────
def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig")


def sha256(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def q_start(q: str) -> pd.Timestamp:
    y, n = int(q[:4]), int(q[-1])
    return pd.Timestamp(year=y, month=3 * (n - 1) + 1, day=1)


def q_label(q: str) -> str:
    return f"{q[:4]}년 {q[-1]}분기"


def lag4(q: str) -> str:
    return f"{int(q[:4]) - 1}Q{q[-1]}"


def to_bool(s: pd.Series) -> pd.Series:
    """True/False/NaN → 'true'/'false'/'' (Tableau가 불리언으로 인식하기 쉬운 형태)."""
    def f(v):
        if pd.isna(v):
            return ""
        if isinstance(v, str):
            v = v.strip().lower() in ("true", "1", "t", "y")
        return "true" if bool(v) else "false"
    return s.map(f)


def sign_dir(v):
    if pd.isna(v):
        return None
    return "증가" if v > 0 else ("감소" if v < 0 else "보합")


ARROW = {"증가": "↑", "감소": "↓", "보합": "→"}


def pct_change(cur, prev):
    if pd.isna(cur) or pd.isna(prev) or prev == 0:
        return np.nan
    return (cur / prev - 1) * 100


# ─────────────────────────────────────────────────────────────
# 1. dm_industry_quarter
# ─────────────────────────────────────────────────────────────
def build_industry(ref: pd.DataFrame, st: pd.DataFrame, latest: str) -> pd.DataFrame:
    d = ref.copy()
    d = d[d["industry"].isin(INDUSTRIES)].sort_values(["industry", "quarter"]).reset_index(drop=True)

    out = pd.DataFrame({
        "industry": d["industry"],
        "quarter": d["quarter"],
    })
    out["quarter_date"] = out["quarter"].map(q_start)
    out["quarter_label"] = out["quarter"].map(q_label)
    out["is_main_period"] = out["quarter"] >= MAIN_START
    out["employment"] = d["employment"]
    out["production"] = d["production"]
    out["production_masked"] = d["production_masked"].fillna(0).astype(int)
    out["classification_break"] = d["classification_break"].fillna(0).astype(int)
    out["review_required"] = d["review_required"].astype(bool)
    out["employment_yoy"] = d["employment_yoy"]
    out["production_yoy"] = d["production_yoy"]

    emp_valid = d["employment_yoy_valid"].astype(bool)
    prod_valid = d["production_yoy_valid"].astype(bool)

    out["employment_lag4"] = d["employment_lag4"]
    out["emp_delta"] = np.where(emp_valid, d["employment"] - d["employment_lag4"], np.nan)

    # 고용 비중: 같은 분기 10개 업종 고용 합 대비
    tot_emp = out.groupby("quarter")["employment"].transform("sum")
    out["employment_share_pct"] = out["employment"] / tot_emp * 100

    # 기여율: 업종 증감 / 합계 증감 × 100
    tot_delta = out.groupby("quarter")["emp_delta"].transform(lambda s: s.sum(min_count=len(INDUSTRIES)))
    tot_lag = out.groupby("quarter")["employment_lag4"].transform("sum")
    tot_yoy = tot_delta / tot_lag * 100
    ok = tot_delta.notna() & (tot_delta != 0) & (tot_yoy.abs() >= CONTRIB_MIN_TOTAL_YOY)
    out["contribution_pct"] = np.where(ok, out["emp_delta"] / tot_delta * 100, np.nan)

    # ── 점검 단계 / 국면 (본분석 패널 기준, 2022Q1~) ─────────────
    s = st[["quarter", "industry", "state", "run_length", "state_start_quarter"]]
    out = out.merge(s, on=["quarter", "industry"], how="left")
    out["run_length"] = out["run_length"]
    out["stage"] = [stage_from_state(a, b) for a, b in zip(out["state"], out["run_length"])]
    out["stage_order"] = out["stage"].map(STAGE_ORDER)
    out["stage_is_reconstructed"] = out["quarter"] != latest

    # ── 가동률: 공식값 우선, 없으면 근사값 + 정의 변경 표시 ─────
    out["op_rate"] = d["op_rate_official"].where(d["op_rate_official"].notna(), d["op_rate_approx"]).values
    out["op_rate_definition_break"] = (d["op_rate_official"].isna() & d["op_rate_approx"].notna()).values
    out["firms_op"] = d["firms_op"].values

    # ── 화면 표시용 필드 ───────────────────────────────────────
    reasons = [[] for _ in range(len(out))]
    emp_disp = out["employment"].astype(float).copy()
    prod_disp = out["production"].astype(float).copy()

    for ind, g in out.groupby("industry"):
        # 분류 변경 전 구간의 0값(섬유의복 등): 첫 번째 0이 아닌 값 이전은 표시하지 않음
        for col, disp in (("employment", emp_disp), ("production", prod_disp)):
            nz = g.index[g[col].fillna(0) != 0]
            first = nz.min() if len(nz) else None
            pre = g.index if first is None else g.index[g.index < first]
            pre = [i for i in pre if out.at[i, col] == 0]
            for i in pre:
                disp.at[i] = np.nan
                txt = "분류 변경 전 구간(원자료 값 0)"
                if txt not in reasons[i]:
                    reasons[i].append(txt)
    for i in out.index[(out["production_masked"] == 1) | out["production"].isna()]:
        prod_disp.at[i] = np.nan
        reasons[i].append("생산 비공개")

    out["employment_display"] = emp_disp
    out["production_display"] = prod_disp
    out["display_limit_reason"] = [" · ".join(r) if r else None for r in reasons]
    out["employment_yoy_display"] = np.where(emp_valid & emp_disp.notna(), out["employment_yoy"], np.nan)
    out["production_yoy_display"] = np.where(prod_valid & prod_disp.notna(), out["production_yoy"], np.nan)

    # ── 지수 (2022년 평균 = 100) ───────────────────────────────
    base = out[out["quarter"].str.startswith(INDEX_BASE_YEAR)].groupby("industry")[["employment", "production"]].mean()
    out["employment_index"] = out["employment"] / out["industry"].map(base["employment"]) * 100
    out["production_index"] = out["production"] / out["industry"].map(base["production"]) * 100
    out["employment_index_display"] = out["employment_display"] / out["industry"].map(base["employment"]) * 100
    out["production_index_display"] = out["production_display"] / out["industry"].map(base["production"]) * 100

    # ── 방향·흐름 ──────────────────────────────────────────────
    out["prod_dir"] = out["production_yoy_display"].map(sign_dir)
    out["emp_dir"] = out["employment_yoy_display"].map(sign_dir)
    out["prod_arrow"] = out["prod_dir"].map(ARROW)
    out["emp_arrow"] = out["emp_dir"].map(ARROW)
    has_flow = out["prod_arrow"].notna() & out["emp_arrow"].notna() & out["is_main_period"]
    out["flow_label"] = np.where(has_flow, "생산" + out["prod_arrow"].fillna("") + " 고용" + out["emp_arrow"].fillna(""), None)
    out["run_start_quarter"] = out["state_start_quarter"]
    out["run_start_date"] = out["run_start_quarter"].map(lambda q: q_start(q) if isinstance(q, str) else pd.NaT)
    out["index_base_label"] = INDEX_BASE_LABEL

    cols = [
        "industry", "quarter", "quarter_date", "quarter_label", "is_main_period",
        "employment", "production", "production_masked", "classification_break", "review_required",
        "employment_yoy", "production_yoy", "emp_delta", "employment_lag4", "employment_share_pct",
        "contribution_pct", "run_length", "stage", "state", "op_rate", "op_rate_definition_break",
        "firms_op", "employment_display", "production_display", "display_limit_reason",
        "employment_yoy_display", "production_yoy_display", "employment_index", "production_index",
        "employment_index_display", "production_index_display", "prod_dir", "emp_dir",
        "prod_arrow", "emp_arrow", "flow_label", "run_start_quarter", "run_start_date",
        "stage_order", "stage_is_reconstructed", "index_base_label",
    ]
    return out[cols].sort_values(["industry", "quarter"]).reset_index(drop=True)


# ─────────────────────────────────────────────────────────────
# 2. dm_total_quarter  (반드시 업종 10개 원값 합으로만 계산)
# ─────────────────────────────────────────────────────────────
def build_total(ind: pd.DataFrame) -> pd.DataFrame:
    n = len(INDUSTRIES)
    g = ind.groupby("quarter")
    t = pd.DataFrame({
        "mfg_employment": g["employment"].sum(min_count=n),
        "mfg_production": g["production"].apply(lambda s: s.sum() if s.notna().sum() == n else np.nan),
    }).reset_index().sort_values("quarter").reset_index(drop=True)

    emp = dict(zip(t["quarter"], t["mfg_employment"]))
    prod = dict(zip(t["quarter"], t["mfg_production"]))
    t["mfg_employment_yoy"] = [pct_change(emp[q], emp.get(lag4(q))) for q in t["quarter"]]
    t["mfg_emp_delta"] = [emp[q] - emp[lag4(q)] if lag4(q) in emp else np.nan for q in t["quarter"]]
    t["mfg_production_yoy"] = [pct_change(prod[q], prod.get(lag4(q))) for q in t["quarter"]]

    def note(q):
        if lag4(q) not in prod:
            return "전년 비교 불가"
        if pd.isna(prod[q]):
            return "생산 비공개로 계산 불가"
        if pd.isna(prod[lag4(q)]):
            return "전년 같은 분기 생산 비공개로 계산 불가"
        return None
    t["mfg_production_yoy_note"] = [note(q) if pd.isna(v) else None for q, v in zip(t["quarter"], t["mfg_production_yoy"])]

    base = t[t["quarter"].str.startswith(INDEX_BASE_YEAR)]
    t["mfg_employment_index"] = t["mfg_employment"] / base["mfg_employment"].mean() * 100
    t["mfg_production_index"] = t["mfg_production"] / base["mfg_production"].mean() * 100
    t["quarter_date"] = t["quarter"].map(q_start)
    t["quarter_label"] = t["quarter"].map(q_label)
    t["scope_label"] = SCOPE_LABEL
    t["index_base_label"] = INDEX_BASE_LABEL
    return t[[
        "quarter", "quarter_date", "quarter_label", "scope_label", "mfg_employment",
        "mfg_employment_yoy", "mfg_emp_delta", "mfg_production", "mfg_production_yoy",
        "mfg_production_yoy_note", "mfg_employment_index", "mfg_production_index", "index_base_label",
    ]]


# ─────────────────────────────────────────────────────────────
# 3. dm_reference  (외부 참고, long format)
# ─────────────────────────────────────────────────────────────
REF_SPECS = {
    # indicator_id: (표시명, scope, role_display, unit, geography, role_source)
    "ppi_adjusted_production_yoy": ("PPI 보정 생산 YoY", "업종별", "EXTERNAL EVIDENCE", "%",
                                    "창원국가산단 명목 생산 ÷ 전국 PPI", "KICOX 생산 + KOSIS PPI"),
    "bsi_industry_business": ("전국 업종 BSI(업황)", "업종별", "CONTEXT ONLY", "pt", "전국", "한국은행 BSI"),
    "trade_export_yoy": ("수출 YoY", "업종별", "CONTEXT ONLY", "%", "창원국가산단", "창원상공회의소 경제동향(전사본)"),
    "bsi_region_business": ("경남 제조업 BSI(업황)", "지역 공통", "CONTEXT ONLY", "pt", "경상남도", "한국은행 BSI"),
    "eis_manufacturing_yoy": ("EIS 제조업 YoY", "지역 공통", "EXTERNAL EVIDENCE", "%",
                              "창원시 5개 구(고용보험 피보험자)", "고용노동부 EIS"),
    "mfg_flow_workers_yoy": ("제조업 입직자 YoY", "지역 공통", "CONTEXT ONLY", "%", "경상남도", "고용노동부"),
    "power_usage_yoy": ("전력사용량 YoY", "지역 공통", "CONTEXT ONLY", "%", "창원시", "한국전력"),
}
CCI_NAME_MAP = {"전기·전자": "전기전자", "석유·화학": "석유화학"}


def _ref_rows(ind_id, df, quality_note):
    lab, scope, role, unit, geo, src = REF_SPECS[ind_id]
    df = df.dropna(subset=["value"]).copy()
    if scope == "지역 공통":
        df["industry"] = None
    df["indicator_id"] = ind_id
    df["indicator_label"] = lab
    df["unit"] = unit
    df["scope"] = scope
    df["geography"] = geo
    df["role_source"] = src
    df["role_display"] = role
    df["quality_note"] = quality_note
    return df


def build_reference(data_dir: Path, ind: pd.DataFrame, log: dict) -> pd.DataFrame:
    parts = []

    # (1) PPI 보정 생산 YoY  = (1+명목 생산 YoY)/(1+PPI YoY) - 1
    p = data_dir / "processed/ppi/ppi_industry_panel.csv"
    if p.exists():
        ppi = read_csv(p)
        ppi = ppi.groupby(["quarter", "kicox_industry"], as_index=False)["ppi_index_yoy_pct"].mean()
        ppi = ppi.rename(columns={"kicox_industry": "industry"})
        m = ind[["industry", "quarter", "production_yoy_display"]].merge(ppi, on=["industry", "quarter"])
        m["value"] = ((1 + m["production_yoy_display"] / 100) / (1 + m["ppi_index_yoy_pct"] / 100) - 1) * 100
        m = m[m["industry"] != "기타"]
        parts.append(_ref_rows("ppi_adjusted_production_yoy", m[["industry", "quarter", "value"]],
                               "전국 PPI 사용·업종 대응표 미확정. 석유화학·전기전자는 두 PPI 항목 평균"))
        log["ppi_adjusted_production_yoy"] = int(m["value"].notna().sum())

    # (2) EIS 제조업 YoY (지역 공통)
    p = data_dir / "processed/eis/eis_validation_panel.csv"
    if p.exists():
        e = read_csv(p).rename(columns={"eis_manufacturing_yoy_pct": "value"})
        parts.append(_ref_rows("eis_manufacturing_yoy", e[["quarter", "value"]].assign(industry=None),
                               "고용보험 피보험자 기준, KICOX 산단 고용과 모집단 다름"))
        log["eis_manufacturing_yoy"] = int(e["value"].notna().sum())

    # (3) 업종별 수출 YoY — 창원상공회의소 보고서 전사본(분기별 파일)
    rows = []
    for f in sorted((data_dir / "raw/cci_report").glob("*.csv")):
        mq = re.search(r"(\d{4}Q[1-4])\.csv$", f.name)
        if not mq:
            continue
        lines = f.read_text(encoding="utf-8-sig").splitlines()
        hdr = next((i for i, l in enumerate(lines) if l.startswith("업종,")), None)
        if hdr is None:
            continue
        from io import StringIO
        t = pd.read_csv(StringIO("\n".join(lines[hdr:])))
        if "수출_전년동기대비(%)" not in t.columns:
            continue
        t["industry"] = t["업종"].replace(CCI_NAME_MAP)
        t = t[t["industry"].isin(INDUSTRIES) & (t["industry"] != "기타")]
        for _, r in t.iterrows():
            rows.append({"industry": r["industry"], "quarter": mq.group(1),
                         "value": pd.to_numeric(r["수출_전년동기대비(%)"], errors="coerce")})
    if rows:
        parts.append(_ref_rows("trade_export_yoy", pd.DataFrame(rows),
                               "창원상공회의소 보고서 수기 전사본, 4개 분기만 확보"))
        log["trade_export_yoy"] = len(rows)

    # (4) zip에 없는 지표: data/external/<indicator_id>.csv (quarter, [industry], value) 가 있으면 사용
    for iid in ["bsi_industry_business", "bsi_region_business", "mfg_flow_workers_yoy", "power_usage_yoy"]:
        f = data_dir / "external" / f"{iid}.csv"
        if f.exists():
            t = read_csv(f)
            if "industry" not in t.columns:
                t["industry"] = None
            parts.append(_ref_rows(iid, t[["industry", "quarter", "value"]], ""))
            log[iid] = int(len(t))
        else:
            log[iid] = "MISSING (data/external/%s.csv 없음)" % iid

    ref = pd.concat(parts, ignore_index=True)
    ref["quarter_date"] = ref["quarter"].map(q_start)
    ref["quarter_label"] = ref["quarter"].map(q_label)
    return ref[[
        "industry", "quarter", "quarter_date", "quarter_label", "indicator_id", "indicator_label",
        "value", "unit", "scope", "geography", "role_source", "role_display", "quality_note",
    ]].sort_values(["scope", "indicator_id", "industry", "quarter"], na_position="first").reset_index(drop=True)


# ─────────────────────────────────────────────────────────────
# 4. QA — 가이드 10-1 값 검증표
# ─────────────────────────────────────────────────────────────
def qa_checks(tot, ind, latest):
    T = tot.set_index("quarter").loc[latest]
    I = ind[ind["quarter"] == latest].set_index("industry")
    checks = [
        ("합계 명목 생산 YoY", round(T["mfg_production_yoy"], 2), 0.39),
        ("합계 고용 YoY", round(T["mfg_employment_yoy"], 2), -3.64),
        ("합계 고용 증감 인원", int(T["mfg_emp_delta"]), -4332),
        ("합계 고용자 수", int(T["mfg_employment"]), 114830),
        ("합계 생산 지수", round(T["mfg_production_index"], 1), 125.9),
        ("합계 고용 지수", round(T["mfg_employment_index"], 1), 99.4),
        ("기계 고용 증감 인원", int(I.loc["기계", "emp_delta"]), -3979),
        ("기계 고용자 수", int(I.loc["기계", "employment"]), 58784),
        ("기계 고용 YoY", round(I.loc["기계", "employment_yoy"], 1), -6.3),
        ("기계 생산 YoY", round(I.loc["기계", "production_yoy"], 1), -19.5),
        ("기계 생산 지수", round(I.loc["기계", "production_index_display"], 1), 118.7),
        ("기계 고용 지수", round(I.loc["기계", "employment_index_display"], 1), 95.1),
        ("기계 흐름", f'{I.loc["기계", "flow_label"]} {int(I.loc["기계", "run_length"])}분기째', "생산↓ 고용↓ 2분기째"),
        ("우선점검 업종", sorted(I.index[I["stage"] == "우선점검"]), ["기계", "목재종이"]),
        ("추가확인 업종", sorted(I.index[I["stage"] == "추가확인"]), []),
        ("업종 emp_delta 합 = 합계", int(I["emp_delta"].sum()), int(T["mfg_emp_delta"])),
    ]
    res = [{"item": k, "actual": a, "expected": e, "pass": a == e} for k, a, e in checks]
    return res


def jsonable(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


# ─────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--out-dir", default="outputs/final_model/07_tableau")
    a = ap.parse_args()
    data_dir, out_dir = Path(a.data_dir), Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    k = data_dir / "processed/kicox"

    ref_panel = read_csv(k / "changwon_state_reference_panel.csv")
    state_panel = read_csv(k / "changwon_state_panel.csv")
    latest = ref_panel["quarter"].max()

    ind = build_industry(ref_panel, state_panel, latest)
    tot = build_total(ind)
    log = {}
    ref = build_reference(data_dir, ind, log)

    # ── 저장: 불리언은 true/false, 날짜는 YYYY-MM-DD ──────────────
    INT_COLS = ["employment", "emp_delta", "employment_lag4", "firms_op", "run_length", "stage_order",
                "employment_display", "mfg_employment", "mfg_emp_delta"]

    def save(df, name, bool_cols=(), date_cols=()):
        df = df.copy()
        for c in INT_COLS:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c]).round().astype("Int64")
        for c in bool_cols:
            df[c] = to_bool(df[c])
        for c in date_cols:
            df[c] = pd.to_datetime(df[c]).dt.strftime("%Y-%m-%d")
        path = out_dir / name
        df.to_csv(path, index=False, encoding="utf-8-sig", float_format="%.6f")
        return path

    p_tot = save(tot, "dm_total_quarter.csv", date_cols=["quarter_date"])
    p_ind = save(ind, "dm_industry_quarter.csv",
                 bool_cols=["is_main_period", "review_required", "op_rate_definition_break", "stage_is_reconstructed"],
                 date_cols=["quarter_date", "run_start_date"])
    p_ref = save(ref, "dm_reference.csv", date_cols=["quarter_date"])

    data_hash = hashlib.sha256("".join(sha256(p) for p in (p_tot, p_ind, p_ref)).encode()).hexdigest()
    meta = pd.DataFrame([{
        "snapshot_quarter": latest,
        "snapshot_version": SNAPSHOT_VERSION,
        "data_hash": data_hash,
        "rule_version": RULE_VERSION,
        "data_cutoff": datetime.now().strftime("%Y-%m-%d"),
        "mart_built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "index_base_label": INDEX_BASE_LABEL,
        "note_scope": NOTE_SCOPE,
        "im_sha256": sha256(k / "changwon_industry_master.csv"),
        "rp_sha256": sha256(k / "changwon_state_reference_panel.csv"),
        "tp_sha256": sha256(k / "changwon_total_master.csv"),
        "cs_sha256": sha256(k / "changwon_state_panel.csv"),
        "dr_sha256": sha256(data_dir / "processed/ppi/ppi_industry_panel.csv"),
    }])
    save(meta, "dm_meta.csv")

    qa = qa_checks(tot, ind, latest)
    report = {
        "snapshot_quarter": latest,
        "rows": {"dm_total_quarter": len(tot), "dm_industry_quarter": len(ind),
                 "dm_reference": len(ref), "dm_meta": 1},
        "reference_indicators": log,
        "stage_counts_latest": ind[ind["quarter"] == latest]["stage"].value_counts().to_dict(),
        "checks": qa,
        "all_pass": all(c["pass"] for c in qa),
    }
    (out_dir / "qa_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=jsonable),
                                             encoding="utf-8")

    print(f"[OK] {out_dir}  (기준 분기 {latest})")
    for n, v in report["rows"].items():
        print(f"  {n:22s} {v:4d}행")
    print("  외부 참고 지표:")
    for n, v in log.items():
        print(f"    {n:30s} {v}")
    print("  가이드 값 검증:")
    for c in qa:
        print(f"    [{'PASS' if c['pass'] else 'FAIL'}] {c['item']}: {c['actual']} (기대 {c['expected']})")


if __name__ == "__main__":
    main()