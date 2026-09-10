# ============================================================
# 창원국가산단 생산실적 실질화용 PPI(생산자물가지수, 기본분류) 수집
# 출처: KOSIS OpenAPI (한국은행, 생산자물가조사, tblId=DT_404Y014)
# ============================================================

import requests
import json
import csv

# ------------------------------------------------------------
# 1. 인증키
# ------------------------------------------------------------
API_KEY = "ZmZkZTNhYjY0MGJhMGMyNDk2MzlhNjMxNmE5MzZkZTA="

# ------------------------------------------------------------
# 2. API 호출
# ------------------------------------------------------------
BASE_URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"

params = {
    "method": "getList",
    "apiKey": API_KEY,
    "itmId": "ALL",          # 지수 항목 (안 맞으면 에러 메시지 보고 조정)
    "objL1": "ALL",           # 업종 전체
    "objL2": "",
    "objL3": "",
    "objL4": "",
    "objL5": "",
    "objL6": "",
    "objL7": "",
    "objL8": "",
    "format": "json",
    "jsonVD": "Y",
    "prdSe": "M",             # 월별 (Q=분기, Y=연)
    "newEstPrdCnt": "48",     # 최근 48개월치
    "orgId": "301",           # 한국은행
    "tblId": "DT_404Y014",    # 생산자물가지수(기본분류)
}

print("KOSIS API 호출 중...")
resp = requests.get(BASE_URL, params=params, timeout=30)

print("HTTP 상태 코드:", resp.status_code)
print("응답 앞부분 미리보기:")
print(resp.text[:500])
print("-" * 60)

# ------------------------------------------------------------
# 3. 결과 저장
# ------------------------------------------------------------
try:
    data = resp.json()
except json.JSONDecodeError:
    print("⚠ JSON으로 해석할 수 없는 응답입니다. 위 미리보기를 확인하세요.")
    data = None

if isinstance(data, list) and len(data) > 0:
    keys = data[0].keys()
    with open("ppi_raw.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(data)
    print(f"저장 완료: ppi_raw.csv ({len(data)}행)")
    print("샘플 데이터 (앞 3행):")
    for row in data[:3]:
        print(row)
elif isinstance(data, dict):
    print("⚠ 리스트가 아니라 딕셔너리 형태로 응답이 왔습니다 (보통 에러 메시지):")
    print(json.dumps(data, ensure_ascii=False, indent=2))
else:
    print("⚠ 예상한 형태의 데이터가 아닙니다. 위 응답 내용을 확인하세요.")
