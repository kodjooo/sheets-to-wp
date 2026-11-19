"""Прежнее поведение пустых полей без ослабления защиты ID, дублей и языков."""
from unittest.mock import Mock
import pytest
from publication_contract import validate_block
from test_publication_contract import rows
from test_trilingual_import import workflow
import trilingual_import as tri
import main

@pytest.mark.parametrize('value', ['',None,'   ',0,'0','0.00'])
def test_price_missing_and_explicit_zero_are_both_valid_but_not_substituted(value):
    block=rows();block[0][1]['PRICE']=value;validate_block(block)
    assert block[0][1]['PRICE']==value
    assert block[0][1]['TEAM']==''

@pytest.mark.parametrize('field',['EVENT START DATE','EVENT END DATE'])
def test_event_date_can_be_unknown_but_present_bad_date_is_rejected(field):
    block=rows();block[0][1][field]='';validate_block(block)
    block[0][1][field]='not a date'
    with pytest.raises(ValueError):validate_block(block)

@pytest.mark.parametrize('field',['LICENSE','TYPE','TEAM'])
def test_optional_variant_fields_keep_their_original_blanks(field):
    block=rows();block[1][1][field]='Licensed';validate_block(block)
    assert not block[0][1].get(field)


def test_empty_fields_repeat_keeps_product_and_variation_ids(workflow):
    w=workflow;w.row.update({'EVENT END DATE':'','PRICE':'','LICENSE':''});w.child.update({'PRICE':0,'LICENSE':'Licensed','TEAM':'Dobles'})
    w.run();ids={k:v for k,v in w.row.items() if ' ID ' in k};childids={k:v for k,v in w.child.items() if ' ID ' in k}
    for call in main.sync_variations_by_ids.call_args_list:
        entries=call.args[1];assert [e['regular_price'] for e in entries]==['','0']
        assert not entries[0]['price_schedule']
        assert all(a['name'] not in ('Team','License') for a in entries[0]['attributes'])
    assert all(data['EVENT END DATE']=='' for data in w.payloads)
    w.row['STATUS']='Revised (complete)';w.run()
    assert ids=={k:v for k,v in w.row.items() if ' ID ' in k}
    assert childids=={k:v for k,v in w.child.items() if ' ID ' in k}
    assert len(w.created)==1 and w.row['STATUS']=='Published'


@pytest.mark.parametrize('wanted,saved,valid',[('','',True),('',None,True),('','0',False),('0','',False),('0','0.00',True),('12','12.00',True),('12','0',False)])
def test_readback_distinguishes_unknown_from_free_and_preserves_omitted_schedule(monkeypatch,wanted,saved,valid):
    import _6_create_variations as variations
    row={'EVENT START DATE':'14/11/2026','EVENT END DATE':'','WEBSITE':'https://example.test/race','RF_REGISTRATION_DEADLINE':'','SUMMARY':'English','ORG INFO':'Organizer'}
    metadata={'event_country':'portugal','event_date_start':'20261114','event_date_end':'','event_short_description':'English','organizer_description':'Organizer','event_ticket_url':row['WEBSITE']}
    product={'type':'variable','id':10,'status':'draft','variations':[101],'price':saved,'meta_data':[{'key':k,'value':v} for k,v in metadata.items()],'miss_events':{'registration_deadline':'2027-01-01 18:00:00'}}
    response=Mock();response.json.return_value=product;monkeypatch.setattr(tri.requests,'get',Mock(return_value=response))
    actual=[{'id':101,'regular_price':saved,'attributes':[{'id':1,'option':'42 km'},{'id':2,'option':''}],'miss_events':{'price_schedule':[{'datetime':'2026-11-10 00:00:00','price':'60'}]}}]
    monkeypatch.setattr(variations,'_load_all_variations',lambda *args:actual)
    args=({'wp_url':'https://example.test','consumer_key':'key','consumer_secret':'secret'},{'en':10},row,{'en':[{'row_index':2,'regular_price':wanted,'attributes':[{'name':'Distance','option':'42 km'}],'price_schedule':[]}]},{'en':{2:101}},{'Distance':1})
    if valid:tri.verify_publication(*args)
    else:
        with pytest.raises(ValueError):tri.verify_publication(*args)
