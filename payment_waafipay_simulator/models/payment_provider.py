# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
from odoo import models, fields

_logger = logging.getLogger(__name__)


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    waafipay_use_simulator = fields.Boolean(
        string="Use Local Simulator",
        default=True,
        help="When enabled and in Test Mode, requests will be routed to the local WaafiPay Simulator without hitting external servers.",
    )

    def _waafipay_make_request(self, payload):
        """
        Override to intercept requests in test mode when local simulator is enabled.
        """
        self.ensure_one()
        if self.code == 'waafipay' and self.state == 'test' and self.waafipay_use_simulator:
            _logger.info("[WAAFIPAY] State is Test Mode & Local Simulator is ENABLED. Routing request locally.")
            return self.env['waafipay.simulator'].process_simulated_request(self, payload)
        
        return super()._waafipay_make_request(payload)
