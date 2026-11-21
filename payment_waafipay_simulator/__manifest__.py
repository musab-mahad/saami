# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'WaafiPay Payment Simulator',
    'version': '18.0.1.0.0',
    'category': 'Accounting/Payment Providers',
    'sequence': 360,
    'summary': 'Simulated sandbox environment for WaafiPay mobile wallet USSD push requests',
    'description': """
WaafiPay Payment Simulator
==========================
Companion testing module for payment_waafipay.
Provides a virtual mobile wallet sandbox (EVCPlus, ZAAD, SAHAL) with customizable
phone numbers, balances, PINs, and simulated transaction responses without needing
physical Somali SIM cards or external sandbox credentials.
    """,
    'author': 'Unknown',
    'depends': ['payment_waafipay'],
    'data': [
        'security/ir.model.access.csv',
        'data/waafipay_test_wallet_data.xml',
        'views/waafipay_test_wallet_views.xml',
        'views/payment_provider_views.xml',
        'views/waafipay_simulator_menus.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
