import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'run'))
from source_http import source_headers, validate_source_response, DEFAULT_ES_USER_AGENT


def test_spanish_profile_does_not_change_portuguese_sources():
    headers = {'User-Agent': 'legacy', 'Accept': 'text/html'}
    assert source_headers('https://running.life/es/carrera/test', headers)['User-Agent'] == DEFAULT_ES_USER_AGENT
    assert source_headers('https://web.rockthesport.com/es/event/test', headers)['User-Agent'] == DEFAULT_ES_USER_AGENT
    assert source_headers('https://portugalrunning.com/test', headers) == headers
    assert source_headers('https://running.life.example.org/test', headers) == headers
    assert headers['User-Agent'] == 'legacy'


def test_explicit_source_identity():
    with patch.dict('os.environ', {'ES_HTTP_USER_AGENT': 'RaceFinder/custom'}):
        assert source_headers('https://running.life/', {})['User-Agent'] == 'RaceFinder/custom'


def test_success_status_challenge_is_not_content():
    with pytest.raises(ValueError, match='страницу защиты'):
        validate_source_response('https://running.life/test', '<title>Just a moment...</title>', {})
    with pytest.raises(ValueError):
        validate_source_response('https://web.rockthesport.com/test', '', {'cf-mitigated': 'challenge'})
    validate_source_response('https://running.life/test', '<h1>Race</h1>', {})
