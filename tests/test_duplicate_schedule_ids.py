"""Одинаковые опции не должны переносить расписание цены на соседнюю строку."""
from unittest.mock import Mock
import pytest
import _6_create_variations as variations


def test_identical_options_apply_different_schedules_to_exact_row_ids(monkeypatch):
    monkeypatch.setattr(variations,'_load_all_variations',Mock(return_value=[{'id':11},{'id':12}]))
    request=Mock();monkeypatch.setattr(variations,'_wcapi_request_with_retry',request)
    entries=[{'row_index':2,'attributes':[{'name':'Distance','option':'10 km'}],'price_schedule':[{'datetime':'2027-01-01 00:00','price':'20'}]},
             {'row_index':3,'attributes':[{'name':'Distance','option':'10 km'}],'price_schedule':[{'datetime':'2027-01-01 00:00','price':'30'}]}]
    variations.reapply_price_schedules(1,entries,lang='pt',variation_ids={2:11,3:12})
    assert [(c.args[1],c.args[2]['miss_events']['price_schedule'][0]['price']) for c in request.call_args_list]==[('products/1/variations/11?lang=pt','20'),('products/1/variations/12?lang=pt','30')]


@pytest.mark.parametrize('mapping',[{2:11,3:11},{2:11,3:99},{2:11}])
def test_invalid_row_ids_cannot_reassign_schedules(monkeypatch,mapping):
    monkeypatch.setattr(variations,'_load_all_variations',Mock(return_value=[{'id':11},{'id':12}]))
    request=Mock();monkeypatch.setattr(variations,'_wcapi_request_with_retry',request)
    entries=[{'row_index':2,'price_schedule':[{'datetime':'2027-01-01 00:00','price':'20'}]},{'row_index':3,'price_schedule':[]}]
    with pytest.raises(ValueError):variations.reapply_price_schedules(1,entries,lang='pt',variation_ids=mapping)
    request.assert_not_called()
