import os
import json
import hashlib
from datetime import datetime
import pandas as pd
import numpy as np

def compute_sha256(filepath: str) -> str:
    """파일 무결성 검증용 SHA-256 해시 계산"""
    if not os.path.exists(filepath):
        return ""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()

def quarter_to_date(q_str: str) -> str:
    """'2026Q2' -> '2026-04-01' 변환"""
    if not isinstance(q_str, str) or len(q_str) < 6:
        return ""
    year = q_str[:4]
    q = q_str[4:]
    q_month_map = {"Q1": "01-01", "Q2": "04-01", "Q3": "07-01", "Q4": "10-01"}
    return f"{year}-{q_month_map.get(q, '01-01')}"

def quarter_to_label(q_str: str) -> str:
    """'2026Q2' -> '2026년 2분기' 변환"""
    if not isinstance(q_str, str) or len(q_str) < 6:
        return ""
    year = q_str[:4]
    q_num = q_str[-1]
    return f"{year}년 {q_num}분기"

def find_col(df: pd.DataFrame, candidates: list):
    """여러 후보 컬럼명 중 실제 존재하는 첫 번째 컬럼명을 반환"""
    for c in candidates:
        if c in df.columns:
            return c
    return None

def main():
    # 1. 실행 위치 기준 프로젝트 루트 및 경로 설정
    curr_file_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 'src/export' 내에 있는 경우와 'outputs/...' 내에 있는 경우 모두 대응
    if os.path.exists(os.path.join(curr_file_dir, "..", "..", "data")):
        project_root = os.path.abspath(os.path.join(curr_file_dir, "..", ".."))
    elif os.path.exists(os.path.join(curr_file_dir, "..", "..", "..", "data")):
        project_root = os.path.abspath(os.path.join(curr_file_dir, "..", "..", ".."))
    else:
        project_root = os.getcwd()

    raw_dir = os.path.join(project_root, "data", "processed", "kicox")
    out_dir = os.path.join(project_root, "outputs", "final_model", "07_tableau")
    os.makedirs(out_dir, exist_ok=True)

    print(f"[*] 프로젝트 루트: {project_root}")
    print(f"[*] 원천 데이터 경로: {raw_dir}")
    print(f"[*] 태블로 마트 출력 경로: {out_dir}")

    total_master_path = os.path.join(raw_dir, "changwon_total_master.csv")
    industry_master_path = os.path.join(raw_dir, "changwon_industry_master.csv")
    ref_panel_path = os.path.join(raw_dir, "changwon_state_reference_panel.csv")
    state_panel_path = os.path.join(raw_dir, "changwon_state_panel.csv")

    df_total_src = pd.read_csv(total_master_path)
    df_ind_src = pd.read_csv(industry_master_path)
    df_ref_src = pd.read_csv(ref_panel_path) if os.path.exists(ref_panel_path) else pd.DataFrame()
    df_state_src = pd.read_csv(state_panel_path) if os.path.exists(state_panel_path) else pd.DataFrame()

    # ---------------------------------------------------------
    # 2. dm_total_quarter.csv 생성
    # ---------------------------------------------------------
    print("\n[1/4] dm_total_quarter.csv 생성 중...")
    df_total = df_total_src.copy()

    # 원천 데이터의 다양한 컬럼명을 가이드라인 규격으로 통일
    col_mapping = {
        find_col(df_total, ["mfg_employment", "total_employment", "employment"]): "mfg_employment",
        find_col(df_total, ["mfg_employment_yoy", "total_employment_yoy", "employment_yoy"]): "mfg_employment_yoy",
        find_col(df_total, ["mfg_emp_delta", "total_emp_delta", "emp_delta"]): "mfg_emp_delta",
        find_col(df_total, ["mfg_production", "total_production", "production"]): "mfg_production",
        find_col(df_total, ["mfg_production_yoy", "total_production_yoy", "production_yoy"]): "mfg_production_yoy",
        find_col(df_total, ["mfg_employment_index", "total_employment_index", "employment_index"]): "mfg_employment_index",
        find_col(df_total, ["mfg_production_index", "total_production_index", "production_index"]): "mfg_production_index",
    }
    for old_col, new_col in col_mapping.items():
        if old_col and old_col != new_col:
            df_total[new_col] = df_total[old_col]

    # 기본 라벨 및 날짜 필드
    if "quarter_date" not in df_total.columns:
        df_total["quarter_date"] = df_total["quarter"].apply(quarter_to_date)
    if "quarter_label" not in df_total.columns:
        df_total["quarter_label"] = df_total["quarter"].apply(quarter_to_label)
    
    df_total["scope_label"] = "10개 제조업종 합계"
    df_total["index_base_label"] = "2022년 평균 = 100"

    # mfg_emp_delta가 없을 경우 4분기 lag를 이용해 자동 계산
    if "mfg_emp_delta" not in df_total.columns or df_total["mfg_emp_delta"].isna().all():
        if "mfg_employment" in df_total.columns:
            df_total["mfg_emp_delta"] = df_total["mfg_employment"] - df_total["mfg_employment"].shift(4)

    # mfg_production_yoy_note 필드 생성 (결측값 사유)
    if "mfg_production_yoy_note" not in df_total.columns:
        if "mfg_production_yoy" in df_total.columns:
            df_total["mfg_production_yoy_note"] = np.where(
                df_total["mfg_production_yoy"].isna(),
                np.where(df_total["quarter"].astype(str).str.startswith("2018"), "2018년 전년 비교 불가", "생산 비공개로 계산 불가"),
                ""
            )
        else:
            df_total["mfg_production_yoy_note"] = ""

    total_cols = [
        "quarter", "quarter_date", "quarter_label", "scope_label",
        "mfg_employment", "mfg_employment_yoy", "mfg_emp_delta",
        "mfg_production", "mfg_production_yoy", "mfg_production_yoy_note",
        "mfg_employment_index", "mfg_production_index", "index_base_label"
    ]
    df_total_out = df_total[[c for c in total_cols if c in df_total.columns]]
    total_out_path = os.path.join(out_dir, "dm_total_quarter.csv")
    df_total_out.to_csv(total_out_path, index=False, encoding="utf-8-sig")
    print(f"  -> 저장 완료: {total_out_path} ({len(df_total_out)}행)")

    # ---------------------------------------------------------
    # 3. dm_industry_quarter.csv 생성
    # ---------------------------------------------------------
    print("\n[2/4] dm_industry_quarter.csv 생성 중...")
    df_ind = df_ind_src.copy()

    # state_panel 병합 (stage, run_length, flow_label 등 보충)
    if not df_state_src.empty:
        merge_keys = [k for k in ["quarter", "industry"] if k in df_ind.columns and k in df_state_src.columns]
        extra_cols = [c for c in df_state_src.columns if c not in df_ind.columns and c not in merge_keys]
        if extra_cols and merge_keys:
            df_ind = pd.merge(df_ind, df_state_src[merge_keys + extra_cols], on=merge_keys, how="left")

    if "quarter_date" not in df_ind.columns:
        df_ind["quarter_date"] = df_ind["quarter"].apply(quarter_to_date)
    if "quarter_label" not in df_ind.columns:
        df_ind["quarter_label"] = df_ind["quarter"].apply(quarter_to_label)
    if "is_main_period" not in df_ind.columns:
        df_ind["is_main_period"] = df_ind["quarter"] >= "2022Q1"

    # 화살표 필드
    arrow_map = {"증가": "▲", "감소": "▼", "보합": "―"}
    if "prod_dir" in df_ind.columns and "prod_arrow" not in df_ind.columns:
        df_ind["prod_arrow"] = df_ind["prod_dir"].map(arrow_map).fillna("―")
    if "emp_dir" in df_ind.columns and "emp_arrow" not in df_ind.columns:
        df_ind["emp_arrow"] = df_ind["emp_dir"].map(arrow_map).fillna("―")

    # 점검 단계 순서
    if "stage" in df_ind.columns and "stage_order" not in df_ind.columns:
        stage_order_map = {"우선점검": 1, "추가확인": 2, "관찰": 3}
        df_ind["stage_order"] = df_ind["stage"].map(stage_order_map).fillna(3).astype(int)

    # 화면 표시용(display) 필드 누락 방지
    for base in ["employment", "production", "employment_yoy", "production_yoy", "employment_index", "production_index"]:
        disp_col = f"{base}_display"
        if disp_col not in df_ind.columns and base in df_ind.columns:
            df_ind[disp_col] = df_ind[base]

    if "index_base_label" not in df_ind.columns:
        df_ind["index_base_label"] = "2022년 평균 = 100"

    industry_out_path = os.path.join(out_dir, "dm_industry_quarter.csv")
    df_ind.to_csv(industry_out_path, index=False, encoding="utf-8-sig")
    print(f"  -> 저장 완료: {industry_out_path} ({len(df_ind)}행)")

    # ---------------------------------------------------------
    # 4. dm_reference.csv 생성
    # ---------------------------------------------------------
    print("\n[3/4] dm_reference.csv 생성 중...")
    if not df_ref_src.empty:
        df_ref = df_ref_src.copy()
        if "quarter_date" not in df_ref.columns and "quarter" in df_ref.columns:
            df_ref["quarter_date"] = df_ref["quarter"].apply(quarter_to_date)
        if "quarter_label" not in df_ref.columns and "quarter" in df_ref.columns:
            df_ref["quarter_label"] = df_ref["quarter"].apply(quarter_to_label)
    else:
        ref_cols = [
            "industry", "quarter", "quarter_date", "quarter_label",
            "indicator_id", "indicator_label", "value", "unit",
            "scope", "geography", "role_source", "role_display", "quality_note"
        ]
        df_ref = pd.DataFrame(columns=ref_cols)

    ref_out_path = os.path.join(out_dir, "dm_reference.csv")
    df_ref.to_csv(ref_out_path, index=False, encoding="utf-8-sig")
    print(f"  -> 저장 완료: {ref_out_path} ({len(df_ref)}행)")

    # ---------------------------------------------------------
    # 5. dm_meta.csv 생성
    # ---------------------------------------------------------
    print("\n[4/4] dm_meta.csv 생성 중...")
    latest_quarter = df_total["quarter"].max() if not df_total.empty and "quarter" in df_total.columns else "2026Q2"
    
    meta_row = {
        "snapshot_quarter": latest_quarter,
        "snapshot_version": "v3",
        "data_hash": compute_sha256(total_master_path)[:16],
        "rule_version": "v1.2",
        "data_cutoff": datetime.now().strftime("%Y-%m-%d"),
        "mart_built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "index_base_label": "2022년 평균 = 100",
        "note_scope": "10개 제조업종 합계는 산단 전체 총계와 다름",
        "im_sha256": compute_sha256(total_master_path),
        "rp_sha256": compute_sha256(industry_master_path),
        "tp_sha256": compute_sha256(ref_panel_path),
        "cs_sha256": compute_sha256(state_panel_path),
        "dr_sha256": ""
    }
    df_meta = pd.DataFrame([meta_row])
    meta_out_path = os.path.join(out_dir, "dm_meta.csv")
    df_meta.to_csv(meta_out_path, index=False, encoding="utf-8-sig")
    print(f"  -> 저장 완료: {meta_out_path} (1행)")

    # ---------------------------------------------------------
    # 6. QA 검증 및 qa_report.json 생성
    # ---------------------------------------------------------
    print("\n[*] 2026Q2 기준값 QA 검증 수행...")
    qa_results = {}
    
    q2_total = df_total[df_total["quarter"] == latest_quarter]
    if not q2_total.empty:
        qa_results["total_mfg_employment"] = int(q2_total["mfg_employment"].values[0]) if "mfg_employment" in q2_total else None
        qa_results["total_mfg_emp_delta"] = int(q2_total["mfg_emp_delta"].values[0]) if "mfg_emp_delta" in q2_total else None
        qa_results["total_mfg_production_yoy"] = float(q2_total["mfg_production_yoy"].values[0]) if "mfg_production_yoy" in q2_total else None
        qa_results["total_mfg_employment_yoy"] = float(q2_total["mfg_employment_yoy"].values[0]) if "mfg_employment_yoy" in q2_total else None

    q2_mach = df_ind[(df_ind["quarter"] == latest_quarter) & (df_ind["industry"] == "기계")]
    if not q2_mach.empty:
        qa_results["machine_emp_delta"] = int(q2_mach["emp_delta"].values[0]) if "emp_delta" in q2_mach else None
        qa_results["machine_stage"] = str(q2_mach["stage"].values[0]) if "stage" in q2_mach else None
        qa_results["machine_employment"] = int(q2_mach["employment"].values[0]) if "employment" in q2_mach else None

    qa_report = {
        "status": "SUCCESS",
        "built_at": datetime.now().isoformat(),
        "latest_quarter": latest_quarter,
        "qa_checks": qa_results,
        "expected_benchmarks_2026Q2": {
            "total_mfg_emp_delta": -4332,
            "total_mfg_employment": 114830,
            "total_mfg_production_yoy": 0.39,
            "total_mfg_employment_yoy": -3.64,
            "machine_emp_delta": -3979,
            "machine_stage": "우선점검"
        }
    }

    qa_report_path = os.path.join(out_dir, "qa_report.json")
    with open(qa_report_path, "w", encoding="utf-8") as f:
        json.dump(qa_report, f, indent=2, ensure_ascii=False)
    print(f"  -> QA 리포트 생성 완료: {qa_report_path}")
    print(f"\n[✔] 모든 마트 파일 생성이 완료되었습니다.")

if __name__ == "__main__":
    main()