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
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/saami_product_data.xml',
        'wizards/saami_create_user_wizard_views.xml',
        'views/saami_product_views.xml',
        'views/saami_member_application_views.xml',
        'views/saami_member_views.xml',
        'views/saami_menus.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
