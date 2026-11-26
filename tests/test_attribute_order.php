<?php
// Изолированная проверка без загрузки WordPress и без записи в БД.
define('ABSPATH', __DIR__);
require __DIR__.'/../wordpress/rf-import-attribute-integrity.php';
function check($value) { if (!$value) { throw new RuntimeException('Проверка порядка не пройдена'); } }
$input = ['pa_distance'=>['name'=>'pa_distance','position'=>0,'value'=>'','is_visible'=>1,'is_taxonomy'=>1,'is_variation'=>1], 'pa_race-start-date'=>['name'=>'pa_race-start-date','position'=>0], 'pa_running'=>['name'=>'pa_running','position'=>0]];
$result = rf_import_distance_last_parent_attributes($input);
check(array_keys($result)===['pa_race-start-date','pa_running','pa_distance']);
check(array_column($result,'position')===[0,1,2]);
foreach ($input as $key=>$value) { unset($value['position']); $actual=$result[$key];unset($actual['position']);check($value===$actual); }
check(rf_import_distance_last_parent_attributes($result)===$result);
check(rf_import_distance_last_parent_attributes([])===[]);
check(rf_import_distance_last_parent_attributes(['pa_running'=>['position'=>8]])===['pa_running'=>['position'=>8]]);
check(rf_import_distance_last_parent_attributes(['pa_distance'=>$input['pa_distance']])===['pa_distance'=>$input['pa_distance']]);
echo "Attribute order: preservation and idempotency passed\n";
