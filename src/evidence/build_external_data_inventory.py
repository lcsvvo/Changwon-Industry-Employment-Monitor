# -*- coding: utf-8 -*-
"""외부 공개데이터 탐색 결과표 (data/processed/final_model/reference/external_data_inventory.csv).

'있을 것 같다' 는 목록이 아니라 2026-09-18 에 실제로 접속·조회해 본 결과다.
status 는 AVAILABLE / PARTIAL / NOT_AVAILABLE / NOT_SUITABLE 중 하나다.

    AVAILABLE      실제로 내려받아 data/raw/<source>/ 에 저장했다
    PARTIAL        일부만 가능(인증키 필요, 공간·업종 단위 부족, 단일 시점 등)
    NOT_AVAILABLE  공개 경로로 받을 수 없다
    NOT_SUITABLE   받을 수는 있으나 이 분석의 질문에 쓸 수 없다

실행:  python src/evidence/build_external_data_inventory.py
"""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/processed/final_model/reference/external_data_inventory.csv"
CHECKED = "2026-09-18"

COLS = ["dataset", "institution", "source_url", "access_method",
        "previous_status", "current_status", "status_changed_at",
        "collection_result", "failure_reason",
        "observation_period", "frequency", "geography", "industry_unit",
        "role", "usable_for_industry_signal", "reason_or_limitation",
        "alternative", "stored_at", "checked_at"]
# 2026-09-19 인증키 4종 확보 후 재판정. 과거 상태를 지우지 않고 previous_status 로 남긴다.
RECHECKED = "2026-09-19"
# 2026-09-19 2차: 관세청 HS6 모집단 확보로 수출 커버리지 확대, KEPCO PARTIAL 고정,
# 고용보험 업종별 flow·고용유지지원금은 구조적 부재로 자동수집 중단 결정.
DECIDED = "2026-09-19"

ROWS = [
    # ---------------------------------------------------------- 실제 수집됨
    dict(dataset="KICOX 국가산업단지 산업동향 — 업종별 고용/생산/가동률/가동업체/입주업체",
         institution="한국산업단지공단",
         source_url="https://www.data.go.kr/data/15085897/fileData.do 외 5건",
         access_method="공공데이터포털 파일데이터 직접 다운로드(인증키 불필요)",
         status="AVAILABLE", observation_period="2026Q2 공표본(연간보정)",
         frequency="분기(2024Q2~) / 그 이전 월별", geography="전국 국가산업단지",
         industry_unit="KICOX 10업종", role="기존 입력의 최신 공표본 대조(개정 확인)",
         usable_for_industry_signal="아니오 — 모형 입력과 동일 계열이라 독립검증 불가",
         reason_or_limitation="포털은 현재 공표본 1개만 제공. 과거 월별 공표본 재취득 불가",
         alternative="연간보정본 xlsx(data/raw/kicox/revision/)",
         stored_at="data/raw/kicox/datagokr/", checked_at=CHECKED),
    dict(dataset="KICOX 전국산업단지현황통계 — 국가산업단지 입주·가동업체수",
         institution="한국산업단지공단",
         source_url="https://www.data.go.kr/data/15085874/fileData.do",
         access_method="공공데이터포털 파일데이터 직접 다운로드",
         status="AVAILABLE", observation_period="2025Q4 공표본", frequency="분기",
         geography="전국 국가산업단지(단지별)", industry_unit="없음(단지 단위)",
         role="단지 단위 업체수 공표 일관성 확인",
         usable_for_industry_signal="아니오 — 업종 구분 없음, 동일 계열",
         reason_or_limitation="업종별 분해 없음",
         alternative="없음", stored_at="data/raw/kicox/datagokr/",
         checked_at=CHECKED),
    dict(dataset="한국은행 기업경기조사(실적) 제조업 월별 BSI",
         institution="한국은행", source_url="https://ecos.bok.or.kr/",
         access_method="ECOS OpenAPI (ECOS_API_KEY; 미설정 시 공개 sample 키 10건 한도)",
         status="AVAILABLE", observation_period="2021-01~2026-08", frequency="월",
         geography="전국(지역 분류축 없음)", industry_unit="제조업 전체",
         role="거시 배경정보(context)",
         usable_for_industry_signal="아니오 — 경남·창원 분해 불가, 업종 대응 불가",
         reason_or_limitation="512Y013 의 분류축은 업종코드뿐이며 지역축이 없다",
         alternative="경남지역 BSI 는 한국은행 경남본부 보도자료 PDF 로만 공표(자동수집 불가)",
         stored_at="data/raw/ecos/legacy_bok_bsi/", checked_at=CHECKED,
         previous_status='AVAILABLE',
         current_status='SUPERSEDED',
         collection_result='2026-09-19 실제 ECOS_API_KEY 수집분으로 대체(아래 신규 행)',
         failure_reason='sample 키(1회 10건)로 받은 전국 제조업 BSI. 기록 보존용'),
    dict(dataset="경상남도 창원시 공장등록현황",
         institution="경상남도 창원시",
         source_url="https://www.data.go.kr/data/3066436/fileData.do",
         access_method="공공데이터포털 파일데이터 직접 다운로드",
         status="PARTIAL", observation_period="2024-12-31 단일 시점", frequency="비정기",
         geography="창원시 전역(산단 내외 구분 없음)",
         industry_unit="KSIC 세세분류 업종명(문자열)",
         role="업체 구성 맥락(context)",
         usable_for_industry_signal="아니오 — 단일 시점이라 YoY 불가, 산단 경계 불일치",
         reason_or_limitation="시계열이 없어 업체수 증감 신호로 쓸 수 없다",
         alternative="KICOX firms_in / firms_op (산단 단위, 분기)",
         stored_at="data/raw/changwon_factory_registry/", checked_at=CHECKED),
    # ---------------------------------------------------------- 인증키 필요
    dict(dataset="관세청 시군구별 품목별 수출입실적",
         institution="관세청",
         source_url="https://www.data.go.kr/data/15134343/openapi.do",
         access_method="OpenAPI (DATA_GO_KR_SERVICE_KEY 필요)",
         status="PARTIAL", observation_period="미수집", frequency="월",
         geography="시군구(창원시)", industry_unit="HS 6단위",
         role="외부수요 확인신호(context)",
         usable_for_industry_signal="조건부 — HS6→KICOX 전수 대응표 확보 시에만",
         reason_or_limitation=("인증키 미보유. 또한 HsSgn(HS 6단위)이 필수 파라미터여서 "
                               "업종 집계에 HS6 전수 열거가 필요하다. 근거 없는 6단위 "
                               "대응은 만들지 않았다"),
         alternative="창원상공회의소 경제동향 보고서의 산단 수출액(단지 총계, 업종 분해 없음)",
         checked_at=CHECKED,
         previous_status='PARTIAL',
         current_status='PARTIAL',
         collection_result='2026-09-19 실제 수집 성공. 확인된 HS6 13개 × 2021.01~2026.06, 창원시 810행. 78회 호출 전부 totalCount 대조 완료',
         failure_reason='업종 전체 집계는 여전히 불가. HsSgn(6자리) 필수인데 HS6 전수목록 API(15049722)에 이 키가 등록되어 있지 않다. 조회기간도 1년 이내 제한',
         stored_at='data/raw/customs/trade/'),
    dict(dataset="한국전력 산업분류별 전력사용량",
         institution="한국전력공사",
         source_url="https://bigdata.kepco.co.kr/cmsmain.do?scode=S01&pcode=000493",
         access_method="전력데이터개방포털 OpenAPI (KEPCO_API_KEY, query parameter apiKey)",
         status="PARTIAL",
         observation_period=("산업분류별 2021-01~2026-06 (66/66개월 전부) · "
                             "업종별 2022-02~2026-06 (53/66개월) · "
                             "고객증감 2021-04~2026-06 (54/66개월, 단위 미확정)"),
         frequency="월",
         geography="시군구(산업분류별=창원시) / 행정구(업종별=창원 5개 구)",
         industry_unit="KSIC 대분류 21종(산업분류별) / 한전 자체 업종 38종(업종별)",
         role="CONTEXT / ACTIVITY (보조·강건성). Triage 판정변수 아님",
         usable_for_industry_signal=(
             "아니오 — 업종별 API 로 KICOX 10업종 대응은 가능하나(등급 B 2 / C 8), "
             "2023Q2~2026Q2 13분기에서 생산·고용 YoY 와의 방향 일치율이 50~55%로 "
             "우연 수준이고 BH-FDR 보정 후 유의 업종이 0/20 이다. 확인신호로 쓰지 않는다"),
         reason_or_limitation=(
             "공간단위가 행정구까지다(산단 경계 아님). 업종별 원자료가 2020-11~2022-01 "
             "15개월 공급측 결손(창원 5개 구 중 2개만 반환)이라 분석기간 앞 5개 분기를 "
             "덮지 못한다. 전력사용량은 조업강도 proxy 일 뿐 생산량이 아니다"),
         alternative="없음(가동률 KICOX 공표치로 대체 불가 — 개념이 다름)",
         stored_at="data/raw/kepco/api/",
         checked_at=CHECKED,
         previous_status='PARTIAL',
         current_status='PARTIAL',
         status_changed_at=DECIDED,
         collection_result=(
             '3종 수집 완료(2026-09-19, 198회 호출·실패 0). 산업분류별 1,386행 '
             '(창원시 × KSIC 대분류 × 66개월 전부), 업종별 8,827행 '
             '(창원 5개 구 × 36업종 × 53개월), 고객증감 3,804행. '
             '엔드포인트·인자는 포털 로그인 후 OPEN API 소개 화면에서 직접 확인했다 '
             '(powerUsage/businessType.do, powerUsage/industryType.do, commonCode.do). '
             '검증: 업종별의 제조업 업종 합계와 산업분류별 KSIC C 제조업이 일치한다 '
             '(수준비 0.994~1.000, YoY 상관 0.994) → crosswalk 제조업 범위 실증 확인. '
             '산출 logs/validation/outputs/kepco_robustness/, data/processed/kepco/'),
         failure_reason=(
             '(1) 업종별 2020-11~2022-01 원자료 결손 — 공급측 문제라 재수집으로 해결되지 '
             '않는다. 업종별 YoY 는 2023Q2 부터만 계산된다. '
             '(2) 고객증감(new/expansion/cancel)은 단위 미확정으로 패널에서 제외. '
             '창원 제조업 고객이 약 6천 호인데 분기 최대값이 365,951 이고 전 항목이 0 인 '
             '분기도 있어 건수로 성립하지 않는다. 고객 수는 powerUsage 의 custCnt 를 쓴다. '
             '(3) 업종 분류체계에 공표 정의·코드표가 없다(official_crosswalk=FALSE).')),
    dict(dataset="KOSIS 고용보험 피보험자·취득·상실",
         institution="고용노동부 / 한국고용정보원 (KOSIS 수록)",
         source_url="https://kosis.kr/openapi/",
         access_method="KOSIS 공유서비스 OpenAPI (KOSIS_API_KEY 필요)",
         status="NOT_AVAILABLE", observation_period="미수집", frequency="월",
         geography="시군구", industry_unit="KSIC",
         role="고용 교차확인(cross-check)",
         usable_for_industry_signal="조건부 — 모집단이 창원시 전역이라 방향 비교만",
         reason_or_limitation=('인증키 없이 호출하면 {"err":"10","errMsg":'
                               '"인증KEY값이 누락되었습니다."} 만 반환(실측 확인)'),
         alternative="고용행정통계(EIS) 화면 조회분 data/raw/eis/ + 창원상의 보고서 업종별 수치",
         checked_at=CHECKED,
         previous_status='NOT_AVAILABLE',
         current_status='PARTIAL',
         collection_result='2026-09-19 인증키로 조회 성공. 다만 고용보험 DB 표가 아니라 사업체노동력조사(지역편) DT_118N_MONA49/59 로 확보 — 창원시 × 제조업 총계 × 반기 입직/이직/빈일자리/종사자 238행',
         failure_reason='고용보험 DB 기반 시군구×산업중분류 피보험자/취득/상실 표는 KOSIS 에 없다. 창원시 지역통계(org 791) 4종은 표는 있으나 OpenAPI 가 err=30 반환',
         stored_at='data/raw/employment_insurance/'),
    # ---------------------------------------------------------- 공개 안 됨
    dict(dataset="고용유지지원금 신청·승인·지급 (지역×업종×월)",
         institution="고용노동부 / 근로복지공단",
         source_url="https://www.data.go.kr (파일·OpenAPI 검색), https://kosis.kr",
         access_method="포털 검색 후 상세페이지 확인",
         status="NOT_AVAILABLE", observation_period="—", frequency="—",
         geography="—", industry_unit="—",
         role="행정 대응 이력 기반 외부 준거 후보",
         usable_for_industry_signal="아니오",
         reason_or_limitation=("검색 결과 지역×업종×월 단위 고용유지지원금 공개자료를 "
                               "찾지 못했다. 근접 자료는 '고용장려금 지원현황(월)'"
                               "(2020년 공표 중단, OpenAPI)과 '장애인 신규고용장려금 "
                               "업종별 지역별'(연 1회, KSIC 대분류)뿐이며 둘 다 "
                               "고용유지지원금이 아니다"),
         alternative="정보공개청구(고용노동부 창원지청) 필요",
         stored_at="—", checked_at=CHECKED),
    dict(dataset="산업단지 입주계약 체결·해지, 휴폐업, 가동/비가동 전환 이벤트",
         institution="한국산업단지공단 / 산업입지정보시스템",
         source_url="https://www.data.go.kr (검색), https://www.industryland.or.kr/",
         access_method="포털 검색 및 사이트 확인",
         status="NOT_AVAILABLE", observation_period="—", frequency="—",
         geography="—", industry_unit="—",
         role="업체 이탈 확인(event)",
         usable_for_industry_signal="아니오",
         reason_or_limitation=("공개된 것은 지자체별 '산업단지 입주기업 현황' 명부 스냅샷뿐이며 "
                               "창원국가산단의 계약해지·휴폐업 이벤트 시계열은 없다. "
                               "KICOX 산업동향의 firms_in/firms_op 증감이 사실상 유일한 "
                               "집계 경로이며 이는 모형 입력과 같은 자료다"),
         alternative="정보공개청구 또는 현장 확인",
         stored_at="—", checked_at=CHECKED),
    dict(dataset="워크넷 구인인원·구인배수 (지역×업종×월)",
         institution="한국고용정보원",
         source_url="https://www.data.go.kr/data/15067938/openapi.do",
         access_method="OpenAPI (인증키 필요)",
         status="NOT_AVAILABLE", observation_period="미수집", frequency="월",
         geography="시군구", industry_unit="KSIC",
         role="채용 감소 vs 이직 증가 구분(후보)",
         usable_for_industry_signal="조건부",
         reason_or_limitation="인증키 미보유. 포털 등록 정보가 2021-04 기준으로 갱신이 불확실",
         alternative="고용보험 취득·상실자 수(KOSIS, 역시 인증키 필요)",
         stored_at="—", checked_at=CHECKED),
    # ---------------------------------------------------------- 받을 수 있으나 부적합
    dict(dataset="한국전력 법정동별 상계거래 전력사용량",
         institution="한국전력공사",
         source_url="https://www.data.go.kr/data/15104908/fileData.do",
         access_method="공공데이터포털 파일데이터 직접 다운로드",
         status="NOT_SUITABLE", observation_period="2025년", frequency="월",
         geography="법정동", industry_unit="없음",
         role="—", usable_for_industry_signal="아니오",
         reason_or_limitation=("포털 제목은 '산업분류별' 이나 실제 제공 파일은 상계거래"
                               "(자가발전 역송) 사용량이며 산업용 전력사용량이 아니다"),
         alternative="한국전력 산업분류별 전력사용량 OpenAPI(인증키 필요)",
         stored_at="—", checked_at=CHECKED),
    dict(dataset="국세청 가동사업자 현황",
         institution="국세청",
         source_url="https://www.data.go.kr/data/15002552/fileData.do",
         access_method="공공데이터포털 파일데이터 직접 다운로드",
         status="NOT_SUITABLE", observation_period="2021-03", frequency="비정기",
         geography="시군구", industry_unit="100대 생활업종",
         role="—", usable_for_industry_signal="아니오",
         reason_or_limitation="제조업 세분이 없고 최신 공표본이 2021-03 이다",
         alternative="없음", stored_at="—", checked_at=CHECKED),
    dict(dataset="산업연구원 국내 제조업 경기실사",
         institution="산업연구원",
         source_url="https://www.data.go.kr/data/15161326/fileData.do",
         access_method="공공데이터포털 파일데이터 직접 다운로드",
         status="NOT_SUITABLE", observation_period="2011~2026", frequency="분기",
         geography="—", industry_unit="—",
         role="—", usable_for_industry_signal="아니오",
         reason_or_limitation="제공 파일은 BSI 수치가 아니라 발간물 목록(제목·URL) 메타데이터다",
         alternative="한국은행 ECOS 512Y013(수집 완료)",
         stored_at="—", checked_at=CHECKED),
    # ---------------------------------------------------------- 저장소 기존 자산
    dict(dataset="고용행정통계(EIS) 창원시 고용보험 피보험자",
         institution="고용노동부", source_url="https://eis.work.go.kr/",
         access_method="화면 조회 결과 수동 저장(공개 API·일괄 다운로드 경로 없음)",
         status="PARTIAL", observation_period="2022Q1~2026Q2", frequency="분기(분기말 월)",
         geography="창원시 5개 구", industry_unit="제조업 총계(업종 분해 없음)",
         role="고용 교차확인(cross-check) — 총계 방향",
         usable_for_industry_signal="아니오 — 업종 분해 없음, 모집단 상이",
         reason_or_limitation="산단이 아닌 창원시 전역. 업종별 값이 없어 총계 방향만 비교",
         alternative="창원상의 보고서 업종별 고용보험 수치(3개 업종)",
         stored_at="data/raw/eis/", checked_at=CHECKED),
    dict(dataset="창원상공회의소 경제동향 수록 업종별 고용보험 피보험자",
         institution="창원상공회의소(원자료: 고용노동부 고용보험DB)",
         source_url="https://changwoncci.korcham.net/",
         access_method="보고서 PDF 수록 표 전사(저장소 기존 자산)",
         status="PARTIAL", observation_period="2022Q2~2026Q1(결측 분기 있음)",
         frequency="분기", geography="창원시 전역",
         industry_unit="기계·장비 / 전기장비 / 자동차·부품 3개",
         role="고용 교차확인(cross-check) — 업종 방향",
         usable_for_industry_signal="제한적 — 매핑 B(기계) / C(전기전자·운송장비)",
         reason_or_limitation="3개 업종만, 12개 분기만 수록. 모집단이 창원시 전역",
         alternative="KOSIS 고용보험 통계(인증키 필요)",
         stored_at="data/raw/changwon_chamber/", checked_at=CHECKED),
]


NEW_ROWS = [
    dict(dataset="고용보험 업종별 flow (피보험자 취득·상실, 시군구×산업중분류×월)",
         institution="고용노동부 / 한국고용정보원",
         source_url="https://kosis.kr/openapi/, https://eis.work.go.kr/",
         access_method="KOSIS OpenAPI 통계표 검색 (KOSIS_API_KEY)",
         previous_status="NOT_AVAILABLE", current_status="NOT_AVAILABLE",
         collection_result="미수집 — 자동수집 중단",
         failure_reason=("고용노동부(118) 통계표 17종에 해당 표 없음. 창원시 지역통계(791) "
                         "4종은 표는 존재하나 OpenAPI 가 err=30(데이터 없음) 반환. "
                         "**공개 통계의 구조적 부재로 판단해 자동수집을 중단한다(2026-09-19).** "
                         "확보한 flow 는 사업체노동력조사(제조업 총계·반기)뿐이다."),
         observation_period="—", frequency="—",
         geography="—", industry_unit="—",
         role="FLOW_INTERPRETATION (업종 단위는 불가)",
         usable_for_industry_signal="아니오",
         reason_or_limitation="업종 단위 고용 flow 는 현재 공개 경로가 없다",
         alternative="사업체노동력조사(지역편) 제조업 총계 — 이미 수집",
         stored_at="—", checked_at=DECIDED),
    dict(dataset="워크넷/고용24 개별 채용공고 API",
         institution="한국고용정보원",
         source_url="https://www.data.go.kr (고용24 채용정보 API)",
         access_method="OpenAPI",
         previous_status="NOT_AVAILABLE", current_status="NOT_SUITABLE",
         status_changed_at=DECIDED,
         collection_result="수집하지 않음 — 최종모형에서 제외 결정",
         failure_reason=("개별 채용공고는 게시 시점의 공고 단위 자료라, 업종×분기 "
                         "구인수요 시계열과 모집단·집계단위가 다르다. 과거 구인수요를 "
                         "복원할 수 없고 공고 등록 행태에 좌우된다. "
                         "**이번 최종모형에 추가하지 않는다(2026-09-19 결정).**"),
         observation_period="—", frequency="공고 등록 시점", geography="사업장 소재지",
         industry_unit="공고별 업종 태그",
         role="—", usable_for_industry_signal="아니오",
         reason_or_limitation="역사적 업종×분기 구인수요와 모집단 불일치",
         alternative="사업체노동력조사 빈일자리(이미 수집, 창원시 제조업 총계·반기)",
         stored_at="—", checked_at=DECIDED),
    dict(dataset="관세청_HS부호 / HSK별 신성질별·성질별 분류 (HS6 모집단 기준자료)",
         institution="관세청",
         source_url="https://www.data.go.kr/data/15049722/fileData.do, .../15049720/",
         access_method="공공데이터포털 원문파일등록 다운로드(인증키 불필요)",
         previous_status="NOT_AVAILABLE", current_status="AVAILABLE",
         status_changed_at=DECIDED,
         collection_result=("XLSX 2종 수집(1.4MB + 2.6MB). 유효 HS6 5,613개 추출, "
                            "그중 귀속 근거가 있는 류 1,248개를 모집단으로 확정"),
         failure_reason="",
         observation_period="2026-01-01 적용본", frequency="연 1회 갱신",
         geography="해당없음(코드 체계)", industry_unit="HS 10/6/2단위 + 관세청 성질분류",
         role="REFERENCE / CODE_UNIVERSE",
         usable_for_industry_signal="간접 — 수출입 집계의 업종 대응 근거",
         reason_or_limitation=("신성질별 분류는 용도별(소비재/원자재/자본재)이라 업종 "
                               "대응 근거로 쓰지 않았다. 류(2단위)와 공표 품명만 사용"),
         alternative="없음", stored_at="data/raw/customs/reference/",
         checked_at=DECIDED),
    dict(dataset="고용노동부 사업체노동력조사(지역편) — 창원시 입직·이직·빈일자리·종사자",
         institution="고용노동부 (KOSIS 수록)",
         source_url="https://kosis.kr/statHtml/statHtml.do?orgId=118&tblId=DT_118N_MONA59",
         access_method="KOSIS OpenAPI statisticsParameterData.do (KOSIS_API_KEY)",
         previous_status="NOT_AVAILABLE", current_status="AVAILABLE",
         status_changed_at=RECHECKED,
         collection_result="238행 수집. 2018상~2026상 반기, 결측 반기 없음",
         failure_reason="",
         observation_period="2018상~2026상", frequency="반기",
         geography="경상남도 창원시(시군구) — 창원국가산단 아님",
         industry_unit="산업 대분류 5구분. 제조업이 한 덩어리(광업.제조업 BC)",
         role="FLOW_INTERPRETATION",
         usable_for_industry_signal="아니오 — 업종 분해 불가(매핑등급 D). 제조업 총계 배경으로만",
         reason_or_limitation="표본조사(RSE 동반). 반기 빈도. 업종별 분해 없음",
         alternative="없음(고용보험 DB 기반 시군구×산업 표가 KOSIS 에 없음)",
         stored_at="data/raw/employment_insurance/", checked_at=RECHECKED),
    dict(dataset="관세청 시군구별 품목별 수출입실적 — 창원시 확인 HS6 13개",
         institution="관세청",
         source_url="https://www.data.go.kr/data/15134343/openapi.do",
         access_method="OpenAPI (DATA_GO_KR_SERVICE_KEY, Encoding 형태 그대로 전달)",
         previous_status="NOT_AVAILABLE(실수집)", current_status="PARTIAL",
         status_changed_at=RECHECKED,
         collection_result="810행 수집. 2021.01~2026.06 월별. 78회 호출 pagination 전부 검증",
         failure_reason="업종 전체 커버리지 불가(HS6 전수목록 API 미등록)",
         observation_period="2021.01~2026.06", frequency="월",
         geography="경상남도 창원시 — 창원국가산단 아님",
         industry_unit="HS 6단위 → KICOX 4업종(기계·운송장비·전기전자·철강)",
         role="CONTEXT / EXTERNAL_DEMAND",
         usable_for_industry_signal="제한적 — 확인된 품목 합계이며 업종 수출 총액이 아니다",
         reason_or_limitation="partial_item_set. 매핑등급 A(87·72·73류) / B(84·85류)",
         alternative="창원상의 경제동향의 산단 수출액(단지 총계, 업종 분해 없음)",
         stored_at="data/raw/customs/trade/", checked_at=RECHECKED),
    dict(dataset="한국은행 ECOS 기업경기조사 — 경남 지역별 + 전국 업종별 BSI",
         institution="한국은행",
         source_url="https://ecos.bok.or.kr/",
         access_method="ECOS OpenAPI StatisticSearch (ECOS_API_KEY)",
         previous_status="PARTIAL(전국 제조업만)", current_status="AVAILABLE",
         status_changed_at=RECHECKED,
         collection_result=("6,460행 수집. 512Y019 경남 340행 + 512Y007 전국 업종별 6,120행, "
                            "2021.01~2026.08 월별. 95회 호출 전부 list_total_count 대조"),
         failure_reason="창원 단위 BSI 는 ECOS 에 존재하지 않음",
         observation_period="2021.01~2026.08", frequency="월",
         geography="경상남도(512Y019) / 전국(512Y007)",
         industry_unit="512Y019 제조업 총계 / 512Y007 KSIC 중분류 18종",
         role="CONTEXT / BUSINESS_SENTIMENT",
         usable_for_industry_signal="아니오 — 업종별 자동판정 금지. 거시 배경으로만",
         reason_or_limitation=("경남 계열은 업종 세분 없음, 업종 세분 계열은 전국. "
                               "경남 업황BSI 는 관측 전 기간 100 미만이라 행 단위 변별력이 없다"),
         alternative="없음",
         stored_at="data/raw/ecos/api/", checked_at=RECHECKED),
    dict(dataset="워크넷/고용24 구인인원·구인배수, 고용장려금(월), KICOX 공장등록 통계",
         institution="한국고용정보원 / 한국산업단지공단",
         source_url="https://www.data.go.kr/data/15067938/openapi.do 외",
         access_method="OpenAPI 재시도 (DATA_GO_KR_SERVICE_KEY)",
         previous_status="NOT_AVAILABLE", current_status="NOT_AVAILABLE",
         collection_result="미수집",
         failure_reason=("인증키는 확보했으나 해당 상세페이지에 기계판독 가능한 엔드포인트 "
                         "명세(swagger host/paths)가 없다. 키도 이 API 들에 등록되어 있지 않다. "
                         "추정 endpoint 로 호출하지 않았다"),
         observation_period="—", frequency="—", geography="—", industry_unit="—",
         role="—", usable_for_industry_signal="아니오",
         reason_or_limitation="포털 명세 부재 + API 별 활용신청 필요",
         alternative="KOSIS 구인배수(시도) DT_1YL1101 — 시도 단위라 산단 해석에 부적합",
         stored_at="—", checked_at=RECHECKED),
    dict(dataset="고용유지지원금 (KOSIS 재검색)",
         institution="고용노동부",
         source_url="https://kosis.kr/openapi/",
         access_method="KOSIS OpenAPI 통계표 검색 (KOSIS_API_KEY)",
         previous_status="NOT_AVAILABLE", current_status="NOT_AVAILABLE",
         collection_result="미수집",
         failure_reason=("인증키로 KOSIS 를 재검색했으나 '고용유지지원금' 검색 결과는 전부 "
                         "한국장애인고용공단의 설문 통계였다. 지역×업종×기간 지원금 통계표 없음. "
                         "**공개 통계의 구조적 부재로 판단해 자동수집을 중단한다(2026-09-19). "
                         "재개 조건은 정보공개청구 결과 확보뿐이다.**"),
         observation_period="—", frequency="—", geography="—", industry_unit="—",
         role="EXTERNAL_REFERENCE_CANDIDATE",
         usable_for_industry_signal="아니오",
         reason_or_limitation="공개 통계표 부재 — 인증키로도 해소되지 않음",
         alternative="정보공개청구(고용노동부 창원지청)",
         stored_at="—", checked_at=RECHECKED),
]


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = ROWS + NEW_ROWS
    for r in rows:
        # 과거 표에는 status 하나뿐이었다. 재판정 결과가 없으면 그대로 이어받는다.
        r.setdefault("previous_status", r.get("status", ""))
        r.setdefault("current_status", r.get("status", ""))
        r.setdefault("status_changed_at",
                     RECHECKED if r["previous_status"] != r["current_status"] else "")
        r.setdefault("collection_result", "")
        r.setdefault("failure_reason", "")
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLS})
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["current_status"]] = counts.get(r["current_status"], 0) + 1
    changed = [r for r in rows if r["previous_status"] != r["current_status"]]
    print(f"[ok] {OUT.relative_to(ROOT)} ({len(rows)} rows, 상태변경 {len(changed)}건)")
    for r in changed:
        print(f"     {r['previous_status']:<14} -> {r['current_status']:<14} {r['dataset'][:52]}")
    for k in ("AVAILABLE", "PARTIAL", "NOT_AVAILABLE", "NOT_SUITABLE"):
        print(f"     {k:15s} {counts.get(k, 0)}")


if __name__ == "__main__":
    main()
