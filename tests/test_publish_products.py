from unittest.mock import Mock
import pytest
import trilingual_import as tri


@pytest.mark.parametrize('string_ids', [False, True])
def test_publish_reads_all_versions_after_status_updates(monkeypatch, string_ids):
    ids = {'es':10, 'en':11, 'pt':12}
    if string_ids: ids = {lang:str(pid) for lang,pid in ids.items()}
    states = {10:'draft', 11:'pending', 12:'publish'}
    calls = []
    def get(url, **kwargs):
        pid = int(url.rsplit('/',1)[1]);r = Mock()
        r.json.return_value = {'id':pid,'status':states[pid],'slug':'race','permalink':'https://example.test/event/race'}
        calls.append(('get',pid));return r
    def put(url, **kwargs):
        pid = int(url.rsplit('/',1)[1]);states[pid] = kwargs['json']['status'];calls.append(('put',pid));return Mock()
    monkeypatch.setattr(tri.requests,'get',get);monkeypatch.setattr(tri.requests,'put',put)
    out = tri.publish_products({'wp_url':'https://example.test','consumer_key':'key','consumer_secret':'secret'},ids)
    assert all(p['status']=='publish' for p in out.values())
    assert [c for c in calls if c[0]=='put']==[('put',10),('put',11)]
    assert calls[-3:]==[('get',10),('get',11),('get',12)]


def test_successful_http_that_leaves_draft_is_not_publication(monkeypatch):
    r = Mock();r.json.return_value={'id':10,'status':'draft','slug':'','permalink':'https://example.test/?p=10'}
    monkeypatch.setattr(tri.requests,'get',Mock(return_value=r));monkeypatch.setattr(tri.requests,'put',Mock())
    with pytest.raises(ValueError,match='черновиком'):
        tri.publish_products({'wp_url':'https://example.test','consumer_key':'key','consumer_secret':'secret'},{'es':10})
