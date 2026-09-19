# -*- coding: utf-8 -*-
"""tests/fixtures/model_wording_rules.json의 금지어를 새로 쓴 파일에서 스스로 검사한다.

사용자가 지시문 안에 준 문구라도 예외 없이 검사한다 — 지시받은 문구라는 사실이
금지어 위반을 면제해 주지 않는다. 걸리면 저장(커밋 아님, 파일 작성)을 완료하기
전에 사용자에게 보고한다. 각 Phase 종료 시 실행해 새로 만든 파일 전체를 점검한다.

이 파일 자체와 tests/fixtures/model_wording_rules.json 자신은 점검 대상에서
제외한다(그 파일은 금지어를 목록으로 담고 있으므로 자기 자신을 걸러낸다).
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / 'tests/fixtures/model_wording_rules.json'
SELF_PATH = Path(__file__).resolve()

# 기본 스캔 대상: 이번 재검증 작업에서 새로 쓰거나 계속 고치는 파일들.
# 인자로 경로를 주면 그 파일/디렉터리만 스캔한다(디렉터리는 아래 확장자만 재귀 탐색).
DEFAULT_TARGETS = (
    'config/model_revalidation_prereg.yaml',
    'config/model_revalidation_prereg.template.yaml',
    'config/electre_tri_b_params.yaml',
    'config/electre_tri_b_params.template.yaml',
    'config/electre_tri_b_params.v1.1-candidates.yaml',
    'config/parameter_briefing.md',
    'src/model/electre.py', 'src/model/prereg.py', 'src/model/resample.py',
    'src/model/perturb.py', 'src/model/robust.py', 'src/model/revalidation.py',
    'src/model/revalidation_phase3.py', 'src/model/revalidation_phase4.py', 'src/model/revalidation_phase5.py',
    'src/run_model_revalidation.py',
    'scripts',
    'tests/test_model_revalidation.py', 'tests/test_model_prereg.py', 'tests/test_model_phase2.py',
    'tests/test_model_phase3.py', 'tests/test_model_phase4.py', 'tests/test_model_phase5.py',
    'notebooks/07_model_revalidation.ipynb', 'notebooks/08_interval_assignment.ipynb',
    'config/electre_tri_b_params.v1.2-candidates.yaml',
    'outputs/report/interval_diagnostic_cards_2026Q2.md',
    'src/model/revalidation_phase6.py', 'tests/test_model_phase6.py',
    'outputs/report/revalidation_history.md',
    # README.md 전체는 대상에 넣지 않는다 — Phase 6 이전부터 있던 기존 본문(16절)에
    # 이미 금지어 '실질생산'이 있어(우리가 쓴 문장이 아니다) 전체 스캔이 통과할 수 없다.
    # Phase 6가 덧붙인 절만 tests/test_model_phase6.py에서 별도로 검사한다.
    # outputs/report/reporting_rules.md는 코드블록 밖 본문만 검사한다(아래
    # allow_quoted_in_codeblock) — 금지 문구를 예시로 원문 인용하는 목적의 문서라서
    # 코드블록 밖에 그 인용이 새어 나오지 않는지를 검사 대상으로 삼는다.
    'outputs/report/reporting_rules.md',
    # outputs/tables/vrc4_provenance_evidence.csv는 넣지 않는다 — 그 excerpt 컬럼은
    # 기획 문서 원문을 판정 없이 그대로 발췌하는 것이 설계 목적이라, 원문에 금지어가
    # 있으면 그대로 옮겨진다(reporting_rules.md·model_wording_rules.json과 같은 이유).
)
SCAN_EXTENSIONS = {'.py', '.yaml', '.yml', '.md', '.csv', '.json', '.ipynb'}
EXCLUDED_PATHS = {RULES_PATH, SELF_PATH}
# 코드블록(```...```) 안의 내용은 검사에서 뺀다 — 금지 문구를 예시로 원문 인용해야
# 하는 문서 전용. 코드블록 밖 본문은 그대로 검사한다.
CODEBLOCK_EXEMPT_FILES = {'outputs/report/reporting_rules.md'}
_CODEBLOCK_RE = re.compile(r'```.*?```', re.DOTALL)


def _strip_codeblocks(text):
    return _CODEBLOCK_RE.sub('', text)


def load_rules():
    rules = json.loads(RULES_PATH.read_text(encoding='utf-8'))
    return rules['forbidden_literals'], rules['forbidden_patterns']


def iter_files(targets):
    for t in targets:
        path = (ROOT / t) if not Path(t).is_absolute() else Path(t)
        if not path.exists():
            continue
        if path.is_file():
            if path.resolve() not in EXCLUDED_PATHS and path.suffix in SCAN_EXTENSIONS:
                yield path
        else:
            for p in sorted(path.rglob('*')):
                if p.is_file() and p.suffix in SCAN_EXTENSIONS and p.resolve() not in EXCLUDED_PATHS:
                    yield p


def check(targets, allow_quoted_in_codeblock=True):
    """allow_quoted_in_codeblock=True(기본)이면 CODEBLOCK_EXEMPT_FILES에 있는 파일은
    ```...``` 코드블록 안의 내용을 빼고 검사한다(코드블록 밖 본문은 그대로 검사).
    """
    literals, patterns = load_rules()
    compiled = [re.compile(p) for p in patterns]
    violations = []
    for path in iter_files(targets):
        try:
            text = path.read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)
        scan_text = _strip_codeblocks(text) if (allow_quoted_in_codeblock and rel in CODEBLOCK_EXEMPT_FILES) else text
        for lit in literals:
            if lit in scan_text:
                line_no = scan_text[:scan_text.index(lit)].count('\n') + 1
                violations.append((rel, 'literal', lit, line_no))
        for pat, cre in zip(patterns, compiled):
            m = cre.search(scan_text)
            if m:
                line_no = scan_text[:m.start()].count('\n') + 1
                violations.append((rel, 'pattern', pat, line_no))
    return violations


def main():
    args = sys.argv[1:]
    allow_quoted = True
    if '--allow-quoted-in-codeblock' in args:
        args = [a for a in args if a != '--allow-quoted-in-codeblock']
        allow_quoted = True  # 명시적으로 켜도 기본값과 같다(항상 켜져 있음 — 플래그는 의도 표기용)
    targets = args if args else DEFAULT_TARGETS
    violations = check(targets, allow_quoted_in_codeblock=allow_quoted)
    if violations:
        print(f'금지어 위반 {len(violations)}건:')
        for rel, kind, needle, line_no in violations:
            print(f'  [{kind}] {rel}:{line_no} — {needle!r}')
        return 1
    print(f'금지어 위반 없음 ({len(list(iter_files(targets)))}개 파일 점검).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
