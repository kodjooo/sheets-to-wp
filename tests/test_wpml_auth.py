"""WPML использует тот же JWT, что и запись ACF; ошибки связи не скрываются."""
from unittest.mock import Mock
import pytest
import requests
import _3_create_product as products
import _4_create_translation as translations


@pytest.mark.parametrize('hook_ok', [True, False])
def test_product_translation_uses_jwt_and_does_not_hide_link_failure(monkeypatch, hook_ok):
    created = Mock(status_code=201)
    created.json.return_value = {'id': 99}
    linked = Mock(ok=hook_ok, status_code=200 if hook_ok else 403)
    if not hook_ok:
        linked.raise_for_status.side_effect = requests.HTTPError('WPML forbidden')
    post = Mock(side_effect=[created, linked])
    original = Mock()
    original.json.return_value = {'slug': 'race'}
    monkeypatch.setattr(translations.requests, 'get', Mock(return_value=original))
    monkeypatch.setattr(translations.requests, 'put', Mock(return_value=Mock(status_code=200)))
    monkeypatch.setattr(translations.requests, 'post', post)
    monkeypatch.setattr(translations, 'get_jwt_token', lambda: 'test-jwt')
    monkeypatch.setattr(translations, 'send_acf_data_translation', Mock(return_value=Mock(status_code=200)))
    config = {'wp_url':'https://example.test', 'consumer_key':'test', 'consumer_secret':'test',
              'wp_admin_user':'test', 'wp_admin_pass':'test'}
    persisted = []
    if hook_ok:
        assert translations.create_product_translation_en({'RACE NAME':'Race'}, 42, config=config, on_created=persisted.append) == 99
    else:
        with pytest.raises(Exception, match='WPML forbidden'):
            translations.create_product_translation_en({'RACE NAME':'Race'}, 42, config=config, on_created=persisted.append)
    assert persisted == [99]
    kwargs = post.call_args_list[-1].kwargs
    assert kwargs['headers'] == {'Authorization':'Bearer test-jwt'}
    assert 'auth' not in kwargs


def test_category_translation_uses_jwt(monkeypatch):
    source = Mock()
    source.json.return_value = {'name':'Running', 'translations':{}}
    monkeypatch.setattr(products.requests, 'get', Mock(return_value=source))
    monkeypatch.setattr(products, '_translate_category_name_to_pt', lambda *a: 'Carreras')
    monkeypatch.setattr(products, 'get_category_id_by_name', lambda *a,**k: 123)
    monkeypatch.setattr(products, 'get_jwt_token', lambda: 'test-jwt')
    post = Mock(return_value=Mock(status_code=200))
    monkeypatch.setattr(products.requests, 'post', post)
    assert products.ensure_category_translation(42,'en','es') == 123
    assert post.call_args.kwargs['headers']['Authorization']=='Bearer test-jwt'
    assert 'auth' not in post.call_args.kwargs
