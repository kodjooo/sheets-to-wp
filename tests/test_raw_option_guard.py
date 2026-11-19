"""Старый ответ verified не доказывает правильность сырых языковых связей."""
from unittest.mock import Mock
import pytest
import trilingual_import as tri

@pytest.mark.parametrize('proof',[
    {'verified':True},
    {'verified':True,'raw_verified':False,'products_checked':1},
    {'verified':True,'raw_verified':True,'products_checked':0},
])
def test_final_pass_requires_raw_database_proof(monkeypatch,proof):
    response=Mock();response.json.return_value=proof
    monkeypatch.setattr(tri.requests,'post',Mock(return_value=response))
    with pytest.raises(ValueError,match='сырые связи'):
        tri.apply_options({'wp_url':'https://example.test','_import_jwt':'test'},
            {'pt':1},{'pt':[{'row_index':2,'attributes':[{'id':1,'term_id':133}]}]}, {'pt':{2:10}})


def test_intermediate_parent_assignment_does_not_require_finished_variations(monkeypatch):
    response=Mock();response.json.return_value={'verified':True,'raw_verified':False,'products_checked':0}
    monkeypatch.setattr(tri.requests,'post',Mock(return_value=response))
    tri.apply_options({'wp_url':'https://example.test','_import_jwt':'test'},
        {'pt':1},{'pt':[{'row_index':2,'attributes':[{'id':1,'term_id':133}]}]})
