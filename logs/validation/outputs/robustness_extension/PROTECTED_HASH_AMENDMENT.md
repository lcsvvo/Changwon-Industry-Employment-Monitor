# 보호대상 해시 변경 기록 (2026-09-18)

`outputs/hybrid_validation/EXECUTION_LOCK.json` 은 Hybrid 검증을 사전등록할 때
저장소 125개 파일의 SHA-256 을 기록해 두었다. 이번 해석층 작업 뒤
**125개 중 123개는 그대로이고 2개가 달라졌다.** 감춰두면 잠금장치의 의미가 없으므로
무엇이 왜 달라졌는지 여기에 남긴다.

## 1. 달라진 파일

| 파일 | 잠금 시 해시 | 원인 | 분석 결과에 미치는 영향 |
|---|---|---|---|
| `outputs/decision_support_final/run_metadata.json` | `c847972d…` | `src/run_triage_rule.py` 재실행 (§2) | 없음 — 실행시각·입력해시 기록만 갱신 |
| `README.md` | `1f5c63af…` | 해석층 문서 링크 추가 | 없음 — 문서 |

## 2. `run_metadata.json` 이 왜 바뀌었나

해석층이 Triage 판정을 바꾸지 않았는지 확인하려고 `src/run_triage_rule.py` 를
다시 실행했다. 그 결과 **판정 산출물은 바이트 단위로 동일**했다.

| 파일 | 재실행 전후 |
|---|---|
| `decision_panel.csv` | 동일 (`a328c9677d851b7b…`) |
| `decision_latest.csv` | 동일 |
| `diagnostic_cards_latest.csv` | 동일 |
| `stage_distribution_by_quarter.csv` | 동일 |

다만 `run_metadata.json` 은 설계상 `run_at_utc`(실행시각)과 `git_head` 를 매 실행마다
새로 기록한다. 따라서 **재실행하면 반드시 해시가 바뀐다.** 잠금 당시의 바이트는
타임스탬프를 포함하므로 복원할 수 없다.

이건 이번 작업이 만든 문제라기보다 잠금 설계의 성질이다. `README.md` 의 재현 절차가
`python src/run_triage_rule.py` 를 안내하고 있으므로, 안내대로 재현하면 누구든 같은
불일치를 만나게 된다.

`outputs/decision_support_final/audit_v3/artifact_hashes.json` 도 같은 파일에 대해
같은 옛 해시를 기록하고 있어 동일하게 불일치한다.

## 3. 그대로인 것

| 검사 | 결과 |
|---|---|
| Hybrid `hybrid_predictions.csv` 해시 | 일치 |
| Hybrid `hybrid_overlap.csv` 해시 | 일치 |
| Hybrid `scripts/run_hybrid_validation.py` 해시 | 일치 |
| Rolling backtest `FREEZE_MANIFEST.json` 전 항목 | 일치 |
| Rolling backtest `predictions_long.csv` 해시 | 일치 |
| 보호대상 125개 중 나머지 123개 | 일치 |

**ELECTRE / Hybrid / rolling backtest 의 어떤 결과값도 바뀌지 않았다.**
outcome, 예측, 지표, 프로토콜은 손대지 않았다.

## 4. 현재 상태와 선택지

`pytest tests/test_hybrid_validation.py::HybridTests::test_lock_and_original_outputs_unchanged`
는 위 2개 파일 때문에 **실패한다.** 나머지 62개 테스트는 통과한다.

선택지는 셋이고, 어느 것을 고를지는 제출 판단의 문제다.

1. **그대로 둔다.** 실패가 "무엇이 바뀌었는지" 를 계속 알려주는 신호로 작동하고,
   이 문서가 그 내용을 설명한다. 사전등록의 증거능력이 가장 강하게 보존된다.
2. **잠금을 갱신한다.** `outputs/hybrid_validation/EXECUTION_LOCK.json` 을 지우고
   `scripts/run_hybrid_validation.py` 를 다시 실행한다. 스크립트가 기존 잠금 덮어쓰기를
   거부하도록 되어 있으므로 의도적으로 지워야 한다. **사전등록 시점이 사후로 밀리므로
   권장하지 않는다.**
3. **보호대상에서 타임스탬프 파일을 뺀다.** `protected()` 에서
   `run_metadata.json` 을 제외하면 재현 실행이 잠금을 깨지 않게 된다.
   다만 이는 잠금장치의 범위를 사후에 좁히는 일이라 별도 판단이 필요하다.

이 작업에서는 **1번(그대로 둠)** 을 선택했다. 잠금은 건드리지 않았고,
`protected()` 정의도 바꾸지 않았다.
