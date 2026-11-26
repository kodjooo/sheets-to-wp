<?php
/** Журнал изменений общих значений, без токенов, IP и тел запросов. */
if ( ! defined( 'ABSPATH' ) ) { exit; }
function rf_term_audit_directory() {
    return defined('RF_TERM_AUDIT_DIR') ? RF_TERM_AUDIT_DIR : '/home/developer/racefinder-validation/term-audit';
}
function rf_term_audit_context() {
    $uri = parse_url( $_SERVER['REQUEST_URI'] ?? '', PHP_URL_PATH );
    $stack = array();
    foreach ( debug_backtrace( DEBUG_BACKTRACE_IGNORE_ARGS, 20 ) as $frame ) {
        $function = ( $frame['class'] ?? '' ) . ( $frame['type'] ?? '' ) . ( $frame['function'] ?? '' );
        if ( str_starts_with( $function, 'rf_term_audit_' ) ) { continue; }
        $stack[] = array( 'function' => $function, 'file' => isset($frame['file']) ? basename($frame['file']) : '', 'line' => $frame['line'] ?? 0 );
    }
    $action = $_REQUEST['action'] ?? '';
    return array( 'user_id' => function_exists('get_current_user_id') ? get_current_user_id() : 0,
        'channel' => PHP_SAPI === 'cli' ? 'cli' : (defined('DOING_CRON') && DOING_CRON ? 'cron' : (defined('REST_REQUEST') && REST_REQUEST ? 'rest' : 'web')),
        'path' => is_string($uri) ? $uri : '', 'action' => is_string($action) ? substr(preg_replace('/[^a-zA-Z0-9_:-]/','',$action),0,100) : '', 'stack' => $stack );
}
function rf_term_audit_write( $event, $data ) {
    $previous = umask(0077); $ok = false;
    try {
        $directory = rf_term_audit_directory();
        if ( ! is_dir($directory) && ! mkdir($directory,0700,true) ) { return false; }
        $path = $directory . '/events-' . gmdate('Y-m-d') . '.jsonl';
        if ( is_link($path) ) { return false; }
        $record = array('time_utc'=>gmdate('c'),'request_id'=>$GLOBALS['rf_term_audit_request_id'] ??= bin2hex(random_bytes(8)), 'event'=>$event,'context'=>rf_term_audit_context(),'data'=>$data);
        $line = json_encode($record, JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES|JSON_THROW_ON_ERROR) . "\n";
        $ok = file_put_contents($path,$line,FILE_APPEND|LOCK_EX) === strlen($line);
        if ( $ok ) { chmod($path,0600); }
    } catch (Throwable $error) { $ok = false; }
    finally { umask($previous); if(!$ok)error_log('RaceFinder: term audit write failed'); }
    return $ok;
}
function rf_term_audit_state( $taxonomy, $term_id=0, $trid=0 ) {
    global $wpdb;
    if ( ! str_starts_with($taxonomy,'pa_') ) { return array(); }
    if (!$trid && $term_id) {
        $trid=(int)$wpdb->get_var($wpdb->prepare("SELECT i.trid FROM {$wpdb->term_taxonomy} tt JOIN {$wpdb->prefix}icl_translations i ON i.element_id=tt.term_taxonomy_id AND i.element_type=CONCAT('tax_',tt.taxonomy) WHERE tt.term_id=%d AND tt.taxonomy=%s",$term_id,$taxonomy));
    }
    return $wpdb->get_results($wpdb->prepare("SELECT t.term_id,t.name,t.slug,tt.term_taxonomy_id,tt.taxonomy,i.translation_id,i.language_code,i.trid,i.source_language_code FROM {$wpdb->terms} t JOIN {$wpdb->term_taxonomy} tt USING(term_id) LEFT JOIN {$wpdb->prefix}icl_translations i ON i.element_id=tt.term_taxonomy_id AND i.element_type=CONCAT('tax_',tt.taxonomy) WHERE tt.taxonomy=%s AND (t.term_id=%d OR (i.trid=%d AND i.trid<>0)) ORDER BY t.term_id",$taxonomy,$term_id,$trid),ARRAY_A);
}
function rf_term_audit_language_before($args) {
    $type=$args['element_type']??'';if(!str_starts_with($type,'tax_pa_'))return;
    global $wpdb;$taxonomy=substr($type,4);$tt=(int)($args['element_id']??0);$term=(int)$wpdb->get_var($wpdb->prepare("SELECT term_id FROM {$wpdb->term_taxonomy} WHERE term_taxonomy_id=%d AND taxonomy=%s",$tt,$taxonomy));
    $safe_args=array_intersect_key($args,array_flip(array('element_id','element_type','trid','language_code','source_language_code','check_duplicates','check_null')));
    $entry=array('args'=>$safe_args,'taxonomy'=>$taxonomy,'term_id'=>$term,'before'=>rf_term_audit_state($taxonomy,$term,(int)($args['trid']??0)));
    $GLOBALS['rf_term_audit_pending'][]=$entry;
    rf_term_audit_write('language_change_requested',$entry);
}
function rf_term_audit_language_after($args) {
    $type=$args['element_type']??'';if(!str_starts_with($type,'tax_pa_'))return;
    $entry=array_pop($GLOBALS['rf_term_audit_pending']);if(!$entry)return;
    $entry['after']=rf_term_audit_state($entry['taxonomy'],$entry['term_id'],(int)($args['trid']??0));
    rf_term_audit_write('language_change_finished',$entry);
}
add_action('wpml_set_element_language_details','rf_term_audit_language_before',0,1);
add_action('wpml_set_element_language_details','rf_term_audit_language_after',PHP_INT_MAX,1);
add_action('wpml_translation_update',function($args){$type=$args['element_type']??'';if(!str_starts_with($type,'tax_pa_'))return;$taxonomy=substr($type,4);rf_term_audit_write('wpml_translation_update',array('operation'=>array_intersect_key($args,array_flip(array('type','trid','element_id','element_type','translation_id','context'))),'state'=>rf_term_audit_state($taxonomy,0,(int)($args['trid']??0))));},PHP_INT_MAX,1);
add_action('edit_terms',function($term,$taxonomy){if(str_starts_with($taxonomy,'pa_'))rf_term_audit_write('term_before_edit',array('taxonomy'=>$taxonomy,'term_id'=>$term,'state'=>rf_term_audit_state($taxonomy,(int)$term)));},0,2);
foreach(array('created_term','edited_term','delete_term') as $hook){add_action($hook,function($term,$tt,$taxonomy)use($hook){if(str_starts_with($taxonomy,'pa_'))rf_term_audit_write($hook,array('taxonomy'=>$taxonomy,'term_id'=>$term,'state'=>rf_term_audit_state($taxonomy,(int)$term)));},PHP_INT_MAX,3);}
add_action('pre_delete_term',function($term,$taxonomy){if(str_starts_with($taxonomy,'pa_'))rf_term_audit_write('term_before_delete',array('taxonomy'=>$taxonomy,'term_id'=>$term,'state'=>rf_term_audit_state($taxonomy,(int)$term)));},0,2);
add_action('shutdown',function(){foreach($GLOBALS['rf_term_audit_pending']??array() as $entry){$entry['after']=rf_term_audit_state($entry['taxonomy'],$entry['term_id']);rf_term_audit_write('language_change_interrupted',$entry);}},PHP_INT_MAX);

function rf_import_check_dictionary_baseline($taxonomy) {
    $file=rf_term_audit_directory().'/baseline.json';if(!is_file($file))return null;
    $baseline=json_decode(file_get_contents($file),true);if(!is_array($baseline)||empty($baseline['terms'])||!is_array($baseline['terms']))return new WP_Error('rf_dictionary_baseline','Повреждён контрольный снимок справочника',array('status'=>503));
    foreach($baseline['terms'] as $expected){if(!is_array($expected)||array_diff(array('taxonomy','term_id','lang','trid','name'),array_keys($expected)))return new WP_Error('rf_dictionary_baseline','Неполный контрольный снимок справочника',array('status'=>503));if($expected['taxonomy']!==$taxonomy)continue;$actual=rf_import_raw_term($taxonomy,'term_id',(int)$expected['term_id']);
        if(!$actual||$actual['lang']!==$expected['lang']||(int)$actual['trid']!==(int)$expected['trid']||$actual['name']!==$expected['name']){
            rf_term_audit_write('dictionary_baseline_mismatch',array('expected'=>$expected,'actual'=>$actual));return new WP_Error('rf_dictionary_changed','Изменились общие переводы атрибутов; требуется проверка справочника',array('status'=>409));
        }
    }
    return null;
}
