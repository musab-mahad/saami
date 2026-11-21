# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError


class SaamiMemberApplication(models.Model):
    _name = 'saami.member.application'
    _description = 'Saami Member Application'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Application Number',
        readonly=True,
        copy=False,
        default=lambda self: _('New'),
    )
    partner_id = fields.Many2one('res.partner', string='Partner', ondelete='restrict', copy=False)
    user_id = fields.Many2one('res.users', string='Portal User', copy=False)

    first_name = fields.Char(string='First Name', required=True, tracking=True)
    middle_name = fields.Char(string='Middle Name', required=True, tracking=True)
    last_name = fields.Char(string='Last Name', required=True, tracking=True)
    full_name = fields.Char(string='Full Name', compute='_compute_full_name', store=True)

    mobile = fields.Char(string='Mobile', required=True, tracking=True)
    email = fields.Char(string='Email', required=True, tracking=True)

    mother_name = fields.Char(string='Mother Name', required=True)
    date_of_birth = fields.Date(string='Date of Birth', required=True)
    gender = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
    ], string='Gender', required=True)
    education_level = fields.Char(string='Education Level', required=True)

    # Address / Location
    country_id = fields.Many2one('res.country', string='Country', required=True)
    state_id = fields.Many2one('res.country.state', string='Region', domain="[('country_id', '=?', country_id)]")
    district = fields.Char(string='District', required=True)
    residence_address = fields.Text(string='Address of Residence', required=True)

    # Bank Details (optional)
    bank_name = fields.Char(string='Bank Name')
    bank_address = fields.Char(string='Bank Address')
    bank_account_no = fields.Char(string='Bank Account Number')

    # Next of Kin 1
    kin1_name = fields.Char(string='Next of Kin 1 Name', required=True)
    kin1_address = fields.Char(string='Next of Kin 1 Address', required=True)
    kin1_mobile = fields.Char(string='Next of Kin 1 Mobile', required=True)

    # Next of Kin 2
    kin2_name = fields.Char(string='Next of Kin 2 Name', required=True)
    kin2_address = fields.Char(string='Next of Kin 2 Address', required=True)
    kin2_mobile = fields.Char(string='Next of Kin 2 Mobile', required=True)

    # KYC Attachments
    photo = fields.Binary(string='Photo', attachment=True, required=True)
    identity_file = fields.Binary(string='Identity Document', attachment=True, required=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('pending_payment', 'Pending Payment'),
        ('pending_approval', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True, copy=False)

    member_id = fields.Many2one('saami.member', string='Member Record', readonly=True, copy=False)
    invoice_id = fields.Many2one('account.move', string='Registration Invoice', readonly=True, copy=False)

    @api.depends('first_name', 'middle_name', 'last_name')
    def _compute_full_name(self):
        for rec in self:
            names = [rec.first_name, rec.middle_name, rec.last_name]
            rec.full_name = ' '.join(filter(None, names))

    @api.model_create_multi
    def create(self, vals_list):
        # Validate that active registration product exists
        reg_product = self.env['saami.product'].search([
            ('purpose', '=', 'registration'),
            ('is_active', '=', True)
        ], limit=1)
        if not reg_product:
            raise UserError(_("Cannot create application: No active Registration Fee product configured in Saami Products."))

        Partner = self.env['res.partner']
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('saami.member.application') or _('New')

            # Ensure partner_id is created or linked upfront
            if not vals.get('partner_id'):
                full_name = ' '.join(filter(None, [
                    vals.get('first_name', ''),
                    vals.get('middle_name', ''),
                    vals.get('last_name', ''),
                ]))
                partner_vals = {
                    'name': full_name or vals.get('email', _('New Applicant')),
                    'email': vals.get('email'),
                    'phone': vals.get('mobile'),
                    'street': vals.get('residence_address'),
                    'country_id': vals.get('country_id'),
                    'state_id': vals.get('state_id'),
                    'city': vals.get('district'),
                }
                partner = Partner.create(partner_vals)
                vals['partner_id'] = partner.id

        records = super().create(vals_list)
        return records

    def write(self, vals):
        res = super().write(vals)
        # Sync name/mobile/email to partner if updated on application
        if any(f in vals for f in ['first_name', 'middle_name', 'last_name', 'mobile', 'email']):
            for rec in self:
                if rec.partner_id:
                    partner_vals = {}
                    if 'first_name' in vals or 'middle_name' in vals or 'last_name' in vals:
                        partner_vals['name'] = rec.full_name
                    if 'mobile' in vals:
                        partner_vals['phone'] = rec.mobile
                    if 'email' in vals:
                        partner_vals['email'] = rec.email
                    if partner_vals:
                        rec.partner_id.write(partner_vals)
        return res

    def action_create_registration_invoice(self):
        """Create registration fee invoice for the application."""
        AccountMove = self.env['account.move']
        reg_prod = self.env['saami.product'].search([
            ('purpose', '=', 'registration'),
            ('is_active', '=', True)
        ], limit=1)
        if not reg_prod:
            raise UserError(_("No active Registration Fee product configured in Saami Products."))

        for rec in self:
            if rec.invoice_id:
                continue

            invoice = AccountMove.create({
                'move_type': 'out_invoice',
                'partner_id': rec.partner_id.id,
                'invoice_origin': rec.name,
                'invoice_line_ids': [(0, 0, {
                    'product_id': reg_prod.product_id.id,
                    'name': reg_prod.description or reg_prod.product_id.name,
                    'quantity': 1.0,
                    'price_unit': reg_prod.amount,
                })],
            })
            invoice.action_post()
            rec.invoice_id = invoice.id
            rec.state = 'pending_payment'

    def action_create_user(self):
        """Open user creation wizard for the application."""
        self.ensure_one()
        if self.user_id:
            raise ValidationError(_("This applicant already has a user account."))
        if not self.email:
            raise ValidationError(_("An email address is required to create a user account."))

        return {
            'name': _('Create Portal User'),
            'type': 'ir.actions.act_window',
            'res_model': 'saami.create.user.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_application_id': self.id,
                'default_partner_id': self.partner_id.id,
                'default_name': self.full_name,
                'default_login': self.email,
            }
        }

    def action_submit_payment(self):
        """Called once payment for registration fee is initiated / awaiting confirmation."""
        for rec in self:
            rec.state = 'pending_approval'

    def action_approve(self):
        """Approve the application and create the saami.member record."""
        Member = self.env['saami.member']

        for rec in self:
            if rec.state == 'approved':
                continue

            partner = rec.partner_id
            if not partner:
                partner = self.env['res.partner'].create({
                    'name': rec.full_name,
                    'email': rec.email,
                    'phone': rec.mobile,
                    'street': rec.residence_address,
                    'country_id': rec.country_id.id,
                    'state_id': rec.state_id.id if rec.state_id else False,
                    'city': rec.district,
                })
                rec.partner_id = partner.id

            member = Member.create({
                'application_id': rec.id,
                'partner_id': partner.id,
                'first_name': rec.first_name,
                'middle_name': rec.middle_name,
                'last_name': rec.last_name,
                'mother_name': rec.mother_name,
                'mobile': rec.mobile,
                'email': rec.email,
                'date_of_birth': rec.date_of_birth,
                'gender': rec.gender,
                'education_level': rec.education_level,
                'country_id': rec.country_id.id,
                'state_id': rec.state_id.id if rec.state_id else False,
                'district': rec.district,
                'residence_address': rec.residence_address,
                'bank_name': rec.bank_name,
                'bank_address': rec.bank_address,
                'bank_account_no': rec.bank_account_no,
                'kin1_name': rec.kin1_name,
                'kin1_address': rec.kin1_address,
                'kin1_mobile': rec.kin1_mobile,
                'kin2_name': rec.kin2_name,
                'kin2_address': rec.kin2_address,
                'kin2_mobile': rec.kin2_mobile,
                'photo': rec.photo,
                'identity_file': rec.identity_file,
                'state': 'active',
            })
            rec.member_id = member.id
            rec.state = 'approved'

    def action_reject(self):
        self.write({'state': 'rejected'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})
