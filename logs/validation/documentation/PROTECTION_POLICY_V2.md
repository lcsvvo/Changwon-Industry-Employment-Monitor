# 재현성 보호정책 V2

`changwon-protection-policy/2.0.0` · 2026-09-18

정책 정의 코드 `src/reproducibility/policy.py`
매니페스트 `outputs/reproducibility/FREEZE_MANIFEST_V2.json`
검사 `tests/test_protection_policy_v2.py`

---

## 0. 이 문서가 바꾸는 것과 바꾸지 않는 것

**바꾸지 않는다.** 기존 잠금 5개(`FREEZE_MANIFEST.json`, rolling/hybrid의
`EXECUTION_LOCK.json`·`PREDICTION_LOCK.json`)와 `PROTECTED_HASH_AMENDMENT.md`는
당시 상태를 나타내는 역사적 감사기록이다. 한 글자도 고치지 않았고 삭제하지 않았다.
V1 기준의 실패(125개 중 2개 불일치)도 그대로 남아 있다.

**바꾼다.** 앞으로 "모형 결과가 바뀌었다"고 말할 수 있는 근거의 범위를 정의한다.

---

## 1. 왜 V2가 필요한가

V1 잠금은 저장소 125개 파일을 한 덩어리로 묶어 바이트 해시를 걸었다.
그 안에 두 종류의 파일이 섞여 들어갔다.

| 파일 | 성격 | 문제 |
|---|---|---|
| `outputs/decision_support_final/run_metadata.json` | 실행마다 `run_at_utc`·`git_head`·라이브러리 버전을 새로 씀 | **재실행하면 반드시 해시가 바뀐다.** 잠금 당시 바이트는 타임스탬프 때문에 복원 불가 |
| `README.md` | 개발 중 계속 고쳐지는 설명 문서 | 문서를 고치면 모형 결과 검사가 실패한다 |

결과적으로 **모형 결과가 하나도 바뀌지 않았는데도** 검사가 실패한다.
실제로 그렇게 됐다. 해석층 작업에서 판정 불변을 확인하려고
`python src/run_triage_rule.py`(README가 안내하는 재현 절차)를 다시 실행했더니
판정 산출물은 바이트 단위로 동일했는데 `run_metadata.json`만 달라졌다.

> 기존 QA에서 deterministic output과 무관한 runtime timestamp 및 mutable
> documentation이 byte-level protection에 포함되어 재실행 시 false failure를
> 발생시킴. 과거 실패를 삭제하지 않고 보호범위를 역할별로 분리함.

이것이 `FREEZE_MANIFEST_V2.json`의 `reason_for_policy_revision`이다.

---

## 2. 4분류

| | 범주 | 무엇이 들어가나 | 해시 보호 | 건수 |
|---|---|---|---|---:|
| A | `IMMUTABLE_PROTOCOL` | 프로토콜, 실행잠금, 예측잠금, 승인 당시 사양, 독립감사 기록 | **예** | 17 |
| B | `DETERMINISTIC_PROTECTED` | 핵심 입력, 판정 코드, 설정, 최종 판정 CSV, rolling/hybrid 결정적 산출물, 해석층 결정적 산출물 | **예** | 93 |
| C | `RUNTIME_METADATA` | 실행시각, 실행 경로, 머신·런타임 정보, 소요시간, QA 집계 | 아니오 | 12 |
| D | `MUTABLE_DOCUMENTATION` | README, PROJECT_STRUCTURE, 설명 문서 | 아니오 | 15 |

**A·B만 바이트/해시 보호 대상이다.**
**C·D의 해시 불일치는 모형 결과 불일치가 아니다.**

C·D에도 `sha256_informational`을 기록한다. 변화를 볼 수는 있게 하되,
그 불일치로 모형 결과 검사를 실패시키지 않는다.

### 경계선을 어떻게 그었나

판단 기준은 하나다. **같은 입력·같은 코드로 같은 결과를 냈는데도,
다른 시각·다른 기계에서 돌렸다는 이유만으로 값이 달라지는가?**
달라진다면 그 파일(또는 그 필드)은 결정적 산출물이 아니다.

이 기준을 적용하면 다음이 C로 간다.

- `full_tests.xml`, `triage_tests.xml` — pytest junit. `timestamp`·`hostname`·`time` 속성을 담고, 테스트를 추가하면 건수도 바뀐다.
- `delivery_verification.json` — 테스트 건수 집계. 테스트 추가는 모형 결과 변경이 아니다.
- `notebook_execution.json` — `executed_at`과 로컬 파이썬 경로.
- `decision_support_final.html`, `11_decision_support_final.ipynb` — 노트북 실행·렌더 산출물.
- rolling/hybrid의 `RUN_METADATA.json` — `completed_at_utc`·`platform`·`runtime_executable` 포함.

반대로 `verification.json`(판정 분포)과 `raw_rebuild_verification.json`(재구축 일치 여부)은
모형 동작을 기술하므로 B에 남는다.

---

## 3. 한 파일 안에 static과 runtime이 섞인 경우

`run_metadata.json`처럼 두 성격이 한 파일에 있는 경우, **파일 전체가 아니라
static 부분만** canonical 해시를 계산한다.

```
canonical_hash = sha256(
    json.dumps(static, sort_keys=True, ensure_ascii=False,
               separators=(",", ":")).encode("utf-8")
)
```

키 순서·들여쓰기에 의존하지 않는다. 파일 전체 바이트 해시가 아니다.

runtime으로 분류하는 최상위 키 (`policy.RUNTIME_KEYS`):

```
run_at_utc, completed_at_utc, locked_at_utc, executed_at, checked_at_utc,
retrieved_at, git_head, python, pandas, numpy, platform,
runtime_executable, hostname, duration_seconds, execution_path
```

`outputs/decision_support_final/run_metadata.json`의 실제 분리 결과

| static (재현성 판정에 사용) | runtime (사용하지 않음) |
|---|---|
| `rule_version`, `window`, `rows`, `rules`, `inputs`(입력 528건 해시), `code_sha256`, `randomness`, `missing_policy`, `numeric_comparison_atol_percentage_units`, `purpose`, `scope`, `working_tree_note` | `run_at_utc`, `git_head`, `python`, `pandas`, `numpy` |

`git_head`를 runtime에 둔 이유: 같은 작업트리라도 커밋이 생기면 값이 바뀐다.
이 저장소는 `working_tree_note`에서 "Uncommitted source hashes are authoritative"라고
이미 밝히고 있으므로, 코드 동일성의 근거는 `code_sha256`이다.

### 원본은 고치지 않는다

`run_metadata.json` 원본을 사후 수정해 옛 해시를 맞추려 하지 않았다.
파생 파일 두 개를 따로 만든다.

- `outputs/reproducibility/run_metadata_static.json`
- `outputs/reproducibility/run_metadata_runtime.json`

`static` 파일이 B, `runtime` 파일이 C다.
`tests/test_protection_policy_v2.py::test_original_run_metadata_is_not_rewritten`이
원본이 V1 해시로 되돌려지지 않았는지를 검사한다.

---

## 4. README 처리

`README.md`는 앞으로 model-output immutability 검사의 보호 대상이 아니다.

**README 수정을 무시한다는 뜻이 아니다.**

- 문서 변경은 `git diff` / `git log`로 추적한다.
- 매니페스트에 `sha256_informational`로 현재 값을 남겨 변화를 볼 수 있게 한다.
- 다만 **README 해시 불일치 ≠ 모형 결과 변경**으로 정의한다.

`outputs/decision_support_final/REPORT.md`, `outputs/robustness_extension/REPORT.md`도
서술 문서라 D에 둔다. 대신 이 문서들의 **수치 주장은 B 범주 CSV로 대조 가능**하다 —
데이터를 고정하고, 서술은 데이터에 맞는지 확인하는 구조다.

---

## 5. 검사 구조

| 테스트 | 묻는 것 |
|---|---|
| `test_protocol_files_unchanged` | A 범주 17건 바이트 고정 |
| `test_deterministic_outputs_unchanged` | B 범주 93건 바이트 고정 |
| `test_deterministic_set_covers_the_decisive_artifacts` | 보호 범위를 몰래 줄이지 않았는지 |
| `test_runtime_metadata_schema` | C 범주에 구속력 있는 해시가 없는지 + 내부 결정적 필드 존재 |
| `test_runtime_metadata_static_split_is_canonical` | static/runtime 분리가 형식뿐 아니라 실제로 됐는지 |
| `test_original_run_metadata_is_not_rewritten` | 원본을 되돌려 옛 해시를 맞춘 흔적이 없는지 |
| `test_documentation_not_in_output_freeze` | D가 A·B와 섞이지 않았는지 |
| `test_readme_change_is_not_a_model_output_failure` | README가 바뀌어도 A·B 검사가 통과하는지 |
| `test_existing_locks_are_not_rewritten` | 기존 잠금 5개가 그대로인지 |
| `test_v1_failure_record_is_preserved_not_overwritten` | V1 불일치 2건 기록이 사실과 맞는지 |
| 회귀검사 5건 | Triage 180행·단계분포·rolling·hybrid·해석층 불변 |

### 기존 테스트는 손대지 않았다

`tests/test_hybrid_validation.py::test_lock_and_original_outputs_unchanged`는
**그대로 두었고 여전히 실패한다.** assert를 느슨하게 만들거나 xfail로 가리지 않았다.
그 실패는 "V1 정책 기준으로는 2건이 달라졌다"는 사실을 계속 알려주는 신호이고,
경위는 `PROTECTED_HASH_AMENDMENT.md`에, 재분류는 이 문서와 V2 매니페스트에 있다.

---

## 6. 이 정책으로 판정하는 법

새로 실행한 뒤 물어야 할 순서.

1. **A·B 범주에 불일치가 있는가?** → 있으면 프로토콜 위반 또는 모형 결과 변경이다. 멈추고 원인을 찾는다.
2. **C 범주만 달라졌는가?** → 재실행·환경 차이다. 모형 결과 변경이 아니다. 단, C 안의 `deterministic_fields`(예: `output_hashes`)는 여전히 검사한다.
3. **D 범주만 달라졌는가?** → 문서 수정이다. `git diff`로 내용을 검토하되 모형 결과 검사를 실패시키지 않는다.

---

## 7. 재생성

```powershell
python scripts/build_freeze_manifest_v2.py
python -m pytest tests/test_protection_policy_v2.py
```

매니페스트를 다시 만들면 A·B의 해시가 **현재 값으로 갱신된다.**
따라서 재생성은 "보호 대상을 확정한다"는 뜻이지 "검사를 통과시킨다"는 뜻이 아니다.
A·B가 바뀐 상태에서 무심코 재생성하면 변경이 묻힌다.
**A·B 불일치를 발견했을 때는 재생성하지 말고 원인을 먼저 확인한다.**
