# ============================================================
# KOSIS 통계표(DT_404Y014, 생산자물가지수 기본분류)의
# 실제 사용 가능한 파라미터 값(항목 코드, 분류 코드)을 먼저 확인하는 스크립트
# ============================================================

import requests
import json

API_KEY = "ZmZkZTNhYjY0MGJhMGMyNDk2MzlhNjMxNmE5MzZkZTA="

META_URL = "https://kosis.kr/openapi/statisticsParameterData.do"

params = {
    "method": "getMeta",
    "apiKey": API_KEY,
    "type": "TBL",
    "orgId": "301",
    "tblId": "DT_404Y014",
    "format": "json",
    "jsonVD": "Y",
}

print("메타데이터 조회 중...")
resp = requests.get(META_URL, params=params, timeout=30)
print("HTTP 상태 코드:", resp.status_code)
print("응답 원문:")
print(resp.text[:3000])
