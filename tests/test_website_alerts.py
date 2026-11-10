import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'run'))
from website_alerts import format_website_changes


def test_long_change_list_is_bounded_and_has_one_direct_sheet_link():
    changes=[{'id':str(i),'race':'🏃'*200,'url':'https://example.test/'+'long/'*200} for i in range(100)]
    text=format_website_changes(changes,'https://docs.google.com/spreadsheets/d/test/edit#gid=0',checked_at='2026-11-10 02:02 MSK')
    assert 'Changed event pages: 100' in text
    assert text.count('• #')==10 and '90 more' in text and text.count('https://')==1
    assert len(text.encode('utf-16-le'))//2 < 3500


def test_short_list_keeps_all_ids_without_redundant_zero_counters():
    text=format_website_changes([{'id':'482','race':'Half Marathon Évora'}],'https://example.test')
    assert '#482 — Half Marathon Évora' in text and 'Changed event pages: 1' in text
    assert 'Unable' not in text and 'Skipped' not in text and 'more' not in text


def test_multiline_names_and_long_ids_do_not_expand_digest():
    text=format_website_changes([{'id':'1'*200,'race':'A\nB\r\nC\tD'*200}]*50,'https://example.test')
    assert text.count('• #')==10 and '40 more' in text
    assert len(text.encode('utf-16-le'))//2 < 3500
