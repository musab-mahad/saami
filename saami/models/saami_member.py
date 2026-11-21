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
    user_id = fields.Many2one('res.users', string='User Account', compute='_compute_user_id', store=True)

    first_name = fields.Char(string='First Name', required=True, tracking=True)
    middle_name = fields.Char(string='Middle Name', required=True, tracking=True)
    last_name = fields.Char(string='Last Name', required=True, tracking=True)
    full_name = fields.Char(string='Full Name', compute='_compute_full_name', store=True)

    mobile = fields.Char(
        string='Mobile',
        compute='_compute_mobile',
        inverse='_inverse_mobile',
        store=True,
        tracking=True,
    )
    email = fields.Char(
        string='Email',
        compute='_compute_email',
        inverse='_inverse_email',
        store=True,
        tracking=True,
    )

    mother_name = fields.Char(string='Mother Name', required=True)
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

    @api.depends('partner_id.user_ids')
    def _compute_user_id(self):
        for rec in self:
            rec.user_id = rec.partner_id.user_ids[:1] if rec.partner_id and rec.partner_id.user_ids else False

    @api.depends('first_name', 'middle_name', 'last_name')
    def _compute_full_name(self):
        for rec in self:
            names = [rec.first_name, rec.middle_name, rec.last_name]
            rec.full_name = ' '.join(filter(None, names))

    @api.depends('partner_id.phone')
    def _compute_mobile(self):
        for rec in self:
            rec.mobile = rec.partner_id.phone

    def _inverse_mobile(self):
        for rec in self:
            if rec.partner_id and rec.mobile:
                rec.partner_id.phone = rec.mobile

    @api.depends('partner_id.email')
    def _compute_email(self):
        for rec in self:
            rec.email = rec.partner_id.email

    def _inverse_email(self):
        for rec in self:
            if rec.partner_id and rec.email:
                rec.partner_id.email = rec.email

    def _compute_total_contributions(self):
        for rec in self:
            # Placeholder until contribution model/ledger is hooked up
            rec.total_contributions = 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('saami.member') or _('New')
        records = super().create(vals_list)
        # Ensure partner name is in sync if created
        for rec in records:
            if rec.partner_id and rec.full_name:
                rec.partner_id.name = rec.full_name
        return records

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ['first_name', 'middle_name', 'last_name']):
            for rec in self:
                if rec.partner_id and rec.full_name:
                    rec.partner_id.name = rec.full_name
        return res

    def action_create_user(self):
        """Open user creation wizard for the member."""
        self.ensure_one()
        if self.user_id:
            raise ValidationError(_("This member already has a user account."))
        if not self.email:
            raise ValidationError(_("An email address is required to create a user account."))

        return {
            'name': _('Create Portal User'),
            'type': 'ir.actions.act_window',
            'res_model': 'saami.create.user.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_member_id': self.id,
                'default_partner_id': self.partner_id.id,
                'default_name': self.full_name,
                'default_login': self.email,
            }
        }

    def action_suspend(self):
        self.write({'state': 'suspended'})

    def action_activate(self):
        self.write({'state': 'active'})

    def action_terminate(self):
        self.write({'state': 'terminated'})
