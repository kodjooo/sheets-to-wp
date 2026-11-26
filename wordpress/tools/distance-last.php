<?php
// Только порядок _product_attributes. Остальные строки БД не записываются.
if (PHP_SAPI !== 'cli' || realpath(ABSPATH) !== realpath('/var/www/www.racefinder.pt')) { throw new RuntimeException('Только PROD CLI'); }
global $wpdb;
umask(0077);
$mode = getenv('RF_ORDER_MODE') ?: 'audit';
$dir = '/home/developer/racefinder-validation/distance-last-20261126';
if (!is_dir($dir)) { mkdir($dir,0700,true); }
function rf_order_write($path,$data) { $json=json_encode($data,JSON_UNESCAPED_UNICODE|JSON_THROW_ON_ERROR);if(file_put_contents($path,$json,LOCK_EX)!==strlen($json))throw new RuntimeException('Не сохранён исходник'); }
function rf_order_value($attributes) {
    if(!is_array($attributes)||!isset($attributes['pa_distance']))return $attributes;
    $distance=$attributes['pa_distance'];unset($attributes['pa_distance']);$attributes['pa_distance']=$distance;$i=0;
    foreach($attributes as &$attribute){if(!is_array($attribute))throw new RuntimeException('Неверный атрибут');$attribute['position']=$i++;}unset($attribute);return $attributes;
}
function rf_order_snapshot($pid) {
    global $wpdb;
    $posts=$wpdb->get_results($wpdb->prepare("SELECT * FROM {$wpdb->posts} WHERE ID=%d OR (post_parent=%d AND post_type='product_variation') ORDER BY ID",$pid,$pid),ARRAY_A);
    $ids=array_map('intval',array_column($posts,'ID'));$in=implode(',',$ids);
    return ['posts'=>$posts,'meta'=>$wpdb->get_results("SELECT * FROM {$wpdb->postmeta} WHERE post_id IN ($in) ORDER BY meta_id",ARRAY_A),'terms'=>$wpdb->get_results("SELECT * FROM {$wpdb->term_relationships} WHERE object_id IN ($in) ORDER BY object_id,term_taxonomy_id",ARRAY_A),'languages'=>$wpdb->get_results("SELECT * FROM {$wpdb->prefix}icl_translations WHERE element_id IN ($in) AND element_type IN ('post_product','post_product_variation') ORDER BY translation_id",ARRAY_A)];
}
function rf_order_clear($pid,$snapshot){wp_cache_delete($pid,'post_meta');clean_post_cache($pid);wc_delete_product_transients($pid);foreach($snapshot['posts'] as $p){if((int)$p['ID']!==$pid){wp_cache_delete((int)$p['ID'],'post_meta');clean_post_cache((int)$p['ID']);}}}
if($mode==='audit') {
    $known=json_decode(file_get_contents('/usr/local/sheets-to-wp-racefinder/sheets-to-wp/logs/distance-last-source-ids-20261126.json'),true,512,JSON_THROW_ON_ERROR);$known=array_map('intval',$known);$in=implode(',',$known);
    $seeds=$wpdb->get_col("SELECT p.ID FROM {$wpdb->posts} p JOIN {$wpdb->users} u ON u.ID=p.post_author WHERE p.post_type='product' AND (u.user_login='Alex' OR p.ID IN ($in))");
    $seedin=implode(',',array_map('intval',$seeds));$trids=$wpdb->get_col("SELECT DISTINCT trid FROM {$wpdb->prefix}icl_translations WHERE element_type='post_product' AND element_id IN ($seedin)");$tridin=implode(',',array_map('intval',$trids));
    $products=$wpdb->get_results("SELECT p.ID,p.post_title,p.post_status,i.language_code FROM {$wpdb->posts} p JOIN {$wpdb->prefix}icl_translations i ON i.element_id=p.ID AND i.element_type='post_product' WHERE p.post_type='product' AND p.post_status NOT IN ('trash','auto-draft') AND i.language_code IN ('pt','en','es') AND (p.ID IN ($seedin) OR i.trid IN ($tridin)) ORDER BY p.ID",ARRAY_A);
    $plan=[];$ambiguous=[];$scanned=0;$correct=0;$langs=[];
    foreach($products as $p){$pid=(int)$p['ID'];$rows=$wpdb->get_results($wpdb->prepare("SELECT * FROM {$wpdb->postmeta} WHERE post_id=%d AND meta_key='_product_attributes'",$pid),ARRAY_A);if(count($rows)!==1){if(count($rows)>1)$ambiguous[]=$pid;continue;}$meta=$rows[0];$raw=maybe_unserialize($meta['meta_value']);if(!is_array($raw)||!isset($raw['pa_distance']))continue;$scanned++;$normalized=rf_order_value($raw);if($normalized===$raw){$correct++;continue;}$plan[]=['id'=>$pid,'title'=>$p['post_title'],'status'=>$p['post_status'],'lang'=>$p['language_code'],'meta_id'=>(int)$meta['meta_id'],'before'=>$meta['meta_value'],'after'=>serialize($normalized),'before_order'=>array_keys($raw),'after_order'=>array_keys($normalized)];$langs[$p['language_code']]=($langs[$p['language_code']]??0)+1;}
    $report=['scanned_with_distance'=>$scanned,'already_correct'=>$correct,'planned'=>count($plan),'languages'=>$langs,'ambiguous'=>$ambiguous,'items'=>$plan];rf_order_write($dir.'/plan.json',$report);echo json_encode(array_diff_key($report,['items'=>1]),JSON_UNESCAPED_UNICODE).PHP_EOL;exit;
}
$plan=json_decode(file_get_contents($dir.'/plan.json'),true,512,JSON_THROW_ON_ERROR);$selected=getenv('RF_ORDER_ID');$results=[];
if(!in_array($mode,['apply','verify','rollback'],true)||($mode==='rollback'&&!$selected))throw new RuntimeException('Неверный режим или не указан ID отката');
foreach($plan['items'] as $item){$pid=$item['id'];if($selected&&(int)$selected!==$pid)continue;$current=$wpdb->get_var($wpdb->prepare("SELECT meta_value FROM {$wpdb->postmeta} WHERE meta_id=%d AND post_id=%d AND meta_key='_product_attributes'",$item['meta_id'],$pid));
    if($mode==='rollback') {
        $backup=$dir.'/before-'.$pid.'.json.gz';if(!file_exists($backup))throw new RuntimeException('Нет исходника для отката');
        if($current!==$item['after'])throw new RuntimeException('Порядок изменён после миграции');
        $changed=$wpdb->query($wpdb->prepare("UPDATE {$wpdb->postmeta} SET meta_value=%s WHERE meta_id=%d AND post_id=%d AND meta_key='_product_attributes' AND BINARY meta_value=BINARY %s",$item['before'],$item['meta_id'],$pid,$item['after']));
        if($changed!==1)throw new RuntimeException('Конфликт при откате');rf_order_clear($pid,rf_order_snapshot($pid));$results[]=['id'=>$pid,'status'=>'rolled_back'];continue;
    }
    if($mode==='apply'&&$current===$item['before']) {
        $lock=(string)$wpdb->get_var($wpdb->prepare("SELECT meta_value FROM {$wpdb->postmeta} WHERE post_id=%d AND meta_key='_edit_lock' LIMIT 1",$pid));if($lock && (int)explode(':',$lock)[0]>time()-180){$results[]=['id'=>$pid,'status'=>'editing_skipped'];continue;}
        $before=rf_order_snapshot($pid);$backup=$dir.'/before-'.$pid.'.json.gz';if(file_exists($backup))throw new RuntimeException('Исходник уже существует: '.$pid);$encoded=gzencode(json_encode($before,JSON_UNESCAPED_UNICODE|JSON_THROW_ON_ERROR));if(file_put_contents($backup,$encoded,LOCK_EX)!==strlen($encoded))throw new RuntimeException('Не сохранён исходник');
        $changed=$wpdb->query($wpdb->prepare("UPDATE {$wpdb->postmeta} SET meta_value=%s WHERE meta_id=%d AND post_id=%d AND meta_key='_product_attributes' AND BINARY meta_value=BINARY %s",$item['after'],$item['meta_id'],$pid,$item['before']));if($changed!==1)throw new RuntimeException('Карточка изменилась после проверки: '.$pid);
        $after=rf_order_snapshot($pid);$expected=$before;foreach($expected['meta'] as &$m){if((int)$m['meta_id']===$item['meta_id'])$m['meta_value']=$item['after'];}unset($m);
        if($after!==$expected){rf_order_write($dir.'/concurrent-'.$pid.'.json',$after);throw new RuntimeException('Параллельное изменение, требуется сверка: '.$pid);}
        rf_order_clear($pid,$after);$current=$item['after'];
    }
    if($current!==$item['after']){$results[]=['id'=>$pid,'status'=>'not_applied'];continue;}
    $snapshot=json_decode(gzdecode(file_get_contents($dir.'/before-'.$pid.'.json.gz')),true,512,JSON_THROW_ON_ERROR);$expected=$snapshot;foreach($expected['meta'] as &$m){if((int)$m['meta_id']===$item['meta_id'])$m['meta_value']=$item['after'];}unset($m);$after=rf_order_snapshot($pid);
    if($after!==$expected){rf_order_write($dir.'/verify-difference-'.$pid.'.json',$after);$results[]=['id'=>$pid,'status'=>'concurrent_change'];continue;}
    $parent=wc_get_product($pid);$keys=array_keys($parent->get_attributes());if(end($keys)!=='pa_distance')throw new RuntimeException('Порядок родителя не подтверждён: '.$pid);
    $count=0;foreach($after['posts'] as $post){if($post['post_type']!=='product_variation'||in_array($post['post_status'],['trash','auto-draft'],true))continue;$variant=wc_get_product((int)$post['ID']);$keys=array_keys($variant->get_variation_attributes());if(in_array('attribute_pa_distance',$keys,true)&&end($keys)!=='attribute_pa_distance')throw new RuntimeException('Порядок варианта не подтверждён: '.$post['ID']);$count++;}
    $results[]=['id'=>$pid,'lang'=>$item['lang'],'status'=>'verified','variants'=>$count];
}
rf_order_write($dir.'/'.$mode.($selected?'-'.$selected:'').'.json',$results);$counts=array_count_values(array_column($results,'status'));echo json_encode(['mode'=>$mode,'counts'=>$counts,'variants'=>array_sum(array_column($results,'variants'))],JSON_UNESCAPED_UNICODE).PHP_EOL;
