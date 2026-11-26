<?php
// Полный обработчик с изолированным хранилищем: без WordPress, сети и PROD.
define('ABSPATH',__DIR__);define('ARRAY_A','ARRAY_A');define('RF_TERM_AUDIT_DIR',sys_get_temp_dir().'/rf-order-endpoint-test-'.getmypid());
function add_action(...$args){}
class WP_Error {public function __construct(public $code,public $message,public $data=[]) {}}
function is_wp_error($x){return $x instanceof WP_Error;}
function rest_ensure_response($x){return $x;}
function current_user_can(...$args){return true;}
function taxonomy_exists($tax){return in_array($tax,['pa_distance','pa_running'],true);}
function wc_attribute_taxonomy_name_by_id($id){return [1=>'pa_distance',2=>'pa_running'][$id];}
function apply_filters($tag,$value=null,$id=0,...$args){return match($tag){'wpml_post_language_details'=>['language_code'=>$GLOBALS['languages'][$id]],'wpml_element_trid'=>1,default=>'pt'};}
function do_action(...$args){}
function get_post_type($id){return $id<200?'product':'product_variation';}
function wp_get_post_parent_id($id){return $id-100;}
function maybe_unserialize($x){return is_string($x)?unserialize($x):$x;}
function wc_delete_product_transients($id){}
function wp_set_object_terms($id,$terms,$tax,$append){$GLOBALS['relations'][$id][$tax]=$terms;return $terms;}
class WC_Product_Attribute {
 public array $data=[];
 function set_id($v){$this->data['id']=$v;}
 function set_name($v){$this->data['name']=$v;}
 function set_options($v){$this->data['options']=$v;}
 function set_position($v){$this->data['position']=$v;}
 function set_visible($v){}
 function set_variation($v){}
}
class FakeProduct {
 private array $attrs=[];
 function __construct(private int $id){}
 function set_attributes($v){$this->attrs=$v;}
 function set_default_attributes($v){}
 function save(){if($this->id<200){$a=[];foreach($this->attrs as $v){$a[$v->data['name']]=['name'=>$v->data['name'],'position'=>$v->data['position']??0];}$GLOBALS['parents'][$this->id]=$a;}else{$GLOBALS['variants'][$this->id]=$this->attrs;}}
}
function wc_get_product($id){return new FakeProduct($id);}
class FakeDB {
 public $posts='posts',$postmeta='postmeta',$prefix='wp_',$terms='terms',$term_taxonomy='term_taxonomy',$term_relationships='term_relationships';
 function prepare($q,...$args){return [$q,$args];}
 function get_var($p){[$q,$a]=$p;
  if(str_contains($q,'language_code'))return $GLOBALS['languages'][$a[0]];
  if(str_contains($q,"meta_key='_default_attributes'"))return serialize([]);
  if(str_contains($q,"meta_key='_product_attributes'"))return serialize($GLOBALS['parents'][$a[0]]??[]);
  if(str_contains($q,'meta_key=%s'))return $GLOBALS['variants'][$a[0]][substr($a[1],10)]??null;
  throw new RuntimeException($q);
 }
 function get_col($p){[$q,$a]=$p;return $GLOBALS['relations'][$a[0]][$a[1]]??[];}
 function get_results($p,$format=null){[$q,$a]=$p;
  if(str_contains($q,'FROM terms t')){[$tax,$value]=$a;foreach($GLOBALS['catalog'] as $term){if($term['taxonomy']===$tax&&($term['term_id']===$value||$term['slug']===$value))return [$term];}return [];}
  if(str_contains($q,'FROM term_relationships r')){$r=[];foreach($GLOBALS['relations'][$a[0]]??[] as $tax=>$ids){foreach($ids as $tid)$r[]=$GLOBALS['catalog'][$tid];}return $r;}
  if(str_contains($q,'FROM posts v JOIN postmeta')){$r=[];foreach($GLOBALS['variants'][$a[0]+100]??[] as $tax=>$slug)$r[]=['meta_key'=>'attribute_'.$tax,'meta_value'=>$slug,'variation_id'=>$a[0]+100];return $r;}
  throw new RuntimeException($q);
 }
}
$wpdb=new FakeDB();$languages=[101=>'pt',102=>'en',103=>'es'];$catalog=[];$parents=[];$variants=[];$relations=[];$items=[];
foreach($languages as $pid=>$lang){$selected=[];$spec=[];foreach([1=>'pa_distance',2=>'pa_running'] as $aid=>$tax){$tid=$pid*10+$aid;$catalog[$tid]=['term_id'=>$tid,'term_taxonomy_id'=>$tid,'taxonomy'=>$tax,'slug'=>$tax.'-'.$lang,'lang'=>$lang,'trid'=>$aid];$spec[]=['id'=>$aid,'term_ids'=>[$tid]];$selected[]=['id'=>$aid,'term_id'=>$tid];}$items[]=['product_id'=>$pid,'language'=>$lang,'attributes'=>$spec,'variations'=>[['id'=>$pid+100,'attributes'=>$selected]]];}
require __DIR__.'/../wordpress/rf-import-languages.php';
class Request {public function __construct(private $items,private $verify){}function get_param($k){return $k==='items'?$this->items:$this->verify;}}
function check($v){if(!$v)throw new RuntimeException('Не пройдена проверка обработчика');}
foreach([false,true,false,true] as $verify){$result=rf_import_apply_options_exact(new Request($items,$verify));check(!is_wp_error($result)&&$result['verified']&&$result['raw_verified']&&$result['products_checked']===3);foreach($parents as $a){check(array_keys($a)===['pa_running','pa_distance']);check(array_column($a,'position')===[0,1]);}}
$parents[101]=array_reverse($parents[101],true);$result=rf_import_apply_options_exact(new Request($items,true));check(is_wp_error($result)&&$result->code==='rf_attribute_order');
echo "Native endpoint: create, repeat and persisted-order rejection passed for PT/EN/ES\n";
