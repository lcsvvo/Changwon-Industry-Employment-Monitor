# Data

출처별 가공 패널과 분류 대응표. 원자료와 인증정보는 로컬에서만 관리.

| Source | Period | Local Raw Path | Processed Path |
|---|---|---|---|
| KICOX 생산, 고용, 가동률, 업체 수 | 2018Q1–2026Q2 | `raw/kicox/core/`, `raw/kicox/revision/` | `processed/kicox/` |
| KOSIS 생산자물가지수 | 2021.01–2026.06 | `raw/ppi/` | `processed/ppi/` |
| EIS 고용보험 피보험자 | 2022Q1–2026Q2 | `raw/eis/` | `processed/eis/` |
| 고용24 공개 채용정보 | 2026년 9월 수집 단면 | `raw/work24/` | `processed/work24/` (로컬 전용) |
| 관세청, KEPCO, ECOS 등 | 자료별 상이 | 출처별 `raw/` 경로 | `processed/customs/`, `processed/kepco/`, `processed/ecos/` 등 |

- **KICOX 출처**: 공공데이터포털 업종별 생산 `15085898`, 고용 `15085897`. 연간보정본을 함께 반영.
- **최종 패널**: 2022Q1–2026Q2, 10개 업종 × 18분기. `processed/final_model/`에 판정과 근거 구성용 자료 저장.
- **역할 구분**: 자동 판정은 KICOX 기준. PPI는 명목 생산의 가격효과, EIS는 다른 모집단의 고용 방향을 확인하는 자료.
- **매핑**: [업종 대응표](processed/final_model/reference/industry_crosswalk/README.md)에 품질과 근거 표시. 지역과 산업 범위가 다른 값을 합산하거나 대체하지 않음.
- **공개 범위**: 집계 가공자료, 대응표, 출처 메타데이터. 원자료, 실제 공고 단위 가공자료와 API 키는 로컬에 보관합니다.
- **접근 조건**: 원자료는 각 제공기관에서 별도 확보. 수집기별 키와 파일 형식은 `src/evidence/collection/` 참고.
- **사건 참고자료**: [외부사건 패널](processed/final_model/reference/external_event_audit/README.md)은 위기 여부의 정답 라벨이 아님.
