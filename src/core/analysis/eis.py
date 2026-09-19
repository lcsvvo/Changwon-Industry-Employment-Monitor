# -*- coding: utf-8 -*-
"""Section 6 — EIS 보조분석(모집단이 다른 두 고용 지표의 증감 방향 비교).

notebooks/02_eda.ipynb 셀 61의 계산을 그대로 옮겼다.
수준값을 합산하거나 한 통계를 다른 통계의 정확성 검증 기준으로 쓰지 않는다.
"""
from pathlib import Path

import numpy as np
import pandas as pd


def load_eis(eis_proc_path, eis_raw_path, record_input=None):
    """EIS 검증 패널이 있으면 그대로 쓰고, 없으면 원자료에서 분기 YoY를 만든다."""
    eis_proc_path, eis_raw_path = Path(eis_proc_path), Path(eis_raw_path)
    if eis_proc_path.is_file():
        eis = pd.read_csv(eis_proc_path)
        if record_input is not None:
            record_input(eis_proc_path, '기존 EIS 검증 패널')
    else:
        eis = pd.read_csv(eis_raw_path, comment='#').sort_values('quarter')
        if record_input is not None:
            record_input(eis_raw_path, '공유된 EIS 분기말 인원')
        assert not eis.quarter.duplicated().any()
        es = eis.set_index(pd.PeriodIndex(eis.quarter, freq='Q')).changwon_manufacturing
        es = es.reindex(pd.period_range(es.index.min(), es.index.max(), freq='Q'))
        eis_yoy = (es / es.shift(4) - 1) * 100
        eis = pd.DataFrame({'quarter': es.index.astype(str),
                            'eis_manufacturing_yoy_pct': eis_yoy.values})
    return eis


def compare(eis, mfg, lag_mfg):
    """KICOX 산단 제조업 고용 YoY와 EIS 창원시 제조업 피보험자 YoY를 합친다.

    KICOX는 패널 내부 lag4 합계를 사용해 첫 분석연도의 값을 잃지 않는다.
    """
    mfg_yoy = mfg.mfg_emp_delta / lag_mfg * 100
    merged = (eis[['quarter', 'eis_manufacturing_yoy_pct']]
              .merge(mfg_yoy.rename('kicox_mfg_yoy').reset_index(), on='quarter', how='inner').dropna())
    merged['부호일치'] = np.sign(merged.kicox_mfg_yoy) == np.sign(merged.eis_manufacturing_yoy_pct)
    return mfg_yoy, merged


def eis_results(merged):
    """results_summary['eis']에 들어가는 값."""
    return {'n_comparable': len(merged), 'n_same': int(merged.부호일치.sum()),
            'start': merged.quarter.min(), 'end': merged.quarter.max()}
