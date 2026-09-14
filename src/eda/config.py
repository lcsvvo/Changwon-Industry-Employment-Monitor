# -*- coding: utf-8 -*-
"""EDA 공통 설정 — 경로·배색·분석 설정값.

notebooks/02_eda.ipynb Section 0의 설정 블록을 그대로 옮긴 것이다.
색상·라벨·설정값은 노트북과 동일하며 여기서 의미나 값을 바꾸지 않는다.
"""
from pathlib import Path
import warnings

# ---------------------------------------------------------------- 경로
_PANEL_REL = Path('data') / 'processed' / 'kicox' / 'changwon_state_panel.csv'


def find_root(start=None):
    """본분석 패널이 있는 프로젝트 루트를 찾는다(노트북 Section 0과 동일한 탐색)."""
    start = Path.cwd() if start is None else Path(start)
    candidates = [start, *start.parents, Path(__file__).resolve().parents[2]]
    root = next((p for p in candidates if (p / _PANEL_REL).is_file()), None)
    if root is None:
        raise FileNotFoundError('프로젝트의 data/processed/kicox/changwon_state_panel.csv가 필요합니다.')
    return root


def project_dirs(root, make=True):
    """노트북이 쓰는 DIR_PROC / DIR_FIG / DIR_TAB / DIR_REPORT를 돌려준다."""
    root = Path(root)
    dirs = {
        'root': root,
        'proc': root / 'data' / 'processed',
        'fig': root / 'outputs' / 'figures',
        'tab': root / 'outputs' / 'tables',
        'report': root / 'outputs' / 'report',
    }
    if make:
        for key in ['fig', 'tab', 'report']:
            dirs[key].mkdir(parents=True, exist_ok=True)
    return dirs


# ---------------------------------------------------------------- 배색 규칙
# 1) 국면 배색 — 좋음/나쁨의 신호등 연상을 줄인 청·청록·황·보라의 범주형 배색.
#    국면은 평가가 아닌 상태 분류이며, 노트북 전체가 이 딕셔너리 하나만 참조한다.
STATE_COLORS = {'S1': '#4C78A8', 'S2': '#72B7B2', 'S3': '#F2CF5B', 'S4': '#B279A2',
                'N': '#BDBDBD', 'INVALID': '#F2F2F2'}
STATE_LABELS = {'S1': 'S1 명목 생산액↑·고용↑', 'S2': 'S2 명목 생산액↑·고용↓',
                'S3': 'S3 명목 생산액↓·고용↑', 'S4': 'S4 명목 생산액↓·고용↓',
                'N': 'N 한 지표 이상 변화 0%', 'INVALID': 'INVALID 계산불가(결측)'}
STATES4 = ['S1', 'S2', 'S3', 'S4']
STATES5 = ['S1', 'S2', 'S3', 'S4', 'N']
STATES6 = ['S1', 'S2', 'S3', 'S4', 'N', 'INVALID']

# 2) 증감 방향 배색(Q2 전용) — 국면 배색과 의미가 겹치지 않도록 별도 색을 쓴다.
DELTA_COLORS = {'down': '#B4485F', 'up': '#3F6FA8', 'neutral': '#BFBFBF'}

# 3) 생산/고용 지표 배색 — 선 그래프에서 두 지표를 구분하는 고정 규칙.
SERIES_COLORS = {'production': '#2F5C8F', 'employment': '#9C5C86'}

# 4) 업종 배색(Q2-B 전용) — 주요 업종 + 나머지 합계. 색 수를 5개로 제한한다.
MAIN_COLORS = ['#2F4B7C', '#6A8EAE', '#A9BED0', '#4E6E5D']
REST_COLOR = '#C9C9C9'

# ---------------------------------------------------------------- 분석 설정값
# 값과 의미는 노트북과 동일하다. 여기서 조정하면 노트북 결과가 달라진다.
SHARE_MIN_RATIO = 0.30   # 기여율 표시 가능 기준: |순증감| / 업종별 증감 절대합
EDA_TOPN = 8             # 1-5에서 두 변수 각각 뽑는 극단 관측 수
SHARE_CUT = 5.0          # Q2 상세표시 대상: 고용비중(%) 하한
ABS_CUT = 300            # Q2 상세표시 대상: 최근 4분기 YoY 증감 절대합(명) 하한
RECENT_N = 4             # Q2 '최근 4분기' 창 길이 (RECENT4 = QUARTERS[-RECENT_N:])
MAIN_CAND_N = 4          # Q2-B 막대 구성에서 개별 표시하는 상위 업종 수
EDA_TOP_SHARE_N = 4      # 1-3에서 합계 비중을 보는 고용 상위 업종 수
SENSITIVITY_THRESHOLDS = [0.5, 1.0, 2.0]   # 중립구간 민감도(본분석 threshold=0은 유지)
# Q3 전환행렬: 행 관측이 이보다 적으면 1건이 행 비율을 5%p 이상 움직이므로 비율 대신 건수만 표시한다.
TRANSITION_MIN_ROW_N = 20

# 1-1에서 보는 핵심 변수
EDA_VARS = {'production': '명목 생산액(억원)', 'employment': '고용(명)',
            'production_yoy': '생산 YoY(%)', 'employment_yoy': '고용 YoY(%)'}

# ---------------------------------------------------------------- PPI 보조분석 설정
PPI_SERIES_KEYS = ['ORG_ID', 'TBL_ID', 'ITM_ID', 'C1', 'PRD_SE']
PPI_FILTER = {'ORG_ID': '301', 'TBL_ID': 'DT_404Y014', 'ITM_ID': '13103134604999', 'PRD_SE': 'M'}
PPI_C1_PREFIX = '13102134604ACC_CD.'
PPI_C1_SUFFIX = 'AA'
PPI_BASE_YEAR_UNIT = '2020=100'

# 코드/명칭은 결과 하드코딩이 아니라 분석에 사용한 입력 매핑이다.
PPI_MAPPING_ROWS = [
    ('기계', '311', '기계및장비', '분류가 가까운 단일 후보'),
    ('운송장비', '312', '운송장비', '전국 운송장비 전체 후보; 산단 품목 비중 미확인'),
    ('비금속', '306', '비금속광물제품', '분류가 가까운 단일 후보'),
    ('음식료', '301', '음식료품', '분류가 가까운 단일 후보'),
    ('목재종이', '303', '목재및종이제품', '분류가 가까운 단일 후보'),
    ('섬유의복', '3021', '섬유및의복', '가죽을 포함하는 상위 항목 대신 하위 후보'),
    ('철강', '3071', '철강1차제품', '비철금속을 포함하는 상위 지수 대신 철강 후보; 가공품 구성 미확인'),
    ('석유화학', '304', '석탄및석유제품', '품목별 가중치 없이 두 후보를 각각 적용'),
    ('석유화학', '305', '화학제품', '품목별 가중치 없이 두 후보를 각각 적용'),
    ('전기전자', '309', '컴퓨터전자및광학기기', '품목별 가중치 없이 두 후보를 각각 적용'),
    ('전기전자', '310', '전기장비', '품목별 가중치 없이 두 후보를 각각 적용'),
]
PPI_EXCLUDED_ROW = {'industry': '기타', 'mapping_reason': '대응 범위 근거 부족',
                    'mapping_use': 'excluded', 'main_analysis_eligible': False,
                    'sensitivity_eligible': False}

PPI_STATUS = ['모든 후보에서 유지', '모든 후보에서 반전', '후보별 방향 다름', '0% 경계 변화', '비교 불가']
PPI_COLORS = ['#E7ECEF', '#76619A', '#DDAE62', '#93A891', '#F8F8F8']
PPI_DISPLAY_NAMES = {
    'quarter': '분기', 'industry': '업종', 'state': '명목국면', 'production_yoy': '명목생산YoY(%)',
    'employment_yoy': '고용YoY(%)', 'ppi_items': '사용후보', 'ppi_lo': 'PPI변화율_최소(%)',
    'ppi_hi': 'PPI변화율_최대(%)', 'adjusted_lo': '조정YoY_최소(%)', 'adjusted_hi': '조정YoY_최대(%)',
    'status': '후보별방향', 'adjusted_state': '조정기준국면'}

# ---------------------------------------------------------------- 그림 기본 설정
FONT_CANDIDATES = ['Malgun Gothic', 'AppleGothic', 'NanumGothic',
                   'Noto Sans CJK KR', 'Noto Sans CJK JP', 'DejaVu Sans']


def setup_matplotlib():
    """한글 폰트와 그림 기본값을 노트북과 동일하게 설정한다.

    실행 환경(Windows / macOS / Linux)에 따라 설치된 한글 폰트가 다르므로
    사용 가능한 첫 폰트를 쓴다.
    """
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm

    warnings.filterwarnings('ignore', message='This figure includes Axes')
    for _font in Path('/usr/local/share/fonts').glob('*.ttf'):
        fm.fontManager.addfont(str(_font))
    installed = {f.name for f in fm.fontManager.ttflist}
    for cand in FONT_CANDIDATES:
        if cand in installed:
            plt.rcParams['font.family'] = [cand, 'sans-serif']
            break
    plt.rcParams['axes.unicode_minus'] = False
    plt.rcParams['figure.dpi'] = 100
    plt.rcParams['axes.grid'] = False
    plt.rcParams['font.size'] = 10
