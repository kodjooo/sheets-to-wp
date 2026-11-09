from unittest.mock import Mock
import pytest
import trilingual_import as tri


@pytest.mark.parametrize('string_ids', [False, True])
def test_readback_preserves_all_editorial_statuses_without_writes(monkeypatch, string_ids):
    states = {10:'draft', 11:'pending', 12:'publish', 13:'private', 14:'future'}
    ids = {str(pid):str(pid) if string_ids else pid for pid in states}
    def get(url, **kwargs):
        pid = int(url.rsplit('/',1)[1]);r = Mock()
        r.json.return_value = {'id':pid,'status':states[pid],'slug':'','permalink':'https://example.test/?p='+str(pid)}
        return r
    monkeypatch.setattr(tri.requests,'get',get)
    put=Mock(side_effect=AssertionError('Статус не должен записываться'))
    monkeypatch.setattr(tri.requests,'put',put)
    out=tri.read_imported_products({'wp_url':'https://example.test','consumer_key':'key','consumer_secret':'secret'},ids)
    assert {int(k):p['status'] for k,p in out.items()} == states
    put.assert_not_called()


@pytest.mark.parametrize('product', [{'id':10,'status':'trash'},{'id':11,'status':'draft'}])
def test_readback_rejects_deleted_or_wrong_product(monkeypatch,product):
    r=Mock();r.json.return_value=product
    monkeypatch.setattr(tri.requests,'get',Mock(return_value=r))
    with pytest.raises(ValueError):
        tri.read_imported_products({'wp_url':'https://example.test','consumer_key':'key','consumer_secret':'secret'},{'es':10})


@pytest.mark.parametrize('lang', ['pt','es','en'])
def test_primary_creation_always_requests_draft(monkeypatch,lang):
    import json
    import _3_create_product as products
    from country_profile import CountryProfile,activate_profile,reset_profile
    token=activate_profile(CountryProfile('es' if lang=='es' else 'pt','spain' if lang=='es' else 'portugal',lang))
    class Captured(Exception): pass
    captured=[]
    def post(url,**kwargs):
        captured.append(json.loads(kwargs['data']))
        raise Captured()
    monkeypatch.setattr(products.requests,'post',post)
    try:
        with pytest.raises(Captured):products.create_product({'RACE NAME':'Test','CATEGORY_IDS_PT':[{'id':1}],'MUNICIPALITY':'Alovera','PROVINCE':'Guadalajara'})
    finally:reset_profile(token)
    assert captured[0]['status']=='draft' and captured[0]['lang']==lang


def test_primary_update_never_sends_editorial_status(monkeypatch):
    import json
    import _3_create_product as products
    put=Mock(return_value=Mock(ok=True))
    monkeypatch.setattr(products.requests,'put',put)
    monkeypatch.setattr(products,'_build_acf_fields_partial',lambda data:{})
    assert products.create_or_update_product({'RACE NAME':'Test'},existing_product_id=12)==12
    assert 'status' not in json.loads(put.call_args.kwargs['data'])


def test_english_update_never_sends_editorial_status(monkeypatch):
    import _4_create_translation as translations
    put=Mock(return_value=Mock(ok=True))
    monkeypatch.setattr(translations.requests,'put',put)
    monkeypatch.setattr(translations,'get_jwt_token',lambda:'test-jwt')
    monkeypatch.setattr(translations,'send_acf_data_translation',Mock(return_value=Mock(status_code=200)))
    monkeypatch.setattr(translations,'link_product_translation',Mock())
    cfg={'wp_url':'https://example.test','consumer_key':'key','consumer_secret':'secret'}
    assert translations.create_or_update_product_pt({'RACE NAME':'Test'},10,config=cfg,existing_pt_product_id=11)==11
    assert all('status' not in call.kwargs['json'] for call in put.call_args_list)
