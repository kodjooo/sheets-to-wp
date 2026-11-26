<?php
// Адресное восстановление по исходным ID. Посты, цены и комиссии не записываются.
if(PHP_SAPI!=='cli'||realpath(ABSPATH)!==realpath('/var/www/www.racefinder.pt'))exit(2);
global $wpdb;umask(0077);$b='/home/developer/racefinder-validation/dictionary-recovery-20261126';
if(file_exists($b.'/dictionary-restored.json'))throw new RuntimeException('Восстановление уже выполнено');
$source=json_decode(gzdecode(file_get_contents($b.'/dictionary-before.json.gz')),true,512,JSON_THROW_ON_ERROR);$before=[];foreach($source['terms'] as $t)$before[(int)$t['term_id']]=$t;
$ids=[138,223,1004,2511,5871,6415,15452,15453];$tables=[$wpdb->terms,$wpdb->term_taxonomy,$wpdb->termmeta,$wpdb->prefix.'icl_translations'];$engines=(int)$wpdb->get_var($wpdb->prepare("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN (%s,%s,%s,%s) AND engine='InnoDB'",...$tables));if($engines!==4)throw new RuntimeException('Нет транзакций справочника');
if(!rf_term_audit_write('dictionary_recovery_requested',['term_ids'=>$ids,'source'=>$b.'/dictionary-before.json.gz']))throw new RuntimeException('Журнал недоступен');
$active=false;$previous=apply_filters('wpml_current_language',null);
try {
 $wpdb->query('START TRANSACTION');$active=true;$in=implode(',',$ids);$wpdb->get_results("SELECT term_id FROM {$wpdb->terms} WHERE term_id IN ($in) FOR UPDATE");$wpdb->get_results("SELECT translation_id FROM {$wpdb->prefix}icl_translations WHERE element_type='tax_pa_running' AND (trid IN (884,1430) OR element_id IN ($in)) FOR UPDATE");
 foreach($ids as $id){$t=rf_import_raw_term($before[$id]['taxonomy'],'term_id',$id);$old=$before[$id];if(!$t||$t['name']!==$old['name']||$t['slug']!==$old['slug']||($t['lang']??null)!==($old['language_code']??null)||($t['trid']??null)!==($old['trid']??null))throw new RuntimeException('Термин изменился после снимка: '.$id);}
 // Ошибочно назначенные португальскими испанские записи сохраняем по тем же ID,
 // отделяя от канонических групп. Их ссылки в карточках исправляются отдельным планом.
 foreach([15452,15453] as $id){do_action('wpml_set_element_language_details',['element_id'=>$id,'element_type'=>'tax_pa_running','trid'=>false,'language_code'=>'es','source_language_code'=>null,'check_duplicates'=>true]);$t=rf_import_raw_term('pa_running','term_id',$id);if(!$t||$t['lang']!=='es'||in_array((int)$t['trid'],[884,1430],true))throw new RuntimeException('Не отделена ошибочная запись');}
 foreach([138=>884,223=>1430] as $id=>$trid){do_action('wpml_set_element_language_details',['element_id'=>$id,'element_type'=>'tax_pa_running','trid'=>$trid,'language_code'=>'pt','source_language_code'=>'en','check_duplicates'=>true]);$t=rf_import_raw_term('pa_running','term_id',$id);if(!$t||$t['lang']!=='pt'||(int)$t['trid']!==$trid)throw new RuntimeException('Не восстановлена исходная связь');}
 foreach([1004=>'Caminhada',2511=>'Walking',5871=>'Walking',6415=>'Walking'] as $id=>$name){$old=$before[$id];do_action('wpml_switch_language',$old['language_code']);$result=wp_update_term($id,$old['taxonomy'],['name'=>$name,'slug'=>$old['slug']]);if(is_wp_error($result))throw new RuntimeException($result->get_error_message());}
 $expected_names=[1004=>'Caminhada',2511=>'Walking',5871=>'Walking',6415=>'Walking'];$changes=[];
 foreach($ids as $id){$old=$before[$id];$t=rf_import_raw_term($old['taxonomy'],'term_id',$id);if(!$t||$t['slug']!==$old['slug']||$t['name']!==($expected_names[$id]??$old['name']))throw new RuntimeException('Изменились защищённые поля термина');$changes[]=['before'=>$old,'after'=>$t];}
 $bindings=[61=>['en',884],138=>['pt',884],15207=>['es',884],218=>['en',1430],223=>['pt',1430],15150=>['es',1430]];
 foreach($bindings as $id=>[$lang,$trid]){$t=rf_import_raw_term('pa_running','term_id',$id);if(!$t||$t['lang']!==$lang||(int)$t['trid']!==$trid)throw new RuntimeException('Повреждена соседняя связь: '.$id);}
 $wpdb->query('COMMIT');$active=false;
 foreach($ids as $id)clean_term_cache($id,$before[$id]['taxonomy']);
 file_put_contents($b.'/dictionary-restored.json',json_encode(['date_utc'=>gmdate('c'),'changes'=>$changes,'protected_ids_and_slugs_preserved'=>true],JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE|JSON_THROW_ON_ERROR));rf_term_audit_write('dictionary_recovery_committed',['changes'=>$changes]);echo 'Original term IDs and language groups restored; aliases retained'.PHP_EOL;
}finally{if($active){$wpdb->query('ROLLBACK');rf_term_audit_write('dictionary_recovery_rollback',['term_ids'=>$ids]);}do_action('wpml_switch_language',$previous);}
