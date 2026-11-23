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
            _logger.info("WaafiPay USSD push approved immediately for tx=%s (tx_id=%s, code=%s)", self.reference, tx_id, response_code)
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
            _logger.info("WaafiPay USSD push pending PIN for tx=%s (tx_id=%s, code=%s)", self.reference, tx_id, response_code)
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
            _logger.warning("WaafiPay USSD push failed for tx=%s (code=%s, msg=%s)", self.reference, response_code, err_msg)
            self._set_error(err_msg)
            return {
                'success': False,
                'message': err_msg,
            }

    def _get_tx_from_notification_data(self, provider_code, notification_data):
        """ Find the transaction based on the notification data from WaafiPay. """
        tx = super()._get_tx_from_notification_data(provider_code, notification_data)
        if provider_code != 'waafipay' or len(tx) == 1:
            return tx

        payment_info = notification_data.get('payment', {}) if isinstance(notification_data.get('payment'), dict) else {}
        params_info = notification_data.get('params', {}) if isinstance(notification_data.get('params'), dict) else {}

        reference = (
            payment_info.get('reference_id')
            or payment_info.get('referenceId')
            or params_info.get('referenceId')
            or params_info.get('reference_id')
            or notification_data.get('referenceId')
            or notification_data.get('reference_id')
        )
        if not reference:
            raise ValidationError("WaafiPay: " + _("Received notification with missing reference."))

        tx = self.search([('reference', '=', str(reference).strip()), ('provider_code', '=', 'waafipay')])
        if not tx:
            raise ValidationError(
                "WaafiPay: " + _("No transaction found matching reference %s.", reference)
            )
        return tx

    def _process_notification_data(self, notification_data):
        """ Process the transaction state based on WaafiPay notification data. """
        super()._process_notification_data(notification_data)
        if self.provider_code != 'waafipay':
            return

        payment_info = notification_data.get('payment', {}) if isinstance(notification_data.get('payment'), dict) else {}
        params_info = notification_data.get('params', {}) if isinstance(notification_data.get('params'), dict) else {}

        tx_id = (
            payment_info.get('transaction_id')
            or payment_info.get('transactionId')
            or params_info.get('transactionId')
            or params_info.get('transaction_id')
            or notification_data.get('transactionId')
            or notification_data.get('transaction_id')
        )
        if tx_id:
            self.write({'waafipay_tx_id': str(tx_id)})

        status_val = (
            payment_info.get('status')
            or params_info.get('state')
            or notification_data.get('status')
            or notification_data.get('state')
            or ''
        ).upper()

        response_code = str(
            notification_data.get('responseCode')
            or params_info.get('responseCode')
            or ''
        )

        _logger.info(
            "WaafiPay _process_notification_data tx=%s: status=%s, responseCode=%s, waafipay_tx_id=%s",
            self.reference, status_val, response_code, tx_id,
        )

        if status_val in ('APPROVED', 'SUCCESS') or response_code in ('2001', '0'):
            self._set_done()
        elif status_val in ('PENDING', 'PROCESSING') or response_code in ('1001',):
            self._set_pending()
        else:
            err_msg = (
                notification_data.get('responseMsg')
                or params_info.get('responseMsg')
                or payment_info.get('message')
                or (f"Payment {status_val}" if status_val else _("Transaction failed"))
            )
            _logger.warning("WaafiPay _process_notification_data setting error for tx=%s: %s", self.reference, err_msg)
            self._set_error(err_msg)
