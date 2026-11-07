import json
import pytest
from country_profile import (PT, ES, profile_for_row, active_profile, activate_profile,
                             reset_profile, localized_prompt, primary_metadata, validate_spanish_row)
from preview_country_import import preview


def spanish_row():
    return {key: '' for key in ['COUNTRY', 'RACE NAME (ES)', 'WP PRODUCT ID ES',
            'WP VARIATION ID ES', 'WP PRODUCT ID EN', 'WP VARIATION ID EN',
            'SUMMARY (ES)', 'ORG INFO (ES)', 'BENEFITS (ES)', 'FAQ (ES)']} | {
                'COUNTRY': 'Spain', 'RACE NAME (ES)': 'Carrera de prueba',
                'LOCATION (CITY)': 'Badalona, Barcelona', 'STATUS': 'Revised (complete)'}


@pytest.fixture
def es_settings(monkeypatch):
    monkeypatch.setenv('ENABLE_SPAIN', 'true')
    monkeypatch.setenv('SPAIN_WP_HOST', 'dev.example.test')
    monkeypatch.setenv('CATEGORY_ROOT_MAP_JSON', json.dumps({'Running': {'en_parent_id': 1, 'es_parent_id': 2}}))


@pytest.mark.parametrize('value,expected', [('', PT), ('Portugal', PT), ('pt', PT), ('España', ES), ('ES', ES), ('Spain', ES)])
def test_country_detection(value, expected):
    assert profile_for_row({'COUNTRY': value}) == expected


def test_unknown_country_rejected():
    with pytest.raises(ValueError):
        profile_for_row({'COUNTRY': 'France'})


def test_es_never_reuses_portuguese_ids_or_content():
    row = {'WP PRODUCT ID PT': '123', 'SUMMARY (PT)': 'Português',
           'WP PRODUCT ID ES': '456', 'SUMMARY (ES)': 'Español'}
    assert ES.prepare_row(row)['WP PRODUCT ID PT'] == '456'
    assert ES.prepare_row(row)['SUMMARY (PT)'] == 'Español'
    assert ES.prepare_row({'WP PRODUCT ID PT': '123'})['WP PRODUCT ID PT'] == ''
    assert row['WP PRODUCT ID PT'] == '123'
    assert ES.column('WP VARIATION ID PT') == 'WP VARIATION ID ES'


def test_context_resets_between_countries():
    token = activate_profile(ES)
    try:
        assert active_profile() == ES
        assert 'испанском' in localized_prompt('на португальском')
    finally:
        reset_profile(token)
    assert active_profile() == PT
    assert localized_prompt('на португальском') == 'на португальском'


def test_es_preflight(es_settings):
    row = spanish_row()
    validate_spanish_row(row, row, 'https://dev.example.test')
    with pytest.raises(ValueError, match='SPAIN_WP_HOST'):
        validate_spanish_row(row, row, 'https://production.example.test')


def test_es_disabled_before_any_writes(es_settings, monkeypatch):
    monkeypatch.setenv('ENABLE_SPAIN', 'false')
    row = spanish_row()
    with pytest.raises(ValueError, match='выключена'):
        validate_spanish_row(row, row, 'https://dev.example.test')


def test_missing_es_column_rejected(es_settings):
    row = spanish_row()
    del row['WP PRODUCT ID ES']
    with pytest.raises(ValueError, match='WP PRODUCT ID ES'):
        validate_spanish_row(row, row, 'https://dev.example.test')


def test_missing_geography_rejected(es_settings):
    row = spanish_row()
    row['LOCATION (CITY)'] = ''
    with pytest.raises(ValueError, match='Муниципалитет'):
        validate_spanish_row(row, row, 'https://dev.example.test')


def test_preview_does_not_require_enabling_writes(es_settings, monkeypatch):
    monkeypatch.setenv('ENABLE_SPAIN', 'false')
    row = spanish_row()
    result = preview([row], row, 'https://dev.example.test')
    assert result[0]['ready']
    assert result[0]['languages'] == ['es', 'en']
    assert result[0]['metadata'] == [
        {'key': '_rf_location_country', 'value': 'es'},
        {'key': '_rf_location_municipality_name', 'value': 'Badalona'},
        {'key': '_rf_location_province_name', 'value': 'Barcelona'}]
    assert active_profile() == PT


def test_preview_reports_unknown_country_and_continues(es_settings):
    row = spanish_row()
    result = preview([dict(row, COUNTRY='unknown'), row], row, 'https://dev.example.test')
    assert not result[0]['ready']
    assert result[1]['ready']


def test_pt_metadata_unchanged():
    assert primary_metadata({'RF_MUNICIPALITY_NAME': 'Porto'}) == [
        {'key': '_rf_location_municipality_name', 'value': 'Porto'}]


def test_invalid_category_map_rejected(es_settings, monkeypatch):
    row = spanish_row()
    monkeypatch.setenv('CATEGORY_ROOT_MAP_JSON', '{"Running": []}')
    with pytest.raises(ValueError, match='es_parent_id'):
        validate_spanish_row(row, row, 'https://dev.example.test')


def test_spanish_province_matches_directory():
    from rf_spain_location import resolve_spanish_location
    assert resolve_spanish_location({'LOCATION (CITY)': 'Badalona, Barcelona'}) == ('Badalona', 'Barcelona')
    with pytest.raises(ValueError):
        resolve_spanish_location({'LOCATION (CITY)': 'Badalona', 'PROVINCE': 'Madrid'})


def test_spanish_homonyms_require_province():
    from rf_spain_location import directory, resolve_spanish_location
    index, _, provinces = directory()
    candidates = next(rows for rows in index.values() if len(rows) > 1 and len({r['prov'] for r in rows}) == len(rows))
    name = candidates[0]['name']
    with pytest.raises(ValueError, match='Неоднозначный'):
        resolve_spanish_location({'MUNICIPALITY': name})
    assert resolve_spanish_location({'MUNICIPALITY': name, 'PROVINCE': candidates[0]['prov']}) == (name, provinces[candidates[0]['prov']]['name'].split('/')[0].strip())


def test_bilingual_province_is_sent_in_bridge_supported_form():
    from rf_spain_location import resolve_spanish_location
    assert resolve_spanish_location({'MUNICIPALITY': 'Amurrio', 'PROVINCE': 'Álava / Araba'}) == ('Amurrio', 'Álava')


def test_country_run_filters_are_explicit(monkeypatch):
    from country_profile import process_country, positive_limit
    monkeypatch.setenv('PROCESS_COUNTRY', 'es')
    assert process_country() == 'es'
    monkeypatch.setenv('MAX_EVENTS_PER_RUN', '25')
    assert positive_limit('MAX_EVENTS_PER_RUN') == 25
    monkeypatch.setenv('PROCESS_COUNTRY', 'unknown')
    with pytest.raises(ValueError):
        process_country()
    monkeypatch.setenv('MAX_EVENTS_PER_RUN', '-1')
    with pytest.raises(ValueError):
        positive_limit('MAX_EVENTS_PER_RUN')


def test_spanish_prompt_translates_its_allowed_heading_examples():
    from pathlib import Path
    from country_profile import SPANISH_HEADINGS
    token = activate_profile(ES)
    try:
        root = Path(__file__).resolve().parents[1] / 'run/prompts'
        for name in ('assistant_system.txt', 'second_system.txt'):
            prompt = localized_prompt((root / name).read_text())
            assert all(label not in prompt for label in SPANISH_HEADINGS)
        assert 'Испанские эквиваленты' in localized_prompt('Португальские эквиваленты')
    finally:
        reset_profile(token)


def test_native_heading_normalization_preserves_facts_and_other_languages():
    from country_profile import normalize_native_headings
    source = {'org_info_pt':'<strong>Locais de partida/chegada:</strong> Calella <strong>Horários de partida por categoria/distância:</strong> 08:30', 'org_info':'Start/finish: Calella'}
    assert normalize_native_headings(source) == source
    token = activate_profile(ES)
    try:
        result = normalize_native_headings(source)
        assert result['org_info_pt'] == '<strong>Lugares de salida/llegada:</strong> Calella <strong>Horarios de salida por categoría/distancia:</strong> 08:30'
        assert result['org_info'] == source['org_info']
        assert source['org_info_pt'].startswith('<strong>Locais')
    finally:
        reset_profile(token)
