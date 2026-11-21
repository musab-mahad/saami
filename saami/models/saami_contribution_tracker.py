# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import datetime


class SaamiContributionTracker(models.Model):
    _name = 'saami.contribution.tracker'
    _description = 'Saami Contributions Tracker'
    _order = 'date desc, member_id'
    _rec_name = 'display_name'

    member_id = fields.Many2one(
        'saami.member',
        string='Member',
        required=True,
        ondelete='cascade',
        index=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
        related='member_id.partner_id',
        store=True,
        index=True,
    )
    date = fields.Date(
        string='Period (Month)',
        required=True,
        index=True,
        default=lambda self: fields.Date.today().replace(day=1),
    )
    month_name = fields.Char(
        string='Month',
        compute='_compute_month_name',
        store=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    expected_amount = fields.Monetary(
        string='Expected Capital',
        currency_field='currency_id',
        help="Benchmark monthly capital contribution configured in Saami Products.",
    )
    actual_amount = fields.Monetary(
        string='Actual Paid',
        currency_field='currency_id',
        compute='_compute_actual_amount',
        store=True,
        help="Total capital contributed for this period.",
    )
    state = fields.Selection([
        ('unpaid', 'Unpaid'),
        ('partial', 'Partially Paid'),
        ('paid', 'Fully Paid'),
        ('excess', 'Paid Extra'),
    ], string='Status', compute='_compute_state', store=True)

    invoice_ids = fields.Many2many(
        'account.move',
        string='Invoices / In-Payments',
        help="Invoices or accounting payments linked to this period contribution.",
    )
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True,
    )

    _sql_constraints = [
        ('uniq_member_month', 'unique(member_id, date)',
         'A contribution tracker entry already exists for this member and month!')
    ]

    @api.depends('date', 'member_id.name', 'member_id.full_name')
    def _compute_display_name(self):
        for rec in self:
            month_str = rec.date.strftime('%B %Y') if rec.date else ''
            member_str = rec.member_id.full_name or rec.member_id.name or ''
            rec.display_name = f"{member_str} - {month_str}" if member_str and month_str else (member_str or month_str or _('New'))

    @api.depends('date')
    def _compute_month_name(self):
        for rec in self:
            rec.month_name = rec.date.strftime('%B %Y') if rec.date else ''

    @api.depends('invoice_ids', 'invoice_ids.payment_state', 'invoice_ids.amount_total')
    def _compute_actual_amount(self):
        for rec in self:
            total_paid = 0.0
            for inv in rec.invoice_ids:
                if inv.state == 'posted':
                    # Amount paid on the invoice
                    total_paid += (inv.amount_total - inv.amount_residual)
            rec.actual_amount = total_paid

    @api.depends('actual_amount', 'expected_amount')
    def _compute_state(self):
        for rec in self:
            if rec.actual_amount <= 0.0:
                rec.state = 'unpaid'
            elif 0.0 < rec.actual_amount < rec.expected_amount:
                rec.state = 'partial'
            elif rec.actual_amount == rec.expected_amount:
                rec.state = 'paid'
            else:
                rec.state = 'excess'

    @api.model
    def generate_monthly_trackers(self, target_date=None):
        """
        Cron / Action method: Generates monthly tracker entries for all active members.
        Defaults to the first day of the current month.
        """
        if not target_date:
            target_date = fields.Date.today().replace(day=1)

        # Get expected amount from active monthly contribution product
        prod_config = self.env['saami.product'].search([
            ('purpose', '=', 'contribution'),
            ('is_active', '=', True),
        ], limit=1)
        default_expected = prod_config.amount if prod_config else 0.0

        active_members = self.env['saami.member'].search([('state', '=', 'active')])
        vals_to_create = []

        for member in active_members:
            existing = self.search([
                ('member_id', '=', member.id),
                ('date', '=', target_date),
            ], limit=1)
            if not existing:
                vals_to_create.append({
                    'member_id': member.id,
                    'date': target_date,
                    'expected_amount': default_expected,
                    'currency_id': prod_config.currency_id.id if prod_config else self.env.company.currency_id.id,
                })

        if vals_to_create:
            return self.create(vals_to_create)
        return self.browse()
