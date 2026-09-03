# Changwon Industry-Employment Monitor

2026년 창원시 AI·데이터 활용 공모전 프로젝트.

창원국가산단의 산업 성장과 고용 변화가 함께 움직이고 있는지를 분석하고, 업종별 차이를 바탕으로 산업·기업·인력 정책의 우선 검토 대상을 제시한다.

## Main Research Question

창원국가산단의 성장이 실제 일자리 증가로 이어지고 있는가?

## Analysis Flow

1. 창원국가산단 생산·가동률·업체 수 변화 확인
2. 생산과 고용 변화 비교
3. 업종별 산업·고용 유형 분류
4. 주요 업종의 변화 특성 분석
5. 가능할 경우 채용·훈련 데이터 결합
6. 산업별 정책 우선순위 제안
7. 「창원 산업·고용 국면판」 구축

## Main Data Candidates

- 창원국가산단 생산실적
- 창원국가산단 고용현황
- 창원국가산단 가동률
- 입주업체 및 가동업체 현황
- 생산자물가지수 등 가격지수
- 고용24 채용공고
- 고용24 직업훈련 과정
- KOSIS 관련 산업·고용 데이터

## Project Structure

```text
data/                  데이터 저장 및 관리
  raw/                 원본 데이터(기본적으로 Git 제외)
  processed/           전처리 완료 데이터
  external/            외부 기관 보조 데이터
notebooks/             탐색 및 분석 노트북
src/                   재사용 가능한 Python 모듈
dashboard/             창원 산업·고용 국면판
results/
  figures/             분석 결과 그래프
  tables/              분석 결과 표
docs/
  competition/         공모전 공고 및 공식 자료
  planning/            최종 주제와 프로젝트 기획
  references/          수상작·정책 등 참고자료
```

## Data Management

원본 데이터는 재다운로드 가능 여부와 파일 크기를 검토한 뒤 관리한다. `data/raw/`의 파일은 Git에서 제외하며, 데이터명·출처·다운로드 URL·수집 시점·사용 변수·저장 위치는 [`data/README.md`](data/README.md)에 기록한다.

## Status

프로젝트 초기 설정 단계이다. 분석 결과와 정책 제안은 데이터 수집·정제·검증 이후에 작성한다.
