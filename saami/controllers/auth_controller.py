# -*- coding: utf-8 -*-
import base64
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


def _parse_image_base64(raw_image):
    if not raw_image or not isinstance(raw_image, str):
        return None
    raw_str = raw_image.strip()
    if ',' in raw_str:
        raw_str = raw_str.split(',', 1)[1].strip()
    try:
        base64.b64decode(raw_str, validate=True)
        return raw_str
    except Exception:
        return None


def _build_profile_response(user):
    base_url = request.httprequest.url_root.rstrip('/') or request.env['ir.config_parameter'].sudo().get_param('web.base.url', '').rstrip('/')
    user_image_url = f"{base_url}/web/image?model=res.partner&id={user.partner_id.id}&field=image_1920" if user.partner_id.image_1920 else None

    Application = request.env['saami.member.application'].sudo()
    Member = request.env['saami.member'].sudo()

    member = Member.search([('partner_id', '=', user.partner_id.id)], limit=1)
    application = Application.search([('partner_id', '=', user.partner_id.id)], limit=1)

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
            'member_id': member.id,
            'member_number': member.name,
            'first_name': member.first_name,
            'middle_name': member.middle_name,
            'last_name': member.last_name,
            'full_name': member.full_name,
            'mobile': member.mobile,
            'email': member.email,
            'gender': member.gender,
            'date_of_birth': str(member.date_of_birth) if member.date_of_birth else None,
            'mother_name': member.mother_name,
            'education_level': member.education_level,
            'image_url': photo_url,
            'district_id': member.district_id.id if member.district_id else False,
            'district': member.district_id.name if member.district_id else (member.district or False),
            'region_id': member.state_id.id if member.state_id else False,
            'region': member.state_id.name if member.state_id else False,
            'country_id': member.country_id.id if member.country_id else False,
            'country': member.country_id.name if member.country_id else False,
            'residence_address': member.residence_address,
            'bank_name': member.bank_name,
            'bank_address': member.bank_address,
            'bank_account_no': member.bank_account_no,
            'next_of_kin_1': {
                'name': member.kin1_name,
                'mobile': member.kin1_mobile,
                'address': member.kin1_address,
            },
            'next_of_kin_2': {
                'name': member.kin2_name,
                'mobile': member.kin2_mobile,
                'address': member.kin2_address,
            },
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
            'application_id': application.id,
            'application_number': application.name,
            'first_name': application.first_name,
            'middle_name': application.middle_name,
            'last_name': application.last_name,
            'full_name': application.full_name,
            'mobile': application.mobile,
            'email': application.email,
            'gender': application.gender,
            'date_of_birth': str(application.date_of_birth) if application.date_of_birth else None,
            'mother_name': application.mother_name,
            'education_level': application.education_level,
            'image_url': photo_url,
            'district_id': application.district_id.id if application.district_id else False,
            'district': application.district_id.name if application.district_id else (application.district or False),
            'region_id': application.state_id.id if application.state_id else False,
            'region': application.state_id.name if application.state_id else False,
            'country_id': application.country_id.id if application.country_id else False,
            'country': application.country_id.name if application.country_id else False,
            'residence_address': application.residence_address,
            'bank_name': application.bank_name,
            'bank_address': application.bank_address,
            'bank_account_no': application.bank_account_no,
            'next_of_kin_1': {
                'name': application.kin1_name,
                'mobile': application.kin1_mobile,
                'address': application.kin1_address,
            },
            'next_of_kin_2': {
                'name': application.kin2_name,
                'mobile': application.kin2_mobile,
                'address': application.kin2_address,
            },
            'state': application.state,
            'invoice_id': inv.id if inv else False,
            'registration_fee': inv.amount_total if inv else 0.0,
            'amount_due': inv.amount_residual if inv else 0.0,
            'currency': (inv.currency_id.name or 'USD') if inv else 'USD',
            'payment_status': inv.payment_state if inv else 'not_paid',
            'is_paid': inv.payment_state in ('paid', 'in_payment') if inv else False,
        }

    return {
        'code': 'SUCCESS',
        'status': status,
        'user': {
            'id': user.id,
            'name': user.name,
            'email': user.login,
            'image_url': user_image_url,
        },
        'profile': details,
    }


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
        preflight = handle_cors(['GET', 'OPTIONS'])
        if preflight:
            return preflight
        return send_json(_build_profile_response(user), status=200)

    @http.route(['/api/saami/auth/profile', '/api/saami/auth/profile/update'], type='http', auth='none', methods=['PUT', 'POST', 'PATCH', 'OPTIONS'], csrf=False)
    @require_jwt
    def update_profile(self, user):
        """
        Protected route to update editable profile details (image, next of kin, contact, bank, address).
        """
        preflight = handle_cors(['PUT', 'POST', 'PATCH', 'OPTIONS'])
        if preflight:
            return preflight

        data = get_json_body()
        if not data:
            return send_json({'code': 'BAD_REQUEST', 'message': 'JSON payload is required.'}, status=400)

        Application = request.env['saami.member.application'].sudo()
        Member = request.env['saami.member'].sudo()

        member = Member.search([('partner_id', '=', user.partner_id.id)], limit=1)
        application = Application.search([('partner_id', '=', user.partner_id.id)], limit=1)

        if not member and not application:
            return send_json({'code': 'NOT_FOUND', 'message': 'No member or application profile found.'}, status=404)

        member_vals = {}
        partner_vals = {}

        # 1. Profile image / photo
        raw_image = data.get('image') or data.get('photo') or data.get('image_base64')
        if raw_image:
            img_b64 = _parse_image_base64(raw_image)
            if img_b64:
                partner_vals['image_1920'] = img_b64
                member_vals['photo'] = img_b64
            else:
                return send_json({'code': 'INVALID_IMAGE', 'message': 'Provided image is not a valid base64 string.'}, status=400)

        # 2. Next of Kin 1
        if 'kin1_name' in data or 'next_of_kin_name' in data:
            member_vals['kin1_name'] = (data.get('kin1_name') or data.get('next_of_kin_name') or '').strip()
        if 'kin1_mobile' in data or 'next_of_kin_phone' in data or 'next_of_kin_mobile' in data:
            member_vals['kin1_mobile'] = (data.get('kin1_mobile') or data.get('next_of_kin_phone') or data.get('next_of_kin_mobile') or '').strip()
        if 'kin1_address' in data or 'next_of_kin_address' in data:
            member_vals['kin1_address'] = (data.get('kin1_address') or data.get('next_of_kin_address') or '').strip()

        # 3. Next of Kin 2
        if 'kin2_name' in data:
            member_vals['kin2_name'] = (data.get('kin2_name') or '').strip()
        if 'kin2_mobile' in data or 'kin2_phone' in data:
            member_vals['kin2_mobile'] = (data.get('kin2_mobile') or data.get('kin2_phone') or '').strip()
        if 'kin2_address' in data:
            member_vals['kin2_address'] = (data.get('kin2_address') or '').strip()

        # 4. Residence & contact details
        if 'residence_address' in data or 'address' in data:
            res_addr = (data.get('residence_address') or data.get('address') or '').strip()
            member_vals['residence_address'] = res_addr
            partner_vals['street'] = res_addr

        if 'mobile' in data or 'phone' in data:
            phone_val = (data.get('mobile') or data.get('phone') or '').strip()
            member_vals['mobile'] = phone_val
            partner_vals['phone'] = phone_val
            partner_vals['mobile'] = phone_val

        if 'education_level' in data:
            member_vals['education_level'] = (data.get('education_level') or '').strip()

        # 5. Bank details
        if 'bank_name' in data:
            member_vals['bank_name'] = (data.get('bank_name') or '').strip()
        if 'bank_address' in data:
            member_vals['bank_address'] = (data.get('bank_address') or '').strip()
        if 'bank_account_no' in data or 'bank_account_number' in data:
            member_vals['bank_account_no'] = (data.get('bank_account_no') or data.get('bank_account_number') or '').strip()

        # 6. Location references
        if 'district_id' in data:
            dist_id = data.get('district_id')
            if dist_id:
                district = request.env['saami.district'].sudo().browse(int(dist_id))
                if not district.exists():
                    return send_json({'code': 'INVALID_DISTRICT', 'message': 'District not found.'}, status=400)
                member_vals['district_id'] = district.id
                member_vals['district'] = district.name
            else:
                member_vals['district_id'] = False

        if 'region_id' in data or 'state_id' in data:
            reg_id = data.get('region_id') or data.get('state_id')
            if reg_id:
                state = request.env['res.country.state'].sudo().browse(int(reg_id))
                if not state.exists():
                    return send_json({'code': 'INVALID_REGION', 'message': 'Region not found.'}, status=400)
                member_vals['state_id'] = state.id
                partner_vals['state_id'] = state.id
            else:
                member_vals['state_id'] = False

        if 'country_id' in data:
            c_id = data.get('country_id')
            if c_id:
                country = request.env['res.country'].sudo().browse(int(c_id))
                if not country.exists():
                    return send_json({'code': 'INVALID_COUNTRY', 'message': 'Country not found.'}, status=400)
                member_vals['country_id'] = country.id
                partner_vals['country_id'] = country.id

        # 7. First/middle/last name
        if 'first_name' in data or 'middle_name' in data or 'last_name' in data:
            fn = data.get('first_name', (member or application).first_name)
            mn = data.get('middle_name', (member or application).middle_name)
            ln = data.get('last_name', (member or application).last_name)
            if 'first_name' in data:
                member_vals['first_name'] = fn
            if 'middle_name' in data:
                member_vals['middle_name'] = mn
            if 'last_name' in data:
                member_vals['last_name'] = ln
            full_name = ' '.join(filter(None, [fn, mn, ln])).strip()
            if full_name:
                partner_vals['name'] = full_name

        if not member_vals and not partner_vals:
            return send_json({'code': 'VALIDATION_ERROR', 'message': 'No editable profile fields provided.'}, status=400)

        # Apply updates
        if partner_vals:
            user.partner_id.sudo().write(partner_vals)
        if member:
            member.write(member_vals)
        elif application:
            application.write(member_vals)

        res = _build_profile_response(user)
        res['message'] = 'Profile updated successfully.'
        return send_json(res, status=200)

    @http.route('/api/saami/auth/change-password', type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False)
    @require_jwt
    def change_password(self, user):
        """
        Protected route to change user password by confirming the current password.
        """
        preflight = handle_cors(['POST', 'OPTIONS'])
        if preflight:
            return preflight

        data = get_json_body()
        if not data:
            return send_json({'code': 'BAD_REQUEST', 'message': 'JSON payload is required.'}, status=400)

        current_password = data.get('current_password') or data.get('old_password') or ''
        new_password = data.get('new_password') or ''

        if not current_password or not new_password:
            return send_json({
                'code': 'VALIDATION_ERROR',
                'message': 'Both current_password and new_password are required.',
            }, status=400)

        if len(new_password) < 8:
            return send_json({
                'code': 'WEAK_PASSWORD',
                'message': 'New password must be at least 8 characters long.',
            }, status=400)

        # Verify current password
        db = request.db or (request.env.cr and request.env.cr.dbname) or request.session.db
        credential = {'login': user.login, 'password': current_password, 'type': 'password'}
        try:
            auth_info = request.session.authenticate(db, credential)
            uid = auth_info.get('uid') if isinstance(auth_info, dict) else auth_info
            if uid != user.id:
                return send_json({
                    'code': 'INVALID_PASSWORD',
                    'message': 'Current password is incorrect.',
                }, status=401)
        except AccessDenied:
            return send_json({
                'code': 'INVALID_PASSWORD',
                'message': 'Current password is incorrect.',
            }, status=401)
        except Exception as e:
            _logger.error("Error verifying current password: %s", str(e), exc_info=True)
            return send_json({
                'code': 'SERVER_ERROR',
                'message': 'Failed to verify current password.',
            }, status=500)

        # Update password
        user.sudo().write({'password': new_password})

        return send_json({
            'code': 'SUCCESS',
            'message': 'Password has been changed successfully.',
        }, status=200)
