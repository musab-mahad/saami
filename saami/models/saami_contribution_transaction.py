# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class SaamiContributionTransaction(models.Model):
    _name = 'saami.contribution.transaction'
    _description = 'Saami Contribution Transaction'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Transaction Reference',
        readonly=True,
        copy=False,
        default=lambda self: _('New'),
    )
    member_id = fields.Many2one(
        'saami.member',
        string='Member',
        required=False,
        ondelete='cascade',
        index=True,
        tracking=True,
    )
    application_id = fields.Many2one(
        'saami.member.application',
        string='Application',
        ondelete='set null',
        index=True,
        tracking=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
        compute='_compute_partner_id',
        store=True,
        readonly=False,
        index=True,
    )

    @api.depends('member_id.partner_id', 'application_id.partner_id')
    def _compute_partner_id(self):
        for tx in self:
            if tx.member_id and tx.member_id.partner_id:
                tx.partner_id = tx.member_id.partner_id
            elif tx.application_id and tx.application_id.partner_id:
                tx.partner_id = tx.application_id.partner_id
            elif not tx.partner_id:
                tx.partner_id = False
    tracker_id = fields.Many2one(
        'saami.contribution.tracker',
        string='Contributions Tracker',
        ondelete='set null',
        index=True,
        help="The monthly contribution tracker period this payment settles.",
    )
    transaction_type = fields.Selection([
        ('monthly_contribution', 'Monthly Capital Contribution'),
        ('registration_fee', 'Registration Fee'),
        ('additional_capital', 'Additional Capital Contribution'),
    ], string='Transaction Type', default='monthly_contribution', required=True, tracking=True)

    date = fields.Date(
        string='Payment Date',
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )
    amount = fields.Monetary(
        string='Amount Paid',
        currency_field='currency_id',
        required=True,
        tracking=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    payment_method = fields.Char(
        string='Payment Channel',
        help="Payment gateway, e.g. WaafiPay, M-Pesa, Bank Transfer, Cash",
    )
    external_reference = fields.Char(
        string='External Gateway Ref',
        copy=False,
        help="Transaction ID or receipt code from payment provider (e.g. M-Pesa receipt)",
    )
    invoice_id = fields.Many2one(
        'account.move',
        string='Invoice',
        readonly=True,
        copy=False,
    )
    payment_id = fields.Many2one(
        'account.payment',
        string='Accounting Payment',
        readonly=True,
        copy=False,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending Confirmation'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)
    email_sent = fields.Boolean(
        string='Receipt Email Sent',
        default=False,
        copy=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('saami.contribution.transaction') or _('New')
        return super().create(vals_list)

    def _send_contribution_paid_email(self):
        """Send email receipt for capital contribution (async via queue_job)."""
        template = self.env.ref('saami.mail_template_contribution_received', raise_if_not_found=False)
        if not template:
            return
        for rec in self.sudo():
            if rec.email_sent or rec.state != 'paid' or not rec.member_id:
                continue
            template.sudo().send_mail(rec.id, force_send=True)
            rec.email_sent = True

    def action_mark_paid(self):
        """Confirm payment and recompute linked tracker."""
        self.write({'state': 'paid'})
        for rec in self:
            if rec.tracker_id:
                rec.tracker_id._compute_actual_amount()
                rec.tracker_id._compute_state()
            if hasattr(rec, 'with_delay'):
                rec.with_delay()._send_contribution_paid_email()
            else:
                rec._send_contribution_paid_email()

    def action_cancel(self):
        self.write({'state': 'cancelled'})
        for rec in self:
            if rec.tracker_id:
                rec.tracker_id._compute_actual_amount()
                rec.tracker_id._compute_state()
