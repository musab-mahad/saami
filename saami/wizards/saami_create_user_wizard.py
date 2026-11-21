# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError


class SaamiCreateUserWizard(models.TransientModel):
    _name = 'saami.create.user.wizard'
    _description = 'Create Portal User for Saami Applicant or Member'

    application_id = fields.Many2one('saami.member.application', string='Application')
    member_id = fields.Many2one('saami.member', string='Member')
    partner_id = fields.Many2one('res.partner', string='Contact', required=True, readonly=True)

    name = fields.Char(string='Full Name', required=True, readonly=True)
    login = fields.Char(string='Email / Login', required=True, readonly=True)
    password = fields.Char(
        string='Initial Password',
        help="Optional: Set a starting password for the user. If left empty, an invitation email will be sent.",
    )
    send_email = fields.Boolean(
        string='Send Invitation Email',
        default=True,
        help="Check to send an email invitation with login instructions.",
    )

    def action_confirm_create_user(self):
        self.ensure_one()
        User = self.env['res.users'].sudo()

        # Check if login already taken
        existing_user = User.search([('login', '=', self.login)], limit=1)
        if existing_user:
            raise ValidationError(_("A user with login '%s' already exists in the system.") % self.login)

        portal_group = self.env.ref('base.group_portal')

        user_vals = {
            'name': self.name,
            'login': self.login,
            'email': self.login,
            'partner_id': self.partner_id.id,
            'groups_id': [(6, 0, [portal_group.id])],
        }
        if self.password:
            user_vals['password'] = self.password

        user = User.with_context(
            no_reset_password=bool(self.password or not self.send_email),
            mail_create_nosubscribe=True,
            mail_create_nolog=True,
            signup_valid=False,
        ).create(user_vals)

        # Link to application or member
        if self.application_id:
            self.application_id.user_id = user.id
        if self.member_id:
            self.member_id.user_id = user.id

        if self.send_email and not self.password:
            user.action_reset_password()

        return {'type': 'ir.actions.act_window_close'}
