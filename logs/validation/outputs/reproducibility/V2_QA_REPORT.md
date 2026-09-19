# V2 QA 결과

`changwon-protection-policy/2.0.0` 적용 후 · 2026-09-18

정책 `docs/reproducibility/PROTECTION_POLICY_V2.md`
매니페스트 `outputs/reproducibility/FREEZE_MANIFEST_V2.json`

---

## 0. 두 개의 QA 결과를 분리해 기록한다

| | 기준 | 결과 | 상태 |
|---|---|---|---|
| **V1 QA (역사기록)** | 잠금 당시 125개 파일 전체 바이트 | **63 tests / 1 failure** | 그대로 보존. 고치지 않음 |
| **V2 QA (이번)** | 역할별 분리 보호 (A·B만 해시) | **77 tests / 76 passed / 1 failure** | 실패 1건은 위 V1 검사 그 자체 |

V2 적용 후에도 전체 스위트는 여전히 1건 실패한다.
그 1건은 `tests/test_hybrid_validation.py::HybridTests::test_lock_and_original_outputs_unchanged`,
즉 **V1 정책 기준의 검사**다. 손대지 않았고 앞으로도 실패한 채로 둔다.

새로 추가한 14건(`tests/test_protection_policy_v2.py`)은 전부 통과한다.
테스트 총수가 63 → 77로 늘어난 것은 V2 검사 14건을 **추가**했기 때문이며,
기존 검사를 지우거나 완화해서가 아니다.

---

## 1. V1 실패를 어떻게 보존했는가

- 기존 잠금 5개(`FREEZE_MANIFEST.json`, rolling·hybrid의 `EXECUTION_LOCK.json`·
  `PREDICTION_LOCK.json`)를 읽기만 했다. 수정·삭제 없음.
  → `test_existing_locks_are_not_rewritten`이 바이트 일치를 검사한다.
- `PROTECTED_HASH_AMENDMENT.md`를 그대로 두었다.
- V2 매니페스트의 `v1_lock_state_at_v2_creation`에 당시 사실을 그대로 옮겼다.

```json
{
  "v1_protected_file_count": 125,
  "matched": 123,
  "mismatched": 2,
  "mismatched_files": [
    { "path": "outputs/decision_support_final/run_metadata.json",
      "v2_category": "RUNTIME_METADATA" },
    { "path": "README.md",
      "v2_category": "MUTABLE_DOCUMENTATION" }
  ],
  "status": "V1 정책 기준으로 여전히 실패 상태다. 이 기록을 성공으로 바꾸지 않는다."
}
```

- `run_metadata.json` 원본을 되돌려 옛 해시를 맞추지 않았다.
  → `test_original_run_metadata_is_not_rewritten`이 현재 해시가 V1 잠금 해시와
  **다른지**를 확인한다(같아지면 되돌린 것으로 보고 실패시킨다).

---

## 2. 보호 범위 (`FREEZE_MANIFEST_V2.json`)

| 범주 | 건수 | 해시 보호 | 예 |
|---|---:|---|---|
| A `IMMUTABLE_PROTOCOL` | 17 | **예** | PROTOCOL.md 2건, EXECUTION_LOCK 2건, PREDICTION_LOCK 2건, FREEZE_MANIFEST.json, artifact_hashes.json, PROTECTED_HASH_AMENDMENT.md, 독립감사 7건, 공모 공고문 |
| B `DETERMINISTIC_PROTECTED` | 93 | **예** | 입력 16 / 코드 26 / 결정적 산출물 51 |
| C `RUNTIME_METADATA` | 12 | 아니오 | run_metadata 4건, junit xml 2건, delivery_verification.json, notebook_execution.json, html, ipynb, 수집 로그, 파생 runtime |
| D `MUTABLE_DOCUMENTATION` | 15 | 아니오 | README.md, PROJECT_STRUCTURE.md, CONTRIBUTING.md, docs/ 3건, REPORT.md 3건 등 |

합계 137건. C·D에는 `sha256_informational`만 기록해 변화를 볼 수 있게 하되,
불일치를 모형 결과 불일치로 처리하지 않는다.

### C 안의 결정적 필드는 계속 검사한다

| 파일 | 따로 검사하는 필드 |
|---|---|
| `outputs/decision_support_final/run_metadata.json` | `rule_version`, `window`, `rows`, `rules`, `inputs`, `code_sha256`, `randomness`, `missing_policy`, `numeric_comparison_atol_percentage_units` |
| `outputs/robustness_extension/run_metadata.json` | `layer`, `window`, `rows`, `triage_rule_version`, `frozen_columns`, `inputs`, `code_sha256` |
| `outputs/rolling_backtest/RUN_METADATA.json` | `output_hashes`, `report_sha256`, `prediction_lock_sha256` |
| `outputs/hybrid_validation/RUN_METADATA.json` | `output_hashes`, `report_sha256`, `execution_lock_sha256`, `prediction_lock_sha256` |

---

## 3. run_metadata static / runtime 분리

원본 `outputs/decision_support_final/run_metadata.json`은 **수정하지 않았다.**
파생 파일 두 개를 새로 만들었다.

| 파일 | 범주 | 내용 |
|---|---|---|
| `outputs/reproducibility/run_metadata_static.json` | B | 12개 static 키 |
| `outputs/reproducibility/run_metadata_runtime.json` | C | 5개 runtime 키 |

| static (재현성 판정에 사용) | runtime (사용 안 함) |
|---|---|
| `code_sha256`, `inputs`(528건), `missing_policy`, `numeric_comparison_atol_percentage_units`, `purpose`, `randomness`, `rows`, `rule_version`, `rules`, `scope`, `window`, `working_tree_note` | `git_head`, `numpy`, `pandas`, `python`, `run_at_utc` |

canonical static 해시 `7818de037782d3f57fa53f69…`
계산식은 `sha256(json.dumps(static, sort_keys=True, ensure_ascii=False, separators=(",",":")))`
— 파일 전체 바이트 해시가 아니므로 들여쓰기·키 순서에 흔들리지 않는다.

원본 파일 해시 `dadd6fd8ed35738c14a6cf00…` (V1 잠금값 `c847972de505171cb7106aa2…`와 다름 — 그대로 둠).

---

## 4. 무엇을 보호대상에서 제외했는가

| 제외한 것 | 이유 | 대신 하는 것 |
|---|---|---|
| `README.md` | 개발 중 수정되는 설명 문서 | `git diff`/`git log`로 추적. `sha256_informational` 기록 |
| `PROJECT_STRUCTURE.md`, `CONTRIBUTING.md`, `docs/**` | 동일 | 동일 |
| `run_metadata.json` 파일 전체 | `run_at_utc`·`git_head`가 매 실행 갱신 | static 부분만 canonical 해시 |
| `full_tests.xml`, `triage_tests.xml` | junit `timestamp`·`hostname`·`time` 포함, 테스트 추가 시 건수 변동 | 테스트 자체를 CI에서 실행 |
| `delivery_verification.json` | 테스트 건수 집계 — 모형 결과 아님 | 동일 |
| `notebook_execution.json` | `executed_at` + 로컬 파이썬 경로 | — |
| `decision_support_final.html`, `11_...ipynb` | 노트북 실행·렌더 산출물 | 수치는 B 범주 CSV로 대조 |
| rolling·hybrid `RUN_METADATA.json` 파일 전체 | `completed_at_utc`·`platform`·`runtime_executable` 포함 | `output_hashes` 등 결정적 필드만 검사 |
| `REPORT.md`(3건), `MODEL_ROLE_CLARIFICATION.md` | 서술 문서 | 수치 주장은 B 범주 CSV로 대조 가능 |

**보호에서 뺐다고 검증에서 뺀 것이 아니다.** C는 스키마와 결정적 필드로,
D는 git 이력과 B 범주 데이터 대조로 확인한다.

---

## 5. 회귀검사 결과 (정책 §8의 10개 항목)

| # | 항목 | 결과 | 근거 |
|---|---|---|---|
| 1 | Triage 180행 stage 완전 동일 | **PASS** | 180행 |
| 2 | 관찰 128 / 추가확인 35 / 우선점검 17 | **PASS** | 분포 일치 |
| 3 | `decision_panel.csv` 동일 | **PASS** | `a328c9677d85…` = V1 잠금값 |
| 4 | `decision_latest.csv` 동일 | **PASS** | `2aa74d772b93…` = V1 잠금값 |
| 5 | `diagnostic_cards_latest` 판정필드 동일 | **PASS** | csv·json·md 3건 모두 V1 잠금값 일치 |
| 6 | `stage_distribution_by_quarter.csv` 동일 | **PASS** | V1 잠금값 일치 |
| 7 | rolling backtest deterministic outputs 동일 | **PASS** | CSV 7건 전부 V1 잠금값 일치 |
| 8 | ELECTRE/Hybrid 역사적 결과 동일 | **PASS** | hybrid predictions·overlap = PREDICTION_LOCK, CW-RBT FREEZE_MANIFEST 17건 전부 일치 |
| 9 | 해석층이 판정값을 overwrite하지 않음 | **PASS** | 180행 `stage`·`employment` 동일 |
| 10 | 문서 변경이 model-output failure로 잡히지 않음 | **PASS** | D∩(A∪B)=∅, README 변경 상태에서 A·B 검사 통과 |

---

## 6. V2 테스트 상세 (14건, 전부 통과)

```
tests/test_protection_policy_v2.py
  test_protocol_files_unchanged                       A 범주 17건 바이트 고정
  test_existing_locks_are_not_rewritten               기존 잠금 5개 불변
  test_v1_failure_record_is_preserved_not_overwritten V1 불일치 2건 기록 정확성
  test_deterministic_outputs_unchanged                B 범주 93건 바이트 고정
  test_deterministic_set_covers_the_decisive_artifacts 보호범위 축소 방지
  test_runtime_metadata_schema                        C 범주에 구속 해시 없음 + 결정적 필드 존재
  test_runtime_metadata_static_split_is_canonical     static/runtime 실제 분리 확인
  test_original_run_metadata_is_not_rewritten         원본 되돌림 금지
  test_documentation_not_in_output_freeze             D가 A·B와 분리
  test_readme_change_is_not_a_model_output_failure    README 변경 ≠ 결과 변경
  test_triage_180_rows_and_stage_distribution_unchanged
  test_decision_artifacts_match_manifest_hashes
  test_rolling_and_hybrid_deterministic_outputs_unchanged
  test_context_layer_does_not_overwrite_triage_fields
```

---

## 7. 남은 것

- 전체 스위트는 **77 tests / 1 failure**로 남는다. 이 실패는 V1 정책 기준 검사이며,
  의도적으로 유지한다. 없애려면 V1 잠금을 다시 만들어야 하는데, 그러면 사전등록
  시점이 사후로 밀린다. `PROTECTED_HASH_AMENDMENT.md` §4의 선택지 3가지는 그대로 열려 있다.
- V2 매니페스트를 재생성하면 A·B 해시가 현재 값으로 갱신된다.
  **A·B 불일치를 발견했을 때는 재생성하지 말고 원인을 먼저 확인해야 한다.**
  이 경고는 정책 문서 §7에도 적어 두었다.
- 이번 작업에서 threshold·판정·outcome·외부데이터 수집은 일절 건드리지 않았다.

---

## 8. 2026-09-19 외부 API 데이터 통합 후 재실행

정책 버전 `changwon-protection-policy/2.1.0` — 외부 수집물과 수집·해석 코드를 보호범위에 추가.
**판정층은 그대로다.**

| | 결과 |
|---|---|
| 전체 스위트 | **92 tests / 91 passed / 1 failed** |
| 실패 1건 | `test_hybrid_validation.py::test_lock_and_original_outputs_unchanged` (V1 정책 기준, 계속 보존) |
| 신규 | `tests/test_external_data.py` 15건 전부 통과 |
| V2 정책 검사 | 14건 전부 통과 |
| V1 잠금 상태 | 125건 중 123 일치 / 2 불일치 — **변화 없음** |

### 보호범위 변화 (2.0.0 → 2.1.0)

| 범주 | 2.0.0 | 2.1.0 |
|---|---:|---:|
| A IMMUTABLE_PROTOCOL | 17 | 17 |
| B DETERMINISTIC_PROTECTED | 93 | **111** |
| C RUNTIME_METADATA | 12 | **16** |
| D MUTABLE_DOCUMENTATION | 15 | **16** |

B 에 추가된 것: 수집기 8종·해석 코드 2종·보조패널 3종·크로스워크 3종·인벤토리 1종.
C 에 추가된 것: 외부 수집 metadata 4종 — `retrieved_at` 을 담으므로 runtime 이되,
`file_hash_sha256`·`raw_response_sha256` 은 `deterministic_fields` 로 따로 검사한다.

### 매니페스트 재생성의 근거

재생성 전 `test_deterministic_outputs_unchanged` 가 **4건 변경**을 정확히 잡아냈다.

```
CHANGED src/build_context_layer.py
CHANGED src/context/questions.py
CHANGED data/processed/context/industry_context_signals.csv
CHANGED outputs/robustness_extension/diagnostic_card_preview.csv
```

전부 해석층 코드와 그 산출물이고, A 범주(프로토콜) 변경은 **0건**,
Triage·rolling·hybrid 산출물 변경도 **0건**이었다. 의도한 변경임을 확인한 뒤에만
재생성했다 — 정책 §7 의 "A·B 불일치를 발견하면 재생성하지 말고 원인을 먼저 확인한다" 를 따랐다.

### 인증정보 취급 검사 (신규)

| 검사 | 결과 |
|---|---|
| 저장소 전체 텍스트 파일에서 키 문자열 탐색 | **0건** |
| `.env.txt` git 추적 | 안 됨 |
| `.env.txt` 과거 커밋 이력 | 없음 |
| `.gitignore` 차단 | `.env.*` 로 이미 차단(+ `*_api_key.txt` 보강) |
| metadata `api_parameters` 내 인증 항목 | 제거됨 |
| 원본 응답·CSV SHA-256 | 3개 출처 모두 일치 |
| pagination 완전성 | 관세청 78회·ECOS 95회 전부 `totalCount` 대조 완료 |
