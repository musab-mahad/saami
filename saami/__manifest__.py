# -*- coding: utf-8 -*-
{
    'name': 'Saami',
    'version': '18.0.1.0.0',
    'category': 'Cooperative',
    'summary': 'Cooperative membership and contribution management system',
    'description': """
Saami Cooperative Management
============================
Cooperative system managing member applications, member lifecycle,
and capital contributions.
    """,
    'author': 'Unknown',
    'website': '',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'account',
        'product',
        'payment',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/saami_product_data.xml',
        'data/saami_cron.xml',
        'wizards/saami_create_user_wizard_views.xml',
        'views/res_config_settings_views.xml',
        'views/saami_dashboard_views.xml',
        'views/saami_product_views.xml',
        'views/saami_contribution_transaction_views.xml',
        'views/saami_contribution_tracker_views.xml',
        'views/saami_member_application_views.xml',
        'views/saami_member_views.xml',
        'views/saami_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'saami/static/src/xml/saami_dashboard.xml',
            'saami/static/src/js/saami_dashboard.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
