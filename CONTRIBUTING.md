# Git 브랜치 및 협업 가이드

팀원이 같은 파일을 안전하게 수정하고 변경 내용을 검토할 수 있도록 `main` 브랜치에 직접 작업하지 않고, 작업별 브랜치를 만들어 Pull Request로 합칩니다.

## 기본 흐름

```text
main 최신화
  → 작업 브랜치 생성
  → 파일 수정 및 검증
  → commit
  → GitHub에 push
  → Pull Request 생성
  → 검토 후 main에 merge
```

## 1. 처음 한 번만: 저장소 복제

GitHub Collaborator 초대를 수락한 뒤 실행합니다.

```bash
git clone https://github.com/lcsvvo/Changwon-Industry-Employment-Monitor.git
cd Changwon-Industry-Employment-Monitor
```

이미 저장소를 복제했다면 이 단계는 반복하지 않습니다.

## 2. 작업 시작 전: main 최신화

새 작업을 시작할 때 항상 로컬 `main`을 원격 저장소의 최신 상태로 맞춥니다.

```bash
git switch main
git pull origin main
```

수정 중인 파일이 있어 `git switch`가 실패하면 변경사항을 먼저 커밋하거나 임시 저장해야 합니다. 다른 사람의 변경을 덮어쓰기 위해 강제 명령을 사용하지 않습니다.

## 3. 작업 브랜치 만들기

최신 `main`에서 작업 목적이 드러나는 브랜치를 만듭니다.

```bash
git switch -c feature/작업명
```

예시:

```bash
git switch -c feature/collect-production-data
git switch -c feature/employment-eda
git switch -c fix/employment-unit
git switch -c docs/update-data-catalog
```

권장 접두사:

| 접두사 | 용도 | 예시 |
| --- | --- | --- |
| `feature/` | 데이터 수집, 분석, 기능 추가 | `feature/industry-classification` |
| `fix/` | 코드·계산·문서 오류 수정 | `fix/production-growth-rate` |
| `docs/` | README와 문서 변경 | `docs/add-analysis-guide` |
| `chore/` | 환경 설정과 구조 정리 | `chore/update-dependencies` |

브랜치 이름은 영문 소문자와 하이픈 사용을 권장합니다. 서로 다른 작업은 하나의 브랜치에 섞지 않습니다.

## 4. 작업 내용 확인 및 커밋

변경된 파일을 먼저 확인합니다.

```bash
git status
git diff
```

원본 데이터, 개인정보, API 키, ZIP, 가상환경 등이 포함되지 않았는지 확인한 뒤 필요한 파일만 선택해 추가합니다.

```bash
git add notebooks/01_production_eda.ipynb
git add data/README.md
git status
```

`git add .`도 사용할 수 있지만 의도하지 않은 파일까지 포함될 수 있으므로 `git status`를 반드시 다시 확인합니다.

커밋 메시지는 변경 목적이 보이도록 작성합니다.

```bash
git commit -m "feat: add production data exploration"
```

메시지 예시:

- `feat: add industrial production preprocessing`
- `fix: correct employment unit conversion`
- `docs: update data source catalog`
- `chore: add analysis dependency`

## 5. 작업 브랜치 push

처음 push할 때:

```bash
git push -u origin feature/작업명
```

같은 브랜치에서 추가 커밋을 push할 때:

```bash
git push
```

`feature/작업명`은 실제 사용 중인 브랜치 이름으로 바꿉니다.

## 6. Pull Request 만들기

GitHub 저장소에서 방금 push한 브랜치의 **Compare & pull request**를 선택합니다.

- base 브랜치: `main`
- compare 브랜치: 본인의 작업 브랜치

Pull Request 설명에는 다음 내용을 적습니다.

1. 작업 목적
2. 변경한 파일과 핵심 내용
3. 사용한 데이터와 출처
4. 실행 또는 검증 방법
5. 확인이 필요한 부분

예시:

```text
## 목적
창원국가산단 생산실적 데이터의 구조와 결측치를 확인했습니다.

## 변경 내용
- 생산실적 EDA Notebook 추가
- data/README.md에 출처와 수집일 기록

## 검증 방법
Notebook의 Run All을 실행해 오류가 없는지 확인했습니다.

## 확인 필요
업종 분류가 연도별로 동일한지 추가 확인이 필요합니다.
```

검토가 끝나면 GitHub에서 Pull Request를 `main`에 merge합니다. merge 후 작업 브랜치는 삭제해도 됩니다.

## 7. 작업 중 main 변경사항 반영

다른 Pull Request가 먼저 합쳐졌다면 작업 브랜치에 최신 `main`을 반영합니다.

```bash
git switch main
git pull origin main
git switch feature/작업명
git merge main
```

충돌이 발생하면 충돌 표시가 있는 파일을 열어 필요한 내용을 남기고 저장한 뒤 다음과 같이 마무리합니다.

```bash
git add 충돌을_해결한_파일
git commit
git push
```

어느 내용을 남겨야 할지 불분명하면 임의로 삭제하지 말고 해당 파일을 수정한 팀원과 확인합니다.

## 8. merge 후 다음 작업 시작

Pull Request가 merge된 뒤 로컬을 정리합니다.

```bash
git switch main
git pull origin main
git branch -d feature/작업명
```

새로운 작업은 다시 최신 `main`에서 별도 브랜치를 만들어 시작합니다.

## 파일별 기본 규칙

- 원본 데이터는 `data/raw/`에 두며 GitHub에는 올리지 않습니다.
- 데이터 출처와 수집 정보는 `data/README.md`에 기록합니다.
- 탐색 분석은 `notebooks/`, 재사용 코드는 `src/`에 둡니다.
- 개인 PC의 절대경로 대신 저장소 기준 상대경로를 사용합니다.
- Notebook은 Pull Request 전에 위에서 아래까지 다시 실행합니다.
- 그래프와 표에는 기간, 단위, 출처를 표시합니다.
- 검증 전 수치나 해석을 확정된 결론처럼 작성하지 않습니다.

## 자주 사용하는 명령어

```bash
# 현재 브랜치와 변경 파일 확인
git status

# 로컬 브랜치 목록 확인
git branch

# 원격 브랜치까지 확인
git branch -a

# 변경 내용 확인
git diff

# 최근 커밋 확인
git log --oneline -10

# 현재 브랜치를 원격에 push
git push
```

`git reset --hard`, 강제 push(`git push --force`), 추적 중인 파일의 강제 삭제는 다른 사람의 작업이나 Git 이력을 잃게 할 수 있으므로 팀 합의 없이 사용하지 않습니다.
