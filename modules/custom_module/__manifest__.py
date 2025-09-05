# __manifest__.py
{
    'name': 'Custom Module',
    'version': '1.0',
    'installable': True,
    'category': 'Menupro',
    'application': True,
    'depends': ['base', 'web','pos_self_order', 'point_of_sale', 'base_import', 'pos_restaurant','bus', 'pos_hr','hr', 'pos_discount','mrp'],
    'data': [
        #'security/ir.model.access.csv',
         'views/login_layout.xml',
        # Category module
        'views/categories/list_pos_category.xml',
        'views/categories/upsert_pos_category.xml',
        # Menus module
        'views/menus/list_menu.xml',
        'views/point_of_sale_dashboard_inherit.xml',
        'views/menus/tree_products.xml',
        #Table Tags
        'views/restaurant_floor.xml',
        'views/table_tags.xml',
        #Employee
        'views/hr_employee_views_inherit.xml',
        #Stock
        'views/stock/product_template_stock.xml',
        'views/stock/stock_picking_views_inherit.xml',
        'views/stock/mrp_bom_views_inherit.xml',
        'views/view_restaurant_discount_config.xml',
    ],
    'assets': {
            'web.assets_backend': [
                'custom_module/static/src/xml/custom_button.xml',
                'custom_module/static/src/js/custom_button.js',
                'custom_module/static/src/js/synchronize_dialog.js',
                'custom_module/static/src/js/synchronize_by_range.js',
                'custom_module/static/src/xml/synchronize_by_range.xml',
                'custom_module/static/src/scss/styles.scss',
                'custom_module/static/src/scss/custom_pwa.scss',
            ],
            'web.assets_frontend' : [
                'custom_module/static/src/scss/login.scss',
                'custom_module/static/src/img/favicon.ico',

            ],
            'point_of_sale._assets_pos': [
                'custom_module/static/src/js/block_navigatio_bar.js',
                'custom_module/static/src/scss/pos.scss',
                'custom_module/static/src/scss/receipt.scss',
                'custom_module/static/src/css/pos_receipt.css',
                'custom_module/static/src/scss/login_screen.scss',
                'custom_module/static/src/xml/saver_screen_inherit.xml',
                'custom_module/static/src/xml/cashier_name_inherit.xml',
                'custom_module/static/src/xml/order_change_receipt_template_inherit.xml',
                'custom_module/static/src/js/pos_navbar_inherit.js',
                'custom_module/static/src/xml/pos_navbar_template_inherit.xml',
                'custom_module/static/src/js/pos_store_inherit.js',
                'custom_module/static/src/js/pos_order_inherit.js',
                'custom_module/static/src/js/floor_screen_inherit.js',
                'custom_module/static/src/xml/receipt_header.xml',
                'custom_module/static/src/js/action_widget_inherit.js',
                'custom_module/static/src/js/hw_printer_inherited.js',
                'custom_module/static/src/xml/pos_discount_control_buttons_inherit.xml',
                'custom_module/static/src/xml/point_of_sale_control_buttons_inherit.xml',
                'custom_module/static/src/js/product_screen_inherit.js',
                'custom_module/static/src/js/closing_popup_inherit.js',
                'custom_module/static/src/js/error_handlers_inherit.js',
                'custom_module/static/src/js/order_tabs_inherit.js',
                'custom_module/static/src/js/numpad_inherit.js',
                'custom_module/static/src/js/payment_screen_inherit.js',
                'custom_module/static/src/xml/payment_screen_inherit.xml'
            ],
    },
    'images': [
        'static/img/logo.png'
    ],
}


