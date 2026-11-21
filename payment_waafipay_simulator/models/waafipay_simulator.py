# Part of Odoo. See LICENSE file for full copyright and licensing details.

import json
import logging
import uuid
from datetime import datetime

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class WaafipaySimulatorRequest(models.Model):
    _name = 'waafipay.simulator.request'
    _description = 'WaafiPay Simulated Request Log'
    _order = 'create_date desc'

    name = fields.Char(string="Request ID", required=True, index=True)
    wallet_id = fields.Many2one(
        comodel_name='waafipay.test.wallet',
        string="Test Wallet",
        ondelete='set null',
    )
    phone = fields.Char(string="Phone Number", required=True)
    amount = fields.Float(string="Amount", digits=(16, 2))
    currency = fields.Char(string="Currency", default="USD")
    reference_id = fields.Char(string="Reference ID")
    invoice_id = fields.Char(string="Invoice ID")
    description = fields.Char(string="Description")
    service_name = fields.Char(string="Service Name", default="API_PURCHASE")
    status = fields.Selection(
        selection=[
            ('approved', 'Approved (2001)'),
            ('rejected', 'Rejected by User (5310)'),
            ('timeout', 'Timed Out (5309)'),
            ('insufficient', 'Insufficient Funds (5206)'),
            ('invalid_pin', 'Invalid PIN (5301)'),
            ('blocked', 'Account Blocked (5308)'),
        ],
        string="Simulation Outcome",
        required=True,
    )
    response_code = fields.Char(string="Response Code")
    transaction_id = fields.Char(string="Simulated Transaction ID")
    order_id = fields.Char(string="Simulated Order ID")
    raw_request = fields.Text(string="Raw Request JSON")
    raw_response = fields.Text(string="Raw Response JSON")


class WaafipaySimulator(models.AbstractModel):
    _name = 'waafipay.simulator'
    _description = 'WaafiPay Simulation Engine'

    @api.model
    def process_simulated_request(self, provider, payload):
        """
        Intercepts an API_PURCHASE request and generates an exact authentic
        WaafiPay JSON response according to the test wallet settings.
        """
        service_params = payload.get('serviceParams', {})
        payer_info = service_params.get('payerInfo', {})
        txn_info = service_params.get('transactionInfo', {})
        
        raw_phone = payer_info.get('accountNo', '')
        phone = str(raw_phone).replace('+', '').replace(' ', '').strip()
        amount_val = float(txn_info.get('amount', 0.0))
        currency_val = txn_info.get('currency', 'USD')
        ref_id = txn_info.get('referenceId', '')
        inv_id = txn_info.get('invoiceId', '')
        desc = txn_info.get('description', '')
        req_id = payload.get('requestId') or str(uuid.uuid4())
        timestamp_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

        _logger.info("Sending request to WaafiPay (SIMULATOR):\n%s", json.dumps(payload, indent=2))

        # 1. Lookup or auto-create virtual wallet
        wallet = self.env['waafipay.test.wallet'].search([('phone', '=', phone)], limit=1)
        if not wallet:
            _logger.info("[WAAFIPAY SIMULATOR] Phone %s not found in wallets, auto-creating with $500 balance", phone)
            wallet = self.env['waafipay.test.wallet'].create({
                'phone': phone,
                'holder_name': f"Test User {phone[-4:]}",
                'balance': 500.0,
                'pin': '1212',
                'behavior': 'approve',
                'state': 'active',
            })

        # 2. Determine outcome based on wallet state & behavior
        sim_tx_id = f"SIM-{uuid.uuid4().hex[:8].upper()}"
        sim_order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
        sim_issuer_id = f"ISS-{uuid.uuid4().hex[:10].upper()}"

        if wallet.state == 'blocked':
            outcome = 'blocked'
            response_code = "5308"
            error_code = "5308"
            response_msg = "RCS_HPP_SUBSCRIPTION_ISNOT_ENABLED: Customer mobile wallet account is blocked."
            params = {}

        elif wallet.behavior == 'reject':
            outcome = 'rejected'
            response_code = "5310"
            error_code = "5310"
            response_msg = "RCS_USER_REJECTED"
            params = {
                'orderId': sim_order_id,
                'description': 'Customer rejected payment prompt on mobile wallet.',
            }

        elif wallet.behavior == 'timeout':
            outcome = 'timeout'
            response_code = "5309"
            error_code = "5309"
            response_msg = "RCS_HPP_USERACTION_TIMEOUT: Customer did not complete the prompt within the timeout period."
            params = {
                'orderId': sim_order_id,
            }

        elif wallet.behavior == 'invalid_pin':
            outcome = 'invalid_pin'
            response_code = "5301"
            error_code = "5301"
            response_msg = "RCS_INVALID_PIN: Invalid customer PIN entered."
            params = {}

        elif wallet.behavior == 'insufficient' or wallet.balance < amount_val:
            outcome = 'insufficient'
            response_code = "5206"
            error_code = "5206"
            response_msg = f"RCS_INSUFFICIENT_FUNDS: Available balance (${wallet.balance:.2f}) is lower than requested amount (${amount_val:.2f})."
            params = {}

        else:
            # Normal Approval
            outcome = 'approved'
            wallet.balance -= amount_val
            response_code = "2001"
            error_code = "0"
            response_msg = "RCS_SUCCESS"
            params = {
                'state': 'APPROVED',
                'referenceId': ref_id,
                'transactionId': sim_tx_id,
                'orderId': sim_order_id,
                'issuerTransactionId': sim_issuer_id,
                'txAmount': f"{amount_val:.2f}",
                'accountNo': phone[:6] + "****" + phone[-4:] if len(phone) >= 10 else phone,
                'accountType': 'MWALLET_ACCOUNT',
            }

        response_data = {
            "schemaVersion": "1.0",
            "timestamp": timestamp_str,
            "responseId": req_id,
            "responseCode": response_code,
            "errorCode": error_code,
            "responseMsg": response_msg,
            "params": params,
        }

        # 3. Log request record in Odoo
        self.env['waafipay.simulator.request'].create({
            'name': req_id,
            'wallet_id': wallet.id,
            'phone': phone,
            'amount': amount_val,
            'currency': currency_val,
            'reference_id': ref_id,
            'invoice_id': inv_id,
            'description': desc,
            'status': outcome,
            'response_code': response_code,
            'transaction_id': sim_tx_id if outcome == 'approved' else False,
            'order_id': sim_order_id,
            'raw_request': json.dumps(payload, indent=2),
            'raw_response': json.dumps(response_data, indent=2),
        })

        _logger.info("WaafiPay Response (SIMULATOR):\n%s", json.dumps(response_data, indent=2))
        return response_data
