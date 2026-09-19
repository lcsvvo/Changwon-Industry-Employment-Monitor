# 외부 공개데이터 원본 (data/raw/external/)

수집 코드는 `src/data_collection/`, 탐색 결과표는
`data/reference/external_data_inventory.csv` 에 있다.

## 규칙

1. **원본은 수정하지 않는다.** 서버가 준 바이트를 그대로 저장한다.
   인코딩 변환·열 정리·결측 처리는 전부 하류(`src/context/`)에서 한다.
2. 각 파일마다 `_metadata/<파일명>.json` 에 출처·시점·해시를 남긴다.
   `tests/test_context_layer.py::test_G_...` 가 해시 일치를 검사한다.
3. 수집하지 못한 자료는 `_metadata/collection_status.json` 에
   **왜 못 받았는지**를 남긴다. 빈 디렉터리로 두지 않는다.
4. 로그인·CAPTCHA·유료 우회를 하지 않는다. 서버가 401/403/429 를 주면
   그대로 기록하고 중단한다.
5. API 키는 환경변수로만 읽는다(`.env.example` 참조). 실제 키는 `.env.txt` 하나에만
   두고 다른 파일로 복사하지 않는다. `src/data_collection/secrets.py` 가 로딩과
   마스킹을 담당하며, `Response` 객체가 생성 시점에 URL·오류문자열의 인증정보를 지운다.
6. 공공데이터포털 인증키는 **Encoding 형태 그대로** 전달한다. 다시 인코딩하면
   `SERVICE_KEY_IS_NOT_REGISTERED_ERROR(403)` 이 난다(실측 확인).

## 디렉터리

| 디렉터리 | 상태 | 내용 |
|---|---|---|
| `kicox_datagokr/` | 수집됨 | 공공데이터포털 KICOX 산업동향 최신 공표본 7건 (인증키 불필요) |
| `changwon_factory_registry/` | 수집됨 | 창원시 공장등록현황 5,636행 (2024-12-31 스냅샷) |
| `employment_insurance/` | 수집됨 | KOSIS 사업체노동력조사(지역편) — 창원시 제조업 입직·이직·빈일자리 238행 |
| `customs_trade/` | 수집됨 | 관세청 시군구별 품목별 수출입 — 창원시 HS6 13품목 810행 |
| `ecos/` | 수집됨 | ECOS 경남 지역별 + 전국 업종별 BSI 6,460행 |
| `customs/` | SUPERSEDED | 인증키 확보 전 미수집 기록. `customs_trade/` 로 대체 |
| `bok_bsi/` | SUPERSEDED | sample 키로 받은 전국 제조업 BSI. `ecos/` 로 대체 |
| `kepco/` | 미수집 | 인증키는 있으나 업무명(endpoint) 미확정 — `_metadata/collection_status.json` 참조 |

`_collection_log_datagokr.json` 에 포털 수집 실행 기록이 있다.

## 역할 — 섞지 않는다

| 자료 | 역할 | 해서는 안 되는 것 |
|---|---|---|
| KICOX 최신 공표본 | vintage check (동일 계열) | 독립검증이라고 말하는 것 |
| 고용보험(창원상의 업종별) | cross-check (다른 모집단) | KICOX 고용값 대체, 점유율 계산 |
| 입직·이직 (KOSIS) | flow-interpretation | 업종별 배분, 입직−이직 = KICOX 고용증감 |
| 수출 (관세청) | context / external-demand | 업종 수출 총액이라 부르기 |
| BSI (ECOS) | context / business-sentiment | 업종 자동판정, 산단 업종 신호라 부르기 |
| 공장등록현황 | context (단일 시점) | 업체수 증감 신호 생성 |

## 재수집

```powershell
python src/evidence/collection/collect_datagokr_files.py
python src/evidence/collection/collect_ecos_bsi.py
python src/evidence/collection/collect_kosis_employment_insurance.py
python src/evidence/collection/collect_customs_exports.py
python src/evidence/collection/collect_kepco_power.py                # endpoint 미확정 시 사유만 기록
python logs/validation/code/check_external_vintage.py
```

공공데이터포털은 각 파일데이터의 **현재 공표본 1개만** 제공한다.
과거 월별 공표본은 포털에서 재취득할 수 없다. 이미 받아둔
`data/raw/kicox/core/` 의 과거 파일이 대체 불가능한 자산이라는 뜻이다.
