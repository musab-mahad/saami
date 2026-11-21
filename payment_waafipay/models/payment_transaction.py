# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import uuid
from datetime import datetime
from werkzeug import urls

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    waafipay_tx_id = fields.Char(string="WaafiPay Transaction ID", readonly=True)

    def _waafipay_create_ussd_push(self, phone_number, description=None):
        """
        Initiate an API_PURCHASE USSD push to a customer's mobile wallet
        (EVCPlus, ZAAD, SAHAL) through WaafiPay.
        """
        self.ensure_one()
        provider = self.provider_id
        if provider.code != 'waafipay':
            raise UserError(_("Provider is not WaafiPay."))

        clean_phone = phone_number.replace('+', '').replace(' ', '').strip()

        payload = {
            "schemaVersion": "1.0",
            "requestId": str(uuid.uuid4()),
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "channelName": "WEB",
            "serviceName": "API_PURCHASE",
            "serviceParams": {
                "merchantUid": provider.waafipay_merchant_uid,
                "apiUserId": provider.waafipay_api_user_id,
                "apiKey": provider.waafipay_api_key,
                "paymentMethod": "MWALLET_ACCOUNT",
                "payerInfo": {
                    "accountNo": clean_phone,
                },
                "transactionInfo": {
                    "referenceId": self.reference,
                    "invoiceId": self.reference,
                    "amount": str(float(self.amount)),
                    "currency": self.currency_id.name or "USD",
                    "description": description or f"Payment {self.reference}",
                }
            }
        }

        response = provider._waafipay_make_request(payload)
        response_code = str(response.get('responseCode', ''))
        params = response.get('params', {}) or {}
        tx_id = params.get('transactionId') or response.get('transactionId')

        if response_code in ('2001', '0'):  # Success in WaafiPay API specs
            self.write({
                'waafipay_tx_id': tx_id,
            })
            self._set_done()
            return {
                'success': True,
                'transaction_id': tx_id,
                'message': response.get('responseMsg', 'Payment confirmed successfully.'),
            }
        elif response_code in ('1001',):  # Asynchronous USSD push sent, awaiting user PIN
            self.write({
                'waafipay_tx_id': tx_id,
            })
            self._set_pending()
            return {
                'success': True,
                'pending': True,
                'transaction_id': tx_id,
                'message': response.get('responseMsg', 'USSD push sent. Awaiting PIN entry on your phone.'),
            }
        else:
            # Explicit failure codes (5206 Insufficient funds, 5310 User rejected, 5301 Invalid PIN, 5001 etc.)
            err_msg = response.get('responseMsg', 'Transaction failed')
            self._set_error(err_msg)
            return {
                'success': False,
                'message': err_msg,
            }
