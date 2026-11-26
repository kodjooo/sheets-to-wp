"""Правильная метка языка не делает испанскую подпись португальской."""
from unittest.mock import Mock
import pytest
from publication_contract import validate_known_term_label
import trilingual_import as tri


@pytest.mark.parametrize('label,lang,source', [('Senderismo','pt','Walking'), ('Caminhada','en','Walking'),
                                            ('Caminhada','es','Walking'), ('Carrera en carretera','pt','Road running')])
def test_wrong_known_label_is_rejected(label, lang, source):
    with pytest.raises(ValueError, match='подпись'):
        validate_known_term_label(label, lang, source)


@pytest.mark.parametrize('label,lang,source', [('Caminhada','pt','Walking'), ('Walking','en','Walking'),
                                            ('Walk','en','Walking'), ('Senderismo','es','Walking'),
                                            ('Carrera en ruta','es','Road running'), ('Proper race name','pt','Proper race name')])
def test_correct_aliases_and_unknown_proper_names_are_allowed(label, lang, source):
    validate_known_term_label(label, lang, source)


def test_actual_ensure_terms_rejects_mislabeled_portuguese_response(monkeypatch):
    response = Mock(); response.json.return_value = {'items': [{'en': {'id': 61, 'name': 'Walking'},
        'pt': {'id': 15452, 'name': 'Senderismo'}, 'es': {'id': 15207, 'name': 'Senderismo'}}]}
    monkeypatch.setattr(tri.requests, 'post', Mock(return_value=response))
    with pytest.raises(ValueError, match='подпись'):
        tri.ensure_terms({'wp_url':'https://example.test','_import_jwt':'test'},
                         [('Running','Caminhada',{'en':'Walking','pt':'Caminhada','es':'Senderismo'})], {'Running':3})
