# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import pprint

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class WaafiPayController(http.Controller):
    _webhook_url = '/payment/waafipay/webhook'

    @http.route(_webhook_url, type='json', auth='public', methods=['POST'], csrf=False)
    def waafipay_webhook(self):
        """ Process the notification data sent by WaafiPay. """
        data = request.get_json_data()
        _logger.info("Notification received from WaafiPay:\n%s", pprint.pformat(data))
        return "OK"
