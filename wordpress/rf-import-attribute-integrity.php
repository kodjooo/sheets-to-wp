<?php
if ( ! defined( 'ABSPATH' ) ) { exit; }
// Язык проверяется по исходным строкам БД: WCML может переводить значения при чтении.
function rf_import_raw_term( $taxonomy, $field, $value ) {
    global $wpdb;
    if ( ! in_array( $field, array( 'term_id', 'slug' ), true ) ) { return null; }
    $where = $field === 'term_id' ? 't.term_id=%d' : 't.slug=%s';
    $rows = $wpdb->get_results( $wpdb->prepare( "SELECT t.term_id,t.name,t.slug,tt.term_taxonomy_id,tt.taxonomy,i.language_code AS lang,i.trid FROM {$wpdb->terms} t JOIN {$wpdb->term_taxonomy} tt USING(term_id) LEFT JOIN {$wpdb->prefix}icl_translations i ON i.element_id=tt.term_taxonomy_id AND i.element_type=CONCAT('tax_',tt.taxonomy) WHERE tt.taxonomy=%s AND {$where}", $taxonomy, $value ), ARRAY_A );
    return count( $rows ) === 1 ? $rows[0] : null;
}

function rf_import_raw_option_issues( $id, $language ) {
    global $wpdb;
    $actual_language = $wpdb->get_var( $wpdb->prepare( "SELECT language_code FROM {$wpdb->prefix}icl_translations WHERE element_type='post_product' AND element_id=%d", $id ) );
    if ( $actual_language !== $language ) { return array( array( 'kind' => 'product_language', 'id' => $id ) ); }
    $issues = array(); $attached = array();
    $relations = $wpdb->get_results( $wpdb->prepare( "SELECT tt.taxonomy,t.term_id,tt.term_taxonomy_id,i.language_code AS lang FROM {$wpdb->term_relationships} r JOIN {$wpdb->term_taxonomy} tt USING(term_taxonomy_id) JOIN {$wpdb->terms} t USING(term_id) LEFT JOIN {$wpdb->prefix}icl_translations i ON i.element_id=tt.term_taxonomy_id AND i.element_type=CONCAT('tax_',tt.taxonomy) WHERE r.object_id=%d AND LEFT(tt.taxonomy,3)='pa_'", $id ), ARRAY_A );
    foreach ( $relations as $r ) {
        $attached[$r['term_taxonomy_id']] = true;
        if ( $r['lang'] !== $language ) { $issues[] = array( 'kind' => 'parent_term_language', 'term_id' => (int) $r['term_id'] ); }
    }
    $values = $wpdb->get_results( $wpdb->prepare( "SELECT m.meta_id,m.meta_key,m.meta_value,v.ID AS variation_id FROM {$wpdb->posts} v JOIN {$wpdb->postmeta} m ON m.post_id=v.ID WHERE v.post_parent=%d AND v.post_type='product_variation' AND v.post_status NOT IN ('trash','auto-draft') AND LEFT(m.meta_key,13)='attribute_pa_' AND m.meta_value<>''", $id ), ARRAY_A );
    // Значения по умолчанию тоже участвуют в выборе варианта.
    $serialized = $wpdb->get_var( $wpdb->prepare( "SELECT meta_value FROM {$wpdb->postmeta} WHERE post_id=%d AND meta_key='_default_attributes' LIMIT 1", $id ) );
    $defaults = maybe_unserialize( $serialized );
    foreach ( is_array( $defaults ) ? $defaults : array() as $tax => $slug ) {
        if ( str_starts_with( $tax, 'pa_' ) && $slug !== '' ) { $values[] = array( 'meta_key' => 'attribute_' . $tax, 'meta_value' => $slug, 'variation_id' => 0 ); }
    }
    foreach ( $values as $v ) {
        $term = rf_import_raw_term( substr( $v['meta_key'], 10 ), 'slug', $v['meta_value'] );
        if ( ! $term || $term['lang'] !== $language || ! isset( $attached[$term['term_taxonomy_id']] ) ) {
            $issues[] = array( 'kind' => 'variation_or_default_term', 'variation_id' => (int) $v['variation_id'], 'key' => $v['meta_key'], 'value' => $v['meta_value'] );
        }
    }
    return $issues;
}

function rf_import_native_defaults( $id, $language, $allowed ) {
    global $wpdb;
    $raw = $wpdb->get_var( $wpdb->prepare( "SELECT meta_value FROM {$wpdb->postmeta} WHERE post_id=%d AND meta_key='_default_attributes' LIMIT 1", $id ) );
    $defaults = maybe_unserialize( $raw );
    if ( ! is_array( $defaults ) ) { return array(); }
    foreach ( $defaults as $tax => $slug ) {
        if ( ! str_starts_with( $tax, 'pa_' ) || $slug === '' ) { continue; }
        $source = rf_import_raw_term( $tax, 'slug', $slug ); $matches = array();
        $aid = wc_attribute_taxonomy_id_by_name( $tax );
        foreach ( array_keys( $allowed[$aid] ?? array() ) as $tid ) {
            $target = rf_import_raw_term( $tax, 'term_id', $tid );
            if ( $source && $target && $target['lang'] === $language && $source['trid'] && $source['trid'] === $target['trid'] ) { $matches[] = $target['slug']; }
        }
        if ( count( $matches ) !== 1 ) { return new WP_Error( 'rf_default_option', 'Не найден однозначный перевод значения по умолчанию', array( 'status' => 409 ) ); }
        $defaults[$tax] = $matches[0];
    }
    return $defaults;
}

// Меняется только порядок и позиции; значения, флаги и названия сохраняются.
function rf_import_distance_last_parent_attributes( $attributes ) {
    if ( ! is_array( $attributes ) || ! isset( $attributes['pa_distance'] ) ) { return $attributes; }
    $distance = $attributes['pa_distance'];
    unset( $attributes['pa_distance'] );
    $attributes['pa_distance'] = $distance;
    $position = 0;
    foreach ( $attributes as &$attribute ) { $attribute['position'] = $position++; }
    unset( $attribute );
    return $attributes;
}
