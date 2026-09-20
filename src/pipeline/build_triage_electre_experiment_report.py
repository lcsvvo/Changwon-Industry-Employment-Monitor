"""Build the one standalone HTML report for triage → selective ELECTRE/SMAA.

The report is deliberately generated outside Jupyter.  Notebooks remain readable
Markdown/Python documents and the HTML is a single, self-contained deliverable.
"""

from __future__ import annotations

import datetime as dt
import html
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/final_model/06_report_assets/triage_electre_experiments.html"


def esc(value: object) -> str:
    if pd.isna(value):
        return "—"
    return html.escape(str(value))


def table(frame: pd.DataFrame) -> str:
    heads = "".join(f"<th>{esc(column)}</th>" for column in frame.columns)
    rows = []
    for values in frame.itertuples(index=False, name=None):
        rows.append("<tr>" + "".join(f"<td>{esc(value)}</td>" for value in values) + "</tr>")
    return f'<div class="table-wrap"><table><thead><tr>{heads}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def main() -> None:
    triage = pd.read_csv(ROOT / "outputs/final_model/02_triage/tables/triage_panel.csv")
    latest = pd.read_csv(ROOT / "outputs/final_model/02_triage/tables/triage_latest_full.csv")
    review = pd.read_csv(ROOT / "outputs/final_model/03_electre_smaa/tables/electre_smaa_review_cases.csv")
    source = pd.read_csv(ROOT / "data/processed/final_model/electre_smaa_check_cases.csv")
    sensitivity = pd.read_csv(ROOT / "logs/validation/triage/sensitivity_own_rules.csv")
    ppi = pd.read_csv(ROOT / "outputs/final_model/04_external_evidence/ppi/nominal_real_disagreement.csv")
    robustness = pd.read_csv(
        ROOT / "logs/experiments/archived_outputs/candidate_models/electre_interval_robustness.csv"
    )

    stage_counts = triage["stage"].value_counts()
    electre_counts = review["electre_stage"].value_counts()
    triage_keys = set(map(tuple, triage.loc[triage["stage"].eq("추가확인"), ["industry", "quarter"]].values))
    review_keys = set(map(tuple, review[["industry", "quarter"]].values))
    source_keys = set(map(tuple, source[["industry", "quarter"]].values))
    key_match = triage_keys == review_keys == source_keys
    overwrite = not review["triage_stage_preserved"].eq("추가확인").all()
    external_used = review["external_data_used_as_electre_criterion"].astype(str).str.lower().eq("true").any()
    sensitive_n = int(review["smaa_parameter_sensitive"].astype(str).str.lower().eq("true").sum())
    necessary_n = int(review["necessary_stage"].notna().sum())
    latest_quarter = str(latest["quarter"].iloc[0])
    c3b = robustness.loc[robustness["metric_id"].eq("C3b")].copy()
    c3b_pass = int(c3b["pass"].astype(str).str.lower().eq("true").sum())

    flow_qa = pd.DataFrame(
        [
            ["Triage 추가확인", len(triage_keys), "선택적 검토 입력"],
            ["ELECTRE/SMAA 입력", len(source_keys), "키 기준 일치" if key_match else "불일치"],
            ["ELECTRE/SMAA 결과", len(review_keys), "Triage 단계 보존" if not overwrite else "덮어쓰기 발견"],
        ],
        columns=["검증 지점", "건수", "판정"],
    )
    result_counts = pd.DataFrame(
        [[stage, int(electre_counts.get(stage, 0))] for stage in ["PRIORITY", "CHECK", "UNDETERMINED", "OBSERVE"]],
        columns=["ELECTRE 결과", "건수"],
    )
    sensitivity_view = sensitivity.sort_values("changed_rows", ascending=False).head(8)[
        ["variant", "changed_rows", "priority_changed_rows", "우선점검", "추가확인", "관찰"]
    ].rename(
        columns={
            "variant": "설정",
            "changed_rows": "변경 사례",
            "priority_changed_rows": "우선점검 변경",
        }
    )
    ppi_view = ppi.head(10)[
        ["industry", "quarter", "nominal_production_yoy", "ppi_adjusted_production_yoy", "sign_agreement"]
    ].copy()
    ppi_view.columns = ["업종", "분기", "명목 생산 YoY", "실질 생산 YoY", "방향 일치"]
    for column in ["명목 생산 YoY", "실질 생산 YoY"]:
        ppi_view[column] = ppi_view[column].map(lambda x: f"{x:.1f}%")

    latest_view = latest.sort_values("rank_in_stage")[
        ["industry", "stage", "decision_entry_trigger", "emp_delta", "run_length", "stage_reason"]
    ].copy()
    latest_view.columns = ["업종", "단계", "핵심 신호", "고용 증감", "상태 지속", "판정 근거"]
    latest_view["고용 증감"] = latest_view["고용 증감"].map(lambda x: f"{x:,.0f}명")
    latest_view["상태 지속"] = latest_view["상태 지속"].map(lambda x: f"{x:.0f}분기")

    generated = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    css = """
:root{--bg:#f8fafc;--ink:#1e2430;--sub:#5f6b7a;--card:#fff;--line:#e2e8f0;--accent:#2563eb;--navy:#172554;--observe:#64748b;--check:#d97706;--priority:#a04f8a;--ok:#0f766e}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Malgun Gothic",sans-serif;line-height:1.72}
.hero{background:linear-gradient(135deg,#07111f,#172554 58%,#2563eb);color:#fff;padding:56px 24px 44px}.hero-inner,.wrap{max-width:980px;margin:auto}.eyebrow{font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:#bfdbfe;font-weight:700}.hero h1{font-size:34px;line-height:1.25;margin:8px 0 10px}.hero p{max-width:760px;margin:0;color:#dbeafe;font-size:17px}
.wrap{padding:30px 22px 72px}.section{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:28px;margin-bottom:22px;box-shadow:0 5px 18px rgba(15,23,42,.04)}h2{font-size:21px;margin:0 0 8px}h3{font-size:17px;margin:24px 0 7px}.lead{color:var(--sub);margin:0 0 20px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.stat,.card{border:1px solid var(--line);border-radius:12px;background:#fff;padding:16px}.stat strong{display:block;font-size:27px;line-height:1.25;color:var(--navy)}.stat span,.small{font-size:13px;color:var(--sub)}
.flow-main{text-align:center;background:#eff6ff;border:1px solid #bfdbfe;border-radius:12px;padding:14px;font-weight:750}.arrow{text-align:center;color:var(--accent);font-size:24px;line-height:1.25}.branches{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.branch{border-radius:12px;padding:16px;border:1px solid var(--line)}.branch b{display:block;margin-bottom:6px}.branch.observe{border-top:5px solid var(--observe)}.branch.check{border-top:5px solid var(--check);background:#fffbeb}.branch.priority{border-top:5px solid var(--priority)}
.table-wrap{overflow-x:auto;margin:13px 0 18px}table{width:100%;border-collapse:collapse;font-size:14px}th{background:#f1f5f9;text-align:left;color:#334155;font-weight:700;white-space:nowrap}th,td{padding:10px 11px;border-bottom:1px solid var(--line);vertical-align:top}tbody tr:hover{background:#f8fafc}
.callout{border-left:5px solid var(--accent);background:#eff6ff;padding:14px 16px;border-radius:8px;margin:16px 0}.note{background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:14px 16px;margin:16px 0}.ok{color:var(--ok);font-weight:750}.warn{color:#b45309;font-weight:750}.steps{counter-reset:step}.experiment{position:relative;padding-left:44px;margin:26px 0}.experiment:before{counter-increment:step;content:counter(step);position:absolute;left:0;top:1px;width:30px;height:30px;border-radius:50%;display:grid;place-items:center;background:var(--navy);color:#fff;font-weight:800}.experiment p{margin:7px 0}.label{font-size:12px;font-weight:800;color:var(--accent);letter-spacing:.06em}.footer{text-align:center;color:var(--sub);font-size:12px;padding:12px}@media(max-width:760px){.grid,.branches{grid-template-columns:1fr 1fr}.hero h1{font-size:28px}}@media(max-width:520px){.grid,.branches{grid-template-columns:1fr}.section{padding:20px}.wrap{padding-left:12px;padding-right:12px}}
"""

    document = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Triage → 선택적 ELECTRE/SMAA와 실험 기록</title><style>{css}</style></head><body>
<header class="hero"><div class="hero-inner"><div class="eyebrow">Changwon Industry &amp; Employment Monitor</div>
<h1>Triage → 선택적 ELECTRE/SMAA와 실험 기록</h1>
<p>전체 자동판정 모형이 아니라, 설명 가능한 1차 선별 뒤 경계·불확실 사례만 다기준으로 다시 살피는 현재 구조와 그 선택 근거를 한 화면에 정리했습니다.</p></div></header>
<main class="wrap">
<section class="section"><h2>한눈에 보기</h2><p class="lead">현재 산출물에서 직접 확인한 운영 규모와 선택적 검토 결과입니다.</p>
<div class="grid"><div class="stat"><strong>{len(triage):,}</strong><span>전체 업종×분기</span></div><div class="stat"><strong>{int(stage_counts.get('추가확인',0)):,}</strong><span>추가확인 → 선택적 검토</span></div><div class="stat"><strong>{int(stage_counts.get('우선점검',0)):,}</strong><span>우선점검 → 외부근거·담당자</span></div><div class="stat"><strong>{sensitive_n:,}</strong><span>SMAA 파라미터 민감 사례</span></div></div>
<div class="callout"><b>핵심 결론</b><br>Triage가 1차 선별을 담당합니다. ELECTRE/SMAA는 <b>추가확인 {len(review):,}건</b>에만 적용되며 Triage 단계를 덮어쓰지 않습니다.</div></section>

<section class="section"><h2>1. 현재 운영 흐름</h2><p class="lead">ELECTRE는 모든 사례가 반드시 거치는 단계가 아닙니다.</p>
<div class="flow-main">Q1 상태 + Q2 규모 + Q3 시간 → 규칙 기반 Triage</div><div class="arrow">↓</div>
<div class="branches"><div class="branch observe"><b>관찰 · {int(stage_counts.get('관찰',0))}건</b>정기 모니터링<br><span class="small">ELECTRE 진입 없음</span></div><div class="branch check"><b>추가확인 · {int(stage_counts.get('추가확인',0))}건</b>경계·충돌·불확실 사례<br><span class="small">Selective ELECTRE/SMAA → Human-in-the-Loop</span></div><div class="branch priority"><b>우선점검 · {int(stage_counts.get('우선점검',0))}건</b>외부근거·담당자 검토<br><span class="small">ELECTRE를 필수 경유하지 않음</span></div></div>
<h3>경로 정합성 검증</h3>{table(flow_qa)}
<p class="{'ok' if key_match and not overwrite and not external_used else 'warn'}">키 일치: {key_match} · Triage stage overwrite: {overwrite} · 외부자료를 ELECTRE 기준으로 사용: {external_used}</p>
<div class="note">불확실 결과는 자동 승격·강등하지 않습니다. 자료·모형 불확실성을 표시한 뒤 담당자 확인 질문과 검토 기능으로 넘깁니다.</div></section>

<section class="section"><h2>2. 최신 분기 Triage</h2><p class="lead">{esc(latest_quarter)} 결과를 보고서 앞쪽에 배치했습니다.</p>{table(latest_view)}</section>

<section class="section"><h2>3. 어떤 실험을 했는가</h2><p class="lead">단순 로그 나열이 아니라 문제 → 실험 → 확인된 결과 → 최종 설계 영향 순으로 읽습니다.</p><div class="steps">
<div class="experiment"><div class="label">ELECTRE TRI-B</div><h3>초기 다기준 주모형 후보</h3><p><b>문제·가설:</b> 고용 규모, 감소율, 상대 부진, 지속성을 비보상적으로 결합하면 단순 합산보다 범주 분류에 적합할 수 있다고 보았습니다.</p><p><b>실험:</b> 기준·고용중시·지속성중시 가중치와 기준 프로파일, λ, 무차별 임계값을 바꾸어 배정과 교란 강건성을 확인했습니다.</p><p><b>결과:</b> C3b 6개 조합 중 사전 기준 0.95 통과는 <b>{c3b_pass}개</b>였습니다. 독립감사에서는 평가공간 불일치와 표집 누락 가능성도 확인했습니다.</p><p><b>영향:</b> 다기준 구조는 보존하되 전체 자동판정이 아니라 선택적 재검토 층으로 역할을 축소했습니다.</p></div>
<div class="experiment"><div class="label">SMAA-TRI</div><h3>고정 가중치의 자의성 점검</h3><p><b>문제·가설:</b> 하나의 weight만 고정하면 결과가 특정 선호에 종속될 수 있습니다.</p><p><b>실험:</b> 호환 파라미터 공간을 표집하고 단계별 CAI, 필요 단계와 가능 단계 집합을 계산했습니다.</p><p><b>결과:</b> {len(review)}건 중 <b>{sensitive_n}건</b>이 둘 이상의 가능 단계를 가져 파라미터 민감으로 표시됐고, 단일 필요 단계가 확인된 사례는 {necessary_n}건입니다.</p><p><b>영향:</b> SMAA는 ‘정답 weight’를 찾는 도구가 아니라 불확실성을 노출하는 보조 결과로 사용합니다.</p>{table(result_counts)}</div>
<div class="experiment"><div class="label">TRIAGE SENSITIVITY</div><h3>운영 threshold와 구성요소 강건성</h3><p><b>실험:</b> A 경계, 규모 gate, Q3·P·반복조건 제거 등 저장소에 남은 15개 specification을 baseline과 비교했습니다.</p><p><b>결과:</b> 설정에 따라 변경 사례 수가 달랐고, 특히 gate·hard exclusion 계열의 영향이 컸습니다. 따라서 threshold는 외부 정답이 아니라 공개해야 할 운영기준입니다.</p>{table(sensitivity_view)}</div>
<div class="experiment"><div class="label">PPI ADJUSTMENT</div><h3>명목 생산과 실질 생산 비교</h3><p><b>실험:</b> 업종별 PPI로 생산을 보정해 명목 YoY와 실질 YoY의 방향·5% 경계 일치 여부를 비교했습니다.</p><p><b>결과:</b> 불일치 기록은 <b>{len(ppi)}건</b>입니다. 생산 신호 해석이 가격 변화에 영향을 받을 수 있음을 보여주며, PPI는 CORE를 숨겨서 교체하는 값이 아니라 별도 민감도 근거로 남겼습니다.</p>{table(ppi_view)}</div>
<div class="experiment"><div class="label">ISOLATION FOREST</div><h3>구현 여부 확인</h3><p><b>결과:</b> 저장소 코드·산출물·로그에서 재현 가능한 Isolation Forest 실험을 찾지 못했습니다.</p><p><b>영향:</b> 수행한 것처럼 결과를 만들지 않고 <b>미수행</b>으로 기록했습니다. 향후 실행하더라도 최종 판정이 아니라 독립적 이상치 보조검증 역할이어야 합니다.</p></div>
</div></section>

<section class="section"><h2>4. 최종 모형 선택</h2><p class="lead">프로젝트의 역사와 현재 운영구조를 분리합니다.</p>
{table(pd.DataFrame([
['Q1~Q3','현상 진단','상태·규모·시간을 직접 설명','점검 순서는 단독 결정 불가','CORE'],
['ELECTRE TRI-B','다기준 범주 분류','비보상·경계 구조 표현','파라미터 외적 정당화와 안정성 한계','추가확인 선택적 재검토'],
['SMAA-TRI','가중치 불확실성','가능 단계와 민감성 노출','정답 weight·정답 label을 만들지 못함','ELECTRE 강건성 보조'],
['Isolation Forest','통계적 이상치','독립 관점 가능','현재 재현 가능한 실험 없음','미수행'],
['Rule-based Triage','1차 선별','설명·감사·운영 용이','threshold 민감성','현재 1차 구조'],
], columns=['후보','목적','장점','실제 확인된 한계','최종 역할']))}
<div class="callout"><b>프로젝트 역사:</b> ELECTRE TRI-B를 전체 사례의 주모형 후보로 검토했습니다.<br><b>최종 운영구조:</b> 현재는 Triage의 ‘추가확인’ 사례만 ELECTRE/SMAA로 재검토하고, 결과를 Human-in-the-Loop 판단 자료로 제공합니다.</div></section>
<div class="footer">생성: {esc(generated)} · source of truth: production pipeline CSV/archived experiment outputs · 단일 HTML 보고서</div>
</main></body></html>"""

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(document, encoding="utf-8")
    print(f"[ok] {OUT.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
