"""DEV: проверка неизвестной цены, нуля и повторного импорта без очистки сохранённых сроков."""
import os,json
from pathlib import Path
from decimal import Decimal
import requests,gspread
from google.oauth2.service_account import Credentials
b=Path('/validation');cfg=json.loads((b/'dev-auth.json').read_text());inp=json.loads((b/'input.json').read_text());phase=os.getenv('RF_DEV_EMPTY_PHASE','seed');host=cfg['WP_URL'];assert host=='https://dev.racefinder.pt'
auth=(cfg['WP_CONSUMER_KEY'],cfg['WP_CONSUMER_SECRET'])
c=gspread.authorize(Credentials.from_service_account_file('/app/google-credentials.json',scopes=['https://www.googleapis.com/auth/spreadsheets']));w=c.open_by_key(inp['spreadsheet_id']).worksheet(inp['worksheet']);values=w.get_all_values();h=values[0];rows=[dict(zip(h,row)) for row in values[1:4]];parent=rows[0]
assert parent['ID']==inp['event_id'];assert parent['STATUS']=='Published',(parent['STATUS'],parent.get('NOTE'))
def api(method,path,lang,body=None):
 r=requests.request(method,host+'/wp-json/wc/v3/'+path,params={'lang':lang},auth=auth,json=body,timeout=90);r.raise_for_status();return r.json()
def canonical_schedule(items):return [(str(x['datetime'])[:16],Decimal(str(x['price']))) for x in items]
products={l:int(parent['WP PRODUCT ID '+l.upper()]) for l in ['es','en','pt']};expected_prices=['','0','12.50'];report={'phase':phase,'products':products,'languages':[]};snap={}
for lang,pid in products.items():
 p=api('GET','products/'+str(pid),lang);assert p['status']=='draft';assert p['lang']==lang,p.get('lang')
 meta={m['key']:m['value'] for m in p['meta_data']};assert not meta.get('event_date_end');assert not meta.get('_icl_lang_duplicate_of')
 vs=api('GET',f'products/{pid}/variations?per_page=100',lang);assert len(vs)==3
 byid={int(v['id']):v for v in vs};ordered=[]
 for row,price in zip(rows,expected_prices):
  vid=int(row['WP VARIATION ID '+lang.upper()]);v=byid[vid];actual=str(v.get('regular_price') or '')
  assert actual=='' if price=='' else actual!='' and Decimal(actual)==Decimal(price),(lang,vid,price,actual)
  ordered.append({'id':vid,'regular_price':actual,'attributes':v['attributes'],'status':v['status']})
 if phase=='seed':
  deadline='2026-11-30 18:00:00';schedule=[{'datetime':'2027-06-01 00:00:00','price':'99'}]
  api('PUT','products/'+str(pid),lang,{'miss_events':{'registration_deadline':deadline},'meta_data':[{'key':'_event_administration_fee','value':'0.85'}]})
  for v in vs:api('PUT',f'products/{pid}/variations/{v["id"]}',lang,{'miss_events':{'price_schedule':schedule},'meta_data':[{'key':'_event_administration_fee','value':'2.35'}]})
 else:
  baseline=json.loads((b/'seed-baseline.json').read_text());assert products==baseline['products']
  old=baseline['variants'][lang];assert {x['id'] for x in ordered}=={x['id'] for x in old}
  for v in ordered:
   prev=next(x for x in old if x['id']==v['id'])
   def sig(item):
    text=str(item.get('regular_price') or '')
    price=Decimal(text) if text else None
    attrs={int(a['id']):a.get('option') for a in item['attributes'] if a.get('option')}
    return item['id'],price,attrs,item['status']
   assert sig(v)==sig(prev),(lang,v,prev)
 p=api('GET','products/'+str(pid),lang);meta={m['key']:m['value'] for m in p['meta_data']}
 assert p['miss_events']['registration_deadline'].startswith('2026-11-30 18:00')
 assert str(meta['_event_administration_fee'])=='0.85'
 for v in api('GET',f'products/{pid}/variations?per_page=100',lang):
  assert canonical_schedule(v['miss_events']['price_schedule'])==[('2027-06-01 00:00',Decimal('99'))]
  assert str({m['key']:m['value'] for m in v['meta_data']}['_event_administration_fee'])=='2.35'
 snap[lang]=ordered;report['languages'].append({'lang':lang,'product_id':pid,'variation_ids':[x['id'] for x in ordered],'unknown_price_preserved':True,'explicit_zero_preserved':True,'paid_price_preserved':True,'end_date_empty':True,'saved_deadline_and_schedules_preserved':True,'fees_preserved':True})
if phase=='seed':
 (b/'seed-baseline.json').write_text(json.dumps({'products':products,'variants':snap},ensure_ascii=False,indent=2))
 from gspread.utils import rowcol_to_a1
 w.update(values=[['Revised (complete)']],range_name=rowcol_to_a1(2,h.index('STATUS')+1),value_input_option='RAW')
else:report['repeat_ids_preserved']=True
report['ok']=True;(b/(phase+'-validation.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False))
