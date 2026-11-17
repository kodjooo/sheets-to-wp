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
