<?php
// Изолированные проверки подписей, контрольного снимка и приватности журнала.
define('ABSPATH',__DIR__);define('ARRAY_A','ARRAY_A');define('RF_TERM_AUDIT_DIR',sys_get_temp_dir().'/rf-term-test-'.getmypid());
function add_action(...$args){}
function get_current_user_id(){return 42;}
class WP_Error {function __construct(public $code,public $message,public $data=[]) {}}
class DB {public $terms='terms',$term_taxonomy='term_taxonomy',$prefix='wp_';public $term;function prepare($q,...$a){return [$q,$a];}function get_results($q,$format=null){return $this->term?[$this->term]:[];}}
$wpdb=new DB();require __DIR__.'/../wordpress/rf-import-attribute-integrity.php';require __DIR__.'/../wordpress/rf-import-term-audit.php';
function check($v){if(!$v)throw new RuntimeException('Ошибка проверки словаря');}
foreach([['Caminhada','pt',true],['Caminhada','en',false],['Caminhada','es',false],['Walking','en',true],['Walk','en',true],['Senderismo','es',true],['Senderismo','pt',false],['Carrera en carretera','pt',false],['Carrera en ruta','es',true],['Corrida de Estrada','pt',true],['Trail Run','pt',true],['20 km','es',true],['Название организатора','pt',true]] as [$label,$lang,$valid])check(rf_import_label_matches_language($label,$lang)===$valid);
check(!rf_import_label_matches_language('Senderismo','pt','Walking'));
check(rf_import_label_matches_language('Caminhada','pt','Walking'));
check(rf_import_label_matches_language('  Walking  ','en','Walking'));
mkdir(RF_TERM_AUDIT_DIR,0700,true);$wpdb->term=['term_id'=>'138','name'=>'Caminhada','slug'=>'caminhada','taxonomy'=>'pa_running','lang'=>'pt','trid'=>'884'];file_put_contents(RF_TERM_AUDIT_DIR.'/baseline.json',json_encode(['terms'=>[$wpdb->term]]));check(rf_import_check_dictionary_baseline('pa_running')===null);
$_SERVER['REQUEST_URI']='/wp-admin/admin-ajax.php?_wpnonce=SECRET_TOKEN';$_POST['password']='SECRET_PASSWORD';$_REQUEST['action']='icl_save_term';
$wpdb->term['lang']='es';$error=rf_import_check_dictionary_baseline('pa_running');check($error instanceof WP_Error&&$error->code==='rf_dictionary_changed');
$path=RF_TERM_AUDIT_DIR.'/events-'.gmdate('Y-m-d').'.jsonl';$text=file_get_contents($path);$entry=json_decode(trim($text),true);check(!str_contains($text,'SECRET_TOKEN')&&!str_contains($text,'SECRET_PASSWORD'));check($entry['context']['user_id']===42&&$entry['context']['path']==='/wp-admin/admin-ajax.php'&&$entry['context']['action']==='icl_save_term');check($entry['data']['expected']['lang']==='pt'&&$entry['data']['actual']['lang']==='es');check((fileperms($path)&0777)===0600);
$wpdb->term=null;check(rf_import_check_dictionary_baseline('pa_running') instanceof WP_Error);
foreach(glob(RF_TERM_AUDIT_DIR.'/*') as $f)unlink($f);rmdir(RF_TERM_AUDIT_DIR);echo "Term dictionary: semantic guards, drift detection and private audit passed\n";
