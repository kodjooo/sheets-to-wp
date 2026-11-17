"""Штатный HTTP-прогон DEV: вход, редактор вариаций, комиссии и сохранение карточки.
Приватные настройки и тестовые строки готовятся отдельно; PROD запрещён фиксированным host.
"""
import os,json,re,time
from decimal import Decimal
from pathlib import Path
import requests,gspread
from bs4 import BeautifulSoup
from google.oauth2.service_account import Credentials
base=Path('/validation');cfg=json.loads((base/'dev-auth.json').read_text());inputs=json.loads((base/'input.json').read_text())
FEE='2.35'; PARENT_FEE='0.85'
host='https://dev.racefinder.pt';auth=(cfg['WP_CONSUMER_KEY'],cfg['WP_CONSUMER_SECRET'])
def signature(variation):
 return (Decimal(variation['regular_price']), {int(a['id']):a['option'] for a in variation['attributes'] if a.get('option')}, variation['status'])
def api(method,path,lang=None,**kw):
 r=requests.request(method,host+'/wp-json/wc/v3/'+path,params={'lang':lang} if lang else {},auth=auth,timeout=90,**kw);r.raise_for_status();return r.json()
taxonomy_by_id={int(a['id']):a['slug'] for a in api('GET','products/attributes?per_page=100')}
client=gspread.authorize(Credentials.from_service_account_file('/app/google-credentials.json',scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive']))
w=client.open_by_key(inputs['spreadsheet_id']).worksheet(inputs['worksheet']);values=w.get_all_values();headers=values[0];rows=[dict(zip(headers,r)) for r in values[1:]]
report={'ok':False,'events':[],'method':'Real wp-login, product edit HTML, load/save variations AJAX and post.php forms'}
session=requests.Session();session.get(host+'/wp-login.php',timeout=45)
r=session.post(host+'/wp-login.php',data={'log':cfg['WP_ADMIN_USER'],'pwd':cfg['WP_ADMIN_PASS'],'wp-submit':'Log In','redirect_to':host+'/wp-admin/','testcookie':'1'},timeout=60)
if not any(c.name.startswith('wordpress_logged_in') for c in session.cookies):raise RuntimeError('DEV login did not establish WordPress session')
def serialize(root):
 out=[]
 for el in root.select('input[name],select[name],textarea[name]'):
  name=el.get('name');typ=el.get('type','').lower()
  if el.has_attr('disabled') or typ in ('submit','button','file','reset'):continue
  if typ in ('checkbox','radio') and not el.has_attr('checked'):continue
  if el.name=='select':
   opts=el.select('option[selected]') or ([] if el.has_attr('multiple') else el.select('option')[:1])
   for opt in opts:out.append((name,opt.get('value',opt.text)))
  else:out.append((name,el.text if el.name=='textarea' else el.get('value','')))
 return out
try:
 for event in inputs['events']:
  row=next(r for r in rows if r.get('ID')==event['id'])
  if row.get('STATUS')!='Published':raise RuntimeError('Import incomplete '+event['id']+' '+row.get('STATUS','')+' '+row.get('NOTE',''))
  langs=['pt','en'] if event['scheme']=='LEGACY' else ['pt','es','en'];group=[];expected={}
  for language in langs:
   check_id=int(row.get('WP PRODUCT ID '+language.upper()) or 0)
   if not check_id or api('GET','products/'+str(check_id),language)['status'] not in (('draft','publish') if os.getenv('RF_DEV_RESUME_EDITOR')=='true' else ('draft',)):
    raise RuntimeError('Standard import did not leave all translations as drafts '+event['id'])
  for lang in langs:
   pid=int(row.get('WP PRODUCT ID '+lang.upper()) or 0)
   if not pid:raise RuntimeError('No product ID '+event['id']+' '+lang)
   p=api('GET','products/'+str(pid),lang)
   variants=api('GET',f'products/{pid}/variations',lang,);before={int(v['id']):v for v in variants};expected[pid]=before
   (base/f'baseline-{pid}.json').write_text(json.dumps(before,ensure_ascii=False))
   if len(before)!=event['rows']:raise RuntimeError('Unexpected variation count '+str(pid))
   api('PUT','products/'+str(pid),lang,json={'status':'publish'})
   url=host+f'/wp-admin/post.php?post={pid}&action=edit&lang={lang}'
   edit=session.get(url,timeout=90);edit.raise_for_status()
   m=re.search(r'var woocommerce_admin_meta_boxes_variations\s*=\s*(\{.*?\});',edit.text,re.S)
   if not m:raise RuntimeError('Variation nonces not found '+str(pid))
   nonces=json.loads(m.group(1))
   ajax=host+'/wp-admin/admin-ajax.php?lang='+lang
   loaded=session.post(ajax,data={'action':'woocommerce_load_variations','security':nonces['load_variations_nonce'],'product_id':pid,'page':1,'per_page':100},timeout=90);loaded.raise_for_status()
   soup=BeautifulSoup(loaded.text,'html.parser');forms=soup.select('.woocommerce_variation')
   if len(forms)!=len(before):raise RuntimeError('Editor shows a different number of variations '+str(pid))
   for form in forms:
    vi=form.select_one('input[name^="variable_post_id"]');vid=int(vi['value'])
    if vid not in before:raise RuntimeError('Editor loaded another variation')
    for attr in before[vid]['attributes']:
     tax=taxonomy_by_id[int(attr['id'])]
     select=next((x for x in form.select('select[name^="attribute_"]') if x.get('name','').startswith('attribute_'+tax+'[')),None)
     if select is None:raise RuntimeError('Editor attribute selector missing '+str(vid)+' '+tax)
     selected=select.select_one('option[selected]') or select.select_one('option')
     if attr.get('option') and (selected is None or not selected.get('value') or selected.get_text(strip=True)!=attr['option']):
      raise RuntimeError('Editor lost selected attribute '+str(vid)+' '+tax)
   data=serialize(soup);fee_names=[k for k,v in data if k.startswith('_event_administration_fee_variation[')]
   if len(fee_names)!=len(before):raise RuntimeError('Administration fee fields missing')
   data=[(k,FEE if k in fee_names else v) for k,v in data]
   data.extend([('action','woocommerce_save_variations'),('security',nonces['save_variations_nonce']),('product_id',str(pid))])
   saved=session.post(ajax,data=data,timeout=120);saved.raise_for_status()
   if 'class="error' in saved.text or saved.text.strip()=='-1':raise RuntimeError('Variation save rejected '+str(pid)+' '+saved.text[:180])
   fresh=session.get(url,timeout=90);fresh.raise_for_status();form=BeautifulSoup(fresh.text,'html.parser').select_one('form#post')
   if form is None:raise RuntimeError('Product edit form missing')
   data=serialize(form);found=any(k=='_event_administration_fee' for k,v in data)
   if not found:raise RuntimeError('Product administration fee missing')
   data=[(k,PARENT_FEE if k=='_event_administration_fee' else v) for k,v in data]
   data.append(('save','Update'))
   saved=session.post(host+'/wp-admin/post.php',data=data,timeout=120);saved.raise_for_status()
   after=api('GET',f'products/{pid}/variations',lang)
   if {int(v['id']) for v in after}!=set(before):raise RuntimeError('Variation IDs changed in editor '+str(pid))
   for v in after:
    old=before[int(v['id'])]
    if signature(v)!=signature(old):raise RuntimeError('Editor changed variation attributes/price '+str(v['id']))
    meta={x['key']:str(x['value']) for x in v.get('meta_data',[])}
    if meta.get('_event_administration_fee')!=FEE:raise RuntimeError('Variation fee not saved '+str(v['id']))
   final=api('GET','products/'+str(pid),lang);meta={x['key']:str(x['value']) for x in final.get('meta_data',[])}
   if meta.get('_event_administration_fee')!=PARENT_FEE:raise RuntimeError('Product fee not saved '+str(pid))
   public=requests.get(final['permalink'],timeout=60);public.raise_for_status()
   group.append({'id':pid,'lang':lang,'url':final['permalink'],'variations':list(before),'variation_count':len(before),'status':final['status'],'parent_fee':PARENT_FEE,'variation_fee':FEE,'real_admin_forms_saved':True,'attributes_prices_ids_unchanged':True,'public_http':public.status_code})
   print(json.dumps({'checked':pid,'lang':lang,'variations':len(before)}),flush=True)
  for checked in group:
   final_variants=api('GET',f"products/{checked['id']}/variations",checked['lang'])
   if {int(v['id']) for v in final_variants}!=set(expected[checked['id']]):raise RuntimeError('Later translation save changed IDs')
   for variant in final_variants:
    old=expected[checked['id']][int(variant['id'])]
    if signature(variant)!=signature(old):raise RuntimeError('Later translation save changed another language')
   checked['verified_after_all_translations_saved']=True
  report['events'].append({'event_id':event['id'],'scheme':event['scheme'],'products':group})
 report['ok']=True
except Exception as e:report['error']=str(e);raise
finally:(base/'full-http-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
