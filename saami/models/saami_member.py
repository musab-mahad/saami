# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class SaamiMember(models.Model):
    _name = 'saami.member'
    _description = 'Saami Member'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'

    name = fields.Char(
        string='Member Number',
        readonly=True,
        copy=False,
        default=lambda self: _('New'),
    )
    application_id = fields.Many2one('saami.member.application', string='Application', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Partner', required=True, ondelete='restrict')
    user_id = fields.Many2one('res.users', string='User Account', related='partner_id.user_ids', readonly=True)

    first_name = fields.Char(string='First Name', required=True, tracking=True)
    middle_name = fields.Char(string='Middle Name', required=True, tracking=True)
    last_name = fields.Char(string='Last Name', required=True, tracking=True)
    full_name = fields.Char(string='Full Name', compute='_compute_full_name', store=True)

    mother_name = fields.Char(string='Mother Name', required=True)
    mobile = fields.Char(string='Mobile', required=True, tracking=True)
    email = fields.Char(string='Email', required=True, tracking=True)
    date_of_birth = fields.Date(string='Date of Birth', required=True)
    gender = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
    ], string='Gender', required=True)
    education_level = fields.Char(string='Education Level')

    # Location
    country_id = fields.Many2one('res.country', string='Country', required=True)
    state_id = fields.Many2one('res.country.state', string='Region')
    district = fields.Char(string='District', required=True)
    residence_address = fields.Text(string='Address of Residence')

    # Bank Details
    bank_name = fields.Char(string='Bank Name')
    bank_address = fields.Char(string='Bank Address')
    bank_account_no = fields.Char(string='Bank Account Number')

    # Next of Kin 1
    kin1_name = fields.Char(string='Next of Kin 1 Name')
    kin1_address = fields.Char(string='Next of Kin 1 Address')
    kin1_mobile = fields.Char(string='Next of Kin 1 Mobile')

    # Next of Kin 2
    kin2_name = fields.Char(string='Next of Kin 2 Name')
    kin2_address = fields.Char(string='Next of Kin 2 Address')
    kin2_mobile = fields.Char(string='Next of Kin 2 Mobile')

    # KYC Attachments
    photo = fields.Binary(string='Photo', attachment=True)
    identity_file = fields.Binary(string='Identity Document', attachment=True)

    state = fields.Selection([
        ('active', 'Active'),
        ('suspended', 'Suspended'),
        ('terminated', 'Terminated'),
    ], string='Status', default='active', tracking=True)

    total_contributions = fields.Monetary(
        string='Total Contributions',
        compute='_compute_total_contributions',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )

    @api.depends('first_name', 'middle_name', 'last_name')
    def _compute_full_name(self):
        for rec in self:
            names = [rec.first_name, rec.middle_name, rec.last_name]
            rec.full_name = ' '.join(filter(None, names))

    def _compute_total_contributions(self):
        for rec in self:
            # Placeholder until contribution model/ledger is hooked up
            rec.total_contributions = 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('saami.member') or _('New')
        return super().create(vals_list)

    def action_suspend(self):
        self.write({'state': 'suspended'})

    def action_activate(self):
        self.write({'state': 'active'})

    def action_terminate(self):
        self.write({'state': 'terminated'})
