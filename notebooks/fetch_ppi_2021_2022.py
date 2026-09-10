# ============================================================
# 창원국가산단 PPI 보조데이터 - 과거 구간(2021.01~2022.12) 추가 수집
# 기존 notebooks/fetch_ppi.py와 동일한 방식, 기간만 변경
# ============================================================

import requests
import json
import csv
import os

API_KEY = "ZmZkZTNhYjY0MGJhMGMyNDk2MzlhNjMxNmE5MzZkZTA="

BASE_URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"

params = {
    "method": "getList",
    "apiKey": API_KEY,
    "itmId": "13103134604999+",   # 기존과 동일한 항목 코드
    "objL1": "ALL",
    "objL2": "",
    "objL3": "",
    "objL4": "",
    "objL5": "",
    "objL6": "",
    "objL7": "",
    "objL8": "",
    "format": "json",
    "jsonVD": "Y",
    "prdSe": "M",
    "startPrdDe": "202101",   # <- 변경된 부분
    "endPrdDe": "202212",     # <- 변경된 부분
    "orgId": "301",
    "tblId": "DT_404Y014",
}

print("KOSIS API 호출 중 (2021.01 ~ 2022.12)...")
resp = requests.get(BASE_URL, params=params, timeout=30)

print("HTTP 상태 코드:", resp.status_code)
print("응답 앞부분 미리보기:")
print(resp.text[:500])
print("-" * 60)

try:
    data = resp.json()
except json.JSONDecodeError:
    print("⚠ JSON으로 해석할 수 없는 응답입니다. 위 미리보기를 확인하세요.")
    data = None

if isinstance(data, list) and len(data) > 0:
    keys = data[0].keys()
    save_path = os.path.join(os.getcwd(), "notebooks", "ppi_raw_2021_2022.csv")
    print("저장 시도 경로:", save_path)
    try:
        with open(save_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(data)
        print(f"✅ 저장 완료: {save_path} ({len(data)}행)")
        print("파일 존재 확인:", os.path.exists(save_path))
    except Exception as e:
        print("❌ 저장 중 에러 발생:", repr(e))
    print("샘플 데이터 (앞 3행):")
    for row in data[:3]:
        print(row)
elif isinstance(data, dict):
    print("⚠ 리스트가 아니라 딕셔너리 형태로 응답이 왔습니다 (보통 에러 메시지):")
    print(json.dumps(data, ensure_ascii=False, indent=2))
else:
    print("⚠ 예상한 형태의 데이터가 아닙니다. 위 응답 내용을 확인하세요.")
