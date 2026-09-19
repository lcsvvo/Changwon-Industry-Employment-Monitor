# -*- coding: utf-8 -*-
"""선택 PPI 매핑 확정 입력의 결측 안전성 테스트."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from model import cards, config, inputs, pipeline, ppi_aux  # noqa: E402

INDUSTRIES = ['기계', '석유화학', '기타']


def resolved(rows):
    return pd.DataFrame(rows, columns=['kicox_industry', 'confirmed'])


@pytest.mark.parametrize('value, expected', [
    (True, True), (False, False), (np.bool_(False), False), ('True', True), (' false ', False),
    (None, 'MISSING'), (np.nan, 'MISSING'), (pd.NA, 'MISSING'), ('', 'MISSING'),
    ('yes', 'INVALID'), (1, 'INVALID'), ('미확정', 'INVALID'),
])
def test_parse_confirmed_value(value, expected):
    assert ppi_aux.parse_confirmed_value(value) == expected


def test_missing_file_marks_confirmation_missing():
    status, summary = ppi_aux.mapping_confirmation(None, INDUSTRIES)
    assert all(v == ('CONFIRMATION_MISSING', None) for v in status.values())
    assert summary['input_status'] == 'NOT_AVAILABLE'


def test_partial_na_mixed_and_all_true():
    status, summary = ppi_aux.mapping_confirmation(resolved([
        ('기계', np.nan), ('석유화학', True), ('석유화학', False), ('기타', 'TRUE')]), INDUSTRIES)
    assert status['기계'] == ('CONFIRMATION_MISSING', None)
    assert status['석유화학'] == ('PARTIALLY_CONFIRMED', False)
    assert status['기타'] == ('CONFIRMED', True)
    assert summary['invalid_values'] == []


def test_invalid_value_is_not_silently_na():
    status, summary = ppi_aux.mapping_confirmation(resolved([
        ('기계', 'yes'), ('석유화학', False), ('기타', False)]), INDUSTRIES)
    assert status['기계'] == ('INVALID_CONFIRMED_VALUE', None)
    assert summary['invalid_values'] == [{'industry': '기계', 'value': 'yes'}]
    assert status['석유화학'] == ('NOT_CONFIRMED', False)


def test_missing_columns_are_reported():
    status, summary = ppi_aux.mapping_confirmation(pd.DataFrame({'kicox_industry': ['기계']}), INDUSTRIES)
    assert summary['input_status'] == 'SCHEMA_MISSING_COLUMNS'
    assert status['기계'][0] == 'CONFIRMATION_MISSING'


@pytest.mark.parametrize('status', list(config.PPI_CONFIRMATION_STATUSES) + [pd.NA])
def test_ppi_text_handles_nullable_values(status):
    row = pd.Series({'ppi_direction_status': 'NOT_COMPARABLE', 'ppi_comparison_reason': 'NO_MAPPING_CANDIDATE',
                     'ppi_mapping_confirmed': pd.NA, 'ppi_mapping_confirmation_status': status}, dtype=object)
    text = cards.ppi_text(row)
    assert 'nan' not in text and '<NA>' not in text
    expected = config.PPI_CONFIRMATION_LABELS['CONFIRMATION_MISSING' if status is pd.NA else status]
    assert expected in text


def test_is_true_never_evaluates_na_as_bool():
    assert cards.is_true(pd.NA) is False and cards.is_true(np.nan) is False and cards.is_true(None) is False
    assert cards.is_true(np.True_) is True and cards.is_true(False) is False


# ---------------------------------------------------------------- 파이프라인 수준
def _assert_outputs_generated(bundle):
    assert len(bundle['panel']) == 180 and len(bundle['cards']) == 10
    assert all(v['passed'] for v in bundle['report']['panel_validation'].values())
    assert bundle['cards_md'].count('### ') == 10


def test_pipeline_without_mapping_file():
    bundle = pipeline.run(ROOT, write=False, input_overrides={'ppi_mapping_resolved': None})
    _assert_outputs_generated(bundle)
    assert bundle['panel']['ppi_mapping_confirmation_status'].eq('CONFIRMATION_MISSING').all()
    assert bundle['panel']['ppi_mapping_confirmed'].isna().all()
    assert config.PPI_CONFIRMATION_LABELS['CONFIRMATION_MISSING'] in bundle['cards_md']
    checks = bundle['report']['crosschecks']
    assert checks['ppi_mapping_all_unconfirmed']['passed'] is False
    assert checks['ppi_mapping_confirmation']['input_status'] == 'NOT_AVAILABLE'
    assert checks['aux_summary_latest']['passed'] is False, '확정 여부를 알 수 없으면 보조요약 대조를 통과로 보지 않는다'


def test_pipeline_with_partial_na_mixed_and_invalid_values():
    frame = inputs.read_csv(ROOT / config.PATHS['ppi_mapping_resolved']).copy()
    frame['confirmed'] = frame['confirmed'].astype(object)
    frame.loc[frame['kicox_industry'] == '기계', 'confirmed'] = np.nan
    petro = frame.index[frame['kicox_industry'] == '석유화학']
    frame.loc[petro[0], 'confirmed'] = True
    frame.loc[petro[1], 'confirmed'] = False
    frame.loc[frame['kicox_industry'] == '철강', 'confirmed'] = 'yes'
    bundle = pipeline.run(ROOT, write=False, input_overrides={'ppi_mapping_resolved': frame})
    _assert_outputs_generated(bundle)
    status = bundle['panel'].drop_duplicates('industry').set_index('industry')['ppi_mapping_confirmation_status']
    assert status['기계'] == 'CONFIRMATION_MISSING'
    assert status['석유화학'] == 'PARTIALLY_CONFIRMED'
    assert status['철강'] == 'INVALID_CONFIRMED_VALUE'
    assert status['목재종이'] == 'NOT_CONFIRMED'
    conf = bundle['report']['crosschecks']['ppi_mapping_confirmation']
    assert conf['passed'] is False and conf['invalid_values'] == [{'industry': '철강', 'value': 'yes'}]
    assert config.PPI_CONFIRMATION_LABELS['INVALID_CONFIRMED_VALUE'] in bundle['cards_md']
