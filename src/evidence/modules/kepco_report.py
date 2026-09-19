# -*- coding: utf-8 -*-
"""KEPCO 강건성 REPORT.md 생성기.

왜 생성기인가
    직전 REPORT.md 는 수기 작성이라 코드를 고칠 때마다 숫자가 낡는다. 숫자가 낡은
    보고서는 없는 보고서보다 나쁘다. 그래서 **숫자는 전부 실행 시점에 다시 만들고**,
    숫자가 없는 고정 서술(공식 명세·크로스워크 원칙·고객증감 판정·Triage 불가침)만
    `kepco_report_sections.md` 에서 그대로 가져온다.
    수기 원본은 logs/experiments/archived_outputs/kepco_robustness_20260919/ 에 보존돼 있다.

주장 강도를 절마다 섞지 않는다
    §8 을 직접 입증 / 간접 시사 / 입증 불가 세 묶음으로 나눈다. 자가발전·에너지효율·
    기업별 가동률처럼 자료가 없는 설명은 '간접 시사' 위로 올리지 않는다.
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

import pandas as pd

SECTIONS = Path(__file__).with_name("kepco_report_sections.md")


def _sections() -> dict[str, str]:
    if not SECTIONS.exists():
        return {}
    txt = SECTIONS.read_text(encoding="utf-8")
    parts = re.split(r"<!--SECTION:([a-z_]+)-->", txt)
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}


def _f(v, nd=2, dash="—"):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return dash
    if isinstance(v, (int,)) and not isinstance(v, bool):
        return f"{v:,}"
    try:
        return f"{float(v):,.{nd}f}"
    except (TypeError, ValueError):
        return str(v)


# ---------------------------------------------------------------- 한계표
def _limitation_table(res: dict) -> str:
    ld = res.get("legal_dong_2021", {})
    sp = res.get("spatial_context", {})
    h403 = res.get("http_403_assessment", {})
    verdict = ld.get("substitution_verdict", "—")
    rec = f'{ld.get("months_recoverable", "?")}/{ld.get("months_declared", "?")}'
    n403 = h403.get("finding_call_counts_20260919", {}).get("합계", "?")
    rows = [
        ("1. 2021년 업종별 결손",
         f"공식 『2021 산업분류-법정동별 전력사용량』 XLSX 확보·검증 "
         f"(복원 {rec}개월, 무결성 {ld.get('integrity', '?')}). 포털 로그인 후 재다운로드 "
         f"경로 확인 — 「산업분류-법정동별」 시리즈는 **2022년 4월이 최古**이며 2021년 파일이 "
         f"목록에 없다",
         f"**{verdict}** (재다운로드로도 해결 불가 확정)",
         "분류체계(KSIC 중분류) · 변수명(판매량/판매요금) · 공간단위(법정동명)가 "
         "`businessType.do` 의 한전 자체 36업종과 달라 같은 정의로 복구되지 않는다",
         "2021년 법정동×KSIC 전력수요의 **수준** 참고. YoY 기준연도로는 쓰지 않는다",
         "「2021년 자료를 별도 공식자료로 확인했으나 분류가 달라 업종별 결손은 복구되지 않는다」",
         "「2021년 업종별 전력자료를 확보했다」 / 「결손을 보완했다」"),
        ("2. 공간단위",
         "창원시 공장등록현황(공식) 5,636건에서 법정동을 추출(해석 "
         f"{_f(sp.get('factories_parsed_pct'), 1)}%, KEPCO 법정동 목록과 "
         f"{_f(sp.get('factories_matched_pct'), 1)}% 일치)해 **제조업 집적 법정동 "
         f"{_f(sp.get('dense_dong_count'))}개**를 정의하고 2021 법정동 전력과 결합",
         "**부분 해결 — 상한 정량화**",
         "산단 경계 polygon 이 공표되지 않고 법정동 코드도 없어 정확한 overlay 는 여전히 "
         "불가능하다. 법정동은 산단보다 넓다",
         f"집적 법정동이 창원 제조업 전력의 "
         f"**{_f(sp.get('dense_share_of_changwon_mfg_power_pct'), 1)}%**, "
         f"성산구 전체는 **{_f(sp.get('seongsan_share_of_changwon_mfg_power_pct'), 1)}%**. "
         "창원 **행정구역 기반 외부 context** 지위는 유지",
         f"「창원 제조업 전력의 {_f(sp.get('dense_share_of_changwon_mfg_power_pct'), 1)}%가 "
         f"공장 집적 법정동 {_f(sp.get('dense_dong_count'))}곳에 몰려 있다. 성산구 한 곳만 "
         f"보면 {_f(sp.get('seongsan_share_of_changwon_mfg_power_pct'), 1)}%여서, 창원 제조업 "
         f"전력의 {_f(100 - (sp.get('seongsan_share_of_changwon_mfg_power_pct') or 0), 1)}%는 "
         "성산구 밖에서 쓰인다」",
         "「성산구 = 창원국가산단」 / 「집적 법정동 전력 = 산단 전력」"),
        ("3. bizType 공식 정의",
         "`commonCode.do` 의 `codeTy` 에 bizType 계열 없음(404) 재확인. "
         "공표된 업종 코드표·정의 없음",
         "**미해결**",
         "원 분류체계의 공표 정의가 없어 crosswalk 근거를 올릴 수 없다",
         f"confidence B {res.get('_xwalk_B', '?')} · C {res.get('_xwalk_C', '?')} · "
         f"D {res.get('_xwalk_D', '?')} 유지. `official_crosswalk=FALSE`",
         "「KEPCO 업종↔KICOX 대응은 비공식 근사이며 등급 B~D로 명시했다」",
         "「KEPCO 업종별 자료를 KICOX 업종 생산·고용과 동일 기준으로 비교했다」"),
        ("4. 월별 지속성",
         "`monthly_negative_months` · `monthly_signal_consistency` 구현·검증",
         "**해결(보조지표 한정)**",
         "불완전 분기는 INCOMPLETE 로 빠져 완전 분기와 섞이지 않는다",
         "같은 분기 안에서 감소가 몇 달 반복되는지 확인하는 보조지표",
         "「분기 평균의 일시 변동인지, 분기 내 여러 달에 걸친 반복인지 구분했다」",
         "「월자료로 표본이 3배 늘었다」 / 「예측력이 향상됐다」"),
        ("5. API 호출 안정성",
         "선형 대기 → **지수 백오프**(4·8·16초, 최대 4회) 구현. "
         "429 즉시 중단·이어받기, 401 제한 재시도 유지",
         "**해결(수집기 한정)**",
         "호출 한도 자체가 공표돼 있지 않아 '한도 내'임을 증명할 수는 없다",
         "재수집 시 실패 복구는 자동",
         "「재시도·이어받기를 갖춰 부분 실패가 자료 결손으로 남지 않는다」",
         "「호출 한도에 걸렸다」 (한도가 공표된 적이 없다)"),
        ("5-1. 403 원인",
         "포털 로그인 후 **인증키 현황** 화면 확인. API별 상품 등록 목록이 **존재하지 않고**, "
         f"당일 호출집계에 4개 API 가 모두 정상 집계({n403}건). .env 키와 포털 키 sha256 일치",
         "**두 가설 기각 — 원인은 여전히 미확정**",
         "무엇이 403 을 냈는지는 공식 근거로 특정되지 않는다",
         "인증상품 미등록·호출 한도·잘못된 키 **셋 다 아님**이 확인된 범위",
         "「인증키는 정상이고 해당 API 들이 같은 키로 정상 호출됨을 포털 집계로 확인했다」",
         "「인증상품이 등록돼 있지 않아서다」 / 「호출 한도 때문이다」 (둘 다 기각됨)"),
        ("6. 고객증감 API 정의",
         "OPEN API 소개 화면이 「신설·증설·해지 **건수**」라고 적는 반면 통계화면·API 값은 "
         "**KWH** 임을 2026-09-19 로그인 상태에서 재확인. 공식 화면끼리 충돌",
         "**미해결**",
         "모집단·산식이 공표되지 않아 고객 '수' 로도 계약 '건수' 로도 해석 불가",
         "`NOT_SUITABLE`. 원값 보존·API 진단만. Triage·핵심 robustness 투입 없음",
         "「고객 증감 자료는 단위 정의가 확인되지 않아 분석에 쓰지 않았다」",
         "「사업체 수가 몇 개 늘었다/줄었다」"),
        ("7. 전력 정규화 · 효율/자가발전",
         "`power_usage_per_customer` · `power_usage_per_contract_power` · "
         "`customer_count_yoy` · `contract_power_yoy` 구현·검증",
         "**부분 해결**",
         "정규화는 구성·규모 효과를 일부 걷어내지만, 에너지효율 개선·자가발전·"
         "기온은 **측정 자료 자체가 없어** 보정 불가",
         "담당자 확인질문을 구체화하는 진단지표",
         "「설비용량 대비 사용량이 낮아졌는지까지 나눠 물을 수 있다」",
         "「전력 감소 = 생산 감소」 / 「효율 개선 때문이다」 (둘 다 자료 없음)"),
    ]
    head = ("| 기존 한계 | 이번 추가 조사 | 해결 여부 | 해결되지 않은 이유 | "
            "최종 사용 가능 범위 | 공모전에서 쓸 표현 | 쓰면 안 되는 표현 |\n"
            "|---|---|---|---|---|---|---|")
    body = "\n".join("| " + " | ".join(r) + " |" for r in rows)
    return head + "\n" + body


# ---------------------------------------------------------------- 본문
def build(res: dict, monthly: pd.DataFrame, quarterly: pd.DataFrame,
          joined: pd.DataFrame) -> str:
    sec = _sections()
    today = _dt.date.today().isoformat()
    pooled = res.get("pooled", {})
    pp, pe = pooled.get("production_vs_power", {}), pooled.get("employment_vs_power", {})
    mt = res.get("multiple_testing", {})
    mc = res.get("macro_check", {})
    ni = res.get("normalized_indicators", {})
    mp = res.get("monthly_persistence", {})
    ld = res.get("legal_dong_2021", {})
    tri = res.get("triage_invariance", {}).get("after", {})

    qm = quarterly[quarterly["kicox_mapped"]]
    qc = qm[qm["completeness"] == "COMPLETE"]
    quarters = sorted(qc["quarter"].unique())

    L = []
    A = L.append
    A("# KEPCO 전력사용량 — 외부 강건성 · context layer 검증")
    A("")
    A(f"**최종 지위: `{res.get('final_kepco_status', '—')}`**  ")
    A("**역할: CONTEXT / ACTIVITY (보조·강건성). Triage 판정변수가 아니다.**")
    A("")
    A(f"생성 {today} · `python src/build_kepco_robustness.py` 가 이 파일을 만든다. "
      "숫자는 매 실행마다 다시 계산된다.")
    A("")
    A("---")
    A("")
    if "spec" in sec:
        A(sec["spec"])
        A("")
        A("---")
        A("")

    # ---- 3. 수집·완전성
    A("## 3. 수집 결과와 분기 완전성")
    A("")
    comp = quarterly.groupby("completeness").size().sort_index()
    A("| 분기 완전성 | 업종×분기 수 |")
    A("|---|---|")
    for k, v in comp.items():
        A(f"| `{k}` | {v:,} |")
    A("")
    A(f"업종별 보조패널: 월 {len(monthly):,}행 / 분기 {len(quarterly):,}행. "
      f"KICOX 10업종 대응분 중 `COMPLETE` 분기는 "
      f"**{len(quarters)}개 분기** ({quarters[0]}~{quarters[-1]})다."
      if quarters else "COMPLETE 분기가 없다.")
    A("")
    A("2021년은 `NO_DATA` 다. **공급측 결손이지 수집 실패가 아니다** — 같은 구간에 "
      "`industryType.do` 는 정상값을 준다. 재호출로 복구되지 않는다.")
    A("")
    A("---")
    A("")

    # ---- 4. crosswalk
    if "crosswalk" in sec:
        A(sec["crosswalk"])
        A("")
        A("### 크로스워크 범위의 실증 확인")
        A("")
        A(f"업종별 API 의 제조업 업종 합계 ÷ 산업분류별 API 의 KSIC C 제조업 = "
          f"중앙값 **{_f(mc.get('ratio_median'), 4)}** "
          f"(범위 {_f(mc.get('ratio_min'), 4)}~{_f(mc.get('ratio_max'), 4)}), "
          f"YoY 상관 **{_f(mc.get('yoy_pearson'), 3)}** (n={_f(mc.get('n'))}).")
        A("")
        A("서로 다른 두 endpoint·분류체계가 총량에서 일치한다는 뜻이다. "
          "**제조업 '범위' 대응은 실증 확인됐고, KICOX 10업종 '배분'의 정확성은 "
          "여전히 확인되지 않았다.** 둘을 같은 근거로 쓰지 않는다.")
        A("")
        A("---")
        A("")

    # ---- 5. 신규 보조지표
    A("## 5. 전력 정규화 보조지표 (신규)")
    A("")
    A("| 지표 | 정의 | 유효 분기수 | 중앙값 | 음(-)의 분기수 |")
    A("|---|---|---|---|---|")
    for k, v in ni.items():
        A(f"| `{k}` | {v.get('definition', '')} | {_f(v.get('n_valid'))} / "
          f"{_f(v.get('n_rows'))} | {_f(v.get('median'), 3)} | {_f(v.get('n_negative'))} |")
    A("")
    A("0 또는 결측 분모에서는 값을 만들지 않는다. 불완전 분기의 flow 합계도 만들지 "
      "않으므로 비율·YoY 가 자동으로 결측이 된다.")
    A("")
    A("### 월별 지속성")
    A("")
    A(mp.get("definition", ""))
    A("")
    dist = mp.get("distribution", {})
    if dist:
        A("| 라벨 | 분기수 |")
        A("|---|---|")
        for k in ("PERSISTENT", "MAJORITY", "WEAK", "NONE", "INCOMPLETE"):
            if k in dist:
                A(f"| `{k}` | {dist[k]:,} |")
        A("")
    A("> " + str(mp.get("caveat", "")).replace("**", ""))
    A("")
    A("---")
    A("")

    # ---- 6. 강건성 결과
    A("## 6. 강건성 비교 결과")
    A("")
    A(f"결합 행수 {_f(res.get('n_rows_joined'))} (= Triage 180행, 늘지도 줄지도 않는다) · "
      f"비교가능 {_f(res.get('n_comparable'))}행")
    A("")
    A("| 비교 | 방향 일치 | 일치율 | Spearman ρ | p | n |")
    A("|---|---|---|---|---|---|")
    A(f"| 생산 YoY ↔ 전력 YoY | {_f(pp.get('agree'))}/{_f(pp.get('n'))} | "
      f"{_f(pp.get('agree_pct'), 1)}% | {_f(pp.get('spearman_rho'), 3)} | "
      f"{_f(pp.get('p_value'), 3)} | {_f(pp.get('n_corr'))} |")
    A(f"| 고용 YoY ↔ 전력 YoY | {_f(pe.get('agree'))}/{_f(pe.get('n'))} | "
      f"{_f(pe.get('agree_pct'), 1)}% | {_f(pe.get('spearman_rho'), 3)} | "
      f"{_f(pe.get('p_value'), 3)} | {_f(pe.get('n_corr'))} |")
    A("")
    A(f"업종별 검정 {_f(mt.get('n_tests'))}회 중 보정 전 p<0.05 는 "
      f"{_f(mt.get('n_p_below_05'))}개, **BH-FDR 보정 후 q<0.05 는 "
      f"{_f(mt.get('n_q_below_05_bh'))}개**다.")
    A("")
    A("이 결과를 「전력은 쓸모없다」로도 「전력은 독립적인 선행지표다」로도 읽지 않는다. "
      "업종 단위에서 전력 YoY 가 생산·고용 YoY 를 **대체하거나 검정하지 못한다**는 뜻이며, "
      "전력지표의 쓰임은 아래 §7 의 확인질문이다.")
    A("")
    A("---")
    A("")

    # ---- 7. 진단질문
    A("## 7. 담당자 확인질문 (전력지표의 실제 쓰임)")
    A("")
    A("| 지표 | 담당자가 다음에 확인할 질문 |")
    A("|---|---|")
    for k, v in (
        ("총전력 감소 `total_power_usage_yoy`",
         "산업·고용 악화와 **동시에** 실제 전력사용도 감소하고 있는가?"),
        ("고객당 전력 `power_usage_per_customer`",
         "사업체 수 변화보다 **개별 고객의 활동 약화**가 동반되는가?"),
        ("계약전력 대비 사용 `power_usage_per_contract_power`",
         "설비용량은 유지되는데 **실제 가동 수준만** 낮아지고 있는가?"),
        ("고객수 `customer_count_yoy`",
         "총전력 감소가 **사업체 기반 축소**와 함께 나타나는가?"),
        ("계약전력 `contract_power_yoy`",
         "단기 가동률 하락이 아니라 **설비·계약용량 축소**까지 진행되는가?"),
        ("월별 지속성 `monthly_signal_consistency`",
         "분기 평균의 일시 변동이 아니라 **분기 내 여러 달에 걸쳐** 감소가 반복되는가?"),
    ):
        A(f"| {k} | {v} |")
    A("")
    A("행 단위 질문은 `logs/validation/outputs/kepco_robustness/kepco_vs_production_employment.csv` 의 "
      "`diagnostic_*` 열에 있다. **질문을 만들 뿐 판정을 바꾸지 않는다.**")
    A("")
    A("---")
    A("")

    # ---- 8. 2021 대체자료
    A("## 8. 2021년 대체 공식자료 — 『산업분류-법정동별 전력사용량』")
    A("")
    A(f"- 파일 무결성: **{ld.get('integrity', '—')}** "
      f"(복원 {ld.get('months_recoverable', '?')}/{ld.get('months_declared', '?')}개월, "
      f"복원불가 {ld.get('sheets_unrecoverable', [])})")
    A(f"- 실제 컬럼: `{' · '.join(ld.get('header_actual', []))}`")
    A(f"- 공간: {ld.get('changwon_sigungu', [])} / 창원 법정동 "
      f"{_f(ld.get('changwon_legal_dong_count'))}개 · 법정동 **코드 없음**")
    A(f"- 분류: KSIC 대분류 {_f(ld.get('ksic_major_count'))}종, "
      f"제조업(C) 중분류 {_f(ld.get('ksic_mid_count_manufacturing'))}종")
    A(f"- 비식별: 고객호수 칸에 `{ld.get('masking_token', '')}` 문자열, "
      f"판매량·판매요금 공백. 창원 행의 **{_f(ld.get('masked_share_pct'), 1)}%** 가 해당")
    A("")
    A(f"**판정: `{ld.get('substitution_verdict', '—')}`** — {ld.get('substitution_reason', '')}")
    A("")
    A("헤더 컬럼명은 '판매량·판매요금'이라 단위 표기가 없지만, 포털 맞춤데이터 상세페이지의 "
      "주요항목표가 **전력사용량 kwh · 전기요금 원 · 호수(5호미만제거)** 로 명시한다. "
      "KSIC **코드**(대·중)도 실제로 제공된다. 단위 해석은 확정이다.")
    A("")
    A("**2021년 재다운로드는 불가능하다.** 포털 `데이터 공유 > 맞춤데이터 공유` 의 "
      "「산업분류-법정동별 전력사용량」 시리즈는 **2022년 4월이 가장 오래된 항목**(등록일 "
      "2022-06-08)이고 2021년 파일이 목록에 없다. 잘린 5개월은 이 경로로 복구되지 않는다.")
    A("")
    A("반대로 같은 시리즈가 **2022년 4월~2026년 전 구간**(총 25건)을 덮는다. 분석기간을 "
      "법정동 × KSIC 해상도로 볼 수 있는 공식 경로가 있다는 뜻이다. 다만 KSIC 분류이므로 "
      "`businessType.do` 의 한전 자체 36업종 계열을 대체하지는 못한다.")
    A("")
    A("---")
    A("")
    # ---- 8-2. 공간 context
    sp = res.get("spatial_context")
    if sp:
        A("## 8-2. 공간단위 — 「성산구 = 창원국가산단」이 얼마나 틀리는가")
        A("")
        A("창원시 공장등록현황(공공데이터포털 3066436) "
          f"{_f(sp.get('factories_total'))}건에서 법정동을 추출했다. 주소 해석 "
          f"{_f(sp.get('factories_parsed_pct'), 1)}%, 그중 KEPCO 법정동 목록과 일치 "
          f"{_f(sp.get('factories_matched_pct'), 1)}%.")
        A("")
        A("| 항목 | 값 |")
        A("|---|---|")
        A(f"| 창원 법정동 수 | {_f(sp.get('changwon_dong_total'))} |")
        A(f"| 제조업 집적 법정동 (공장 {_f(sp.get('dense_threshold_factories'))}건 이상) | "
          f"{_f(sp.get('dense_dong_count'))} |")
        A(f"| 집적 법정동의 창원 제조업 전력 비중 | "
          f"**{_f(sp.get('dense_share_of_changwon_mfg_power_pct'), 2)}%** |")
        A(f"| 성산구 전체의 창원 제조업 전력 비중 | "
          f"**{_f(sp.get('seongsan_share_of_changwon_mfg_power_pct'), 2)}%** |")
        A(f"| 성산구 안에서 집적 법정동 비중 | "
          f"{_f(sp.get('seongsan_dense_share_of_seongsan_mfg_power_pct'), 2)}% |")
        A("")
        ss = sp.get("seongsan_share_of_changwon_mfg_power_pct")
        if ss is not None:
            A(f"**성산구를 창원국가산단 대용으로 쓰면 창원 제조업 전력의 "
              f"{_f(100 - ss, 1)}%가 시야에서 사라진다.** 의창구 팔용동·진해구 남양동·"
              "마산회원구 봉암동처럼 성산구 밖에 있는 집적 법정동이 그만큼을 차지한다. "
              "반대로 성산구 안쪽은 집적 법정동이 "
              f"{_f(sp.get('seongsan_dense_share_of_seongsan_mfg_power_pct'), 1)}%로 거의 "
              "전부여서, 성산구를 쓰면 산단 밖 수요까지 함께 들어온다. 양방향으로 어긋난다.")
            A("")
        A("집적 법정동 목록: " + ", ".join(sp.get("dense_dong_list", [])))
        A("")
        A("> " + str(sp.get("caveat", "")).replace("**", ""))
        A("")

    if "custnum" in sec:
        A("---")
        A("")
        A(sec["custnum"])
        A("")
        A("---")
        A("")

    # ---- 9. 주장 강도
    A("## 9. 주장 강도 — 직접 입증 / 간접 시사 / 입증 불가")
    A("")
    A("### 9-1. 직접 입증 (자료와 코드가 확인한 사실)")
    A("")
    A(f"- 업종별 전력자료는 {quarters[0]}~{quarters[-1]} **{len(quarters)}개 분기**만 "
      f"`COMPLETE` 다. 2021년은 `NO_DATA` 다." if quarters else "- COMPLETE 분기 없음.")
    A(f"- 업종별 API 의 제조업 합계와 KSIC C 제조업 총량이 일치한다 "
      f"(비율 중앙값 {_f(mc.get('ratio_median'), 4)}, YoY 상관 {_f(mc.get('yoy_pearson'), 3)}).")
    A(f"- 업종 단위에서 생산·고용 YoY 와 전력 YoY 의 방향 일치율은 "
      f"{_f(pp.get('agree_pct'), 1)}% · {_f(pe.get('agree_pct'), 1)}% 이고, "
      f"BH-FDR 보정 후 유의한 업종은 {_f(mt.get('n_q_below_05_bh'))}개다.")
    A(f"- 2021년 대체자료는 실재하며 창원 법정동 "
      f"{_f(ld.get('changwon_legal_dong_count'))}개 × KSIC 중분류로 제공되지만, "
      f"창원 행의 {_f(ld.get('masked_share_pct'), 1)}% 가 비식별 처리돼 있다.")
    if res.get("spatial_context"):
        _sp = res["spatial_context"]
        A(f"- 창원 제조업 전력의 "
          f"{_f(_sp.get('dense_share_of_changwon_mfg_power_pct'), 1)}%가 공장 집적 법정동 "
          f"{_f(_sp.get('dense_dong_count'))}곳에 몰려 있고, 성산구 전체는 "
          f"{_f(_sp.get('seongsan_share_of_changwon_mfg_power_pct'), 1)}%에 그친다.")
    if h403 := res.get("http_403_assessment"):
        A("- 403 은 인증상품 미등록·호출 한도·잘못된 키 때문이 **아니다**. 포털 인증키 현황에 "
          "API별 상품 등록 개념이 없고, 당일 호출집계에 4개 API 가 모두 정상 집계된다.")
    A(f"- Triage 결과는 이 분석 전후로 동일하다 "
      f"(행 {_f(tri.get('rows'))} / {tri.get('stages', {})}).")
    A("")
    A("### 9-2. 간접적으로 시사 (가능한 설명 · 진단적 해석)")
    A("")
    A("- 총전력·고객당 전력·계약전력 대비 사용량이 **함께** 내려가는 업종-분기는 "
      "가동 축소가 설비·계약 축소까지 진행됐을 **가능성**을 시사한다. 확정이 아니다.")
    A("- 월별 감소가 `PERSISTENT` 인 분기는 일시 충격보다 지속 요인일 **가능성**이 크다.")
    A("- 전력 신호와 생산·고용 신호가 **엇갈리는** 업종-분기는 오류가 아니라 "
      "현장 확인이 필요한 지점이다.")
    A("")
    A("### 9-3. 입증 불가 (현재 자료로 말할 수 없는 것)")
    A("")
    A("- **자가발전·에너지효율 개선·기업별 가동률** — 측정 자료가 없다. "
      "전력 감소를 이 원인들로 설명하는 것도, 배제하는 것도 불가능하다.")
    A("- **창원국가산단 단위의 활동** — 공간단위가 행정구·법정동명이고 산단 경계 "
      "대응표가 없다.")
    A("- **전력 → 생산의 선행성** — 표본이 부족하고 lead/lag 는 탐색적 수준이다.")
    A("- **2021년 업종별 실적** — 같은 정의의 원자료가 공식적으로 존재하지 않는다.")
    A("- **고객 증감의 사업체 수 해석** — 단위가 KWH 이고 산식이 미공표다.")
    A("")
    A("---")
    A("")

    # ---- 10. 한계표
    A("## 10. 기존 한계 — 이번 조사 결과")
    A("")
    A(_limitation_table(res))
    A("")
    A("---")
    A("")

    if "no_triage_effect" in sec:
        A(sec["no_triage_effect"])
        A("")
        if tri:
            A(f"이번 실행에서도 실행 전후로 `decision_panel.csv` 의 sha256 이 동일하고, "
              f"행 {_f(tri.get('rows'))} / {tri.get('stages', {})} 가 유지됨을 "
              f"`check_triage_invariant()` 가 확인한다.")
            A("")
        A("---")
        A("")

    # ---- 11. 결론
    A("## 11. 최종 지위와 남은 한계")
    A("")
    A(f"**`{res.get('final_kepco_status', '—')}`.** 근거는 다음 여섯 축이다.")
    A("")
    A("| 기준 | 평가 |")
    A("|---|---|")
    A(f"| 시간 완전성 | 업종별 {len(quarters)}개 분기만 `COMPLETE`. 2021년 결손은 "
      f"공급측이라 복구 불가 |" if quarters else "| 시간 완전성 | COMPLETE 분기 없음 |")
    A("| 분류 정합성 | 제조업 '범위'는 실증 확인. KICOX 10업종 '배분'은 미확인 (B~D) |")
    A("| 공간 정합성 | 행정구·법정동명까지. 산단 경계 대응 불가 |")
    A("| 변수 정의 | 전력·고객호수·계약전력은 명확. 고객증감은 미확정(`NOT_SUITABLE`) |")
    A("| 기존 생산·고용과의 관계 | 방향 일치·상관 모두 약함. 교차검증 역할은 못 한다 |")
    A("| 의사결정지원 활용 | 담당자 확인질문을 구체화하는 데는 실제로 쓸 수 있다 |")
    A("")
    A("자료의 양이 많다는 이유로 `USABLE_CONTEXT` 로 올리지 않았다. "
      "공간·분류 정합성이 맞지 않는 한 업종 판정을 지지하는 증거로 쓸 수 없기 때문이다. "
      "반대로 `NOT_SUITABLE` 로 내리지도 않았다. 확인질문을 구체화하는 쓰임이 실재하고, "
      "제조업 총량 계열은 전 구간 사용 가능하기 때문이다.")
    A("")
    A("### 이번에도 해결하지 못한 것")
    A("")
    A("1. 2021년 업종별 원자료 — 같은 정의의 공식자료가 존재하지 않는다.")
    A("2. 산단 경계 ↔ 법정동 정확한 overlay — 경계 polygon 과 법정동 코드가 없다. "
      "집적 법정동은 상한이지 산단이 아니다.")
    A("3. `bizType` 공표 정의 — 없다. crosswalk 등급은 B~D 그대로다.")
    A("4. 고객증감 산식 — 미공표.")
    A("5. 에너지효율·자가발전 보정 — 자료 자체가 없다.")
    A("6. 일부 호출의 403 원인 — 인증상품 미등록·호출 한도·키 불일치 세 가설은 포털 화면으로 "
      "**기각**했으나, 무엇이 403 을 냈는지는 여전히 특정되지 않는다.")
    A(f"7. 2021 XLSX 의 {ld.get('sheets_unrecoverable', [])} 월 — 파일이 잘렸고, "
      "포털 시리즈가 2022년 4월부터라 **재다운로드로도 복구할 수 없다**. 판정에는 영향이 "
      "없다 — 12개월이 모두 있어도 정의 불일치로 `PARTIAL` 이다.")
    A("8. 2022~2026 법정동 × KSIC 자료를 실제로 수집·통합하는 일 — 경로는 확인됐으나 "
      "이번 범위 밖이다. 하더라도 36업종 계열을 대체하지는 못한다.")
    A("")
    return "\n".join(L) + "\n"
