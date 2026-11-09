import hashlib
from pathlib import Path
from copy import deepcopy
import pytest
from joint_content import content_prompt, validate_joint_result, PROMPT_MARKER
from country_profile import PT, ES, activate_profile, reset_profile


def sample():
    result = {}
    for suffix in ('','_pt','_es'):
        for key,value in {'title':'Race','summary':'Summary','org_info':'Info','benefits':['Water'],'faq':'Q: Where?\nA: Here.','cancellation':''}.items():
            result[key+suffix] = value
    return result


def test_joint_result_requires_third_language_and_faq_parity():
    good = sample();assert validate_joint_result(good)['benefits_es']=='Water'
    bad = deepcopy(good);del bad['summary_es']
    with pytest.raises(ValueError,match='summary_es'):validate_joint_result(bad)
    bad=deepcopy(good);bad['faq_es']=''
    with pytest.raises(ValueError):validate_joint_result(bad)
    bad=deepcopy(good);bad['faq_es']='P: Dónde?\nR: Aquí.'
    with pytest.raises(ValueError,match='FAQ'):validate_joint_result(bad)


@pytest.mark.parametrize('country', [PT,ES])
def test_joint_prompt_keeps_portuguese_and_spanish_roles_independent_of_country(country):
    prompt=(Path(__file__).resolve().parents[1]/'run/prompts/assistant_system.txt').read_text()
    token=activate_profile(country)
    try:
        joint=content_prompt(prompt,True)
        assert '_pt — европейский португальский; _es — испанский' in joint
        assert 'title_es' in joint and 'summary_es' in joint
        assert 'должны быть на ИСПАНСКОМ' not in joint
    finally:
        reset_profile(token)


def test_original_prompts_are_retained_verbatim_and_legacy_does_not_see_extension():
    root=Path(__file__).resolve().parents[1]/'run/prompts'
    expected={'assistant_system.txt': '12282d0edebcc47ffe51cf8762d995d25225545fee7f1efa536de4e2e3e729c3', 'second_system.txt': '0e799737818c7af453b65ba44a5620c7eb89efa0832a770b9b4f3d69dd754382'}
    token=activate_profile(PT)
    try:
        for name,digest in expected.items():
            text=(root/name).read_text();original=text.split(PROMPT_MARKER)[0]
            assert hashlib.sha256(original.encode()).hexdigest()==digest
            assert content_prompt(text)==original.strip()
    finally:
        reset_profile(token)


def test_cleaner_receives_complete_three_language_json_above_old_text_limit(monkeypatch):
    import json
    from unittest.mock import Mock
    import _2_content_generation as generation
    prompt=(Path(__file__).resolve().parents[1]/'run/prompts/second_system.txt').read_text()
    monkeypatch.setattr(generation,'_load_prompt_file',lambda _:prompt)
    create=Mock(return_value=Mock(output_text='{}'))
    monkeypatch.setattr(generation._OPENAI_CLIENT.responses,'create',create)
    payload=sample();payload['summary']='x'*45000
    generation.call_second_openai_assistant(payload,trilingual=True)
    sent=create.call_args.kwargs['input'][-1]['content'][0]['text']
    assert json.loads(sent)==payload


def test_both_existing_steps_request_all_three_languages_in_strict_schema(monkeypatch):
    import json
    from unittest.mock import Mock
    import _2_content_generation as generation
    root=Path(__file__).resolve().parents[1]/'run/prompts'
    monkeypatch.setattr(generation,'_load_prompt_file',lambda name:(root/Path(name).name).read_text())
    create=Mock(return_value=Mock(output_text=json.dumps(sample())))
    monkeypatch.setattr(generation._OPENAI_CLIENT.responses,'create',create)
    generation.call_openai_assistant('Source facts',trilingual=True)
    generation.call_second_openai_assistant(sample(),trilingual=True)
    assert create.call_count==2
    for call in create.call_args_list:
        fmt=call.kwargs['text']['format']
        assert fmt['strict'] and fmt['schema']['additionalProperties'] is False
        assert all(key in fmt['schema']['required'] for key in ('title','title_pt','title_es','summary_es','org_info_es','cancellation_es'))


def test_cleaner_cannot_replace_english_summary_with_spanish_or_drop_faq():
    from joint_content import validate_cleaned_result
    first=sample();first['summary']='English summary';first['title']='Alcarria Marathon'
    cleaned=deepcopy(first);cleaned.update(summary='Resumen en español',title='Maratón Alcarria',faq='')
    cleaned['org_info']='Cleaned information'
    result=validate_cleaned_result(first,cleaned)
    assert result['summary']=='English summary' and result['title']=='Alcarria Marathon'
    assert result['faq']==first['faq'] and result['org_info']=='Cleaned information'
