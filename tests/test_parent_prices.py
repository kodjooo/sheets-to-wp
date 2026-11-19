"""Итоговые цены родителей и уже наступившие этапы расписания."""
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import Mock
import pytest
import trilingual_import as tri
from test_trilingual_import import workflow

@pytest.mark.parametrize('base,schedule,expected',[
    ('60',[{'datetime':'2026-11-01 00:00','price':'65'}],'65'),
    ('50',[{'datetime':'2026-11-01 00:00','price':'55'},{'datetime':'2026-12-01 00:00','price':'60'}],'55'),
    ('10',[{'datetime':'2027-01-01 00:00','price':'20'}],'10'),
    ('',[{'datetime':'2027-01-01 00:00','price':'20'}],''),
    ('0',[], '0'),
    ('20',[{'datetime':'2026-11-01 00:00','price':'0'}],'0'),
    ('10',[{'datetime':'2026-11-18 00:00','price':'30'},{'datetime':'2026-11-01 00:00','price':'20'}],'30'),
])
def test_effective_regular_price_respects_due_dates_and_zero(base,schedule,expected):
    now=datetime(2026,11,19,12,tzinfo=ZoneInfo('Europe/Lisbon'))
    assert tri.effective_regular_price({'regular_price':base,'price_schedule':schedule},now)==expected


def test_price_boundary_uses_wordpress_timezone():
    now=datetime(2026,11,19,0,30,tzinfo=ZoneInfo('Europe/Madrid'))
    entry={'regular_price':'10','price_schedule':[{'datetime':'2026-11-19 00:00','price':'20'}]}
    assert tri.effective_regular_price(entry,now)=='20'
    assert tri.effective_regular_price(entry,now.astimezone(ZoneInfo('UTC')))=='10'


def test_missing_site_clock_cannot_guess_price_timezone():
    with pytest.raises(ValueError,match='часовой пояс'):
        tri.site_price_now({})


def test_finalize_price_failure_keeps_ids_and_does_not_mark_success(workflow,monkeypatch):
    w=workflow
    monkeypatch.setattr(tri,'finalize_prices',Mock(side_effect=ValueError('Parent price missing')))
    with pytest.raises(ValueError):w.run()
    assert w.row['STATUS']=='Revised (complete)'
    ids={k:v for k,v in w.row.items() if ' ID ' in k}
    monkeypatch.setattr(tri,'finalize_prices',Mock())
    w.run()
    assert w.row['STATUS']=='Published'
    assert ids=={k:v for k,v in w.row.items() if ' ID ' in k}
    assert len(w.created)==1
