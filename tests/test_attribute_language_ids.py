"""Одинаковые подписи PT/EN не должны определять язык значений карточки."""
from unittest.mock import Mock
import pytest
import _5_taxonomy_and_attributes as attrs
import _3_create_product as products


@pytest.mark.parametrize("lang,term_id", [("pt", 133), ("en", 57), ("es", 12131)])
def test_parent_uses_exact_language_ids(monkeypatch, lang, term_id):
    monkeypatch.setattr(attrs, "get_or_create_attribute", lambda name: 3)
    monkeypatch.setattr(attrs, "get_or_create_attribute_term", lambda aid, value, lang: term_id)
    monkeypatch.setattr(products, "get_jwt_token", lambda: "test-token")
    response = Mock()
    response.json.return_value = {"verified": True}
    post = Mock(return_value=response)
    monkeypatch.setattr(attrs.requests, "post", post)
    unsafe_write = Mock(side_effect=AssertionError("Не отправлять неоднозначные названия в WC REST"))
    monkeypatch.setattr(attrs, "_safe_wc_request", unsafe_write)

    assert attrs.assign_attributes_to_product(123, {"Distance": ["10 km", "10 km"]}, lang=lang)
    assert post.call_count == 2
    for call, verify_only in zip(post.call_args_list, (False, True)):
        data = call.kwargs["json"]
        assert data == {"items": [{"product_id": 123, "language": lang,
                                  "attributes": [{"id": 3, "term_ids": [term_id]}],
                                  "variations": []}], "verify_only": verify_only}
    unsafe_write.assert_not_called()


def test_parent_language_verification_failure_is_not_ignored(monkeypatch):
    monkeypatch.setattr(attrs, "get_or_create_attribute", lambda name: 3)
    monkeypatch.setattr(attrs, "get_or_create_attribute_term", lambda *a, **kw: 133)
    monkeypatch.setattr(products, "get_jwt_token", lambda: "test-token")
    response = Mock()
    response.json.return_value = {"verified": False}
    monkeypatch.setattr(attrs.requests, "post", Mock(return_value=response))
    with pytest.raises(ValueError, match="не подтвердил"):
        attrs.assign_attributes_to_product(123, {"Distance": "10 km"}, lang="pt")


def test_term_list_excludes_wpml_language_fallback(monkeypatch):
    response = Mock()
    response.json.return_value = [
        {"id": 11, "name": "1.6 km", "lang": "pt"},
        {"id": 22, "name": "1.6 km", "lang": "en"},
        {"id": 33, "name": "1.6 km"},
    ]
    monkeypatch.setattr(attrs, "_safe_wc_request", Mock(return_value=response))
    assert attrs._list_all_attribute_terms(3, lang="en") == [
        {"id": 22, "name": "1.6 km", "lang": "en"}
    ]


def test_equal_label_resolves_requested_language(monkeypatch):
    response = Mock()
    response.json.return_value = [
        {"id": 11, "name": "1.6 km", "lang": "pt"},
        {"id": 22, "name": "1.6 km", "lang": "en"},
    ]
    request = Mock(return_value=response)
    monkeypatch.setattr(attrs, "_safe_wc_request", request)
    assert attrs.get_or_create_attribute_term(3, "1.6 km", lang="en") == 22
    assert request.call_count == 1


def test_new_term_has_explicit_language_and_unique_slug(monkeypatch):
    monkeypatch.setattr(attrs, "_list_all_attribute_terms", lambda *a, **kw: [])
    response = Mock()
    response.json.return_value = {"id": 22, "name": "1.6 km", "lang": "en"}
    request = Mock(return_value=response)
    monkeypatch.setattr(attrs, "_safe_wc_request", request)
    assert attrs.get_or_create_attribute_term(3, "1.6 km", lang="en") == 22
    payload = request.call_args.kwargs["data"]
    assert payload["lang"] == "en" and payload["slug"].endswith("-en")


def test_term_exists_other_language_is_never_used(monkeypatch):
    monkeypatch.setattr(attrs, "_list_all_attribute_terms", lambda *a, **kw: [])
    response = Mock(status_code=400)
    response.raise_for_status.side_effect = attrs.requests.HTTPError("term_exists")
    response.json.return_value = {"code": "term_exists", "data": {"resource_id": 11}}
    monkeypatch.setattr(attrs, "_safe_wc_request", Mock(return_value=response))
    with pytest.raises(attrs.requests.HTTPError):
        attrs.get_or_create_attribute_term(3, "1.6 km", lang="en")
