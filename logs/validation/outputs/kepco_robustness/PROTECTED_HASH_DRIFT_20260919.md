# 보호대상 해시 불일치 기록 — 2026-09-19 (KEPCO context layer 작업)

## 왜 이 파일이 있나

`outputs/reproducibility/FREEZE_MANIFEST_V2.json` 은 2026-09-19T03:02:44 에 만들어졌다.
그 시점 **이후에** 두 갈래의 작업이 B 범주(DETERMINISTIC_PROTECTED) 파일을 바꿨다.
매니페스트를 조용히 다시 만들면 이 사실이 사라진다. 그래서 **매니페스트는 그대로 두고**
무엇이 왜 바뀌었는지만 여기에 적는다. 기존 `PROTECTED_HASH_AMENDMENT.md` 와 같은 방식이다.

기록 시점 2026-09-19 · 확인 방법 `pytest tests/test_protection_policy_v2.py`

## 불일치 목록

| 보호대상 파일 | 매니페스트 sha256(앞 16) | 현재 sha256(앞 16) | 변경 출처 |
|---|---|---|---|
| `src/context/external_panels.py` | `cd005bd5ca246573…` | `1db7f924ccc2c829…` | 관세청 포털 일괄 CSV 통합 작업 (별도 완료 작업) |
| `src/data_collection/collect_kepco_power.py` | `5a5f0e69e0103cb2…` | `cf257ccb0b8a9a5a…` | **이번 KEPCO 작업** — 지수 백오프·403 처리 추가 (Codex 수정분 + 후속 보완) |
| `data/processed/context/industry_context_signals.csv` | `3d6a80955a6f98cd…` | `b520802629bd6a48…` | 관세청 포털 일괄 CSV 통합 작업 (별도 완료 작업) |
| `data/processed/context/trade_context_panel.csv` | `db65702d1cb0a76e…` | `ab7c0ff4ef2e9261…` | 관세청 포털 일괄 CSV 통합 작업 (별도 완료 작업) |
| `data/processed/context/trade_coverage_by_industry.csv` | `f7d4038b253b23f0…` | `9b6ffa8decdf0da4…` | 관세청 포털 일괄 CSV 통합 작업 (별도 완료 작업) |
| `outputs/robustness_extension/diagnostic_card_preview.csv` | `d32ec5e41aa09be6…` | `7e20e8414a8ad4eb…` | 관세청 포털 일괄 CSV 통합 작업 (별도 완료 작업) |

## 판단

- 6건 중 **5건은 관세청 작업**에서 비롯됐고, 이번 KEPCO 작업 착수 시점에 이미 불일치 상태였다.
- 1건(`collect_kepco_power.py`)만 이번 KEPCO 작업 범위다. 선형 대기를 지수 백오프로 바꾸고
  403 을 재시도하지 않도록 한 변경이며, **수집 로직의 판정 규칙은 바꾸지 않는다**.
- `src/context/kepco_power.py` · `src/build_kepco_robustness.py` 는 매니페스트 B 범주에
  **포함돼 있지 않다.** 보호 범위 자체가 이 두 파일을 덮지 않는다.
- Triage 판정(180 / 관찰 128 / 추가확인 35 / 우선점검 17)은 이 변경들과 무관하게 그대로다.
  `outputs/kepco_robustness/results_summary.json` 의 `triage_invariance` 가 실행 전후 sha256 동일을 기록한다.

## 재기준화(re-baseline)를 하지 않은 이유

매니페스트를 다시 만들면 위 6건이 **한꺼번에** 정상으로 기록된다.
관세청 5건은 이번 작업의 판단 범위 밖이므로, 두 갈래를 한 번에 승인해 버리는 결과가 된다.
재기준화는 사용자가 6건 전부를 확인한 뒤 결정할 사항으로 남긴다.

승인 시 실행:

```bash
python scripts/build_freeze_manifest_v2.py
pytest tests/test_protection_policy_v2.py
```

## 이번 작업과 무관한 기존 실패

`tests/test_hybrid_validation.py::test_lock_and_original_outputs_unchanged` 의 실패는
V1 잠금 기준 검사이며 `run_metadata.json`(runtime)·`README.md`(documentation) 때문이다.
이번 작업 이전부터 있던 실패이고, 이번 변경으로 늘어나지 않았다.

