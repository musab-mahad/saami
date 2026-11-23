# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import pprint

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class WaafiPayController(http.Controller):
    _webhook_url = '/payment/waafipay/webhook'

    @http.route(_webhook_url, type='http', auth='public', methods=['POST'], csrf=False)
    def waafipay_webhook(self):
        """ Process the notification data sent by WaafiPay. """
        remote_addr = request.httprequest.remote_addr
        raw_body = request.httprequest.get_data(as_text=True)
        _logger.info("WaafiPay webhook hit from %s | raw_body=%s", remote_addr, raw_body)

        data = request.get_json_data() or request.params
        _logger.info("WaafiPay webhook parsed data:\n%s", pprint.pformat(data))
        if not data:
            _logger.warning("WaafiPay webhook rejected: empty payload from %s", remote_addr)
            return request.make_json_response({'status': 'error', 'message': 'No data received'}, status=400)

        # Handle WaafiPay webhook registration / test ping
        if data.get('event') == 'webhook.test':
            _logger.info("WaafiPay: Received and handled webhook.test validation ping.")
            return request.make_json_response({'status': 'OK', 'message': 'WaafiPay webhook validation ping received'}, status=200)

        try:
            tx_sudo = request.env['payment.transaction'].sudo()._get_tx_from_notification_data('waafipay', data)
            _logger.info("WaafiPay webhook matched tx=%s (current state=%s)", tx_sudo.reference, tx_sudo.state)
            tx_sudo._handle_notification_data('waafipay', data)
            _logger.info("WaafiPay webhook finished processing tx=%s (new state=%s)", tx_sudo.reference, tx_sudo.state)
        except Exception as e:
            _logger.error("WaafiPay: Error processing webhook notification: %s", e, exc_info=True)
            return request.make_json_response({'status': 'error', 'message': str(e)}, status=400)

        return request.make_json_response({'status': 'success', 'message': 'Notification processed'}, status=200)
