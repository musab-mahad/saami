# -*- coding: utf-8 -*-
import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class SaamiPasswordReset(models.Model):
    _name = 'saami.password.reset'
    _description = 'Saami Password Reset OTP'
    _order = 'id desc'

    user_id = fields.Many2one('res.users', string='User', ondelete='cascade', index=True)
    login_email = fields.Char(string='Email', required=True, index=True)
    request_ip = fields.Char(string='Request IP', index=True)
    code_hash = fields.Char(string='OTP Hash', copy=False)
    expires_at = fields.Datetime(string='Expires At', index=True)
    attempts = fields.Integer(string='Failed Attempts', default=0)
    used_at = fields.Datetime(string='Used At')
    state = fields.Selection([
        ('active', 'Active'),
        ('used', 'Used'),
        ('cancelled', 'Cancelled'),
        ('expired', 'Expired'),
        ('ignored', 'Ignored'),
    ], string='Status', default='active', required=True, index=True)

    @api.model
    def _hash_code(self, code):
        return hashlib.sha256(str(code).strip().encode('utf-8')).hexdigest()

    @api.model
    def _is_member_suspended(self, user):
        if not user or not user.partner_id:
            return False
        return bool(self.env['saami.member'].sudo().search_count([
            ('partner_id', '=', user.partner_id.id),
            ('state', '=', 'suspended'),
        ]))

    @api.model
    def _is_rate_limited(self, email, ip_addr):
        window_start = fields.Datetime.now() - timedelta(hours=1)
        email_count = self.search_count([
            ('login_email', '=', email),
            ('create_date', '>=', window_start),
        ])
        if email_count >= 3:
            return True
        if ip_addr:
            ip_count = self.search_count([
                ('request_ip', '=', ip_addr),
                ('create_date', '>=', window_start),
            ])
            if ip_count >= 10:
                return True
        return False

    @api.model
    def _request_reset(self, email, ip_addr=None):
        clean_email = (email or '').strip().lower()
        if self._is_rate_limited(clean_email, ip_addr):
            return False, 'RATE_LIMITED'

        user = self.env['res.users'].sudo().search([('login', '=ilike', clean_email)], limit=1)
        if user and self._is_member_suspended(user):
            return False, 'MEMBER_SUSPENDED'

        if not user or not user.active:
            self.create({
                'login_email': clean_email,
                'request_ip': ip_addr or False,
                'state': 'ignored',
            })
            return True, 'OK'

        # Cancel any prior active OTPs for this user
        prior_active = self.search([
            ('user_id', '=', user.id),
            ('state', '=', 'active'),
        ])
        if prior_active:
            prior_active.write({'state': 'cancelled'})

        otp = f"{secrets.randbelow(1000000):06d}"
        now = fields.Datetime.now()
        reset_rec = self.create({
            'user_id': user.id,
            'login_email': clean_email,
            'request_ip': ip_addr or False,
            'code_hash': self._hash_code(otp),
            'expires_at': now + timedelta(minutes=15),
            'state': 'active',
        })

        template = self.env.ref('saami.mail_template_password_reset', raise_if_not_found=False)
        if template:
            try:
                template.sudo().with_context(otp_code=otp).send_mail(reset_rec.id, force_send=True)
            except Exception as exc:
                _logger.warning("Failed to send password reset email to %s: %s", clean_email, exc)

        return True, 'OK'

    @api.model
    def _verify_and_reset(self, email, code, new_password):
        clean_email = (email or '').strip().lower()
        clean_code = (code or '').strip()

        user = self.env['res.users'].sudo().search([('login', '=ilike', clean_email)], limit=1)
        if user and self._is_member_suspended(user):
            return False, 'MEMBER_SUSPENDED', 'Your membership has been suspended. Please contact support.'

        if not user or not user.active or not clean_code:
            return False, 'VALIDATION_ERROR', 'The code is invalid or has expired.'

        reset_rec = self.search([
            ('user_id', '=', user.id),
            ('state', '=', 'active'),
        ], order='id desc', limit=1)

        if not reset_rec:
            return False, 'VALIDATION_ERROR', 'The code is invalid or has expired.'

        now = fields.Datetime.now()
        if reset_rec.expires_at and reset_rec.expires_at < now:
            reset_rec.write({'state': 'expired'})
            return False, 'VALIDATION_ERROR', 'The code is invalid or has expired.'

        expected_hash = reset_rec.code_hash or ''
        provided_hash = self._hash_code(clean_code)
        if not hmac.compare_digest(expected_hash, provided_hash):
            new_attempts = (reset_rec.attempts or 0) + 1
            vals = {'attempts': new_attempts}
            if new_attempts >= 5:
                vals['state'] = 'cancelled'
            reset_rec.write(vals)
            return False, 'VALIDATION_ERROR', 'The code is invalid or has expired.'

        reset_rec.write({
            'state': 'used',
            'used_at': now,
        })
        user.sudo().write({
            'password': new_password,
            'saami_token_version': (user.saami_token_version or 1) + 1,
        })
        return True, 'SUCCESS', 'Password has been reset.'
