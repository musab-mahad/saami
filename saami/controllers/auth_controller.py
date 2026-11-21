# -*- coding: utf-8 -*-
import logging
import requests
from odoo import http, _
from odoo.http import request
from odoo.exceptions import AccessDenied

from .jwt_utils import (
    send_json,
    handle_cors,
    get_json_body,
    generate_jwt,
    require_jwt,
)

_logger = logging.getLogger(__name__)


def verify_google_id_token(id_token, expected_email=None):
    """
    Verifies a Google ID token with Google's tokeninfo endpoint.
    Checks:
    1. HTTP response is 200 from Google.
    2. aud matches one of the configured Client IDs in saami.google_client_id.
    3. email matches expected_email (case-insensitive) if expected_email is provided.
    4. email_verified is true.
    Returns: (is_valid: bool, error_dict_or_payload: dict)
    """
    if not id_token:
        return False, {
            "code": "MISSING_GOOGLE_TOKEN",
            "message": "Google ID token is required for Google authentication."
        }

    raw_client_ids = request.env['ir.config_parameter'].sudo().get_param('saami.google_client_id', '')
    allowed_client_ids = [c.strip() for c in (raw_client_ids or '').split(',') if c.strip()]
    if not allowed_client_ids:
        _logger.error("Google login failed: saami.google_client_id is not configured in settings.")
        return False, {
            "code": "CONFIG_ERROR",
            "message": "Google authentication is not properly configured on the server."
        }

    try:
        resp = requests.get(
            'https://oauth2.googleapis.com/tokeninfo',
            params={'id_token': id_token},
            timeout=10
        )
    except Exception as exc:
        _logger.error("Google token verification request failed: %s", str(exc))
        return False, {
            "code": "GOOGLE_VERIFY_FAILED",
            "message": "Unable to verify Google token with Google servers."
        }

    if resp.status_code != 200:
        _logger.warning("Google token verification rejected by Google: status %s, body: %s", resp.status_code, resp.text)
        return False, {
            "code": "INVALID_GOOGLE_TOKEN",
            "message": "Invalid or expired Google token."
        }

    payload = resp.json()
    token_aud = payload.get('aud', '').strip()
    token_email = (payload.get('email') or '').strip().lower()
    token_email_verified = payload.get('email_verified') in (True, 'true', 'True', 1)

    if token_aud not in allowed_client_ids:
        _logger.warning("Google token aud mismatch: received %s, allowed: %s", token_aud, allowed_client_ids)
        return False, {
            "code": "INVALID_GOOGLE_TOKEN",
            "message": "Google token audience mismatch."
        }

    if not token_email_verified:
        return False, {
            "code": "GOOGLE_EMAIL_NOT_VERIFIED",
            "message": "Your Google email address is not verified by Google."
        }

    if expected_email and token_email != expected_email.strip().lower():
        _logger.warning("Google token email mismatch: payload %s vs expected %s", token_email, expected_email)
        return False, {
            "code": "GOOGLE_EMAIL_MISMATCH",
            "message": "The email in the Google token does not match the provided email."
        }

    return True, payload


class SaamiAuthController(http.Controller):

    @http.route(['/api/saami/auth/login', '/api/saami/auth/google'], type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False)
    def login(self):
        preflight = handle_cors(['POST', 'OPTIONS'])
        if preflight:
            return preflight

        data = get_json_body()
        if not data:
            return send_json({'code': 'BAD_REQUEST', 'message': 'JSON payload is required.'}, status=400)

        login = (data.get('login') or data.get('email') or '').strip().lower()
        password = data.get('password') or ''
        id_token = (data.get('id_token') or '').strip()
        login_type = data.get('login_type') or ('google' if id_token else 'password')
        is_google_auth = (
            request.httprequest.path.rstrip('/').endswith('/google')
            or login_type == 'google'
            or bool(id_token)
        )

        if is_google_auth:
            if not id_token:
                return send_json({
                    'code': 'VALIDATION_ERROR',
                    'message': 'Google ID token (id_token) is required for Google login.',
                }, status=400)

            is_valid, token_res = verify_google_id_token(id_token, expected_email=login or None)
            if not is_valid:
                return send_json(token_res, status=401)

            token_email = (token_res.get('email') or login).strip().lower()
            user = request.env['res.users'].sudo().search([('login', '=ilike', token_email)], limit=1)

            if not user:
                return send_json({
                    'code': 'USER_NOT_FOUND',
                    'message': 'No registered member account found for this Google email. Please register first.',
                }, status=404)

            if not user.active:
                return send_json({
                    'code': 'ACCOUNT_INACTIVE',
                    'message': 'Your account is deactivated. Please contact support.',
                }, status=403)

            uid = user.id
        else:
            if not login or not password:
                return send_json({
                    'code': 'VALIDATION_ERROR',
                    'message': 'Login and password are required.',
                }, status=400)

            # Authenticate against Odoo database
            db = request.db or (request.env.cr and request.env.cr.dbname) or request.session.db
            credential = {'type': 'password', 'login': login, 'password': password}
            try:
                auth_info = request.session.authenticate(db, credential)
                uid = auth_info['uid']
            except AccessDenied:
                return send_json({
                    'code': 'AUTH_FAILED',
                    'message': 'Invalid login credentials.',
                }, status=401)
            except Exception as e:
                _logger.error("Authentication error: %s", str(e), exc_info=True)
                return send_json({
                    'code': 'SERVER_ERROR',
                    'message': 'Authentication engine encountered an issue.',
                }, status=500)

            user = request.env['res.users'].sudo().browse(uid)

        # Find linked application and member record
        Application = request.env['saami.member.application'].sudo()
        Member = request.env['saami.member'].sudo()

        member = Member.search([('partner_id', '=', user.partner_id.id)], limit=1)
        application = Application.search([('partner_id', '=', user.partner_id.id)], limit=1)

        status = 'guest'
        member_number = None
        application_number = None

        if member:
            status = member.state  # 'active', 'suspended', 'terminated'
            member_number = member.name
        elif application:
            status = application.state  # 'draft', 'pending_payment', 'pending_approval', etc.
            application_number = application.name

        extra_payload = {
            'status': status,
            'member_id': member.id if member else False,
            'application_id': application.id if application else False,
        }
        token = generate_jwt(user, extra_payload=extra_payload)

        base_url = request.httprequest.url_root.rstrip('/') or request.env['ir.config_parameter'].sudo().get_param('web.base.url', '').rstrip('/')
        user_image_url = f"{base_url}/web/image?model=res.partner&id={user.partner_id.id}&field=image_1920" if user.partner_id.image_1920 else None

        user_data = {
            'id': user.id,
            'name': user.name,
            'email': user.login,
            'image_url': user_image_url,
            'status': status,
            'member_number': member_number,
            'application_number': application_number,
        }
        if application and not member:
            inv = application.invoice_id
            user_data['registration'] = {
                'invoice_id': inv.id if inv else False,
                'amount_total': inv.amount_total if inv else 0.0,
                'amount_due': inv.amount_residual if inv else 0.0,
                'currency': (inv.currency_id.name or 'USD') if inv else 'USD',
                'payment_status': inv.payment_state if inv else 'not_paid',
                'is_paid': inv.payment_state in ('paid', 'in_payment') if inv else False,
            }

        return send_json({
            'code': 'SUCCESS',
            'message': 'Logged in successfully.',
            'token': token,
            'user': user_data,
        }, status=200)

    @http.route('/api/saami/auth/me', type='http', auth='none', methods=['GET', 'OPTIONS'], csrf=False)
    @require_jwt
    def me(self, user):
        """
        Protected route returning the current authenticated profile.
        """
        Application = request.env['saami.member.application'].sudo()
        Member = request.env['saami.member'].sudo()

        member = Member.search([('partner_id', '=', user.partner_id.id)], limit=1)
        application = Application.search([('partner_id', '=', user.partner_id.id)], limit=1)

        base_url = request.httprequest.url_root.rstrip('/') or request.env['ir.config_parameter'].sudo().get_param('web.base.url', '').rstrip('/')
        user_image_url = f"{base_url}/web/image?model=res.partner&id={user.partner_id.id}&field=image_1920" if user.partner_id.image_1920 else None

        status = 'guest'
        details = {}

        if member:
            status = member.state
            if member.photo:
                photo_url = f"{base_url}/web/image?model=saami.member&id={member.id}&field=photo"
            elif member.partner_id.image_1920:
                photo_url = f"{base_url}/web/image?model=res.partner&id={member.partner_id.id}&field=image_1920"
            else:
                photo_url = None

            details = {
                'type': 'member',
                'member_number': member.name,
                'full_name': member.full_name,
                'mobile': member.mobile,
                'email': member.email,
                'image_url': photo_url,
                'district_id': member.district_id.id if member.district_id else False,
                'district': member.district_id.name if member.district_id else (member.district or False),
                'region_id': member.state_id.id if member.state_id else False,
                'region': member.state_id.name if member.state_id else False,
                'country_id': member.country_id.id if member.country_id else False,
                'country': member.country_id.name if member.country_id else False,
                'total_contributions': member.total_contributions,
                'currency': member.currency_id.name,
                'state': member.state,
            }
        elif application:
            status = application.state
            inv = application.invoice_id
            if application.photo:
                photo_url = f"{base_url}/web/image?model=saami.member.application&id={application.id}&field=photo"
            elif user.partner_id.image_1920:
                photo_url = f"{base_url}/web/image?model=res.partner&id={user.partner_id.id}&field=image_1920"
            else:
                photo_url = None

            details = {
                'type': 'application',
                'application_number': application.name,
                'full_name': application.full_name,
                'mobile': application.mobile,
                'email': application.email,
                'image_url': photo_url,
                'district_id': application.district_id.id if application.district_id else False,
                'district': application.district_id.name if application.district_id else (application.district or False),
                'region_id': application.state_id.id if application.state_id else False,
                'region': application.state_id.name if application.state_id else False,
                'country_id': application.country_id.id if application.country_id else False,
                'country': application.country_id.name if application.country_id else False,
                'state': application.state,
                'invoice_id': inv.id if inv else False,
                'registration_fee': inv.amount_total if inv else 0.0,
                'amount_due': inv.amount_residual if inv else 0.0,
                'currency': (inv.currency_id.name or 'USD') if inv else 'USD',
                'payment_status': inv.payment_state if inv else 'not_paid',
                'is_paid': inv.payment_state in ('paid', 'in_payment') if inv else False,
            }

        return send_json({
            'code': 'SUCCESS',
            'status': status,
            'user': {
                'id': user.id,
                'name': user.name,
                'email': user.login,
                'image_url': user_image_url,
            },
            'profile': details,
        }, status=200)
