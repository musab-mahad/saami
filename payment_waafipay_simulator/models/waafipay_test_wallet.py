# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class WaafipayTestWallet(models.Model):
    _name = 'waafipay.test.wallet'
    _description = 'WaafiPay Simulated Mobile Wallet'
    _order = 'phone asc'

    phone = fields.Char(
        string="Phone Number",
        required=True,
        index=True,
        help="Full international number without +, e.g., 252611111111",
    )
    holder_name = fields.Char(
        string="Account Holder",
        required=True,
        default="Test Customer",
    )
    provider_type = fields.Selection(
        selection=[
            ('evcplus', 'Hormuud EVCPlus (25261...)'),
            ('zaad', 'Telesom ZAAD (25263...)'),
            ('sahal', 'Golis SAHAL (25290...)'),
            ('waafi', 'WAAFI Global'),
        ],
        string="Wallet Provider",
        default='evcplus',
        required=True,
    )
    pin = fields.Char(
        string="Wallet PIN",
        default="1212",
        required=True,
        help="Simulated wallet secret PIN",
    )
    balance = fields.Float(
        string="Available Balance",
        default=500.0,
        digits=(16, 2),
        required=True,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string="Currency",
        default=lambda self: self.env.ref('base.USD', raise_if_not_found=False) or self.env.company.currency_id,
        required=True,
    )
    state = fields.Selection(
        selection=[
            ('active', 'Active'),
            ('blocked', 'Blocked / Frozen'),
        ],
        string="Account Status",
        default='active',
        required=True,
    )
    behavior = fields.Selection(
        selection=[
            ('approve', 'Auto-Approve (Normal Successful Payment)'),
            ('reject', 'Auto-Reject (Customer Cancels USSD Prompt)'),
            ('timeout', 'Auto-Timeout (Customer Ignores Prompt)'),
            ('insufficient', 'Force Insufficient Balance Failure'),
            ('invalid_pin', 'Force Invalid PIN Failure'),
        ],
        string="Simulation Behavior",
        default='approve',
        required=True,
        help="How the simulated wallet responds when an API_PURCHASE USSD push is initiated.",
    )
    request_ids = fields.One2many(
        comodel_name='waafipay.simulator.request',
        inverse_name='wallet_id',
        string="Simulated Requests",
    )
    request_count = fields.Integer(
        string="Total Requests",
        compute='_compute_request_count',
    )

    _sql_constraints = [
        ('phone_unique', 'unique(phone)', 'A test wallet with this phone number already exists!'),
    ]

    @api.depends('request_ids')
    def _compute_request_count(self):
        for rec in self:
            rec.request_count = len(rec.request_ids)

    def name_get(self):
        result = []
        for rec in self:
            name = f"{rec.phone} ({rec.holder_name}) - Balance: ${rec.balance:.2f}"
            result.append((rec.id, name))
        return result

    @api.onchange('phone')
    def _onchange_phone(self):
        if not self.phone:
            return
        clean = self.phone.replace('+', '').replace(' ', '').strip()
        self.phone = clean
        if clean.startswith('25261'):
            self.provider_type = 'evcplus'
        elif clean.startswith('25263'):
            self.provider_type = 'zaad'
        elif clean.startswith('25290'):
            self.provider_type = 'sahal'
        else:
            self.provider_type = 'waafi'

    def action_topup_balance(self):
        """ Quick helper to add $100 to the test wallet balance. """
        for rec in self:
            rec.balance += 100.0
