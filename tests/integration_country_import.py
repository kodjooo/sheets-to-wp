"""Явный интеграционный прогон на одноразовой loopback-копии WordPress.

Подменяются только таблица, источники и генерация текста. WC/JWT/ACF/WPML реальны.
Запускать отдельно от pytest, передав private auth.json и roots.json копии БД.
"""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-dir', required=True)
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    private = Path(args.private_dir)
    state = json.loads((private / 'state.json').read_text())
    assert state['clone_db'] == 'rf_dev_smoke_20261029' and state['stage'] == 'loopback-ready'
    auth = json.loads((private / 'auth.json').read_text())
    roots = json.loads((private / 'roots.json').read_text())
    os.environ.update({
        'GOOGLE_SPREADSHEET_ID': 'isolated-local-fixture', 'OPENAI_API_KEY': 'unused-test',
        'OPENCAGE_API_KEY': 'unused-test', 'WP_URL': 'http://127.0.0.1:8099',
        'WP_ADMIN_USER': auth['user'], 'WP_ADMIN_PASS': auth['password'],
        'WP_CONSUMER_KEY': auth['key'], 'WP_CONSUMER_SECRET': auth['secret'],
        'ENABLE_SPAIN': 'true', 'SPAIN_WP_HOST': '127.0.0.1',
        'CATEGORY_ROOT_MAP_JSON': json.dumps({'Running': {
            'en_parent_id': roots['en'], 'es_parent_id': roots['es'], 'pt_parent_id': roots['pt']}}),
        'SKIP_AI': 'false', 'SKIP_IMAGE': 'true', 'LOG_FILE': '',
        'TELEGRAM_NOTIFICATIONS_ENABLED': 'false', 'PROCESS_COUNTRY': 'all',
    })
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'run'))
    import requests
    import main as pipeline
    import _5_taxonomy_and_attributes as taxonomy
    import _6_create_variations as variations_api
    # Внутренний HTTP имитирует TLS-терминацию; используем Basic auth как на HTTPS DEV.
    taxonomy.wcapi.is_ssl = variations_api.wcapi.is_ssl = True
    from country_profile import active_profile, PT

    request = requests.sessions.Session.request
    def local_only(session, method, url, **kwargs):
        parts = urlsplit(url)
        assert parts.hostname == '127.0.0.1' and parts.port in (8098, 8099), 'External call forbidden'
        kwargs.setdefault('timeout', 35)
        return request(session, method, url, **kwargs)
    requests.sessions.Session.request = local_only
    rows = []
    for code, city, local_title in [('es', 'Badalona, Barcelona', 'Prueba ES'), ('pt', 'Lisboa', 'Teste PT')]:
        row = {'ID': 'RF-SMOKE-'+code, 'COUNTRY': 'Spain' if code == 'es' else '',
               'STATUS': 'Revised (complete)', 'CATEGORY': 'Running',
               'RACE NAME (ES)': local_title if code == 'es' else '',
               'RACE NAME (PT)': local_title if code == 'pt' else 'PT COLUMN MUST STAY',
               'LOCATION (CITY)': city, 'LOCATION': '41.45, 2.25' if code == 'es' else '38.72, -9.14',
               'WEBSITE': 'https://example.invalid/rf-smoke-'+code,
               'BOOK URL': 'https://example.invalid/book-'+code,
               'EVENT START DATE': '15/06/2027', 'EVENT END DATE': '15/06/2027',
               'REGISTRATION DEADLINE': '10/06/2027 18:00', 'PRICE': '15', 'DISTANCE': '5 km'}
        rows.extend([row, {'STATUS': '', 'DISTANCE': '10 km', 'PRICE': '25',
}])
    required = ['COUNTRY','RACE NAME (ES)','RACE NAME (PT)','WP PRODUCT ID ES','WP PRODUCT ID PT',
                'WP PRODUCT ID EN','WP VARIATION ID ES','WP VARIATION ID PT','WP VARIATION ID EN',
                'SUMMARY (ES)','ORG INFO (ES)','BENEFITS (ES)','FAQ (ES)', 'NOTE']
    headers = {key: i+1 for i,key in enumerate(dict.fromkeys(required + [k for r in rows for k in r]))}
    for row in rows:
        for key in headers: row.setdefault(key, '')
    pipeline.load_all_rows = lambda: ([(i+2, dict(r)) for i,r in enumerate(rows)], headers)
    def update(index, updates, headers): rows[index-2].update(updates)
    pipeline._batch_update_cells = update
    pipeline.log_network_diagnostics = lambda: None
    pipeline.extract_text_from_url = lambda _: ('Verified test source ' * 100, None)
    pipeline.validate_source_texts = lambda **kwargs: []
    pipeline.get_coordinates_with_city_fallback = lambda *a: (41.45, 2.25) if active_profile().code == 'es' else (38.72, -9.14)
    pipeline.translate_title_to_en = lambda title: 'RF Smoke ' + active_profile().code.upper() + ' 20261029'
    pipeline.call_openai_assistant = lambda *a,**k: 'Test source'
    pipeline.call_second_openai_assistant = lambda *a,**k: {
        'summary': 'Integration test', 'org_info': 'Integration test information',
        'benefits': 'Water', 'faq': 'Q: Test?\nA: Yes.', 'summary_pt': 'Prueba de integración' if active_profile().code=='es' else 'Teste de integração',
        'org_info_pt': 'Información de prueba', 'benefits_pt': 'Agua',
        'faq_pt': 'Q: Test?\nA: Yes.', 'image_prompt': 'unused'}
    runs = []
    api_auth = (auth['key'], auth['secret'])
    def snapshot():
        result = []
        for index in [0,2]:
            row = rows[index]
            primary = 'ES' if index == 0 else 'PT'
            pair = []
            for language in [primary, 'EN']:
                pid = int(row['WP PRODUCT ID '+language])
                product = requests.get(os.environ['WP_URL']+'/wp-json/wc/v3/products/'+str(pid),auth=api_auth).json()
                variations = requests.get(os.environ['WP_URL']+'/wp-json/wc/v3/products/'+str(pid)+'/variations',auth=api_auth,params={'per_page':100,'lang':language.lower()}).json()
                assert isinstance(variations,list) and len(variations)==2, (pid,variations)
                assert sorted(v['regular_price'] for v in variations)==['15','25'], variations
                metadata = {m['key']:m['value'] for m in product['meta_data']}
                assert metadata.get('event_country') == ('spain' if index==0 else 'portugal'), metadata
                assert metadata.get('event_ticket_url') == row['BOOK URL'], metadata
                other = 'en' if language == primary else primary.lower()
                other_id = int(row['WP PRODUCT ID '+('EN' if language == primary else primary)])
                assert int(product.get('translations', {}).get(other, 0)) == other_id, product.get('translations')
                if index == 0:
                    assert metadata.get('_rf_location_country') == 'es', metadata
                    assert metadata.get('_rf_location_municipality_name') == 'Badalona', metadata
                    assert metadata.get('_rf_location_province_name') == 'Barcelona', metadata
                pair.append({'language':language.lower(),'id':pid,'status':product['status'],
                             'variation_ids':sorted(v['id'] for v in variations),
                             'country':metadata.get('event_country'),
                             'municipality':metadata.get('_rf_location_municipality_name'),
                             'province':metadata.get('_rf_location_province_name')})
            result.append(pair)
        return result
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            pipeline.run_automation()
        assert rows[0]['STATUS']=='Published' and rows[2]['STATUS']=='Published', rows
        assert rows[0]['RACE NAME (PT)']=='PT COLUMN MUST STAY'
        assert active_profile()==PT
        runs.append(snapshot())
        # Повторная отправка тех же блоков на обновление не должна создавать товары/варианты.
        rows[0]['STATUS']=rows[2]['STATUS']='Revised (complete)'
        with contextlib.redirect_stdout(io.StringIO()):
            pipeline.run_automation()
        runs.append(snapshot())
        assert runs[0]==runs[1], runs
        assert rows[1]['WP VARIATION ID ES'] and not rows[1]['WP VARIATION ID PT']
        assert rows[3]['WP VARIATION ID PT'] and not rows[3]['WP VARIATION ID ES']
        result={'passed':True,'database':'disposable clone','runs':runs,
                'scope':'Real WC/JWT/ACF/WPML and variations; local table and deterministic content fixtures',
                'checks':['ES+EN','legacy blank-country PT+EN','two distances and prices',
                          'Book URL','country metadata','repeat without duplicate IDs','country context reset']}
        Path(args.report).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(result,ensure_ascii=False))
    except Exception:
        Path(args.report).write_text(json.dumps({'passed':False,'rows':rows},ensure_ascii=False,indent=2))
        raise


if __name__=='__main__': main()
