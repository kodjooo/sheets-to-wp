"""Проверки границы старых строк, возобновления и независимости страны от языка."""
from types import SimpleNamespace
from unittest.mock import Mock
import json
import pytest
import main as m
import trilingual_import as tri
from country_profile import PT, ES, CountryProfile, activate_profile, reset_profile, active_profile, primary_metadata


@pytest.mark.parametrize('lang', tri.LANGUAGES)
def test_existing_product_is_never_automatically_expanded(monkeypatch, lang):
    monkeypatch.setenv('NEW_EVENT_LANGUAGES', 'pt,es,en')
    assert tri.language_scheme({'WP PRODUCT ID ' + lang.upper(): '19'}) == 'LEGACY'


def test_existing_link_without_ids_is_legacy(monkeypatch):
    monkeypatch.setenv('NEW_EVENT_LANGUAGES', 'pt,es,en')
    assert tri.language_scheme({'LINK RACEFINDER': 'https://example.test/event/race'}) == 'LEGACY'


def test_new_defaults_and_partial_resume_keep_three_languages(monkeypatch):
    monkeypatch.delenv('NEW_EVENT_LANGUAGES', raising=False)
    assert tri.language_scheme({}) == tri.SCHEME
    monkeypatch.setenv('NEW_EVENT_LANGUAGES', 'legacy')
    assert tri.language_scheme({'LANGUAGE SCHEME': tri.SCHEME, 'WP PRODUCT ID PT': 123}) == tri.SCHEME
    with pytest.raises(ValueError):tri.language_scheme({'LANGUAGE SCHEME': 'surprise'})


def test_portuguese_event_in_spanish_stays_portuguese():
    profile = CountryProfile('pt', 'portugal', 'es')
    token = activate_profile(profile)
    try:
        assert primary_metadata({'RF_MUNICIPALITY_NAME': 'Lisboa'}) == [{'key':'_rf_location_municipality_name','value':'Lisboa'}]
        assert profile.column('WP PRODUCT ID PT') == 'WP PRODUCT ID ES'
    finally:reset_profile(token)

@pytest.fixture
def workflow(monkeypatch):
    native_result={'summary':'English summary','org_info':'English info','benefits':'Water','faq':'Q: Time?\nA: Morning.',
        'summary_pt':'Native summary','org_info_pt':'Native info','benefits_pt':'Agua','faq_pt':'Q: Time?\nA: Morning.',
        'title':'English race','title_pt':'Corrida','title_es':'Carrera',
        'summary_es':'Resumen español','org_info_es':'Información española','benefits_es':'Agua','faq_es':'Q: Time?\nA: Morning.',
        'cancellation_es':'Condiciones','cancellation':'Terms EN','cancellation_pt':'Terms native','organizer_name':'Organizer','organizer_email':'contact@example.test'}
    row={'ID':'TEST-TRI','STATUS':'Revised (complete)','COUNTRY':'Portugal','RACE NAME (PT)':'Corrida',
         'RACE NAME (ES)':'Carrera','CATEGORY':'Running','LOCATION':'38.72, -9.14','LOCATION (CITY)':'Lisboa',
         'WEBSITE':'https://example.test/race','REGULATIONS':'','EVENT START DATE':'20/06/2027',
         'EVENT END DATE':'20/06/2027','DISTANCE':'5 km','PRICE':'12'}
    child={'DISTANCE':'10 km','PRICE':'20','STATUS':''}
    for lang in tri.LANGUAGES:
        for key in ('title', *tri.FIELDS):row.setdefault(tri.column(key,lang),'')
        row['WP PRODUCT ID '+lang.upper()]='';row['WP VARIATION ID '+lang.upper()]=''
    row.update({'LANGUAGE SCHEME':'','LANGUAGE STATE':'','INPUT FINGERPRINT':'','CONTENT FINGERPRINT':'','THIRD LANGUAGE FINGERPRINT':'','ATTRIBUTE TRANSLATIONS':'','NOTE':''})
    headers={key:i+1 for i,key in enumerate(row)}
    saved={2:row,3:child};writes=[];created=[];targets={};contexts=[];payloads=[]
    def write(index,updates,columns):saved[index].update(updates);writes.append((index,dict(updates)))
    def create(data,existing_product_id=None,on_created=None):
        profile=active_profile();contexts.append((profile.code,profile.country,profile.language));payloads.append(dict(data))
        if existing_product_id:return int(existing_product_id)
        pid=100+len(created);created.append(pid)
        if on_created:on_created(pid)
        return pid
    def ensure(cfg,origin,lang,existing=None):
        key=(origin,lang)
        targets.setdefault(key,200+len(targets))
        assert not existing or int(existing)==targets[key]
        return targets[key]
    monkeypatch.setenv('CATEGORY_ROOT_MAP_JSON',json.dumps({'Running':{'pt_parent_id':1,'es_parent_id':2,'en_parent_id':3}}))
    monkeypatch.setenv('ENABLE_SPAIN','true');monkeypatch.setenv('SPAIN_WP_HOST','example.test')
    monkeypatch.setattr(m,'SKIP_AI',False);monkeypatch.setattr(m,'SKIP_IMAGE',True)
    monkeypatch.setattr(m,'_batch_update_cells',write)
    monkeypatch.setattr(m,'extract_text_from_url',Mock(return_value=('Verified source text',None)))
    monkeypatch.setattr(m,'validate_source_texts',Mock(return_value=[]))
    monkeypatch.setattr(m,'translate_title_to_en',Mock(side_effect=AssertionError('Separate title translation must not run')))
    monkeypatch.setattr(m,'call_openai_assistant',Mock(return_value=dict(native_result)))
    monkeypatch.setattr(m,'call_second_openai_assistant',Mock(return_value=native_result))
    monkeypatch.setattr(m,'get_coordinates_with_city_fallback',Mock(return_value=(38.72,-9.14)))
    monkeypatch.setattr(m,'resolve_municipality',lambda value:'Lisboa')
    monkeypatch.setattr(m,'_build_pt_category_ids_from_en',lambda row:[{'id':1}])
    monkeypatch.setattr(m,'create_product_pt_primary',create)
    monkeypatch.setattr(m,'assign_attributes_to_product',Mock())
    monkeypatch.setattr(m,'sync_variations_by_ids',Mock(side_effect=lambda pid,entries,lang=None:{e['row_index']:pid*10+i for i,e in enumerate(entries)}))
    monkeypatch.setattr(m,'reapply_price_schedules',Mock())
    monkeypatch.setattr(tri,'write_content',Mock())
    monkeypatch.setattr(tri,'link_variations',Mock())
    monkeypatch.setattr(tri,'auth_token',Mock(return_value='test-jwt'))
    monkeypatch.setattr(tri,'attribute_id',lambda name: {'Distance':1,'Team':2,'Running':3}.get(name,4))
    monkeypatch.setattr(tri,'ensure_terms',lambda cfg,specs,ids:{(name,value):{lang:{'id':1,'name':labels[lang]} for lang in tri.LANGUAGES} for name,value,labels in specs})
    monkeypatch.setattr(tri,'verify_publication',Mock())
    monkeypatch.setattr(tri,'publish_products',Mock(return_value={lang:{'permalink':'https://example.test/event/test'} for lang in tri.LANGUAGES}))
    monkeypatch.setattr(tri,'apply_options',Mock())
    monkeypatch.setattr(tri,'resolve_categories',Mock(return_value={'ids':{'pt':[1],'es':[2],'en':[3]},'groups':[]}))
    monkeypatch.setattr(tri,'verify_categories',Mock())
    monkeypatch.setattr(tri,'ensure_translation',Mock(side_effect=ensure))
    response=Mock();response.json.return_value={'permalink':'https://example.test/event/test'}
    monkeypatch.setattr(tri.requests,'get',Mock(return_value=response))
    def run(profile=PT):
        token=activate_profile(profile)
        try:tri.process_trilingual(m,2,dict(row),[(3,dict(child))],headers)
        finally:reset_profile(token)
    return SimpleNamespace(row=row,child=child,headers=headers,run=run,created=created,targets=targets,writes=writes,contexts=contexts,payloads=payloads,create=create)


@pytest.mark.parametrize('profile', [PT,ES])
def test_three_languages_share_country_prices_and_stable_ids(workflow,profile):
    w=workflow
    if profile==ES:w.row.update({'COUNTRY':'Spain','LOCATION (CITY)':'Badalona, Barcelona'})
    w.run(profile)
    first={key:value for key,value in w.row.items() if ' ID ' in key}
    assert w.row['STATUS']=='Published' and w.row['LANGUAGE SCHEME']==tri.SCHEME
    assert len(w.created)==1 and len(w.targets)==2
    assert {context[1] for context in w.contexts}=={profile.country}
    assert {context[2] for context in w.contexts}==set(tri.LANGUAGES)
    assert all(w.row['WP PRODUCT ID '+lang.upper()] for lang in tri.LANGUAGES)
    assert all(w.child['WP VARIATION ID '+lang.upper()] for lang in tri.LANGUAGES)
    for call in m.sync_variations_by_ids.call_args_list:
        assert [entry['regular_price'] for entry in call.args[1]]==['12','20']
    w.row['STATUS']='Revised (complete)';w.run(profile)
    assert first=={key:value for key,value in w.row.items() if ' ID ' in key}
    assert len(w.created)==1
    assert m.call_openai_assistant.call_count==1 and m.call_second_openai_assistant.call_count==1
    assert active_profile()==PT


def test_missing_third_language_does_not_checkpoint_partial_pair(workflow,monkeypatch):
    w=workflow
    good=dict(m.call_second_openai_assistant.return_value)
    m.call_second_openai_assistant.return_value['org_info_es']=''
    with pytest.raises(ValueError):w.run()
    assert w.row['STATUS']=='Revised (complete)' and not w.row['CONTENT FINGERPRINT']
    assert not w.created
    m.call_second_openai_assistant.return_value=good
    w.run()
    assert m.call_openai_assistant.call_count==2
    m.translate_title_to_en.assert_not_called()
    assert w.row['STATUS']=='Published'


def test_wp_failure_after_primary_creation_reuses_id_and_all_text(workflow,monkeypatch):
    w=workflow
    def fail_after_create(*args,**kwargs):
        w.create(*args,**kwargs)
        raise RuntimeError('Lost response after create')
    monkeypatch.setattr(m,'create_product_pt_primary',fail_after_create)
    with pytest.raises(RuntimeError):w.run()
    assert w.row['WP PRODUCT ID PT']==100 and w.row['STATUS']=='Revised (complete)'
    monkeypatch.setattr(m,'create_product_pt_primary',w.create);w.run()
    assert len(w.created)==1 and w.row['STATUS']=='Published'
    assert m.call_openai_assistant.call_count==1 and m.call_second_openai_assistant.call_count==1


def test_missing_headers_stop_before_generation_or_writes(workflow):
    del workflow.headers['CONTENT FINGERPRINT']
    with pytest.raises(ValueError,match='CONTENT FINGERPRINT'):workflow.run()
    assert not workflow.writes
    m.call_openai_assistant.assert_not_called()


def test_input_change_invalidates_both_translation_caches(workflow):
    w=workflow;w.run();w.row['PRICE']='15';w.row['STATUS']='Revised (complete)';w.run()
    assert m.call_openai_assistant.call_count==2
    assert m.call_second_openai_assistant.call_count==2
    assert len(w.created)==1


def test_blank_or_wrong_shape_translation_is_rejected():
    source={key:'Value' for key in ('title',*tri.FIELDS)}
    with pytest.raises(ValueError):tri.validate_translation({**source,'summary':''},source)
    with pytest.raises(ValueError):tri.validate_translation({**source,'benefits':[]},source)


def test_fingerprint_ignores_generated_ids_and_translations(workflow):
    w=workflow;before=tri.source_fingerprint(w.row,[(2,w.row),(3,w.child)],'source','',None,'pt')
    w.row.update({'WP PRODUCT ID EN':123,'SUMMARY':'Generated','RACE NAME (ES)':'Nuevo'})
    assert tri.source_fingerprint(w.row,[(2,w.row),(3,w.child)],'source','',None,'pt')==before


def test_sheet_preparation_protects_old_rows_and_does_not_rebaseline_new_rows():
    from prepare_trilingual_sheet import preparation
    values=[['ID','STATUS'],['old-no-wp-id','Revised (complete)'],['variant','']]
    headers,updates,count=preparation(values)
    assert count==1 and updates[1]['values']==[['LEGACY'],['']]
    # Повторная подготовка колонок не переводит новые строки в старый режим.
    _,again,count=preparation([headers,['fresh','Revised (complete)']])
    assert count==0 and len(again)==1


def test_main_dispatches_new_event_and_skips_published_repeat(workflow,monkeypatch):
    w=workflow
    monkeypatch.setenv('NEW_EVENT_LANGUAGES','pt,es,en')
    monkeypatch.setattr(m,'log_network_diagnostics',lambda:None)
    monkeypatch.setattr(m,'load_all_rows',lambda:([(2,dict(w.row)),(3,dict(w.child))],w.headers))
    m.run_automation()
    assert w.row['STATUS']=='Published' and len(w.created)==1
    m.run_automation()
    assert m.call_openai_assistant.call_count==1 and m.call_second_openai_assistant.call_count==1


def test_acf_failure_is_not_reported_as_published_and_retry_keeps_id(workflow,monkeypatch):
    w=workflow
    monkeypatch.setattr(tri,'write_content',Mock(side_effect=RuntimeError('ACF failed')))
    with pytest.raises(RuntimeError):w.run()
    assert w.row['STATUS']=='Revised (complete)' and len(w.created)==1
    monkeypatch.setattr(tri,'write_content',Mock());w.run()
    assert w.row['STATUS']=='Published' and len(w.created)==1
    assert m.call_openai_assistant.call_count==1


def test_translated_faq_must_preserve_machine_readable_question_answer_pairs():
    source={'title':'Race','summary':'Summary','org_info':'Info','benefits':'Water','faq':'Q: Where?\nA: Here.'}
    with pytest.raises(ValueError,match='FAQ'):tri.validate_translation({**source,'faq':'P: Onde?\nR: Aqui.'},source)


def test_retry_uses_all_three_cached_versions_when_wp_failed(workflow,monkeypatch):
    w=workflow
    monkeypatch.setattr(tri,'write_content',Mock(side_effect=ValueError('Temporary WP failure')))
    with pytest.raises(ValueError):w.run()
    assert w.row['LANGUAGE STATE']=='IN_PROGRESS'
    monkeypatch.setattr(tri,'write_content',Mock())
    monkeypatch.setattr(m,'extract_text_from_url',Mock(side_effect=RuntimeError('Source changed or unavailable')))
    w.run()
    assert w.row['STATUS']=='Published' and w.row['LANGUAGE STATE']=='COMPLETE'
    assert m.call_openai_assistant.call_count==1
    assert m.call_second_openai_assistant.call_count==1


def test_preview_requires_trilingual_columns_before_promising_readiness(workflow,monkeypatch):
    from preview_country_import import preview
    w=workflow;monkeypatch.setenv('NEW_EVENT_LANGUAGES','pt,es,en')
    result=preview([w.row],w.headers,'https://example.test')[0]
    assert result['ready'] and set(result['languages'])==set(tri.LANGUAGES)
    del w.headers['INPUT FINGERPRINT']
    result=preview([w.row],w.headers,'https://example.test')[0]
    assert not result['ready'] and 'INPUT FINGERPRINT' in result['error']


def test_variation_categories_are_preserved_for_each_language(workflow):
    w=workflow;w.child.update(CATEGORY='Cycling',SUBCATEGORY='MTB');w.run()
    assert len(w.payloads)==3
    assert all(('Cycling','MTB') in data['extra_categories'] for data in w.payloads)


def test_variations_are_linked_in_same_event_after_sync(workflow):
    w=workflow;w.run()
    calls=tri.link_variations.call_args_list
    assert len(calls)==4
    for call in calls:
        assert call.args[1] in (1000,1001)
        assert call.args[3] in ('en','es')
        assert call.args[1] % 10 == call.args[2] % 10


def test_variation_link_failure_stays_incomplete_and_resumes_before_parent_save(workflow,monkeypatch):
    w=workflow
    monkeypatch.setattr(tri,'link_variations',Mock(side_effect=RuntimeError('Variation link failed')))
    with pytest.raises(RuntimeError):w.run()
    assert w.row['STATUS']=='Revised (complete)' and w.row['LANGUAGE STATE']=='IN_PROGRESS'
    assert all(w.row['WP PRODUCT ID '+lang.upper()] for lang in tri.LANGUAGES)
    linked=Mock();monkeypatch.setattr(tri,'link_variations',linked);w.run()
    assert w.row['STATUS']=='Published' and len(w.created)==1
    assert linked.call_args_list[0].kwargs=={'allow_missing':True}
    assert m.call_openai_assistant.call_count==1


def test_unavailable_cover_reports_clear_error_before_product_creation(workflow, monkeypatch):
    monkeypatch.setattr(m, 'SKIP_IMAGE', False)
    monkeypatch.setattr(m, 'generate_image', Mock(return_value=None))
    m.call_second_openai_assistant.return_value['image_prompt'] = 'Race cover'
    with pytest.raises(ValueError, match='обложку'):
        workflow.run()
    assert not workflow.created
    assert 'обложку' in workflow.row['NOTE']


def test_publish_failure_keeps_row_retryable_with_saved_ids(workflow,monkeypatch):
    w=workflow
    monkeypatch.setattr(tri,'publish_products',Mock(side_effect=ValueError('Still draft')))
    with pytest.raises(ValueError,match='Still draft'):w.run()
    assert w.row['STATUS']=='Revised (complete)' and w.row['LANGUAGE STATE']=='IN_PROGRESS'
    assert w.row['WP PRODUCT ID PT'] and w.row['WP PRODUCT ID ES'] and w.row['WP PRODUCT ID EN']
    monkeypatch.setattr(tri,'publish_products',Mock(return_value={lang:{'permalink':'https://example.test/event/race'} for lang in tri.LANGUAGES}))
    w.run()
    assert w.row['STATUS']=='Published' and len(w.created)==1
    assert m.call_openai_assistant.call_count==1


def test_joint_generation_uses_only_existing_two_steps_for_both_countries(workflow):
    w=workflow;w.run()
    m.call_openai_assistant.assert_called_once()
    assert m.call_openai_assistant.call_args.kwargs['trilingual'] is True
    m.call_second_openai_assistant.assert_called_once()
    assert m.call_second_openai_assistant.call_args.kwargs['trilingual'] is True
    m.translate_title_to_en.assert_not_called()
    assert all(w.row[tri.column(key,lang)] for lang in tri.LANGUAGES for key in ('title','summary','org_info'))


@pytest.mark.parametrize('title,is_test',[('TEST Antonio Marathon Alcarria 2026',True),('TEST TRIATHLON 2026',True),('Testing Marathon 2026',False)])
def test_joint_titles_preserve_test_marker_without_separate_translation(workflow,title,is_test):
    w=workflow;w.row['RACE NAME (PT)']=title;w.run()
    assert w.row['RACE NAME (PT)']==title
    assert w.row['RACE NAME'].startswith('TEST ')==is_test
    assert w.row['RACE NAME (ES)'].startswith('TEST ')==is_test
    assert title in m.call_openai_assistant.call_args.args[0]
    m.translate_title_to_en.assert_not_called()
