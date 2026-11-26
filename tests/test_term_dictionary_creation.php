<?php
// Настоящий обработчик со снимком транзакции в изолированном хранилище.
define('ABSPATH',__DIR__);define('ARRAY_A','ARRAY_A');define('RF_TERM_AUDIT_DIR',sys_get_temp_dir().'/rf-term-creation-'.getmypid());
function add_action(...$args){}
function get_current_user_id(){return 0;}
class WP_Error {function __construct(public $code,public $message,public $data=[]) {}}
function is_wp_error($v){return $v instanceof WP_Error;}
function rest_ensure_response($v){return $v;}
function taxonomy_exists($tax){return $tax==='pa_running';}
function wc_attribute_taxonomy_name_by_id($id){return 'pa_running';}
function sanitize_title($s){return strtolower(str_replace(' ','-',$s));}
function clean_term_cache(...$args){}
function apply_filters($name,...$args){if($name!=='wpml_current_language')throw new RuntimeException('Не использовать кеш WPML для выбора термина');return $GLOBALS['language'];}
function get_term_by(...$args){return null;}
function wp_insert_term($name,$tax,$args){$id=1000+count($GLOBALS['terms']);$GLOBALS['terms'][$id]=['term_id'=>$id,'term_taxonomy_id'=>$id,'name'=>$name,'slug'=>$args['slug'],'taxonomy'=>$tax,'lang'=>$GLOBALS['language'],'trid'=>$id];$GLOBALS['created_contexts'][]=$GLOBALS['language'];return ['term_id'=>$id,'term_taxonomy_id'=>$id];}
function do_action($name,...$args){if($name==='wpml_switch_language'){$GLOBALS['language']=$args[0];return;}if($name==='wpml_set_element_language_details'){$a=$args[0];$GLOBALS['terms'][$a['element_id']]['lang']=$a['language_code'];$GLOBALS['terms'][$a['element_id']]['trid']=$a['trid'];if($GLOBALS['break_existing']??false)unset($GLOBALS['terms'][138]);}}
class DB {
 public $terms='terms',$term_taxonomy='term_taxonomy',$termmeta='termmeta',$prefix='wp_';public $backup;public $rolled=false;
 function prepare($q,...$args){return [$q,$args];}
 function get_var($p){[$q,$a]=$p;
  if(str_contains($q,'information_schema'))return 4;
  if(str_contains($q,'GET_LOCK')||str_contains($q,'RELEASE_LOCK'))return '1';
  if(str_contains($q,'t.name=%s')){foreach($GLOBALS['terms'] as $t)if($t['name']===$a[2]&&$t['lang']==='en')return $t['term_id'];return null;}
  if(str_contains($q,'SELECT trid'))return $GLOBALS['terms'][$a[0]]['trid']??null;
  if(str_contains($q,'SELECT term_id'))return $a[0];
  throw new RuntimeException($q);
 }
 function get_results($p,$format=null){[$q,$a]=$p;
  if(str_contains($q,'SELECT language_code,element_id')){$out=[];foreach($GLOBALS['terms'] as $t)if($t['trid']===$a[0])$out[]=['language_code'=>$t['lang'],'element_id'=>$t['term_id']];return $out;}
  if(str_contains($q,'FROM terms t')){foreach($GLOBALS['terms'] as $t)if($t['taxonomy']===$a[0]&&($t['term_id']===$a[1]||$t['slug']===$a[1]))return [$t];return [];}
  throw new RuntimeException($q);
 }
 function get_col($p){[$q,$a]=$p;$out=[];foreach($GLOBALS['terms'] as $t)if($t['trid']===$a[0]&&$t['lang']===$a[2])$out[]=$t['term_id'];return $out;}
 function query($q){if($q==='START TRANSACTION')$this->backup=$GLOBALS['terms'];elseif($q==='ROLLBACK'){$GLOBALS['terms']=$this->backup;$this->rolled=true;}elseif($q!=='COMMIT')throw new RuntimeException($q);return true;}
}
require __DIR__.'/../wordpress/rf-import-languages.php';
class Request {function get_param($key){return [['attribute_id'=>3,'labels'=>['en'=>'Walking','pt'=>'Caminhada','es'=>'Senderismo']]];}}
function check($v){if(!$v)throw new RuntimeException('Проверка создания справочника не пройдена');}
function setup_terms(){global $wpdb,$terms,$language,$created_contexts,$break_existing;$wpdb=new DB();$language='pt';$created_contexts=[];$break_existing=false;$terms=[];foreach([61=>['en','Walking'],138=>['pt','Caminhada']] as $id=>[$lang,$name])$terms[$id]=['term_id'=>$id,'term_taxonomy_id'=>$id,'name'=>$name,'slug'=>strtolower($name),'taxonomy'=>'pa_running','lang'=>$lang,'trid'=>884];}
setup_terms();$result=rf_import_ensure_terms_exact(new Request());check(!is_wp_error($result)&&$result['items'][0]['pt']['id']===138&&$created_contexts===['es']&&$language==='pt');$ids=array_keys($terms);$result=rf_import_ensure_terms_exact(new Request());check(!is_wp_error($result)&&array_keys($terms)===$ids);
setup_terms();$terms[138]['name']='Senderismo';$before=$terms;$result=rf_import_ensure_terms_exact(new Request());check(is_wp_error($result)&&$result->code==='rf_dictionary_label'&&$wpdb->rolled&&$terms===$before);
setup_terms();$before=$terms;$break_existing=true;$result=rf_import_ensure_terms_exact(new Request());check(is_wp_error($result)&&$result->code==='rf_dictionary_replaced'&&$wpdb->rolled&&$terms===$before);
foreach(glob(RF_TERM_AUDIT_DIR.'/*') as $f)unlink($f);rmdir(RF_TERM_AUDIT_DIR);echo "Term creation: language context, repeat, bad labels and replacement rollback passed\n";
