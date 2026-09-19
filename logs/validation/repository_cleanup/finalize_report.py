"""Record submission cleanup counts, protected data and unchanged final results."""
import csv,hashlib,json,re,subprocess
from collections import Counter
from pathlib import Path
R=Path(__file__).resolve().parents[2];D=Path(__file__).resolve().parent
rows=list(csv.DictReader((D/'inventory.csv').open(encoding='utf-8-sig')))
supp=list(csv.DictReader((D/'supplemental_plan.csv').open(encoding='utf-8-sig')))
deleted={x['path'] for x in supp}
for x in rows:
    if x['path'] in deleted:x.update(category='DELETE_LOW_VALUE',target='',reason='Unreferenced regenerable candidate figure')
    if x['path']=='scripts/submission_cleanup_plan.py':x.update(category='ARCHIVE_EXPERIMENT',target='logs/repository_cleanup/submission_cleanup_plan.py',reason='One-time cleanup audit, not current pipeline')
with (D/'inventory.csv').open('w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
baseline=json.loads((D/'baseline.json').read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert all(sha(R/'outputs/decision_support_final'/n)==h for n,h in baseline['final_csv_sha256'].items())
raw=[x for x in rows if x['path'].startswith('data/raw/')]
assert all(sha(R/x['path'])==x['sha256'] for x in raw)
for n in ['src/model/triage_rule.py','src/model/triage_delivery.py']:
    assert sha(R/n)==next(x['sha256'] for x in rows if x['path']==n)
ops=list(csv.DictReader((D/'operations.csv').open(encoding='utf-8-sig')))
assert all((R/x['target']).is_file() for x in ops if x['category']=='ARCHIVE_EXPERIMENT')
generated=list(csv.DictReader((D/'generated_cleanup.csv').open(encoding='utf-8-sig')))
excluded={'.git','.venv','private','.claude'}
files=[p for p in R.rglob('*') if p.is_file() and not any(x in excluded for x in p.relative_to(R).parts)]
nb=json.loads((D/'core_notebook_execution.json').read_text());delivery=json.loads((R/'outputs/decision_support_final/audit_v3/delivery_verification.json').read_text())
(D/'REPORT.md').touch();(D/'summary.json').touch()
broken=[]
for p in [R/'README.md',R/'PROJECT_STRUCTURE.md',R/'logs/README.md',*list((R/'outputs/decision_support_final').glob('*.md'))]:
    for target in re.findall(r'\]\(([^)]+)\)',p.read_text(encoding='utf-8-sig')):
        if re.match(r'\w+://',target) or target.startswith('#'):continue
        t=target.split('#')[0]
        if not (p.parent/t).exists():broken.append(dict(file=str(p.relative_to(R)),target=target))
assert not broken,broken
status=lambda:subprocess.check_output(['git','status','--short','--untracked-files=all'],cwd=R,text=True).splitlines()
# Create both report files before taking the final Git/file-count snapshot.
(D/'REPORT.md').touch();(D/'summary.json').touch()
s=status();files=[p for p in R.rglob('*') if p.is_file() and not any(x in excluded for x in p.relative_to(R).parts)]
counts=Counter(x['category'] for x in rows);oc=Counter(x['category'] for x in ops)
summary=dict(audited_files_before=baseline['files'],files_after=len(files),git_changes_before=633,git_changes_after=len(s),git_tracked_modified=sum(not l.startswith('??') for l in s),git_untracked=sum(l.startswith('??') for l in s),classification=dict(counts),moved=oc['ARCHIVE_EXPERIMENT'],deleted_original=oc['DELETE_LOW_VALUE'],deleted_regenerated=len(generated),raw_files_preserved=len(raw),final_csv_identical=len(baseline['final_csv_sha256']),core_rule_and_delivery_unchanged=True,notebooks=nb,delivery=delivery,broken_active_markdown_links=broken,review_uncertain=[])
(D/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
report=f'''# 최종 제출용 저장소 정리 보고

## 1. 정리 전 상태

- 감사 파일 {baseline['files']}개 → 현재 {len(files)}개. `.git`, `.venv`, `private`, `.claude` 제외, 원천데이터 포함. 최초 감사 도구 1개가 포함된 수치다.
- 최초 Git 변경 633개. 감사 도구를 만든 직후 명세의 변경 수는 634개다.
- 후보 감사·재검증·QP 반복 출력이 메인에 혼재했고, 최종 검증이 504개 과거 파일과 snapshot 경로에 의존했다.

## 2. KEEP_FINAL

- 최초 감사 대상 중 {counts['KEEP_FINAL']}개 유지. 원천데이터 {len(raw)}개는 해시가 모두 그대로다.
- `src/model/triage_rule.py`, `triage_delivery.py`, `triage_audit.py`, `src/run_triage_rule.py`: 현재 단계·카드·독립 검산·고정 민감도 재현. 규칙 및 카드 구현은 정리 전 해시와 동일하다.
- `src/build_*.py`, `qa_master.py`, `src/eda/`, Q1/Q2/Q3 분석: raw → processed → 본분석 경로.
- notebooks 01·02·03·11, 현재 테스트 3개 모듈, 최종 실행/검증 스크립트 4개.
- `outputs/decision_support_final/` 핵심 표·카드·규칙 출처·보고서·HTML 및 Q1~Q3/EDA 결과. CSV는 분석·검증, JSON은 구조화 인계, MD/HTML은 검토용이다.
- 새 `data/reference/triage_history/` 4개 최소 기준표는 보고서 과거 비교용이며 현재 판정에 사용하지 않는다.

## 3. ARCHIVE_EXPERIMENT

- 실제 이동 {oc['ARCHIVE_EXPERIMENT']}개(최초 감사 분류 {counts['ARCHIVE_EXPERIMENT']}개와 이후 생성된 일회성 도구 1개).
- `logs/experiments/electre_mrsort/`: 후보 구현·실행 진입점·전용 테스트와 fixtures·입력.
- `logs/experiments/sensitivity_history/`: 원본 v3 코드와 대표 민감도.
- `logs/audits/independent_audit/`: REPORT/findings/parameter spaces/연속공간 인증서 등 핵심 감사 근거.
- `logs/archived_outputs/`: 후보 선택·비채택·강건성 결론의 최소 표.
- `logs/legacy_notebooks/`: 04~10; `legacy_scripts/`, `legacy_configs/`: 역사 도구와 실제 설정.
- 이동 대상은 모두 Git untracked여서 native Move-Item을 사용했다. tracked 대상이면 git mv를 사용하는 적용 절차를 마련했다.

## 4. DELETE_LOW_VALUE

- 기존 파일 {oc['DELETE_LOW_VALUE']}개 삭제(주 분류 876개 + 추가 후보 그림 17개). 검증이 다시 만든 캐시·중간본 {len(generated)}개도 별도로 삭제했다.
- 중복 baseline/replay snapshot, raw rebuild 사본, 반복 CSV/JSON/HTML, 후보 trace/grid/checkpoint, 캐시·로그, unused candidate templates, 과거 실행 manifest.
- 대표 사례: independent_audit/baseline/pipeline 출력 복제, qp_runs/revalidation_runs 상세 반복 결과, outputs/runs 실행별 복제, 참조 없는 ELECTRE/interval/revalidation 그림.
- 원천데이터·docs 원본·Git tracked 파일 삭제 0개. 불확실한 중요 원본을 삭제하지 않았다.

## 5. 최종 디렉터리 구조

```text
data/{{raw,processed,reference/triage_history}}
src/
  build_*.py / qa_master.py / eda/ / q*_analysis.py
  model/{{triage_rule,triage_delivery,triage_audit}}.py
  run_triage_rule.py
notebooks/ 01 / 02 / 03 / 11
scripts/ 최종 build / execute / raw rebuild / verify
tests/ pipeline_rules / triage_rule / diagnostic_card
outputs/ decision_support_final / tables / figures / report
logs/
  preprocessing / experiments / audits / archived_outputs
  legacy_notebooks / legacy_scripts / legacy_configs
  repository_cleanup
docs/ 원본 기획·방법론·근거
```

최종 엔진은 YAML 설정을 사용하지 않으므로 config/는 제거했다. 보존 자료가 없는 _review 등 디렉터리를 만들지 않았다.

## 6. 의존성 수정

- model/__init__의 과거 모듈 eager import 제거.
- 최종 audit/runner가 과거 outputs 및 electre_input_panel 대신 최소 비교 기준표를 읽도록 수정.
- final audit/verify의 504개 역사 파일 보호명세 의존성을 제거하고 현재 입력·코드 해시, scalar 검산, 카드 일치 검증 유지.
- notebook/report generator의 baseline 경로·보존 설명 수정; README와 PROJECT_STRUCTURE 재작성, 모형 역할 문서 경로 수정.
- raw rebuild는 TemporaryDirectory에서 수행하고 최종 비교 요약만 보존. 반복 데이터 사본이 저장소에 쌓이지 않는다.
- 현재 Markdown 링크의 깨진 참조 0개. 과거 자료의 당시 경로·해시는 역사 기록이며 전체 과거 실행 배포본은 아님을 logs/README에 명시했다.

## 7. 실행 검증

- 데이터 구축·QA·보조 검증: 01 노트북 정상 실행. 원자료 독립 재구축 master 340행/전체 34행/상태 180행 일치.
- EDA 02와 Q1/Q2/Q3 03 정상 실행. 실행 증거는 core_notebook_execution.json.
- 최종 triage와 진단카드 10개 정상 생성. 11 노트북 16개 코드 셀 오류 0, HTML 생성.
- 현재 전체 suite 27 passed, skipped 0. 그중 triage/card 15 passed(중복 합산하지 않음). 후보 테스트는 후보 코드와 함께 보존.
- 정리 전 최종 CSV 20개가 모두 바이트 단위 동일. 관찰 128/추가확인 35/우선점검 17, 최신 2026Q2 기계·목재종이 우선점검 유지.
- 재실행으로 생긴 날짜·출력 metadata만 달라진 원래 tracked 노트북 01~03 및 QA/출처표는 시작 시 변경이 없던 공유본으로 복원했다. 실행 통과 기록은 보존했다.

## 8. Git 정리 결과

- 변경파일 633 → {len(s)}개. tracked 수정 {summary['git_tracked_modified']}개, untracked {summary['git_untracked']}개. 자동 커밋·전체 staging 없음.
- 추가 ignore: temp/, 최종 검증의 임시 raw_rebuild/, jupyter/, jupyter_runtime/, 반복 *tests.xml.
- 기존 pycache/checkpoint/pytest cache/coverage/tmp/log ignore 유지. 최종 CSV/JSON/MD/HTML 및 핵심 역사 증빙은 ignore하지 않음.
- 남은 untracked는 최종 구현·결과 및 선정된 후보 증빙이다. Git 경고는 사용자 홈의 global ignore 접근 권한에 관한 것이며 status 수집·검증은 성공했다.
- 자동 승인 검토가 최초 일괄 정리를 거부했으나, 파일별 참조 검증·tracked 원본 보호·CSV 동일성 근거를 보강해 재검토 승인 후 실행했다. 남은 승인 차단 없음.

## 9. 남은 REVIEW_UNCERTAIN

없음. 미해결 현재 실행 의존성 0개. 원자료 배포는 기존처럼 data/README 안내에 따라 별도로 확보해야 한다.

파일별 분류·원본 해시는 inventory.csv, 실제 이동/삭제는 operations.csv, 개별 의존성 검증은 dependency_validation.json, 추가 그림 검증은 supplemental_plan.csv, 재생성 파일 정리는 generated_cleanup.csv, 요약은 summary.json을 참고한다.
'''
(D/'REPORT.md').write_text(report,encoding='utf-8')
print(json.dumps({k:v for k,v in summary.items() if k not in {'notebooks','delivery'}},ensure_ascii=False,indent=2))
