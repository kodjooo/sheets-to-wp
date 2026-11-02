<?php
/**
 * Plugin Name: RaceFinder Import Languages
 * Description: Самостоятельные языковые версии импортируемого мероприятия.
 */
if ( ! defined( 'ABSPATH' ) ) { exit; }

add_action( 'rest_api_init', function () {
    register_rest_route( 'custom-api/v1', '/ensure-language/', array(
        'methods' => 'POST',
        'permission_callback' => function () { return current_user_can( 'manage_woocommerce' ); },
        'callback' => 'rf_import_ensure_language',
        'args' => array(
            'original_id' => array( 'required' => true, 'type' => 'integer', 'minimum' => 1 ),
            'lang_code' => array( 'required' => true, 'type' => 'string', 'enum' => array( 'pt', 'es', 'en' ) ),
            'existing_id' => array( 'type' => 'integer', 'minimum' => 0, 'default' => 0 ),
        ),
    ) );
} );

function rf_import_ensure_language( $request ) {
    global $wpdb;
    $origin = (int) $request['original_id'];
    $lang = (string) $request['lang_code'];
    if ( 'product' !== get_post_type( $origin ) || ! current_user_can( 'edit_post', $origin ) ) {
        return new WP_Error( 'rf_invalid_origin', 'Недоступное исходное мероприятие', array( 'status' => 403 ) );
    }
    $details = apply_filters( 'wpml_post_language_details', null, $origin );
    $trid = apply_filters( 'wpml_element_trid', null, $origin, 'post_product' );
    if ( ! is_array( $details ) || ! $trid || empty( $details['language_code'] ) || $lang === $details['language_code'] ) {
        return new WP_Error( 'rf_invalid_language', 'Не определена группа WPML либо запрошен язык оригинала', array( 'status' => 400 ) );
    }
    $languages = apply_filters( 'wpml_active_languages', null, array( 'skip_missing' => 0 ) );
    if ( ! is_array( $languages ) || ! isset( $languages[$lang] ) ) {
        return new WP_Error( 'rf_inactive_language', 'Язык не включён в WPML', array( 'status' => 400 ) );
    }
    // Повтор после потери ответа и параллельные запросы не должны создавать четвёртую карточку.
    $lock = 'rf_import_language_' . $origin;
    if ( '1' !== (string) $wpdb->get_var( $wpdb->prepare( 'SELECT GET_LOCK(%s, 10)', $lock ) ) ) {
        return new WP_Error( 'rf_language_busy', 'Группа переводов занята', array( 'status' => 409 ) );
    }
    try {
        $translations = (array) apply_filters( 'wpml_get_element_translations', null, $trid, 'post_product' );
        $id = isset( $translations[$lang] ) ? (int) $translations[$lang]->element_id : 0;
        $expected = (int) $request['existing_id'];
        if ( $expected && get_post( $expected ) && $expected !== $id ) {
            return new WP_Error( 'rf_translation_conflict', 'Сохранённый ID принадлежит другой группе или языку', array( 'status' => 409 ) );
        }
        if ( $id && ( 'product' !== get_post_type( $id ) || ! current_user_can( 'edit_post', $id ) || 'trash' === get_post_status( $id ) ) ) {
            return new WP_Error( 'rf_invalid_translation', 'Недоступная языковая версия', array( 'status' => 409 ) );
        }
        if ( ! $id ) {
            $id = wp_insert_post( array(
                'post_type' => 'product', 'post_status' => 'draft',
                'post_title' => get_the_title( $origin ), 'post_author' => get_current_user_id(),
            ), true );
            if ( is_wp_error( $id ) ) { return $id; }
            wp_set_object_terms( $id, 'variable', 'product_type' );
            do_action( 'wpml_set_element_language_details', array(
                'element_id' => $id, 'element_type' => 'post_product', 'trid' => $trid,
                'language_code' => $lang, 'source_language_code' => $details['language_code'],
                'check_duplicates' => true,
            ) );
        }
        // Такой же переход к самостоятельному переводу используется в seed-es Кирилла.
        delete_post_meta( $id, '_icl_lang_duplicate_of' );
        update_post_meta( $id, '_rf_import_origin', $origin );
        update_post_meta( $id, '_rf_import_language_scheme', 'PT_ES_EN' );
        $country = get_post_meta( $origin, 'event_country', true );
        if ( $country ) { update_post_meta( $id, 'event_country', $country ); }
        $actual = apply_filters( 'wpml_post_language_details', null, $id );
        $actual_trid = apply_filters( 'wpml_element_trid', null, $id, 'post_product' );
        if ( ! is_array( $actual ) || $lang !== $actual['language_code'] || (int) $actual_trid !== (int) $trid ) {
            return new WP_Error( 'rf_language_link_failed', 'WPML не подтвердил связь перевода', array( 'status' => 500 ) );
        }
        return rest_ensure_response( array( 'id' => (int) $id, 'language' => $lang, 'independent' => ! get_post_meta( $id, '_icl_lang_duplicate_of', true ) ) );
    } finally {
        $wpdb->get_var( $wpdb->prepare( 'SELECT RELEASE_LOCK(%s)', $lock ) );
    }
}

add_action( 'rest_api_init', function () {
    register_rest_route( 'custom-api/v1', '/link-variation-language/', array(
        'methods' => 'POST',
        'permission_callback' => function () { return current_user_can( 'manage_woocommerce' ); },
        'callback' => 'rf_import_link_variation_language',
        'args' => array(
            'original_id' => array( 'required' => true, 'type' => 'integer', 'minimum' => 1 ),
            'translated_id' => array( 'required' => true, 'type' => 'integer', 'minimum' => 1 ),
            'lang_code' => array( 'required' => true, 'type' => 'string', 'enum' => array( 'pt', 'es', 'en' ) ),
        ),
    ) );
} );

function rf_import_link_variation_language( $request ) {
    $origin = (int) $request['original_id'];
    $target = (int) $request['translated_id'];
    $lang = (string) $request['lang_code'];
    if ( 'product_variation' !== get_post_type( $origin ) || 'product_variation' !== get_post_type( $target ) ) {
        return new WP_Error( 'rf_missing_variation', 'Вариация не найдена', array( 'status' => 404 ) );
    }
    $parent = (int) wp_get_post_parent_id( $origin );
    $target_parent = (int) wp_get_post_parent_id( $target );
    if ( ! current_user_can( 'edit_post', $parent ) || ! current_user_can( 'edit_post', $target_parent ) ) {
        return new WP_Error( 'rf_variation_forbidden', 'Нет доступа к родительским товарам', array( 'status' => 403 ) );
    }
    $group = apply_filters( 'wpml_element_trid', null, $parent, 'post_product' );
    $target_group = apply_filters( 'wpml_element_trid', null, $target_parent, 'post_product' );
    $parent_language = apply_filters( 'wpml_post_language_details', null, $target_parent );
    if ( ! $group || (int) $group !== (int) $target_group || $parent === $target_parent || ! is_array( $parent_language ) || $lang !== $parent_language['language_code'] ) {
        return new WP_Error( 'rf_variation_parent_conflict', 'Вариации принадлежат разным мероприятиям или неверному языку', array( 'status' => 409 ) );
    }
    $trid = apply_filters( 'wpml_element_trid', null, $origin, 'post_product_variation' );
    $target_trid = apply_filters( 'wpml_element_trid', null, $target, 'post_product_variation' );
    $details = apply_filters( 'wpml_post_language_details', null, $origin );
    if ( ! $trid || ! is_array( $details ) || $lang === $details['language_code'] ) {
        return new WP_Error( 'rf_variation_language', 'Не определён исходный язык вариации', array( 'status' => 409 ) );
    }
    $translations = (array) apply_filters( 'wpml_get_element_translations', null, $trid, 'post_product_variation' );
    if ( isset( $translations[$lang] ) && (int) $translations[$lang]->element_id !== $target ) {
        return new WP_Error( 'rf_variation_target_exists', 'В группе уже есть другая вариация этого языка', array( 'status' => 409 ) );
    }
    if ( (int) $target_trid !== (int) $trid ) {
        $previous = (array) apply_filters( 'wpml_get_element_translations', null, $target_trid, 'post_product_variation' );
        if ( count( $previous ) > 1 ) {
            return new WP_Error( 'rf_variation_group_conflict', 'Вариация уже связана с другой группой', array( 'status' => 409 ) );
        }
        do_action( 'wpml_set_element_language_details', array(
            'element_id' => $target, 'element_type' => 'post_product_variation', 'trid' => $trid,
            'language_code' => $lang, 'source_language_code' => $details['language_code'],
            'check_duplicates' => true,
        ) );
    }
    if ( (int) apply_filters( 'wpml_element_trid', null, $target, 'post_product_variation' ) !== (int) $trid ) {
        return new WP_Error( 'rf_variation_link_failed', 'WPML не подтвердил связь вариаций', array( 'status' => 500 ) );
    }
    return rest_ensure_response( array( 'linked' => true, 'id' => $target ) );
}
