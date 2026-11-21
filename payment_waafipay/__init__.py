# Part of Odoo. See LICENSE file for full copyright and licensing details.

from . import controllers
from . import models

from odoo.addons.payment import setup_provider, reset_payment_provider


def post_init_hook(env):
    setup_provider(env, 'waafipay')
    method = env.ref('payment_waafipay.payment_method_waafipay', raise_if_not_found=False)
    if method:
        method.active = True
        provider = env['payment.provider'].search([('code', '=', 'waafipay')])
        if provider and method not in provider.payment_method_ids:
            provider.payment_method_ids = [(4, method.id)]


def uninstall_hook(env):
    reset_payment_provider(env, 'waafipay')
