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
    _description = 'Saami Verification & Password Reset OTP'
    _order = 'id desc'

    user_id = fields.Many2one('res.users', string='User', ondelete='cascade', index=True)
    login_email = fields.Char(string='Email', required=True, index=True)
    request_ip = fields.Char(string='Request IP', index=True)
    purpose = fields.Selection([
        ('password_reset', 'Password Reset'),
        ('email_verification', 'Email Verification'),
    ], string='Purpose', default='password_reset', required=True, index=True)
    code_hash = fields.Char(string='OTP Hash', copy=False)
    reset_token = fields.Char(string='Reset Token', copy=False, index=True)
    reset_token_expires_at = fields.Datetime(string='Reset Token Expires At')
    expires_at = fields.Datetime(string='Expires At', index=True)
    attempts = fields.Integer(string='Failed Attempts', default=0)
    used_at = fields.Datetime(string='Used At')
    state = fields.Selection([
        ('active', 'Active'),
        ('verified', 'Code Verified'),
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
    def _check_rate_limit(self, email, ip_addr, purpose='password_reset'):
        now = fields.Datetime.now()
        cooldown_start = now - timedelta(seconds=30)
        recent = self.search_count([
            ('login_email', '=', email),
            ('purpose', '=', purpose),
            ('create_date', '>=', cooldown_start),
        ])
        if recent >= 1:
            return True, 'Please wait 30 seconds before requesting another code.'

        window_start = now - timedelta(hours=1)
        email_count = self.search_count([
            ('login_email', '=', email),
            ('purpose', '=', purpose),
            ('create_date', '>=', window_start),
        ])
        if email_count >= 3:
            return True, 'Too many requests. Please try again later.'
        if ip_addr:
            ip_count = self.search_count([
                ('request_ip', '=', ip_addr),
                ('purpose', '=', purpose),
                ('create_date', '>=', window_start),
            ])
            if ip_count >= 10:
                return True, 'Too many requests. Please try again later.'
        return False, None

    @api.model
    def _issue_otp(self, user, clean_email, ip_addr, purpose, template_xmlid):
        prior_active = self.search([
            ('user_id', '=', user.id),
            ('purpose', '=', purpose),
            ('state', 'in', ('active', 'verified')),
        ])
        if prior_active:
            prior_active.write({'state': 'cancelled'})

        otp = f"{secrets.randbelow(1000000):06d}"
        now = fields.Datetime.now()
        reset_rec = self.create({
            'user_id': user.id,
            'login_email': clean_email,
            'request_ip': ip_addr or False,
            'purpose': purpose,
            'code_hash': self._hash_code(otp),
            'expires_at': now + timedelta(minutes=15),
            'state': 'active',
        })

        template = self.env.ref(template_xmlid, raise_if_not_found=False)
        if template:
            try:
                template.sudo().with_context(otp_code=otp).send_mail(reset_rec.id, force_send=True)
            except Exception as exc:
                _logger.warning("Failed to send %s email to %s: %s", purpose, clean_email, exc)
        return reset_rec, otp

    @api.model
    def _request_email_verification(self, email, ip_addr=None, skip_rate_limit=False):
        clean_email = (email or '').strip().lower()
        if not skip_rate_limit:
            limited, msg = self._check_rate_limit(clean_email, ip_addr, purpose='email_verification')
            if limited:
                return False, 'RATE_LIMITED', msg

        user = self.env['res.users'].sudo().search([('login', '=ilike', clean_email)], limit=1)
        if not user or not user.active or user.saami_email_verified:
            self.create({
                'login_email': clean_email,
                'request_ip': ip_addr or False,
                'purpose': 'email_verification',
                'state': 'ignored',
            })
            return True, 'OK', None

        self._issue_otp(user, clean_email, ip_addr, 'email_verification', 'saami.mail_template_email_verification')
        return True, 'OK', None

    @api.model
    def _verify_email_otp(self, email, code):
        clean_email = (email or '').strip().lower()
        clean_code = (code or '').strip()

        user = self.env['res.users'].sudo().search([('login', '=ilike', clean_email)], limit=1)
        if not user or not user.active or not clean_code:
            return False, 'VALIDATION_ERROR', 'The code is invalid or has expired.'

        rec = self.search([
            ('user_id', '=', user.id),
            ('purpose', '=', 'email_verification'),
            ('state', '=', 'active'),
        ], order='id desc', limit=1)
        if not rec:
            return False, 'VALIDATION_ERROR', 'The code is invalid or has expired.'

        now = fields.Datetime.now()
        if rec.expires_at and rec.expires_at < now:
            rec.write({'state': 'expired'})
            return False, 'VALIDATION_ERROR', 'The code is invalid or has expired.'

        if not hmac.compare_digest(rec.code_hash or '', self._hash_code(clean_code)):
            new_attempts = (rec.attempts or 0) + 1
            vals = {'attempts': new_attempts}
            if new_attempts >= 5:
                vals['state'] = 'cancelled'
            rec.write(vals)
            return False, 'VALIDATION_ERROR', 'The code is invalid or has expired.'

        rec.write({'state': 'used', 'used_at': now})
        user.sudo().write({'saami_email_verified': True})
        return True, 'SUCCESS', 'Email verified successfully. You can now sign in.'

    @api.model
    def _request_reset(self, email, ip_addr=None):
        clean_email = (email or '').strip().lower()
        limited, msg = self._check_rate_limit(clean_email, ip_addr, purpose='password_reset')
        if limited:
            return False, 'RATE_LIMITED', msg

        user = self.env['res.users'].sudo().search([('login', '=ilike', clean_email)], limit=1)
        if user and self._is_member_suspended(user):
            return False, 'MEMBER_SUSPENDED', 'Your membership has been suspended. Please contact support.'

        if not user or not user.active:
            self.create({
                'login_email': clean_email,
                'request_ip': ip_addr or False,
                'purpose': 'password_reset',
                'state': 'ignored',
            })
            return True, 'OK', None

        self._issue_otp(user, clean_email, ip_addr, 'password_reset', 'saami.mail_template_password_reset')
        return True, 'OK', None

    @api.model
    def _verify_reset_code(self, email, code):
        clean_email = (email or '').strip().lower()
        clean_code = (code or '').strip()

        user = self.env['res.users'].sudo().search([('login', '=ilike', clean_email)], limit=1)
        if user and self._is_member_suspended(user):
            return False, 'MEMBER_SUSPENDED', 'Your membership has been suspended. Please contact support.', None

        if not user or not user.active or not clean_code:
            return False, 'VALIDATION_ERROR', 'The code is invalid or has expired.', None

        rec = self.search([
            ('user_id', '=', user.id),
            ('purpose', '=', 'password_reset'),
            ('state', '=', 'active'),
        ], order='id desc', limit=1)
        if not rec:
            return False, 'VALIDATION_ERROR', 'The code is invalid or has expired.', None

        now = fields.Datetime.now()
        if rec.expires_at and rec.expires_at < now:
            rec.write({'state': 'expired'})
            return False, 'VALIDATION_ERROR', 'The code is invalid or has expired.', None

        if not hmac.compare_digest(rec.code_hash or '', self._hash_code(clean_code)):
            new_attempts = (rec.attempts or 0) + 1
            vals = {'attempts': new_attempts}
            if new_attempts >= 5:
                vals['state'] = 'cancelled'
            rec.write(vals)
            return False, 'VALIDATION_ERROR', 'The code is invalid or has expired.', None

        token = secrets.token_urlsafe(32)
        rec.write({
            'state': 'verified',
            'reset_token': token,
            'reset_token_expires_at': now + timedelta(minutes=10),
        })
        return True, 'SUCCESS', 'Code verified.', token

    @api.model
    def _verify_and_reset(self, email, new_password, code=None, reset_token=None):
        clean_email = (email or '').strip().lower()
        clean_code = (code or '').strip()
        clean_token = (reset_token or '').strip()

        user = self.env['res.users'].sudo().search([('login', '=ilike', clean_email)], limit=1)
        if user and self._is_member_suspended(user):
            return False, 'MEMBER_SUSPENDED', 'Your membership has been suspended. Please contact support.'

        if not user or not user.active or (not clean_token and not clean_code):
            return False, 'VALIDATION_ERROR', 'The code is invalid or has expired.'

        now = fields.Datetime.now()
        if clean_token:
            rec = self.search([
                ('user_id', '=', user.id),
                ('purpose', '=', 'password_reset'),
                ('state', '=', 'verified'),
                ('reset_token', '=', clean_token),
            ], order='id desc', limit=1)
            if not rec or (rec.reset_token_expires_at and rec.reset_token_expires_at < now):
                if rec:
                    rec.write({'state': 'expired'})
                return False, 'VALIDATION_ERROR', 'The code is invalid or has expired.'
        else:
            rec = self.search([
                ('user_id', '=', user.id),
                ('purpose', '=', 'password_reset'),
                ('state', '=', 'active'),
            ], order='id desc', limit=1)
            if not rec:
                return False, 'VALIDATION_ERROR', 'The code is invalid or has expired.'
            if rec.expires_at and rec.expires_at < now:
                rec.write({'state': 'expired'})
                return False, 'VALIDATION_ERROR', 'The code is invalid or has expired.'
            if not hmac.compare_digest(rec.code_hash or '', self._hash_code(clean_code)):
                new_attempts = (rec.attempts or 0) + 1
                vals = {'attempts': new_attempts}
                if new_attempts >= 5:
                    vals['state'] = 'cancelled'
                rec.write(vals)
                return False, 'VALIDATION_ERROR', 'The code is invalid or has expired.'

        rec.write({'state': 'used', 'used_at': now})
        user.sudo().write({
            'password': new_password,
            'saami_token_version': (user.saami_token_version or 1) + 1,
        })
        return True, 'SUCCESS', 'Password has been reset.'
