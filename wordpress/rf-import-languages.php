<?php
/**
 * Plugin Name: RaceFinder Import Languages
 * Description: Самостоятельные языковые версии импортируемого мероприятия.
 */
if ( ! defined( 'ABSPATH' ) ) { exit; }

// Справочники значений связываются до сохранения родителей: WCML использует эти связи.
add_action( 'rest_api_init', function () {
    register_rest_route( 'custom-api/v1', '/ensure-import-terms/', array(
        'methods' => 'POST',
        'permission_callback' => function () { return current_user_can( 'manage_woocommerce' ); },
        'callback' => 'rf_import_ensure_terms',
    ) );
} );

// При работе с конкретными ID запрещаем фильтру WPML незаметно подставлять другой язык.
function rf_import_with_exact_terms( $callback, $request ) {
    global $woocommerce_wpml;
    $filter = static function () { return true; };
    add_filter( 'wpml_disable_term_adjust_id', $filter, PHP_INT_MAX );
    // Иначе CRUD сравнит новое значение с отображаемым переводом вместо сохранённой меты.
    $metadata_filter = isset( $woocommerce_wpml->attributes ) ? array( $woocommerce_wpml->attributes, 'filter_product_variation_post_meta_attribute_values_in_current_language' ) : null;
    $metadata_priority = $metadata_filter ? has_filter( 'get_post_metadata', $metadata_filter ) : false;
    if ( false !== $metadata_priority ) { remove_filter( 'get_post_metadata', $metadata_filter, $metadata_priority ); }
    try {
        return call_user_func( $callback, $request );
    } finally {
        if ( false !== $metadata_priority ) { add_filter( 'get_post_metadata', $metadata_filter, $metadata_priority, 4 ); }
        remove_filter( 'wpml_disable_term_adjust_id', $filter, PHP_INT_MAX );
    }
}

function rf_import_ensure_terms( $request ) {
    return rf_import_with_exact_terms( 'rf_import_ensure_terms_exact', $request );
}

function rf_import_ensure_terms_exact( $request ) {
    global $wpdb;
    $items = $request->get_param( 'items' );
    if ( ! is_array( $items ) || ! $items || count( $items ) > 200 ) {
        return new WP_Error( 'rf_invalid_terms', 'Требуется от 1 до 200 значений', array( 'status' => 400 ) );
    }
    foreach ( $items as $item ) {
        $taxonomy = wc_attribute_taxonomy_name_by_id( (int) ( $item['attribute_id'] ?? 0 ) );
        if ( ! $taxonomy || ! taxonomy_exists( $taxonomy ) ) {
            return new WP_Error( 'rf_invalid_attribute', 'Неизвестный атрибут', array( 'status' => 400 ) );
        }
        foreach ( array( 'en', 'pt', 'es' ) as $lang ) {
            if ( empty( $item['labels'][$lang] ) || ! is_string( $item['labels'][$lang] ) || strlen( $item['labels'][$lang] ) > 200 ) {
                return new WP_Error( 'rf_invalid_label', 'Нет подписи атрибута', array( 'status' => 400 ) );
            }
        }
    }
    $result = array();
    foreach ( $items as $item ) {
        $taxonomy = wc_attribute_taxonomy_name_by_id( (int) $item['attribute_id'] );
        $type = 'tax_' . $taxonomy;
        $lock = 'rf_terms_' . md5( $taxonomy . $item['labels']['en'] );
        if ( '1' !== (string) $wpdb->get_var( $wpdb->prepare( 'SELECT GET_LOCK(%s,10)', $lock ) ) ) {
            return new WP_Error( 'rf_terms_busy', 'Справочник занят', array( 'status' => 409 ) );
        }
        try {
            $base = $wpdb->get_var( $wpdb->prepare(
                "SELECT tt.term_taxonomy_id FROM {$wpdb->term_taxonomy} tt JOIN {$wpdb->terms} t ON t.term_id=tt.term_id JOIN {$wpdb->prefix}icl_translations i ON i.element_id=tt.term_taxonomy_id AND i.element_type=%s WHERE tt.taxonomy=%s AND t.name=%s AND i.language_code='en' ORDER BY tt.term_id LIMIT 1",
                $type, $taxonomy, $item['labels']['en']
            ) );
            $trid = $base ? apply_filters( 'wpml_element_trid', null, (int) $base, $type ) : null;
            $terms = $trid ? (array) apply_filters( 'wpml_get_element_translations', null, $trid, $type ) : array();
            $output = array();
            foreach ( array( 'en', 'pt', 'es' ) as $lang ) {
                $ttid = isset( $terms[$lang] ) ? (int) $terms[$lang]->element_id : 0;
                if ( ! $ttid ) {
                    $slug = sanitize_title( $item['labels'][$lang] ) . '-rf-' . substr( md5( $taxonomy . $item['labels']['en'] ), 0, 8 ) . '-' . $lang;
                    // Детерминированный slug восстанавливает запись после оборванного запроса.
                    $term = get_term_by( 'slug', $slug, $taxonomy );
                    $created = $term ? array( 'term_id' => $term->term_id, 'term_taxonomy_id' => $term->term_taxonomy_id ) : wp_insert_term( $item['labels'][$lang], $taxonomy, array( 'slug' => $slug ) );
                    if ( is_wp_error( $created ) ) { return $created; }
                    $ttid = (int) $created['term_taxonomy_id'];
                    do_action( 'wpml_set_element_language_details', array(
                        'element_id' => $ttid, 'element_type' => $type, 'trid' => $trid ?: false,
                        'language_code' => $lang, 'source_language_code' => $lang === 'en' ? null : 'en', 'check_duplicates' => true,
                    ) );
                    if ( ! $trid ) { $trid = apply_filters( 'wpml_element_trid', null, $ttid, $type ); }
                }
                $term_id = (int) $wpdb->get_var( $wpdb->prepare( "SELECT term_id FROM {$wpdb->term_taxonomy} WHERE term_taxonomy_id=%d", $ttid ) );
                $term = get_term( $term_id, $taxonomy );
                if ( ! $term || is_wp_error( $term ) || (int) apply_filters( 'wpml_element_trid', null, $ttid, $type ) !== (int) $trid ) {
                    return new WP_Error( 'rf_term_link_failed', 'WPML не подтвердил связь значений', array( 'status' => 500 ) );
                }
                $output[$lang] = array( 'id' => $term_id, 'name' => $term->name, 'slug' => $term->slug );
            }
            $result[] = $output;
        } finally {
            $wpdb->get_var( $wpdb->prepare( 'SELECT RELEASE_LOCK(%s)', $lock ) );
        }
    }
    return rest_ensure_response( array( 'items' => $result ) );
}

add_action( 'rest_api_init', function () {
    register_rest_route( 'custom-api/v1', '/apply-import-options/', array(
        'methods' => 'POST',
        'permission_callback' => function () { return current_user_can( 'manage_woocommerce' ); },
        'callback' => 'rf_import_apply_options',
    ) );
} );

function rf_import_apply_options( $request ) {
    return rf_import_with_exact_terms( 'rf_import_apply_options_exact', $request );
}

function rf_import_apply_options_exact( $request ) {
    global $wpdb;
    $items = $request->get_param( 'items' );
    if ( ! is_array( $items ) || ! $items || count( $items ) > 3 ) {
        return new WP_Error( 'rf_invalid_options', 'Требуется от 1 до 3 карточек', array( 'status' => 400 ) );
    }
    $group = null;
    foreach ( $items as $item ) {
        $id = (int) ( $item['product_id'] ?? 0 );
        $lang = $item['language'] ?? '';
        $details = apply_filters( 'wpml_post_language_details', null, $id );
        $trid = apply_filters( 'wpml_element_trid', null, $id, 'post_product' );
        if ( 'product' !== get_post_type( $id ) || ! current_user_can( 'edit_post', $id ) || ! $trid || ! in_array( $lang, array( 'pt', 'es', 'en' ), true ) || ! is_array( $details ) || $details['language_code'] !== $lang || ( $group !== null && (int) $group !== (int) $trid ) ) {
            return new WP_Error( 'rf_invalid_option_product', 'Карточка не соответствует языку/группе', array( 'status' => 409 ) );
        }
        $group = $trid;
        if ( empty( $item['attributes'] ) || ! is_array( $item['attributes'] ) || count( $item['attributes'] ) > 30 || ! is_array( $item['variations'] ?? array() ) || count( $item['variations'] ?? array() ) > 500 ) {
            return new WP_Error( 'rf_invalid_option_shape', 'Неверный список атрибутов/вариантов', array( 'status' => 400 ) );
        }
        $allowed = array();
        foreach ( $item['attributes'] as $attr ) {
            $aid = (int) ( $attr['id'] ?? 0 );
            $taxonomy = wc_attribute_taxonomy_name_by_id( $aid );
            if ( ! $taxonomy || ! taxonomy_exists( $taxonomy ) || empty( $attr['term_ids'] ) || ! is_array( $attr['term_ids'] ) ) {
                return new WP_Error( 'rf_invalid_option_attribute', 'Неизвестный атрибут', array( 'status' => 400 ) );
            }
            foreach ( $attr['term_ids'] as $term_id ) {
                $term = get_term( (int) $term_id, $taxonomy );
                $actual_lang = $term && ! is_wp_error( $term ) ? $wpdb->get_var( $wpdb->prepare( "SELECT language_code FROM {$wpdb->prefix}icl_translations WHERE element_type=%s AND element_id=%d", 'tax_' . $taxonomy, $term->term_taxonomy_id ) ) : '';
                if ( $actual_lang !== $lang ) {
                    return new WP_Error( 'rf_invalid_option_language', 'Значение относится к другому языку', array( 'status' => 409 ) );
                }
                $allowed[$aid][(int) $term_id] = true;
            }
        }
        foreach ( $item['variations'] ?? array() as $variation ) {
            $vid = (int) ( $variation['id'] ?? 0 );
            if ( 'product_variation' !== get_post_type( $vid ) || (int) wp_get_post_parent_id( $vid ) !== $id || empty( $variation['attributes'] ) || ! is_array( $variation['attributes'] ) ) {
                return new WP_Error( 'rf_invalid_option_variation', 'Вариант принадлежит другому мероприятию', array( 'status' => 409 ) );
            }
            foreach ( $variation['attributes'] as $attr ) {
                if ( empty( $allowed[(int) $attr['id']][(int) $attr['term_id']] ) ) {
                    return new WP_Error( 'rf_invalid_variation_option', 'Значение не назначено карточке', array( 'status' => 409 ) );
                }
            }
        }
    }
    $previous = apply_filters( 'wpml_current_language', null );
    try {
        if ( ! $request->get_param( 'verify_only' ) ) {
            foreach ( $items as $item ) {
                do_action( 'wpml_switch_language', $item['language'] );
                $attributes = array();
                foreach ( $item['attributes'] as $attr ) {
                    $attribute = new WC_Product_Attribute();
                    $attribute->set_id( (int) $attr['id'] );
                    $attribute->set_name( wc_attribute_taxonomy_name_by_id( (int) $attr['id'] ) );
                    $attribute->set_options( array_map( 'intval', $attr['term_ids'] ) );
                    $attribute->set_visible( true );
                    $attribute->set_variation( true );
                    $attributes[] = $attribute;
                }
                $product = wc_get_product( (int) $item['product_id'] );
                $product->set_attributes( $attributes );
                $product->save();
            }
            foreach ( $items as $item ) {
                do_action( 'wpml_switch_language', $item['language'] );
                foreach ( $item['variations'] ?? array() as $variation ) {
                    $attributes = array();
                    foreach ( $variation['attributes'] as $attr ) {
                        $taxonomy = wc_attribute_taxonomy_name_by_id( (int) $attr['id'] );
                        $term = get_term( (int) $attr['term_id'], $taxonomy );
                        $attributes[$taxonomy] = $term->slug;
                    }
                    $product = wc_get_product( (int) $variation['id'] );
                    $product->set_attributes( $attributes );
                    $product->save();
                }
                wc_delete_product_transients( (int) $item['product_id'] );
            }
        }
        foreach ( $items as $item ) {
            foreach ( $item['attributes'] as $attr ) {
                $taxonomy = wc_attribute_taxonomy_name_by_id( (int) $attr['id'] );
                $actual = array_map( 'intval', $wpdb->get_col( $wpdb->prepare( "SELECT tt.term_id FROM {$wpdb->term_relationships} r JOIN {$wpdb->term_taxonomy} tt ON tt.term_taxonomy_id=r.term_taxonomy_id WHERE r.object_id=%d AND tt.taxonomy=%s", (int) $item['product_id'], $taxonomy ) ) );
                $expected = array_map( 'intval', $attr['term_ids'] );
                sort( $actual ); sort( $expected );
                if ( $actual !== $expected ) {
                    return new WP_Error( 'rf_parent_option_mismatch', 'Карточка сохранила другие ID значений', array( 'status' => 409 ) );
                }
            }
            foreach ( $item['variations'] ?? array() as $variation ) {
                foreach ( $variation['attributes'] as $attr ) {
                    $taxonomy = wc_attribute_taxonomy_name_by_id( (int) $attr['id'] );
                    $term = get_term( (int) $attr['term_id'], $taxonomy );
                    $stored = $wpdb->get_var( $wpdb->prepare( "SELECT meta_value FROM {$wpdb->postmeta} WHERE post_id=%d AND meta_key=%s", (int) $variation['id'], 'attribute_' . $taxonomy ) );
                    if ( $stored !== $term->slug ) {
                        return new WP_Error( 'rf_variation_option_mismatch', 'Вариант сохранил другое языковое значение', array( 'status' => 409 ) );
                    }
                }
            }
        }
        return rest_ensure_response( array( 'verified' => true ) );
    } finally {
        do_action( 'wpml_switch_language', $previous );
    }
}

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
