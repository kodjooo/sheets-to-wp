<?php
// Проверка выполняется только из CLI и только на существующем DEV.
if (PHP_SAPI !== 'cli') { exit(1); }
$_SERVER['HTTP_HOST']='dev.racefinder.pt'; $_SERVER['SERVER_NAME']='dev.racefinder.pt';
$_SERVER['REQUEST_URI']='/wp-json/'; $_SERVER['REQUEST_METHOD']='POST'; $_SERVER['HTTPS']='on';
define('REST_REQUEST',true); define('WP_USE_THEMES',false);
require '/var/www/dev.racefinder.pt/wp-load.php';
if (realpath(ABSPATH)!==realpath('/var/www/dev.racefinder.pt')) { exit(2); }
$scope='editability-20261117'; $report=['scope'=>$scope,'ok'=>false,'created'=>[]];
function rf_check($value,$message) { if (!$value) { throw new RuntimeException($message); } }
function rf_call($path,$body=[],$method='POST') {
    if (str_starts_with($path,'/wc/v3/')) { $body['lang']=apply_filters('wpml_current_language',null); }
    $proc=proc_open(['php',__DIR__.'/dev-editor-bridge.php'],[['pipe','r'],['pipe','w'],['file','/tmp/rf-editability-20261117/bridge-errors.log','a']],$pipes);
    fwrite($pipes[0],json_encode(['path'=>$path,'method'=>$method,'body'=>$body,'user'=>get_current_user_id()])); fclose($pipes[0]);
    $raw=stream_get_contents($pipes[1]); fclose($pipes[1]); $code=proc_close($proc); $response=json_decode($raw,true);
    if ($code || !is_array($response)) { throw new RuntimeException('REST bridge failed: '.substr($raw,0,500)); }
    $data=$response['data']; if ($response['status']>=300) { throw new RuntimeException($path.' HTTP '.$response['status'].' '.wp_json_encode($data)); }
    return $data;
}
try {
    global $wpdb;
    $admins=get_users(['role'=>'administrator','number'=>1,'fields'=>'ID']);
    rf_check(count($admins)===1,'Нет администратора для локальной проверки'); wp_set_current_user((int)$admins[0]);
    rf_check(current_user_can('manage_woocommerce'),'Нет права manage_woocommerce');
    $catalog=rf_call('/custom-api/v1/import-category-catalog/',[],'GET'); $by_id=[];
    foreach ($catalog as $c) { $by_id[$c['id']]=$c; }
    $child=null; $root=null;
    foreach ($catalog as $c) {
        if ($c['lang']!=='en' || !$c['parent'] || !isset($c['translations']['en'],$c['translations']['pt'],$c['translations']['es'])) { continue; }
        $r=$by_id[$c['parent']] ?? null;
        if ($r && !$r['parent'] && isset($r['translations']['en'],$r['translations']['pt'],$r['translations']['es'])) { $child=$c; $root=$r; break; }
    }
    rf_check($child && $root,'Нет полной существующей группы категорий');
    $roots=$root['translations']; $names=[];
    foreach (['pt','es','en'] as $lang) { $names[$lang]=$by_id[$child['translations'][$lang]]['name']; }
    $category=rf_call('/custom-api/v1/ensure-import-category-group/',['source_id'=>$child['id'],'roots'=>$roots,'names'=>$names]);
    $attribute=null; $term_group=null;
    foreach (wc_get_attribute_taxonomies() as $a) {
        if ($a->attribute_name !== 'distance') { continue; }
        $tax=wc_attribute_taxonomy_name($a->attribute_name);
        $terms=$wpdb->get_results($wpdb->prepare("SELECT t.term_id AS id,t.name,t.slug,i.trid,i.language_code AS lang FROM {$wpdb->terms} t JOIN {$wpdb->term_taxonomy} tt USING(term_id) JOIN {$wpdb->prefix}icl_translations i ON i.element_id=tt.term_taxonomy_id AND i.element_type=%s WHERE tt.taxonomy=%s ORDER BY t.term_id",'tax_'.$tax,$tax),ARRAY_A);
        $groups=[]; $first=[];
        foreach ($terms as $t) { $groups[$t['trid']][$t['lang']]=$t; if ($t['lang']==='en' && !isset($first[$t['name']])) { $first[$t['name']]=$t['id']; } }
        foreach ($groups as $g) {
            if (isset($g['pt'],$g['es'],$g['en']) && $g['en']['name']==='10 km' && $first[$g['en']['name']]===$g['en']['id']) { $attribute=(int)$a->attribute_id; $term_group=$g; break 2; }
        }
    }
    rf_check($attribute && $term_group,'Нет полного существующего атрибута PT/ES/EN');
    $labels=[]; foreach (['pt','es','en'] as $lang) { $labels[$lang]=$term_group[$lang]['name']; }
    $terms=rf_call('/custom-api/v1/ensure-import-terms/',['items'=>[['attribute_id'=>$attribute,'labels'=>$labels]]])['items'][0];
    do_action('wpml_switch_language','pt');
    $original=rf_call('/wc/v3/products',['name'=>'RF MAIN VALIDATION 2026-11-11 PT','type'=>'variable','status'=>'draft','catalog_visibility'=>'hidden','meta_data'=>[['key'=>'_rf_test_scope','value'=>$scope],['key'=>'event_country','value'=>'Spain'],['key'=>'event_date','value'=>'20271230'],['key'=>'event_date_end','value'=>'20271231']]]);
    $products=['pt'=>(int)$original['id']]; $report['created'][]=$products['pt'];
    foreach (['es','en'] as $lang) {
        $result=rf_call('/custom-api/v1/ensure-language/',['original_id'=>$products['pt'],'lang_code'=>$lang]);
        $products[$lang]=(int)$result['id']; $report['created'][]=$products[$lang];
        update_post_meta($products[$lang],'_rf_test_scope',$scope);
        $repeat=rf_call('/custom-api/v1/ensure-language/',['original_id'=>$products['pt'],'lang_code'=>$lang]);
        rf_check((int)$repeat['id']===$products[$lang],'Повтор создал новый перевод');
        do_action('wpml_switch_language',$lang);
        rf_call('/wc/v3/products/'.$products[$lang],['name'=>'RF MAIN VALIDATION 2026-11-11 '.strtoupper($lang),'status'=>'draft','description'=>'Draft integration check '.$lang,'catalog_visibility'=>'hidden'],'PUT');
    }
    $items=[];
    foreach (['pt','es','en'] as $lang) { $items[]=['product_id'=>$products[$lang],'language'=>$lang,'attributes'=>[['id'=>$attribute,'term_ids'=>[(int)$terms[$lang]['id']]]],'variations'=>[]]; }
    rf_call('/custom-api/v1/apply-import-options/',['items'=>$items]);
    $variations=[];
    foreach (['pt','es','en'] as $lang) {
        do_action('wpml_switch_language',$lang);
        $existing=$wpdb->get_col($wpdb->prepare("SELECT ID FROM {$wpdb->posts} WHERE post_type='product_variation' AND post_parent=%d AND post_status!='trash' ORDER BY ID",$products[$lang]));
        rf_check(count($existing)<=1,'Появились лишние варианты участия');
        $payload=['regular_price'=>'10.00','status'=>'draft','attributes'=>[['id'=>$attribute,'option'=>$terms[$lang]['name']]]];
        $v=$existing ? rf_call('/wc/v3/products/'.$products[$lang].'/variations/'.$existing[0],$payload,'PUT') : rf_call('/wc/v3/products/'.$products[$lang].'/variations',$payload);
        $variations[$lang]=(int)$v['id']; $report['created'][]=$variations[$lang]; update_post_meta($variations[$lang],'_rf_test_scope',$scope);
        if ($lang!=='pt') { rf_call('/custom-api/v1/link-variation-language/',['original_id'=>$variations['pt'],'translated_id'=>$variations[$lang],'lang_code'=>$lang]); }
    }
    foreach ($items as &$item) { $lang=$item['language']; $item['variations']=[['id'=>$variations[$lang],'attributes'=>[['id'=>$attribute,'term_id'=>(int)$terms[$lang]['id']]]]]; }
    unset($item);
    rf_call('/custom-api/v1/apply-import-options/',['items'=>$items]);
    rf_check(rf_call('/custom-api/v1/apply-import-options/',['items'=>$items,'verify_only'=>true])['verified'],'Не прошла проверка атрибутов');
    $plan=['roots'=>[$roots],'groups'=>[$category],'ids'=>[]];
    foreach (['pt','es','en'] as $lang) {
        do_action('wpml_switch_language',$lang); $ids=[(int)$roots[$lang],(int)$category['categories'][$lang]['id']]; $plan['ids'][$lang]=$ids;
        $request=new WP_REST_Request('POST','/');
        rf_import_with_exact_terms(function() use($products,$lang,$ids){ return wp_set_object_terms($products[$lang],$ids,'product_cat',false); },$request);
        clean_post_cache($products[$lang]); rf_check(get_post_status($products[$lang])==='draft','Карточка не осталась черновиком');
        rf_check(apply_filters('wpml_post_language_details',null,$products[$lang])['language_code']===$lang,'Неверный язык карточки');
        rf_check(!get_post_meta($products[$lang],'_icl_lang_duplicate_of',true),'Перевод остался технической копией');
    }
    rf_check(rf_call('/custom-api/v1/verify-import-categories/',['plan'=>$plan,'products'=>$products])['verified'],'Не прошла проверка категорий');
    $before_repeat=(int)$wpdb->get_var("SELECT COUNT(*) FROM {$wpdb->posts} WHERE post_type IN ('product','product_variation')");
    foreach (['es','en'] as $lang) { $again=rf_call('/custom-api/v1/ensure-language/',['original_id'=>$products['pt'],'lang_code'=>$lang,'existing_id'=>$products[$lang]]); rf_check((int)$again['id']===$products[$lang],'Повтор изменил ID'); }
    rf_call('/custom-api/v1/apply-import-options/',['items'=>$items,'verify_only'=>true]);
    rf_check($before_repeat===(int)$wpdb->get_var("SELECT COUNT(*) FROM {$wpdb->posts} WHERE post_type IN ('product','product_variation')"),'Повтор создал дубли');
    $editor=[];
    foreach (['pt','es','en'] as $lang) {
        do_action('wpml_switch_language',$lang);
        $editor[$lang]=rf_call('/rf-test/admin',['product_id'=>$products[$lang],'variation_id'=>$variations[$lang],'lang'=>$lang,'fee'=>'1.25']);
        rf_check($editor[$lang]['unchanged'],'Атрибуты изменились после сохранения комиссии '.$lang);
        rf_check($editor[$lang]['fee']==='1.25','Комиссия не сохранилась '.$lang);
    }
    rf_call('/custom-api/v1/apply-import-options/',['items'=>$items,'verify_only'=>true]);
    $report['editor']=$editor;
    wp_set_current_user(0); $denied=rest_do_request(new WP_REST_Request('GET','/custom-api/v1/import-category-catalog'));
    rf_check(in_array($denied->get_status(),[401,403],true),'Закрытый маршрут доступен без авторизации');
    $report+=['products'=>$products,'variations'=>$variations,'languages'=>['pt','es','en'],'all_drafts'=>true,'options_verified'=>true,'categories_verified'=>true,'repeat_ids_preserved'=>true,'anonymous_denied'=>true]; $report['ok']=true;
} catch(Throwable $e) { $report['error']=$e->getMessage(); $report['error_line']=$e->getLine(); }
finally {
    // Убираем только созданные этой проверкой записи через корзину, без удаления чужих данных.
    wp_set_current_user((int)($admins[0] ?? 0)); $scoped=$wpdb->get_col($wpdb->prepare("SELECT DISTINCT post_id FROM {$wpdb->postmeta} WHERE meta_key='_rf_test_scope' AND meta_value=%s",$scope));
    foreach ($scoped as $id) { if (get_post_type($id)==='product') { wp_trash_post((int)$id); } }
    foreach ($scoped as $id) { if (get_post_status($id)!=='trash') { wp_trash_post((int)$id); } }
    $report['test_records_trashed']=count($scoped); do_action('wpml_switch_language',apply_filters('wpml_default_language',null));
    file_put_contents('/tmp/rf-editability-20261117/dev-acceptance.json',wp_json_encode($report,JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE));
}
echo wp_json_encode($report,JSON_UNESCAPED_UNICODE),PHP_EOL; exit($report['ok']?0:1);
