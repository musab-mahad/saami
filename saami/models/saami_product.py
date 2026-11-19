# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class SaamiProduct(models.Model):
    _name = 'saami.product'
    _description = 'Saami Product Configuration'
    _order = 'purpose, id'

    name = fields.Char(string='Name', compute='_compute_name', store=True)
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=True,
        domain="[('sale_ok', '=', True)]",
        help="Select the product to use on generated invoices.",
    )
    purpose = fields.Selection([
        ('registration', 'Registration Fee'),
        ('contribution', 'Monthly Contribution'),
    ], string='Purpose', required=True)

    amount = fields.Monetary(string='Amount', required=True, currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    description = fields.Char(
        string='Invoice Description',
        help="Custom description to appear on invoice line. Defaults to product name if blank.",
    )
    is_active = fields.Boolean(string='Active', default=True)

    _sql_constraints = [
        ('uniq_active_purpose', 'unique(purpose, is_active)',
         'Only one active Saami Product configuration is allowed per purpose!')
    ]

    @api.depends('product_id', 'purpose')
    def _compute_name(self):
        for rec in self:
            purpose_label = dict(self._fields['purpose'].selection).get(rec.purpose, '')
            rec.name = f"{purpose_label} - {rec.product_id.display_name or rec.product_id.name}" if rec.product_id else purpose_label

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            if not self.amount:
                self.amount = self.product_id.lst_price
            if not self.description:
                self.description = self.product_id.name
