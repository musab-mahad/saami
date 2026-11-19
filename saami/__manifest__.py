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
    ],
    'data': [
        'security/ir.model.access.csv',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
