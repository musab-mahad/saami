# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[('waafipay', "WaafiPay")], ondelete={'waafipay': 'set default'}
    )
    waafipay_merchant_uid = fields.Char(
        string="Merchant UID",
        help="The Merchant UID provided by WaafiPay.",
        groups='base.group_system',
    )
    waafipay_api_user_id = fields.Char(
        string="API User ID",
        groups='base.group_system',
    )
    waafipay_api_key = fields.Char(
        string="API Key",
        groups='base.group_system',
    )
    waafipay_webhook_url = fields.Char(
        string="Webhook URL",
        help="The public URL for receiving transaction notifications from WaafiPay.",
    )
    waafipay_test_phone = fields.Char(
        string="Test Phone Number",
        help="Phone number in international format (e.g., 25261XXXXXX).",
    )

    def _get_default_payment_method_codes(self):
        default_codes = super()._get_default_payment_method_codes()
        if self.code == 'waafipay':
            default_codes.add('waafipay')
        return default_codes

    def _waafipay_get_api_url(self):
        """ Return the API URL based on the provider state. """
        if self.state == 'enabled':
            return 'https://api.waafipay.net/asm'
        return 'https://sandbox.waafipay.com/asm'

    def _waafipay_make_request(self, payload):
        """ Make a request to the WaafiPay API. """
        import requests
        import json
        
        url = self._waafipay_get_api_url()
        headers = {'Content-Type': 'application/json'}
        
        # Inject credentials into the serviceParams of the payload
        if 'serviceParams' in payload:
            payload['serviceParams'].update({
                'merchantUid': self.waafipay_merchant_uid,
                'apiUserId': self.waafipay_api_user_id,
                'apiKey': self.waafipay_api_key,
            })

        _logger.info("Sending request to WaafiPay (%s):\n%s", url, json.dumps(payload, indent=2))
        
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            response_data = response.json()
            _logger.info("WaafiPay Response:\n%s", json.dumps(response_data, indent=2))
            return response_data
        except requests.exceptions.RequestException as e:
            _logger.error("WaafiPay Connection Error: %s", str(e))
            from odoo.exceptions import UserError
            raise UserError(f"WaafiPay Connection Error: {str(e)}")

    def button_test_ussd_push(self):
        """ Manually trigger a test USSD push using real API call. """
        self.ensure_one()
        if not self.waafipay_test_phone:
            from odoo.exceptions import UserError
            raise UserError("Please provide a test phone number first!")

        from datetime import datetime
        import uuid

        payload = {
            "schemaVersion": "1.0",
            "requestId": str(uuid.uuid4()),
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "channelName": "WEB",
            "serviceName": "API_PURCHASE",
            "serviceParams": {
                "merchantUid": self.waafipay_merchant_uid,
                "apiUserId": self.waafipay_api_user_id,
                "apiKey": self.waafipay_api_key,
                "paymentMethod": "MWALLET_ACCOUNT",
                "payerInfo": {
                    "accountNo": self.waafipay_test_phone
                },
                "transactionInfo": {
                    "referenceId": f"TEST-{uuid.uuid4().hex[:6].upper()}",
                    "invoiceId": f"INV-{uuid.uuid4().hex[:6].upper()}",
                    "amount": "1.0",
                    "currency": "USD",
                    "description": "Odoo WaafiPay Test Payment"
                }
            }
        }

        response = self._waafipay_make_request(payload)
        
        from odoo import _
        message = f"Response Code: {response.get('responseCode')} - {response.get('responseMsg')}"
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('WaafiPay API Response'),
                'message': message,
                'sticky': True,
            }
        }
