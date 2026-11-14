# Industry Crosswalk

외부 분류체계를 KICOX 10개 업종으로 연결하는 대응표.

| File | Classification |
|---|---|
| `employment_insurance_to_kicox.csv` | 고용보험 산업분류 |
| `ksic_to_kicox.csv`, `kepco_biztype_to_kicox.csv` | KSIC, 전력 업종분류 |
| `hs6_universe_customs.csv` | 현행 관세청 HS 6단위 모집단 |
| `hs_to_kicox.csv`, `hs6_verified_to_kicox.csv` | 초기 탐색용 대응표 |
| `ecos_bsi_to_kicox.csv` | ECOS 경기심리 업종 |
| `labor_force_survey_to_kicox.csv` | 사업체노동력조사 산업분류 |
| `ppi_to_kicox.csv` | 생산자물가지수 품목분류 |

## Mapping Quality

| Grade | Meaning | Use |
|---|---|---|
| A | 직접 대응 | 범위 확인 후 사용 |
| B | 상위, 하위 분류 대응 | 범위 차이를 표시하고 방향 위주 해석 |
| C | 복수 후보, 부분 포함 | 조건부 밴드와 방향만 표시 |
| D | 매핑 불가 | 업종 단위 신호 생성 제외 |

- **C, D**: 불확실성 표시. 자동 업종 확인신호 생성 제외.
- **다른 모집단**: KICOX 고용 대체와 합산 제외. 방향 일치, 불일치, 비교불가만 구분.
- **HS6 구성**: 관세청 HS부호 `15049722`, HSK별 분류 `15049720` 기반. `src/evidence/build_hs6_universe.py`에서 생성.
- **해석 범위**: 품목 매핑에 포함된 수출입을 업종 전체 수출입으로 해석할 수 없음.
