# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'Payment Provider: WaafiPay',
    'version': '18.0.1.0.0',
    'category': 'Accounting/Payment Providers',
    'sequence': 350,
    'summary': "A Somali payment provider for EVC Plus, ZAAD, and SAHAL.",
    'description': " ",  # TODO: Add description
    'depends': ['payment'],
    'data': [
        'data/payment_method_data.xml',
        'data/payment_provider_data.xml',
        'views/payment_provider_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'license': 'LGPL-3',
}
