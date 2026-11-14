# -*- coding: utf-8 -*-
"""업종 크로스워크 CSV 생성 (data/processed/final_model/reference/industry_crosswalk/).

대응 관계는 사람이 판단해 이 파일에 근거와 함께 적는다. 자동 문자열 유사도
매칭을 쓰지 않는다. PPI 대응만은 이미 확정된
`data/processed/ppi/ppi_industry_mapping_resolved.csv` 를 그대로 옮긴다.

실행:  python src/evidence/build_industry_crosswalk.py
"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/processed/final_model/reference/industry_crosswalk"
COLS = ["source_scheme", "source_category", "source_code", "target_kicox_industry",
        "mapping_type", "mapping_confidence", "rationale", "source"]

CCI = ("창원상공회의소 『창원지역 경제동향』 수록 고용보험DB 업종 표기 "
       "(data/raw/changwon_chamber/창원시_업종별_고용보험피보험자_동향.csv)")
EIS = ("고용노동부 고용행정통계 산업 대분류 "
       "(data/raw/eis/eis_changwon_insured_2022M03_2026M06.csv)")

EMPLOYMENT_INSURANCE = [
    ("고용보험 산업분류", "기계·장비", "", "기계", "approximate", "B",
     "KSIC 29(기타 기계 및 장비)에 해당. KICOX '기계'는 29 중심이나 금속가공(25) 일부를 "
     "포함할 수 있어 범위가 한쪽으로 넓다. 방향 비교까지만 사용", CCI),
    ("고용보험 산업분류", "전기장비", "", "전기전자", "ambiguous", "C",
     "KSIC 28(전기장비)만 해당. KICOX '전기전자'는 26(전자부품·컴퓨터·영상·통신)과 "
     "27(의료·정밀·광학)도 포함해 부분포함이다. 단정형 신호 생성 금지", CCI),
    ("고용보험 산업분류", "자동차·부품", "", "운송장비", "ambiguous", "C",
     "KSIC 30(자동차·트레일러)만 해당. KICOX '운송장비'는 31(기타 운송장비: 조선·항공 등)을 "
     "포함하며 창원에는 31 비중이 작지 않다. 부분포함", CCI),
    ("고용보험 산업분류", "제조업", "C", "해당없음(제조업 총계)", "approximate", "B",
     "KICOX 10업종 합계(산단 제조업)와 개념은 같으나 모집단이 창원시 전역이다. "
     "업종별로 배분하지 않고 총계 방향 비교에만 사용", EIS),
    ("고용보험 산업분류", "서비스업", "", "해당없음", "unavailable", "D",
     "산단 제조업 10업종에 대응 항목 없음", CCI),
    ("고용보험 산업분류", "건설업", "F", "해당없음", "unavailable", "D",
     "산단 제조업 10업종에 대응 항목 없음", CCI),
    ("고용보험 산업분류", "전체", "", "해당없음", "unavailable", "D",
     "전산업 총계. 제조업 업종 해석에 쓰지 않는다", CCI),
]

KSIC_SRC = "통계청 한국표준산업분류(KSIC) 제10차·제11차 중분류"
KSIC = [
    ("KSIC 중분류", "식료품 제조업", "10", "음식료", "direct", "A", "음료(11)와 함께 '음식료'에 대응", KSIC_SRC),
    ("KSIC 중분류", "음료 제조업", "11", "음식료", "direct", "A", "식료품(10)과 함께 '음식료'에 대응", KSIC_SRC),
    ("KSIC 중분류", "섬유제품 제조업(의복 제외)", "13", "섬유의복", "direct", "A", "의복(14)과 함께 대응", KSIC_SRC),
    ("KSIC 중분류", "의복·의복액세서리 및 모피제품 제조업", "14", "섬유의복", "direct", "A", "섬유(13)와 함께 대응", KSIC_SRC),
    ("KSIC 중분류", "가죽·가방 및 신발 제조업", "15", "섬유의복", "approximate", "B",
     "KICOX '섬유의복' 범위에 가죽이 포함되는지 공표 정의로 확정 불가. 부분포함 가능", KSIC_SRC),
    ("KSIC 중분류", "목재 및 나무제품 제조업(가구 제외)", "16", "목재종이", "direct", "A", "펄프·종이(17)와 함께 대응", KSIC_SRC),
    ("KSIC 중분류", "펄프·종이 및 종이제품 제조업", "17", "목재종이", "direct", "A", "목재(16)와 함께 대응", KSIC_SRC),
    ("KSIC 중분류", "인쇄 및 기록매체 복제업", "18", "목재종이", "ambiguous", "C",
     "KICOX '목재종이'에 인쇄가 포함되는지 불확실", KSIC_SRC),
    ("KSIC 중분류", "코크스·연탄 및 석유정제품 제조업", "19", "석유화학", "direct", "A", "화학(20)과 함께 대응", KSIC_SRC),
    ("KSIC 중분류", "화학물질 및 화학제품 제조업(의약품 제외)", "20", "석유화학", "direct", "A", "석유정제(19)와 함께 대응", KSIC_SRC),
    ("KSIC 중분류", "의료용 물질 및 의약품 제조업", "21", "석유화학", "ambiguous", "C",
     "의약품이 '석유화학'에 포함되는지 불확실", KSIC_SRC),
    ("KSIC 중분류", "고무 및 플라스틱제품 제조업", "22", "석유화학", "approximate", "B",
     "관행상 화학계열로 묶이나 KICOX 공표 정의로 확정 불가", KSIC_SRC),
    ("KSIC 중분류", "비금속 광물제품 제조업", "23", "비금속", "direct", "A", "명칭·범위 직접 대응", KSIC_SRC),
    ("KSIC 중분류", "1차 금속 제조업", "24", "철강", "approximate", "B",
     "24는 비철금속도 포함해 '철강'보다 범위가 넓다", KSIC_SRC),
    ("KSIC 중분류", "금속가공제품 제조업(기계·가구 제외)", "25", "기계", "ambiguous", "C",
     "KICOX 에서 금속가공이 '철강'과 '기계' 중 어디로 집계되는지 공표 정의로 확정 불가", KSIC_SRC),
    ("KSIC 중분류", "전자부품·컴퓨터·영상·음향·통신장비 제조업", "26", "전기전자", "direct", "A", "28과 함께 대응", KSIC_SRC),
    ("KSIC 중분류", "의료·정밀·광학기기 및 시계 제조업", "27", "전기전자", "approximate", "B",
     "KICOX '전기전자'에 포함되는 것으로 보이나 의료기기 범위가 불확실", KSIC_SRC),
    ("KSIC 중분류", "전기장비 제조업", "28", "전기전자", "direct", "A", "26과 함께 대응", KSIC_SRC),
    ("KSIC 중분류", "기타 기계 및 장비 제조업", "29", "기계", "direct", "A", "KICOX '기계'의 중심 범위", KSIC_SRC),
    ("KSIC 중분류", "자동차 및 트레일러 제조업", "30", "운송장비", "direct", "A", "31과 함께 대응", KSIC_SRC),
    ("KSIC 중분류", "기타 운송장비 제조업", "31", "운송장비", "direct", "A", "30과 함께 대응", KSIC_SRC),
    ("KSIC 중분류", "가구 제조업", "32", "기타", "ambiguous", "C", "KICOX '기타' 구성 미공표", KSIC_SRC),
    ("KSIC 중분류", "기타 제품 제조업", "33", "기타", "ambiguous", "C", "KICOX '기타' 구성 미공표", KSIC_SRC),
]

HS_SRC = "관세청 HS 부호(류 2단위). 관세청 시군구별 품목별 수출입실적 API 는 HS 6단위를 요구한다"
HS = [
    ("HS 류(2단위)", "곡물·육·수산·조제식료품 등", "01-24", "음식료", "approximate", "B",
     "식품류 전반. 6단위 열거가 필요해 자동 집계는 부분적", HS_SRC),
    ("HS 류(2단위)", "방직용 섬유·의류", "50-63", "섬유의복", "approximate", "B",
     "섬유·의류 전반", HS_SRC),
    ("HS 류(2단위)", "목재·펄프·지류", "44-49", "목재종이", "approximate", "B", "목재·종이 전반", HS_SRC),
    ("HS 류(2단위)", "광물성 연료·화학공업 생산품·플라스틱·고무", "27-40", "석유화학", "approximate", "B",
     "석유정제·화학·플라스틱·고무 전반", HS_SRC),
    ("HS 류(2단위)", "토석류·도자·유리", "68-70", "비금속", "approximate", "B", "비금속광물 전반", HS_SRC),
    ("HS 류(2단위)", "철강 및 철강제품", "72-73", "철강", "direct", "A", "철강 직접 대응", HS_SRC),
    ("HS 류(2단위)", "비철금속(구리·알루미늄 등)", "74-81", "철강", "ambiguous", "C",
     "KICOX '철강'이 비철을 포함하는지 불확실. 억지로 배정하지 않는다", HS_SRC),
    ("HS 류(2단위)", "원자로·보일러·기계류", "84", "기계", "approximate", "B",
     "84는 전산기기(8471 등)를 포함해 '전기전자'와 겹친다. 6단위 분리 필요", HS_SRC),
    ("HS 류(2단위)", "전기기기·음향영상기기", "85", "전기전자", "approximate", "B",
     "85 전반이 전기전자에 대응", HS_SRC),
    ("HS 류(2단위)", "철도차량", "86", "운송장비", "direct", "A", "기타 운송장비", HS_SRC),
    ("HS 류(2단위)", "자동차 및 부품", "87", "운송장비", "direct", "A", "자동차·부품", HS_SRC),
    ("HS 류(2단위)", "항공기", "88", "운송장비", "direct", "A", "기타 운송장비", HS_SRC),
    ("HS 류(2단위)", "선박", "89", "운송장비", "direct", "A", "기타 운송장비(조선)", HS_SRC),
    ("HS 류(2단위)", "광학·의료·정밀기기", "90", "전기전자", "ambiguous", "C",
     "KSIC 27 대응 여부가 불확실한 것과 같은 이유", HS_SRC),
    ("HS 류(2단위)", "가구·완구·잡품", "94-96", "기타", "ambiguous", "C", "KICOX '기타' 구성 미공표", HS_SRC),
]


ECOS_SRC = ("한국은행 ECOS 512Y007 업종별 기업경기실사지수 업종코드 "
            "(KSIC 중분류 기반). 전국 단위 심리지수")
ECOS_BSI = [
    ("ECOS 업종코드", "식료품", "C1000", "음식료", "direct", "A",
     "KSIC 10 식료품. 음료(C1100)와 함께 '음식료'를 구성", ECOS_SRC),
    ("ECOS 업종코드", "음료", "C1100", "음식료", "direct", "A",
     "KSIC 11 음료. 식료품(C1000)과 함께 대응", ECOS_SRC),
    ("ECOS 업종코드", "섬유", "C1300", "섬유의복", "direct", "A",
     "KSIC 13 섬유. 의복모피(C1400)와 함께 대응", ECOS_SRC),
    ("ECOS 업종코드", "의복모피", "C1400", "섬유의복", "direct", "A",
     "KSIC 14 의복. 섬유(C1300)와 함께 대응", ECOS_SRC),
    ("ECOS 업종코드", "목재·나무", "C1600", "목재종이", "direct", "A",
     "KSIC 16 목재. 펄프·종이(C1700)와 함께 대응", ECOS_SRC),
    ("ECOS 업종코드", "펄프·종이", "C1700", "목재종이", "direct", "A",
     "KSIC 17 펄프·종이. 목재(C1600)와 함께 대응", ECOS_SRC),
    ("ECOS 업종코드", "석유정제·코크스", "C1900", "석유화학", "direct", "A",
     "KSIC 19 석유정제. 화학(C2000)과 함께 대응", ECOS_SRC),
    ("ECOS 업종코드", "화학물질·제품", "C2000", "석유화학", "direct", "A",
     "KSIC 20 화학. 석유정제(C1900)와 함께 대응", ECOS_SRC),
    ("ECOS 업종코드", "고무·플라스틱", "C2200", "석유화학", "approximate", "B",
     "KSIC 22. 관행상 화학계열이나 KICOX 공표 정의로 확정 불가", ECOS_SRC),
    ("ECOS 업종코드", "비금속광물", "C2300", "비금속", "direct", "A",
     "KSIC 23. 명칭·범위 직접 대응", ECOS_SRC),
    ("ECOS 업종코드", "1차금속", "C2400", "철강", "approximate", "B",
     "KSIC 24 는 비철금속도 포함해 '철강'보다 범위가 넓다", ECOS_SRC),
    ("ECOS 업종코드", "금속가공", "C2500", "기계", "ambiguous", "C",
     "KSIC 25 가 KICOX 에서 '철강'과 '기계' 중 어디로 집계되는지 확정 불가", ECOS_SRC),
    ("ECOS 업종코드", "전자·영상·통신장비", "C2600", "전기전자", "direct", "A",
     "KSIC 26. 전기장비(C2800)와 함께 대응", ECOS_SRC),
    ("ECOS 업종코드", "전기장비", "C2800", "전기전자", "direct", "A",
     "KSIC 28. 전자·영상·통신(C2600)과 함께 대응", ECOS_SRC),
    ("ECOS 업종코드", "기타기계·장비", "C2900", "기계", "direct", "A",
     "KSIC 29. KICOX '기계'의 중심 범위", ECOS_SRC),
    ("ECOS 업종코드", "자동차", "C3000", "운송장비", "direct", "A",
     "KSIC 30. 조선·기타운수(C3100)와 함께 대응", ECOS_SRC),
    ("ECOS 업종코드", "조선·기타운수", "C3100", "운송장비", "direct", "A",
     "KSIC 31. 자동차(C3000)와 함께 대응", ECOS_SRC),
    ("ECOS 업종코드", "제조업", "C0000", "해당없음(제조업 총계)", "approximate", "B",
     "업종 배분 금지. 제조업 총계 맥락으로만 사용", ECOS_SRC),
]

LFS_SRC = ("고용노동부 사업체노동력조사(지역편) DT_118N_MONA49/59 산업 대분류 "
           "(data/raw/employment_insurance/)")
LABOR_FLOW = [
    ("사업체노동력조사 산업분류", "광업.제조업(BC)", "IND201701", "해당없음(제조업 총계)",
     "unavailable", "D",
     "제조업이 한 덩어리라 KICOX 10업종으로 나눌 수 없다. 총계 방향 비교에만 사용", LFS_SRC),
    ("사업체노동력조사 산업분류", "전산업", "IND201700", "해당없음", "unavailable", "D",
     "전산업 총계. 제조업 업종 해석에 쓰지 않는다", LFS_SRC),
]

HS6_SRC = ("관세청 시군구별 품목별 수출입실적 API 응답으로 존재를 확인한 HS 6단위 "
           "(data/raw/customs/trade/)")
HS6_VERIFIED = [
    ("HS 6단위", "승용차", "870323", "운송장비", "direct", "A", "HS 87류 자동차", HS6_SRC),
    ("HS 6단위", "기어박스와 부분품", "870840", "운송장비", "direct", "A", "HS 87류 자동차 부품", HS6_SRC),
    ("HS 6단위", "자동차부품 기타", "870899", "운송장비", "direct", "A", "HS 87류 자동차 부품", HS6_SRC),
    ("HS 6단위", "도금 평판압연제품", "721049", "철강", "direct", "A", "HS 72류 철강", HS6_SRC),
    ("HS 6단위", "철구조물 기타", "730890", "철강", "direct", "A", "HS 73류 철강제품", HS6_SRC),
    ("HS 6단위", "펌프 기타", "841319", "기계", "approximate", "B",
     "HS 84류. 84류는 전산기기(8471 등)도 포함해 류 단위로는 범위가 넓다", HS6_SRC),
    ("HS 6단위", "잭·호이스트", "842542", "기계", "approximate", "B", "HS 84류 기계", HS6_SRC),
    ("HS 6단위", "선반 기타", "845819", "기계", "approximate", "B", "HS 84류 기계", HS6_SRC),
    ("HS 6단위", "기타 기계류", "847989", "기계", "approximate", "B", "HS 84류 기계", HS6_SRC),
    ("HS 6단위", "밸브 기타", "848180", "기계", "approximate", "B", "HS 84류 기계", HS6_SRC),
    ("HS 6단위", "정지형 변환기", "850440", "전기전자", "approximate", "B", "HS 85류 전기기기", HS6_SRC),
    ("HS 6단위", "개폐기기 기타", "853690", "전기전자", "approximate", "B", "HS 85류 전기기기", HS6_SRC),
    ("HS 6단위", "전선 기타", "854449", "전기전자", "approximate", "B", "HS 85류 전기기기", HS6_SRC),
]

# --------------------------------------------------------------- KEPCO 업종
# 한국전력 『업종별 전력사용량』 API(`powerUsage/businessType.do`)가 쓰는 업종명이다.
#
# **공식 대응표가 존재하지 않는다.** 포털 `commonCode.do` 는 시도·시군구·계약종별·
# 산업분류(KSIC 대분류)·발전원·복지할인 코드는 주지만 **업종(bizType) 코드표는 주지
# 않는다**(`codeTy=bizTypeCd|bizType|busiCd` 모두 404). API 가이드도 "업종명
# (ex: 1차 금속, 가구및기타)" 이라고만 적는다. 그래서 `official_crosswalk = FALSE` 다.
#
# 다만 근거 없는 키워드 매칭은 아니다. 36개 업종명을 KSIC 중분류와 대조하면
# 제조업 구간(10~33)이 **명칭 단위로 거의 1:1** 대응한다 — 식료품제조=10,
# 섬 유=13, 1차 금속=24, 기타 기계=29, 자 동 차=30 … 즉 KEPCO 업종은 KSIC 중분류의
# 축약 표기로 보인다. 예외는 세 가지뿐이다.
#     · KSIC 21(의약품) 에 대응하는 업종이 없다
#     · KSIC 23(비금속광물제품) 이 '유 리'·'시 멘 트' 둘로 쪼개져 있다(부분포함)
#     · KSIC 26 이 '영상. 음향'·'사무 기기' 둘로, KSIC 32+33 이 '가구및기타' 하나로
# 그래서 **KEPCO 업종명 → KSIC 중분류 → KICOX** 2단계로 잇고,
# 2단계째는 위 `KSIC` 표(공표 분류 기준)를 그대로 쓴다.
#
# 등급 규칙(기계적으로 적용한다)
#     원 분류체계가 공표 정의를 갖지 않으므로 `ksic_to_kicox` 등급에서 **한 단계
#     내린다**(A→B, B→C, C→C). 분할·병합이 일어난 업종은 부분포함이므로 C 로 둔다.
#     비제조(농림어업·광업·수도·재생재료)와 용도 구분(가정용부문·순수써비스·
#     관공용·국군용·유엔군용·기타공공용·사업자용·전철)은 KICOX 10업종에 대응
#     항목이 없다 → D. 억지로 배정하지 않는다.
#
# 주의: 이 38업종 목록은 순수한 산업분류가 아니다. 제조업 세분류와 용도별
# 계약 구분이 **섞여 있다**. 그래서 '업종 합계 = 창원 전력 총량' 으로 읽으면 안 된다.
KEPCO_SRC = ("한국전력공사 전력데이터 개방포털 『업종별 전력사용량』 API 응답의 bizType 값 "
             "(https://bigdata.kepco.co.kr/openapi/v1/powerUsage/businessType.do). "
             "공표된 업종 정의·코드표 없음")
KEPCO_VIA = "KEPCO 업종명 → KSIC 중분류 {ksic} → KICOX (ksic_to_kicox.csv 경유)"
KEPCO_COLS = COLS + ["official_crosswalk", "note"]

# (업종명, KSIC 중분류, KICOX, mapping_type, 등급, 근거보강, 비고)
KEPCO_BIZTYPE = [
    ("식료품제조", "10", "음식료", "approximate", "B", "", ""),
    ("음료품제조", "11", "음식료", "approximate", "B", "", ""),
    ("담배제조업", "12", "해당없음", "unavailable", "D",
     "KICOX 10업종에 담배 대응 항목이 없다", "창원 관측치 없음"),
    ("섬 유", "13", "섬유의복", "approximate", "B", "", ""),
    ("의복. 모피", "14", "섬유의복", "approximate", "B", "", ""),
    ("가죽. 신발", "15", "섬유의복", "ambiguous", "C",
     "KSIC 15 가 KICOX '섬유의복' 에 포함되는지 공표 정의로 확정 불가", ""),
    ("목재. 나무", "16", "목재종이", "approximate", "B", "", ""),
    ("펄프. 종이", "17", "목재종이", "approximate", "B", "", ""),
    ("출판. 인쇄", "18", "목재종이", "ambiguous", "C",
     "KICOX '목재종이' 에 인쇄가 포함되는지 불확실", ""),
    ("석유 정제", "19", "석유화학", "approximate", "B", "", ""),
    ("화학 제품", "20", "석유화학", "approximate", "B", "", ""),
    ("고무. 플라", "22", "석유화학", "ambiguous", "C",
     "관행상 화학계열이나 KICOX 공표 정의로 확정 불가", ""),
    ("유 리", "23", "비금속", "ambiguous", "C",
     "KSIC 23(비금속광물제품)의 일부만 담는다 — 도자기·콘크리트 등이 빠진다", "부분포함"),
    ("시 멘 트", "23", "비금속", "ambiguous", "C",
     "KSIC 23 의 일부만 담는다. '유 리' 와 합쳐도 23 전체가 되는지 확정 불가", "부분포함"),
    ("1차 금속", "24", "철강", "ambiguous", "C",
     "KSIC 24 는 비철금속도 포함해 '철강' 보다 범위가 넓다", ""),
    ("조립 금속", "25", "기계", "ambiguous", "C",
     "KICOX 에서 금속가공이 '철강'과 '기계' 중 어디로 집계되는지 확정 불가", ""),
    ("영상. 음향", "26", "전기전자", "ambiguous", "C",
     "KSIC 26 이 '영상. 음향'·'사무 기기' 둘로 쪼개져 있다", "부분포함"),
    ("사무 기기", "26", "전기전자", "ambiguous", "C",
     "KSIC 26 의 컴퓨터·사무기기 부분", "부분포함"),
    ("의료. 광학", "27", "전기전자", "ambiguous", "C",
     "KICOX '전기전자' 에 포함되는 것으로 보이나 의료기기 범위가 불확실", ""),
    ("전기 기기", "28", "전기전자", "approximate", "B", "", ""),
    ("기타 기계", "29", "기계", "approximate", "B", "", ""),
    ("자 동 차", "30", "운송장비", "approximate", "B", "", ""),
    ("기타 운송", "31", "운송장비", "approximate", "B", "", ""),
    ("가구및기타", "32+33", "기타", "ambiguous", "C",
     "KSIC 32(가구)+33(기타제품) 병합. KICOX '기타' 구성 미공표", "병합"),
    # ---- KICOX 10업종에 대응 항목이 없는 업종 (강제 배정하지 않는다)
    ("농업. 임업", "A", "해당없음", "unavailable", "D", "제조업이 아니다", ""),
    ("어 업", "A", "해당없음", "unavailable", "D", "제조업이 아니다", ""),
    ("석탄. 원유", "B", "해당없음", "unavailable", "D", "광업이다", ""),
    ("금속비금속", "B", "해당없음", "unavailable", "D",
     "목록상 '석탄. 원유' 바로 뒤, '식료품제조' 앞에 놓인 광업 항목이다. "
     "제조업의 금속·비금속이 아니다", "명칭이 제조업과 혼동되기 쉽다"),
    ("수 도", "D/E", "해당없음", "unavailable", "D", "수도·환경 부문", ""),
    ("재생 재료", "E", "해당없음", "unavailable", "D", "재생용 재료 수집·가공", ""),
    # ---- 산업이 아니라 용도·계약 구분 (섞여 있다는 점이 이 목록의 핵심 한계다)
    ("가정용부문", "", "해당없음", "unavailable", "D", "용도 구분. 산업분류가 아니다", ""),
    ("순수써비스", "", "해당없음", "unavailable", "D", "용도 구분. 산업분류가 아니다", ""),
    ("사업자 용", "", "해당없음", "unavailable", "D", "용도 구분. 산업분류가 아니다", ""),
    ("관 공 용", "", "해당없음", "unavailable", "D", "용도 구분. 산업분류가 아니다", ""),
    ("국 군 용", "", "해당없음", "unavailable", "D", "용도 구분. 산업분류가 아니다", ""),
    ("유엔군 용", "", "해당없음", "unavailable", "D", "용도 구분. 산업분류가 아니다", ""),
    ("기타공공용", "", "해당없음", "unavailable", "D", "용도 구분. 산업분류가 아니다", ""),
    ("전 철", "", "해당없음", "unavailable", "D", "용도 구분. 산업분류가 아니다", ""),
]


def kepco_rows() -> list[tuple]:
    out = []
    for biz, ksic, kicox, mtype, grade, extra, note in KEPCO_BIZTYPE:
        basis = KEPCO_VIA.format(ksic=ksic) if ksic else "대응 경로 없음"
        if extra:
            basis += ". " + extra
        if grade in ("B", "C") and ksic:
            basis += (". 원 분류체계에 공표 정의가 없어 ksic_to_kicox 등급에서 "
                      "한 단계 내렸다")
        out.append(("KEPCO 업종분류(비공식)", biz, "", kicox, mtype, grade,
                    basis, KEPCO_SRC, "FALSE", note))
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    def write(name: str, rows: list[tuple], cols: list[str] | None = None) -> None:
        p = OUT / name
        with p.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols or COLS)
            w.writerows(rows)
        print(f"[ok] {p.relative_to(ROOT)} ({len(rows)} rows)")

    write("employment_insurance_to_kicox.csv", EMPLOYMENT_INSURANCE)
    write("ksic_to_kicox.csv", KSIC)
    write("hs_to_kicox.csv", HS)
    write("hs6_verified_to_kicox.csv", HS6_VERIFIED)
    write("ecos_bsi_to_kicox.csv", ECOS_BSI)
    write("labor_force_survey_to_kicox.csv", LABOR_FLOW)
    write("kepco_biztype_to_kicox.csv", kepco_rows(), KEPCO_COLS)

    # PPI 는 이미 확정된 대응표를 형식만 맞춰 옮긴다.
    src = ROOT / "data/processed/ppi/ppi_industry_mapping_resolved.csv"
    r = pd.read_csv(src)
    r.columns = [c.lstrip("﻿") for c in r.columns]
    rows = [("KOSIS 생산자물가지수 기본분류", x.ppi_item or "", x.ppi_level or "",
             x.kicox_industry,
             {"A": "direct", "B": "approximate", "C": "ambiguous", "D": "unavailable"}[x.grade],
             x.grade, x.basis, f"{src.relative_to(ROOT)} (확정본)")
            for x in r.itertuples()]
    write("ppi_to_kicox.csv", rows)


if __name__ == "__main__":
    main()
