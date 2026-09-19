"""재현성 보호정책 V2.

기존 잠금(FREEZE_MANIFEST, EXECUTION_LOCK, PREDICTION_LOCK)은 역사적 감사기록으로
그대로 둔다. 이 패키지는 그것을 대체하지 않고, 보호범위를 역할별로 나눈 V2 정책을
새로 정의한다.

정책 문서 : docs/reproducibility/PROTECTION_POLICY_V2.md
매니페스트 : outputs/reproducibility/FREEZE_MANIFEST_V2.json
"""
