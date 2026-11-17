<?php
// CLI-проверка только DEV; не устанавливать этот файл в web-каталог.
if (PHP_SAPI !== 'cli') { exit(1); }
$input=json_decode(stream_get_contents(STDIN),true);
$_SERVER['HTTP_HOST']='dev.racefinder.pt'; $_SERVER['SERVER_NAME']='dev.racefinder.pt'; $_SERVER['REQUEST_URI']='/wp-json'.$input['path']; $_SERVER['REQUEST_METHOD']=$input['method']; $_SERVER['HTTPS']='on';
if ($input['path']==='/rf-test/admin') { define('WP_ADMIN',true); $_GET['lang']=$input['body']['lang']; $_REQUEST['lang']=$_GET['lang']; }
define('REST_REQUEST',$input['path']!=='/rf-test/admin'); define('WP_USE_THEMES',false);
require '/var/www/dev.racefinder.pt/wp-load.php';
if(realpath(ABSPATH)!==realpath('/var/www/dev.racefinder.pt'))exit(2);
wp_set_current_user((int)$input['user']);
if ($input['path']==='/rf-test/admin') {
    $pid=(int)$input['body']['product_id']; $vid=(int)$input['body']['variation_id'];
    if (get_post_meta($pid,'_rf_test_scope',true)!=='editability-20261117' || wp_get_post_parent_id($vid)!==$pid) exit(3);
    do_action('wpml_switch_language',$input['body']['lang']);
    require_once WC_ABSPATH.'includes/admin/class-wc-admin-meta-boxes.php';
    require_once WC_ABSPATH.'includes/admin/meta-boxes/class-wc-meta-box-product-data.php';
    $parent=wc_get_product($pid); $variant=wc_get_product($vid);
    $before=$variant->get_attributes(); $form=['product-type'=>'variable','post_ID'=>$pid,'_regular_price'=>'','_sale_price'=>'','_tax_status'=>'taxable','_stock_status'=>'instock','_event_administration_fee'=>'0.50'];
    foreach ($parent->get_attributes() as $i=>$attr) {
        $i=count($form['attribute_names']??[]);
        $form['attribute_names'][$i]=$attr->get_name(); $form['attribute_values'][$i]=$attr->get_options();
        $form['attribute_position'][$i]=$i; $form['attribute_visibility'][$i]=1; $form['attribute_variation'][$i]=1;
        $allowed=array_map(fn($t)=>$t->slug,$attr->get_terms()?:[]);
        $selected=$before[$attr->get_name()]??'';
        if ($selected && !in_array($selected,$allowed,true)) {
            echo json_encode(['status'=>409,'data'=>['message'=>'Редактор не предлагает сохранённое значение','taxonomy'=>$attr->get_name(),'stored'=>$selected,'allowed'=>$allowed]]); exit;
        }
        $form['attribute_'.$attr->get_name()][0]=$selected;
    }
    $form['variable_post_id']=[0=>$vid]; $form['variable_regular_price']=[0=>$variant->get_regular_price()];
    $form['variable_enabled']=[0=>1]; $form['_event_administration_fee_variation']=[0=>$input['body']['fee']];
    $_POST=$form; $_REQUEST=array_merge($_REQUEST,$form);
    WC_Meta_Box_Product_Data::save($pid,get_post($pid));
    WC_Meta_Box_Product_Data::save_variations($pid,get_post($pid));
    clean_post_cache($vid); $after=wc_get_product($vid)->get_attributes();
    echo json_encode(['status'=>200,'data'=>['unchanged'=>$before===$after,'before'=>$before,'after'=>$after,'fee'=>get_post_meta($vid,'_event_administration_fee',true),'parent_fee'=>get_post_meta($pid,'_event_administration_fee',true)]]); exit;
}
$r=new WP_REST_Request($input['method'],rtrim($input['path'],'/')); $r->set_body_params($input['body']);
$result=rest_do_request($r);
echo json_encode(['status'=>$result->get_status(),'data'=>$result->get_data()]);
