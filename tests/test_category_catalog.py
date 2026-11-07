"""Формат Антонио не меняется: проверяем выбор существующей группы и её иерархию."""
import json
from unittest.mock import Mock
import pytest
import category_catalog as catalog
import trilingual_import as tri
from test_trilingual_import import workflow

ROOTS={'en':17,'pt':129,'es':10508}


def node(id,name,lang,parent,translations):
    return {'id':id,'name':name,'lang':lang,'parent':parent,'translations':translations}


def records():
    group={'en':29,'pt':247,'es':10523};duplicate={'en':12088,'pt':12090,'es':12089}
    return [node(i,n,l,0,ROOTS) for l,i,n in [('en',17,'Running'),('pt',129,'Corrida'),('es',10508,'Carreras')]]+[
        node(29,'Ultra Marathons','en',17,group),node(247,'Ultra Maratonas','pt',129,group),node(10523,'Ultramaratones','es',10508,group),
        node(12088,'Ultra Marathon','en',17,duplicate),node(12090,'Ultra Marathon','pt',0,duplicate),node(12089,'Ultra Maratón','es',10508,duplicate)]


@pytest.mark.parametrize('label',['Ultra marathon','Ultra Marathon','Ultra Marathons','Ultra Maratona','Ultramaratón'])
def test_existing_canonical_group_wins_over_duplicate_for_all_aliases(label):
    chosen,names=catalog.select_category(records(),'Running',label,ROOTS)
    assert chosen['id']==29 and names['en']=='Ultra Marathons'


def test_missing_english_mtb_uses_existing_portuguese_spanish_group():
    group={'pt':188,'es':10529};data=[node(188,'Mountain Biking (MTB / Off-Road)','pt',130,group),node(10529,'Mountain Bike (MTB)','es',10510,group)]
    chosen,names=catalog.select_category(data,'Cycling','MTB',{'en':36,'pt':130,'es':10510})
    assert chosen['id']==188 and names=={'en':'MTB','pt':'BTT','es':'MTB'}


def test_wrong_parent_and_ambiguous_categories_are_not_guessed():
    with pytest.raises(ValueError):catalog.select_category([node(1,'Ultra Marathons','en',0,{})],'Running','Ultra marathon',ROOTS)
    with pytest.raises(ValueError):catalog.select_category(records()+[node(99,'Ultra Marathons','en',17,{'en':99})],'Running','Ultra marathon',ROOTS)


def test_all_variation_categories_and_comma_separated_subcategories_preserved():
    row={'CATEGORY':'Running','SUBCATEGORY':'Ultra marathon'}
    block=[(2,row),(3,{'CATEGORY':'Running','SUBCATEGORY':'Trail Run, Walking'}),(4,{'CATEGORY':'Cycling','SUBCATEGORY':'MTB'})]
    assert catalog.category_pairs(row,block)==[('Running','Ultra marathon'),('Running','Trail Run'),('Running','Walking'),('Cycling','MTB')]
    assert row['SUBCATEGORY']=='Ultra marathon'


@pytest.mark.parametrize('bad_parent',[False,True])
def test_resolver_uses_existing_ids_and_rejects_misplaced_translation(monkeypatch,bad_parent):
    import _3_create_product as products
    monkeypatch.setattr(products,'get_jwt_token',lambda:'jwt')
    monkeypatch.setenv('CATEGORY_ROOT_MAP_JSON',json.dumps({'Running':{l+'_parent_id':i for l,i in ROOTS.items()}}))
    get=Mock();get.json.return_value=records();monkeypatch.setattr(catalog.requests,'get',Mock(return_value=get))
    group={'trid':651,'roots':ROOTS,'categories':{l:{'id':i,'lang':l,'parent':0 if bad_parent and l=='pt' else ROOTS[l]} for l,i in {'en':29,'pt':247,'es':10523}.items()}}
    response=Mock();response.json.return_value=group
    post=Mock(return_value=response);monkeypatch.setattr(catalog.requests,'post',post)
    cfg={'wp_url':'https://example.test','consumer_key':'ck','consumer_secret':'cs'};row={'CATEGORY':'Running','SUBCATEGORY':'Ultra marathon'}
    if bad_parent:
        with pytest.raises(ValueError,match='родителя'):catalog.resolve_categories(cfg,row,[(2,row)])
    else:
        plan=catalog.resolve_categories(cfg,row,[(2,row)])
        assert plan['ids']=={'en':[17,29],'pt':[129,247],'es':[10508,10523]}
        assert post.call_args.kwargs['json']['source_id']==29
        assert post.call_args.kwargs['headers']['Authorization']=='Bearer jwt'


def test_category_validation_failure_is_incomplete_and_retry_reuses_ids(workflow,monkeypatch):
    w=workflow;check=Mock(side_effect=ValueError('Wrong category parent'))
    monkeypatch.setattr(tri,'verify_categories',check)
    with pytest.raises(ValueError):w.run()
    assert w.row['STATUS']=='Revised (complete)' and w.row['LANGUAGE STATE']=='IN_PROGRESS'
    saved={l:w.row['WP PRODUCT ID '+l.upper()] for l in tri.LANGUAGES}
    monkeypatch.setattr(tri,'verify_categories',Mock());w.run()
    assert w.row['STATUS']=='Published' and saved=={l:w.row['WP PRODUCT ID '+l.upper()] for l in tri.LANGUAGES}
    assert len(w.created)==1


def test_each_language_receives_its_own_category_plan(workflow):
    w=workflow;w.run()
    for context,payload in zip(w.contexts,w.payloads):
        assert payload['CATEGORY_IDS_PT']==[{'id':{'pt':1,'es':2,'en':3}[context[2]]}]


def test_roots_from_different_sports_fail_even_without_subcategory(monkeypatch):
    import _3_create_product as products
    monkeypatch.setattr(products,'get_jwt_token',lambda:'jwt')
    monkeypatch.setenv('CATEGORY_ROOT_MAP_JSON',json.dumps({'Running':{l+'_parent_id':i for l,i in ROOTS.items()}}))
    data=records();data[0]['translations']={'en':17,'pt':130,'es':10508}
    response=Mock();response.json.return_value=data;monkeypatch.setattr(catalog.requests,'get',Mock(return_value=response))
    row={'CATEGORY':'Running','SUBCATEGORY':''}
    with pytest.raises(ValueError,match='одной группе'):catalog.resolve_categories({'wp_url':'https://example.test'},row,[(2,row)])


def test_test_marker_is_not_treated_as_part_of_race_name(monkeypatch):
    import _2_content_generation as generation
    source={'title':'TEST Antonio Marathon Alcarria 2026','summary':'Summary','org_info':'Info','benefits':'','faq':''}
    response=Mock(output_text=json.dumps({**source,'title':'Maratona Alcarria 2026'}))
    create=Mock(return_value=response);monkeypatch.setattr(generation._OPENAI_CLIENT.responses,'create',create)
    result=tri.translate_content(source,'pt')
    assert result['title']=='TEST Antonio Maratona Alcarria 2026'
    sent=json.loads(create.call_args.kwargs['input'][1]['content'][0]['text'])
    assert sent['title']=='Marathon Alcarria 2026'


@pytest.mark.parametrize('title,core,translated,expected',[
    ('TEST TRIATHLON 2026','TRIATHLON 2026','Triatlo 2026','TEST Triatlo 2026'),
    ('Testing Marathon 2026','Testing Marathon 2026','Testing Maratona 2026','Testing Maratona 2026'),
])
def test_marker_does_not_remove_part_of_real_event_name(monkeypatch,title,core,translated,expected):
    import _2_content_generation as generation
    source={'title':title,'summary':'Summary','org_info':'Info','benefits':'','faq':''}
    response=Mock(output_text=json.dumps({**source,'title':translated}));create=Mock(return_value=response)
    monkeypatch.setattr(generation._OPENAI_CLIENT.responses,'create',create)
    assert tri.translate_content(source,'pt')['title']==expected
    assert json.loads(create.call_args.kwargs['input'][1]['content'][0]['text'])['title']==core


def test_empty_deadline_removes_previous_value_without_changing_public_status(monkeypatch):
    import _3_create_product as products
    monkeypatch.setattr(products,'_collect_category_ids',lambda row:[])
    monkeypatch.setattr(products,'_build_acf_fields_partial',lambda row:{})
    response=Mock(ok=True);put=Mock(return_value=response);monkeypatch.setattr(products.requests,'put',put)
    assert products.create_or_update_product({'RACE NAME (PT)':'Race','RF_REGISTRATION_DEADLINE':''},existing_product_id=42)==42
    payload=json.loads(put.call_args.kwargs['data'])
    assert payload['miss_events']=={'registration_deadline':''}
    assert 'status' not in payload
