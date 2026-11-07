<?php
/**
 * Plugin Name: RaceFinder Import Languages
 * Description: Самостоятельные языковые версии импортируемого мероприятия.
 */
if ( ! defined( 'ABSPATH' ) ) { exit; }

add_action( 'rest_api_init', function () {
    register_rest_route( 'custom-api/v1', '/import-category-catalog/', array(
        'methods' => 'GET', 'permission_callback' => function () { return current_user_can( 'manage_woocommerce' ); },
        'callback' => function () {
            global $wpdb;
            // Обычный WC REST на DEV отфильтровывает часть EN даже с lang=all.
            $rows = $wpdb->get_results( "SELECT t.term_id AS id,t.name,tt.parent,i.language_code AS lang,i.trid FROM {$wpdb->terms} t JOIN {$wpdb->term_taxonomy} tt USING(term_id) JOIN {$wpdb->prefix}icl_translations i ON i.element_id=tt.term_taxonomy_id AND i.element_type='tax_product_cat' WHERE tt.taxonomy='product_cat' ORDER BY t.term_id", ARRAY_A );
            $groups = array();
            foreach ( $rows as $r ) { $groups[$r['trid']][$r['lang']] = (int) $r['id']; }
            foreach ( $rows as &$r ) { $r['id'] = (int) $r['id']; $r['parent'] = (int) $r['parent']; $r['translations'] = $groups[$r['trid']]; }
            unset( $r );
            return rest_ensure_response( $rows );
        },
    ) );
    foreach ( array( 'ensure-import-category-group' => 'rf_import_category_group', 'verify-import-categories' => 'rf_import_verify_categories' ) as $route => $callback ) {
        register_rest_route( 'custom-api/v1', '/' . $route . '/', array(
            'methods' => 'POST', 'permission_callback' => function () { return current_user_can( 'manage_woocommerce' ); },
            'callback' => function ( $request ) use ( $callback ) { return rf_import_with_exact_terms( $callback, $request ); },
        ) );
    }
} );

function rf_import_category_record( $id ) {
    global $wpdb;
    $row = $wpdb->get_row( $wpdb->prepare(
        "SELECT t.term_id AS id,t.name,tt.parent,tt.term_taxonomy_id AS tt,i.language_code AS lang,i.trid,i.source_language_code FROM {$wpdb->terms} t JOIN {$wpdb->term_taxonomy} tt USING(term_id) JOIN {$wpdb->prefix}icl_translations i ON i.element_id=tt.term_taxonomy_id AND i.element_type='tax_product_cat' WHERE tt.taxonomy='product_cat' AND t.term_id=%d", (int) $id
    ), ARRAY_A );
    if ( $row ) { foreach ( array( 'id', 'parent', 'tt', 'trid' ) as $key ) { $row[$key] = (int) $row[$key]; } }
    return $row;
}

function rf_import_category_group( $request ) {
    global $wpdb;
    $roots = $request->get_param( 'roots' ); $names = $request->get_param( 'names' );
    $source = rf_import_category_record( $request->get_param( 'source_id' ) );
    if ( ! is_array( $roots ) || ! is_array( $names ) || ! $source ) { return new WP_Error( 'rf_category_input', 'Не задана группа категорий', array( 'status' => 400 ) ); }
    $root_group = null;
    foreach ( array( 'en', 'pt', 'es' ) as $lang ) {
        $root = rf_import_category_record( $roots[$lang] ?? 0 );
        if ( ! $root || $root['lang'] !== $lang || $root['parent'] !== 0 || ( $root_group && $root_group !== $root['trid'] ) || empty( $names[$lang] ) || ! is_string( $names[$lang] ) ) {
            return new WP_Error( 'rf_category_root', 'Неверный язык или группа родительской категории', array( 'status' => 409 ) );
        }
        $root_group = $root['trid']; $roots[$lang] = $root['id'];
    }
    if ( ! isset( $roots[$source['lang']] ) || $source['parent'] !== $roots[$source['lang']] ) { return new WP_Error( 'rf_category_source', 'Исходная подкатегория находится под другим родителем', array( 'status' => 409 ) ); }
    $lock = 'rf_category_' . $source['trid'];
    if ( '1' !== (string) $wpdb->get_var( $wpdb->prepare( 'SELECT GET_LOCK(%s,10)', $lock ) ) ) { return new WP_Error( 'rf_category_busy', 'Группа занята', array( 'status' => 409 ) ); }
    $previous = apply_filters( 'wpml_current_language', null );
    try {
        $categories = array();
        $ids = $wpdb->get_col( $wpdb->prepare( "SELECT tt.term_id FROM {$wpdb->prefix}icl_translations i JOIN {$wpdb->term_taxonomy} tt ON tt.term_taxonomy_id=i.element_id WHERE i.element_type='tax_product_cat' AND i.trid=%d", $source['trid'] ) );
        foreach ( $ids as $id ) {
            $c = rf_import_category_record( $id );
            if ( isset( $roots[$c['lang']] ) ) {
                if ( $c['parent'] !== $roots[$c['lang']] || isset( $categories[$c['lang']] ) ) { return new WP_Error( 'rf_category_parent', 'Перевод категории находится под неверным родителем', array( 'status' => 409 ) ); }
                $categories[$c['lang']] = $c;
            }
        }
        $new_english = ! isset( $categories['en'] );
        $original_lang = 'en';
        foreach ( $categories as $c ) { if ( empty( $c['source_language_code'] ) ) { $original_lang = $c['lang']; break; } }
        foreach ( array( 'en', 'pt', 'es' ) as $lang ) {
            if ( isset( $categories[$lang] ) ) { continue; }
            do_action( 'wpml_switch_language', $lang );
            $slug = 'rf-category-' . $source['trid'] . '-' . $lang;
            $existing = get_term_by( 'slug', $slug, 'product_cat' );
            $created = $existing ? array( 'term_id' => $existing->term_id, 'term_taxonomy_id' => $existing->term_taxonomy_id ) : wp_insert_term( $names[$lang], 'product_cat', array( 'parent' => $roots[$lang], 'slug' => $slug ) );
            if ( is_wp_error( $created ) ) { return $created; }
            do_action( 'wpml_set_element_language_details', array( 'element_id' => (int) $created['term_taxonomy_id'], 'element_type' => 'tax_product_cat', 'trid' => $source['trid'], 'language_code' => $lang, 'source_language_code' => $lang === 'en' && $new_english ? null : $original_lang, 'check_duplicates' => true ) );
            $categories[$lang] = rf_import_category_record( $created['term_id'] );
        }
        // В старой группе мог быть удалён EN-оригинал: восстанавливаем его без создания новой группы.
        if ( $new_english ) {
            foreach ( $categories as $lang => $c ) {
                do_action( 'wpml_set_element_language_details', array( 'element_id' => $c['tt'], 'element_type' => 'tax_product_cat', 'trid' => $source['trid'], 'language_code' => $lang, 'source_language_code' => $lang === 'en' ? null : 'en', 'check_duplicates' => true ) );
            }
        }
        foreach ( $categories as $lang => $c ) {
            $actual = rf_import_category_record( $c['id'] );
            if ( ! $actual || $actual['lang'] !== $lang || $actual['parent'] !== $roots[$lang] || $actual['trid'] !== $source['trid'] ) { return new WP_Error( 'rf_category_link', 'Не сохранились язык/родитель/группа категории', array( 'status' => 409 ) ); }
            $categories[$lang] = $actual;
        }
        return rest_ensure_response( array( 'trid' => $source['trid'], 'roots' => $roots, 'categories' => $categories ) );
    } finally { do_action( 'wpml_switch_language', $previous ); $wpdb->get_var( $wpdb->prepare( 'SELECT RELEASE_LOCK(%s)', $lock ) ); }
}

function rf_import_verify_categories( $request ) {
    global $wpdb;
    $plan = $request->get_param( 'plan' ); $products = $request->get_param( 'products' );
    if ( ! is_array( $plan ) || ! is_array( $products ) || count( $products ) !== 3 || ! isset( $plan['ids'], $plan['groups'], $plan['roots'] ) ) { return new WP_Error( 'rf_category_plan', 'Нет плана категорий', array( 'status' => 400 ) ); }
    $product_group = null;
    foreach ( array( 'pt', 'es', 'en' ) as $lang ) {
        $id = (int) ( $products[$lang] ?? 0 ); $details = apply_filters( 'wpml_post_language_details', null, $id );
        $trid = apply_filters( 'wpml_element_trid', null, $id, 'post_product' );
        if ( ! $details || $details['language_code'] !== $lang || ! current_user_can( 'edit_post', $id ) || ! $trid || ( $product_group && (int) $trid !== (int) $product_group ) ) { return new WP_Error( 'rf_category_product', 'Карточки не принадлежат одной группе', array( 'status' => 409 ) ); }
        $product_group = $trid; $expected = array_map( 'intval', $plan['ids'][$lang] ?? array() );
        if ( ! $expected ) { return new WP_Error( 'rf_category_empty', 'Категории не заданы', array( 'status' => 409 ) ); }
        foreach ( $expected as $cid ) {
            $c = rf_import_category_record( $cid );
            if ( ! $c || $c['lang'] !== $lang || ( $c['parent'] && ! in_array( $c['parent'], $expected, true ) ) ) { return new WP_Error( 'rf_category_hierarchy', 'Неверный язык или иерархия категории', array( 'status' => 409 ) ); }
        }
        $actual = array_map( 'intval', $wpdb->get_col( $wpdb->prepare( "SELECT tt.term_id FROM {$wpdb->term_relationships} r JOIN {$wpdb->term_taxonomy} tt USING(term_taxonomy_id) WHERE r.object_id=%d AND tt.taxonomy='product_cat'", $id ) ) );
        foreach ( array_diff( $actual, $expected ) as $extra ) {
            $c = rf_import_category_record( $extra );
            // Автоматическая категория истёкшего события добавляется сайтом, а не таблицей.
            $english = $c ? $wpdb->get_var( $wpdb->prepare( "SELECT t.name FROM {$wpdb->prefix}icl_translations i JOIN {$wpdb->term_taxonomy} tt ON tt.term_taxonomy_id=i.element_id JOIN {$wpdb->terms} t USING(term_id) WHERE i.element_type='tax_product_cat' AND i.trid=%d AND i.language_code='en'", $c['trid'] ) ) : '';
            if ( $c && $c['lang'] === $lang && $c['parent'] === 0 && $english === 'Expired' ) { $actual = array_values( array_diff( $actual, array( $extra ) ) ); }
        }
        sort( $actual ); sort( $expected );
        if ( $actual !== $expected ) { return new WP_Error( 'rf_category_assignment', 'В карточке отсутствуют нужные категории или появились лишние', array( 'status' => 409 ) ); }
    }
    foreach ( $plan['roots'] as $roots ) {
        $root_group = null;
        foreach ( array( 'pt', 'es', 'en' ) as $lang ) {
            $root = rf_import_category_record( $roots[$lang] ?? 0 );
            if ( ! $root || $root['lang'] !== $lang || $root['parent'] !== 0 || ( $root_group && $root_group !== $root['trid'] ) || ! in_array( $root['id'], array_map( 'intval', $plan['ids'][$lang] ), true ) ) { return new WP_Error( 'rf_category_root_changed', 'Изменилась группа родительских категорий', array( 'status' => 409 ) ); }
            $root_group = $root['trid'];
        }
    }
    foreach ( $plan['groups'] as $group ) {
        foreach ( array( 'pt', 'es', 'en' ) as $lang ) {
            $c = rf_import_category_record( $group['categories'][$lang]['id'] ?? 0 );
            if ( ! $c || $c['trid'] !== (int) $group['trid'] || $c['lang'] !== $lang || $c['parent'] !== (int) $group['roots'][$lang] ) { return new WP_Error( 'rf_category_group_changed', 'Изменилась группа переводов категории', array( 'status' => 409 ) ); }
        }
    }
    return rest_ensure_response( array( 'verified' => true ) );
}

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
                // WCML может вернуть уже переведённые ID при чтении старой карточки,
                // и CRUD не заметит отличия от сырых связей. Фиксируем отношения явно.
                foreach ( $item['attributes'] as $attr ) {
                    $saved = wp_set_object_terms( (int) $item['product_id'], array_map( 'intval', $attr['term_ids'] ), wc_attribute_taxonomy_name_by_id( (int) $attr['id'] ), false );
                    if ( is_wp_error( $saved ) ) { return $saved; }
                }
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
