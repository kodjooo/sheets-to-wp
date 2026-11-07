"""Ошибки настоящей вкладки и различимость локализованных вариантов."""
from copy import deepcopy
from unittest.mock import Mock
import pytest
from publication_contract import validate_block, label_catalog
from test_trilingual_import import workflow
import trilingual_import as tri


def rows():
    return [(2, {'CATEGORY':'Running','WEBSITE':'https://example.test/event','EVENT START DATE':'14/11/2026',
                 'EVENT END DATE':'14/11/2026','DISTANCE':'42 km','PRICE':'50','TEAM':''}),
            (3, {'DISTANCE':'42 km','PRICE':'50','TEAM':'Dobles'}),
            (4, {'DISTANCE':'42 km','PRICE':'50','TEAM':'Equipos de 4'})]


def test_empty_individual_becomes_explicit_and_all_languages_differ_from_team_options():
    block=rows();validate_block(block)
    assert block[0][1]['TEAM']=='Individual'
    labels=label_catalog(block,'')
    for lang in tri.LANGUAGES:
        assert len({labels[r['TEAM']][lang] for _,r in block})==3
    assert labels['Dobles']=={'en':'Pairs','pt':'Duplas','es':'Parejas'}


@pytest.mark.parametrize('key,value', [('WP VARIATION ID EN','12/11/2026'),('PRICE',''),('PRICE','NaN'),
                                     ('PRICE','-1'),('PRICE CHANGES','tomorrow=2'),('RACE START TIME','25:61')])
def test_bad_input_is_rejected(key,value):
    block=rows();block[0][1][key]=value
    with pytest.raises(ValueError):validate_block(block)


def test_duplicate_options_cannot_be_distinguished_only_by_price():
    block=rows();block[2][1].update(TEAM='Dobles',PRICE='70')
    with pytest.raises(ValueError,match='одинаковые'):validate_block(block)


def test_invalid_license_wildcard_rejected():
    block=rows();block[1][1]['LICENSE']='Federado'
    with pytest.raises(ValueError,match='LICENSE'):validate_block(block)


def test_cached_arbitrary_labels_do_not_call_model(monkeypatch):
    import publication_contract as contract
    block=rows();block[0][1]['TYPE']='Special wave'
    translate=Mock(return_value=[{'en':'Special wave','pt':'Vaga especial','es':'Salida especial'}])
    monkeypatch.setattr(contract,'translate_labels',translate)
    first=label_catalog(block,'')
    import json
    assert label_catalog(block,json.dumps(first))==first
    assert translate.call_count==1


def test_preflight_failure_does_not_generate_content_or_call_wp(workflow):
    w=workflow;w.row['WP VARIATION ID EN']='06/11/2026'
    with pytest.raises(ValueError,match='REGISTRATION DEADLINE'):w.run()
    import main
    main.call_openai_assistant.assert_not_called()
    assert not w.created and w.row['STATUS']=='Revised (complete)'


def test_failed_readback_never_marks_success(workflow,monkeypatch):
    w=workflow
    monkeypatch.setattr(tri,'verify_publication',Mock(side_effect=ValueError('Saved price mismatch')))
    with pytest.raises(ValueError):w.run()
    assert w.row['STATUS']=='Revised (complete)' and w.row['LANGUAGE STATE']=='IN_PROGRESS'
    assert 'Saved price mismatch' in w.row['NOTE']


def test_distinct_source_labels_cannot_collapse_to_one_option(workflow):
    w=workflow;w.row['TEAM']='Dobles';w.child.update(TEAM='Pairs',DISTANCE='5 km')
    with pytest.raises(ValueError,match='неразличимыми'):w.run()
    assert not w.created


def test_unapproved_next_event_is_not_imported_as_a_variation(workflow):
    import main
    w=workflow;w.child.update(ID='NEXT',**{'RACE NAME (PT)':'Next event'})
    w.run()
    for call in main.sync_variations_by_ids.call_args_list:
        assert len(call.args[1])==1


def test_failed_source_refresh_cannot_silently_resume_old_published_text(workflow,monkeypatch):
    import main
    w=workflow;w.run();w.row['STATUS']='Revised (complete)'
    source=Mock(side_effect=RuntimeError('Source unavailable'))
    monkeypatch.setattr(main,'extract_text_from_url',source)
    for _ in range(2):
        with pytest.raises(RuntimeError,match='Source unavailable'):w.run()
        assert w.row['STATUS']=='Revised (complete)'
        assert w.row['LANGUAGE STATE']=='CHECKING_SOURCE'
    assert source.call_count==2
    assert len(w.contexts)==3


def test_removing_price_schedule_clears_saved_schedule(monkeypatch):
    import _6_create_variations as variations
    monkeypatch.setattr(variations,'_build_product_attr_map',lambda pid:{'Distance':1})
    monkeypatch.setattr(variations,'_load_all_variations',lambda *args,**kwargs:[{'id':10,'regular_price':'50','attributes':[{'id':1,'option':'42 km'}]}])
    request=Mock();monkeypatch.setattr(variations,'_wcapi_request_with_retry',request)
    variations.sync_variations_by_ids(1,[{'row_index':2,'existing_variation_id':10,'regular_price':'50',
        'attributes':[{'name':'Distance','option':'42 km','id':1}],'price_schedule':[],'strict_schedule':True}],lang='es')
    request.assert_called_once_with('PUT','products/1/variations/10?lang=es',{'miss_events':{'price_schedule':[]}})


def test_identical_visible_labels_are_assigned_by_distinct_language_ids(monkeypatch):
    response=Mock();response.json.return_value={'verified':True}
    request=Mock(return_value=response);monkeypatch.setattr(tri.requests,'post',request)
    entries={lang:[{'row_index':2,'attributes':[{'id':1,'option':'42 km','term_id':20+i}]}] for i,lang in enumerate(tri.LANGUAGES)}
    ids={lang:100+i for i,lang in enumerate(tri.LANGUAGES)}
    mappings={lang:{2:200+i} for i,lang in enumerate(tri.LANGUAGES)}
    tri.apply_options({'wp_url':'https://example.test','_import_jwt':'test'},ids,entries,mappings)
    assert [c.kwargs['json']['verify_only'] for c in request.call_args_list]==[False,True]
    items=request.call_args_list[-1].kwargs['json']['items']
    assert [i['attributes'][0]['term_ids'] for i in items]==[[20],[21],[22]]
    assert [i['variations'][0]['attributes'][0]['term_id'] for i in items]==[20,21,22]


def test_exact_term_failure_cannot_mark_event_success(workflow,monkeypatch):
    w=workflow
    monkeypatch.setattr(tri,'apply_options',Mock(side_effect=ValueError('Wrong term language')))
    with pytest.raises(ValueError):w.run()
    assert w.row['STATUS']=='Revised (complete)' and w.row['LANGUAGE STATE']=='IN_PROGRESS'


@pytest.mark.parametrize('fault', [None,'draft','wrong_id','description','benefits','faq','deadline','price','blank_price','label','missing','schedule'])
def test_real_readback_contract_rejects_incorrect_saved_data(monkeypatch,fault):
    import _6_create_variations as variations
    row={'EVENT START DATE':'14/11/2026','EVENT END DATE':'14/11/2026','WEBSITE':'https://example.test/race',
         'RF_REGISTRATION_DEADLINE':'2026-11-12 18:00','SUMMARY':'English','ORG INFO':'Organizer'}
    metadata={'event_country':'portugal','event_date_start':'20261114','event_date_end':'20261114',
              'event_short_description':'English','organizer_description':'Organizer','event_ticket_url':row['WEBSITE']}
    if fault=='description':metadata['event_short_description']='Wrong language'
    if fault=='benefits':metadata['race_benefits']='Wrong language'
    if fault=='faq':metadata['event_faq_items']='1'
    product={'id':11 if fault=='wrong_id' else 10,'status':'draft' if fault=='draft' else 'publish','meta_data':[{'key':k,'value':v} for k,v in metadata.items()],
             'miss_events':{'registration_deadline':'2026-11-11 18:00:00' if fault=='deadline' else '2026-11-12 18:00:00'}}
    response=Mock();response.json.return_value=product
    monkeypatch.setattr(tri.requests,'get',Mock(return_value=response))
    actual=[{'id':101,'regular_price':'' if fault=='blank_price' else '51' if fault=='price' else '50.00',
             'attributes':[{'id':1,'option':'Wrong' if fault=='label' else '42 km'}],
             'miss_events':{'price_schedule':[{'datetime':'2026-11-10 00:00:00','price':'60'}] if fault=='schedule' else []}}]
    monkeypatch.setattr(variations,'_load_all_variations',lambda *args:[] if fault=='missing' else actual)
    args=({'wp_url':'https://example.test','consumer_key':'key','consumer_secret':'secret'},{'en':10},row,
          {'en':[{'row_index':2,'regular_price':'0' if fault=='blank_price' else '50','attributes':[{'name':'Distance','option':'42 km'}],'price_schedule':[]}]},
          {'en':{2:101}},{'Distance':1})
    if fault:
        with pytest.raises(ValueError):tri.verify_publication(*args)
    else:tri.verify_publication(*args)
