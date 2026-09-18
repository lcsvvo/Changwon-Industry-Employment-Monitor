# ============================================================
# 창원국가산단 생산실적 실질화용 PPI(생산자물가지수, 기본분류) 수집
# 출처: KOSIS OpenAPI (한국은행, 생산자물가조사, tblId=DT_404Y014)
# ============================================================

# 최초 1회만 실행 (이미 설치했다면 생략)
# install.packages(c("httr", "jsonlite", "dplyr"))

library(httr)
library(jsonlite)
library(dplyr)

# ------------------------------------------------------------
# 1. 인증키 설정
# ------------------------------------------------------------
api_key <- "ZmZkZTNhYjY0MGJhMGMyNDk2MzlhNjMxNmE5MzZkZTA="

# ------------------------------------------------------------
# 2. 통계표 항목(업종) 목록 먼저 확인하기
#    -> objL1에 어떤 코드들이 있는지 몰라서, 우선 ALL로 전체를 받아보고
#       그 안에서 필요한 업종만 R에서 필터링하는 방식으로 진행합니다.
# ------------------------------------------------------------

base_url <- "https://kosis.kr/openapi/Param/statisticsParameterData.do"

query <- list(
  method       = "getList",
  apiKey       = api_key,
  itmId        = "T60+",        # 지수(전체 항목) - 안 맞으면 아래 안내 참고
  objL1        = "ALL",         # 업종 전체
  objL2        = "",
  objL3        = "",
  objL4        = "",
  objL5        = "",
  objL6        = "",
  objL7        = "",
  objL8        = "",
  format       = "json",
  jsonVD       = "Y",
  prdSe        = "M",           # 월별 (Q=분기, Y=연)
  newEstPrdCnt = "48",          # 최근 48개월치
  orgId        = "301",         # 한국은행
  tblId        = "DT_404Y014"   # 생산자물가지수(기본분류)
)

res <- GET(base_url, query = query)

# ------------------------------------------------------------
# 3. 응답 확인
# ------------------------------------------------------------
status_code(res)   # 200이어야 정상
raw_text <- content(res, as = "text", encoding = "UTF-8")

# 에러 메시지인지 실제 데이터인지 먼저 확인
cat(substr(raw_text, 1, 500), "\n")  # 앞부분만 미리보기

data <- fromJSON(raw_text)

# ------------------------------------------------------------
# 4. 결과 저장
# ------------------------------------------------------------
if (is.data.frame(data)) {
  write.csv(data, "ppi_raw.csv", row.names = FALSE, fileEncoding = "UTF-8")
  cat("저장 완료: ppi_raw.csv (", nrow(data), "행 )\n")
  print(head(data))
} else {
  cat("⚠ 데이터프레임이 아닙니다. 아래 원본 응답을 확인하세요 (파라미터 오류 가능성):\n")
  print(data)
}
