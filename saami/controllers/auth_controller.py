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
    parse_base64_file,
    generate_jwt,
    require_jwt,
)

_logger = logging.getLogger(__name__)


def _get_api_base_url():
    req_url = request.httprequest.url_root.rstrip('/')
    param_url = (request.env['ir.config_parameter'].sudo().get_param('web.base.url', '') or '').rstrip('/')
    if param_url.startswith('https://') and req_url.startswith('http://'):
        req_host = request.httprequest.host.split(':', 1)[0].lower()
        param_host = param_url.split('://', 1)[1].split('/', 1)[0].split(':', 1)[0].lower()
        if req_host == param_host:
            return param_url
    return req_url or param_url


def _build_profile_response(user):
    base_url = _get_api_base_url()
    user_image_url = f"{base_url}/api/saami/user/{user.partner_id.id}/avatar" if user.partner_id.image_1920 else None

    Application = request.env['saami.member.application'].sudo()
    Member = request.env['saami.member'].sudo()

    member = Member.search([('partner_id', '=', user.partner_id.id)], limit=1)
    application = Application.search([('partner_id', '=', user.partner_id.id)], limit=1)

    status = 'guest'
    details = {}

    if member:
        status = member.state
        if member.photo or member.partner_id.image_1920:
            photo_url = f"{base_url}/api/saami/member/{member.id}/photo"
        else:
            photo_url = None

        details = {
            'type': 'member',
            'member_id': member.id,
            'member_number': member.name,
            'application_number': member.application_id.name if member.application_id else (application.name if application else None),
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
            'identity_url': f"{base_url}/api/saami/member/{member.id}/identity" if member.identity_file else None,
            'district_id': member.district_id.id if member.district_id else False,
            'district': member.district_id.name if member.district_id else (member.district or False),
            'region_id': member.state_id.id if member.state_id else False,
            'region': member.state_id.name if member.state_id else False,
            'country_id': member.country_id.id if member.country_id else False,
            'country': member.country_id.name if member.country_id else False,
            'residence_address': member.residence_address,
            'next_of_kin': {
                'name': member.kin_name,
                'mobile': member.kin_mobile,
                'document_type': member.kin_document_type,
                'document_country_id': member.kin_document_country_id.id if member.kin_document_country_id else False,
                'document_country': member.kin_document_country_id.name if member.kin_document_country_id else False,
                'document_number': member.kin_document_number,
            },
            'id_document_type': member.id_document_type,
            'id_document_country_id': member.id_document_country_id.id if member.id_document_country_id else False,
            'id_document_country': member.id_document_country_id.name if member.id_document_country_id else False,
            'id_document_number': member.id_document_number,
            'total_contributions': member.total_contributions,
            'currency': member.currency_id.name,
            'state': member.state,
        }
    elif application:
        status = application.state
        inv = application.invoice_id
        if application.photo or user.partner_id.image_1920:
            photo_url = f"{base_url}/api/saami/application/{application.id}/photo"
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
            'identity_url': f"{base_url}/api/saami/application/{application.id}/identity" if application.identity_file else None,
            'district_id': application.district_id.id if application.district_id else False,
            'district': application.district_id.name if application.district_id else (application.district or False),
            'region_id': application.state_id.id if application.state_id else False,
            'region': application.state_id.name if application.state_id else False,
            'country_id': application.country_id.id if application.country_id else False,
            'country': application.country_id.name if application.country_id else False,
            'residence_address': application.residence_address,
            'next_of_kin': {
                'name': application.kin_name,
                'mobile': application.kin_mobile,
                'document_type': application.kin_document_type,
                'document_country_id': application.kin_document_country_id.id if application.kin_document_country_id else False,
                'document_country': application.kin_document_country_id.name if application.kin_document_country_id else False,
                'document_number': application.kin_document_number,
            },
            'id_document_type': application.id_document_type,
            'id_document_country_id': application.id_document_country_id.id if application.id_document_country_id else False,
            'id_document_country': application.id_document_country_id.name if application.id_document_country_id else False,
            'id_document_number': application.id_document_number,
            'state': application.state,
            'rejection_reason': application.rejection_reason or None,
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
            token_name = (token_res.get('name') or token_email.split('@')[0]).strip()
            user = request.env['res.users'].sudo().search([('login', '=ilike', token_email)], limit=1)

            if not user:
                company = request.env['res.company'].sudo().search([], limit=1)
                portal_group = request.env.ref('base.group_portal')
                partner = request.env['res.partner'].sudo().create({
                    'name': token_name,
                    'email': token_email,
                    'company_id': company.id,
                })
                user = request.env['res.users'].sudo().with_context(
                    no_reset_password=True,
                    mail_create_nosubscribe=True,
                    mail_create_nolog=True,
                    signup_valid=False,
                ).create({
                    'name': token_name,
                    'login': token_email,
                    'email': token_email,
                    'partner_id': partner.id,
                    'company_id': company.id,
                    'company_ids': [(6, 0, [company.id])],
                    'groups_id': [(6, 0, [portal_group.id])],
                    'saami_email_verified': True,
                })
                request.env['saami.member.application'].sudo().create({
                    'partner_id': partner.id,
                    'user_id': user.id,
                    'full_name': token_name,
                    'email': token_email,
                    'state': 'draft',
                })
            elif not user.active:
                return send_json({
                    'code': 'ACCOUNT_INACTIVE',
                    'message': 'Your account is deactivated. Please contact support.',
                }, status=403)
            elif not user.saami_email_verified:
                user.sudo().write({'saami_email_verified': True})

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
            if not user.saami_email_verified:
                return send_json({
                    'code': 'EMAIL_NOT_VERIFIED',
                    'message': 'Please verify your email address before signing in.',
                }, status=403)

        # Find linked application and member record
        Application = request.env['saami.member.application'].sudo()
        Member = request.env['saami.member'].sudo()

        member = Member.search([('partner_id', '=', user.partner_id.id)], limit=1)
        application = Application.search([('partner_id', '=', user.partner_id.id)], limit=1)

        status = 'guest'
        member_number = None
        application_number = None

        if member:
            if member.state == 'suspended':
                return send_json({
                    'code': 'MEMBER_SUSPENDED',
                    'message': 'Your membership has been suspended. Please contact support.',
                }, status=403)
            status = member.state
            member_number = member.name
            application_number = member.application_id.name if member.application_id else (application.name if application else None)
        elif application:
            status = application.state  # 'draft', 'pending_payment', 'pending_approval', etc.
            application_number = application.name

        extra_payload = {
            'status': status,
            'member_id': member.id if member else False,
            'application_id': application.id if application else False,
        }
        token = generate_jwt(user, extra_payload=extra_payload)

        base_url = _get_api_base_url()
        user_image_url = f"{base_url}/api/saami/user/{user.partner_id.id}/avatar" if user.partner_id.image_1920 else None

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
            user_data['rejection_reason'] = application.rejection_reason or None
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
            img_b64 = parse_base64_file(raw_image)
            if img_b64:
                partner_vals['image_1920'] = img_b64
                member_vals['photo'] = img_b64
            else:
                return send_json({'code': 'INVALID_IMAGE', 'message': 'Provided image is not a valid base64 string.'}, status=400)

        # 2. Next of Kin (1 person)
        if 'kin_name' in data or 'kin1_name' in data or 'next_of_kin_name' in data:
            member_vals['kin_name'] = (data.get('kin_name') or data.get('kin1_name') or data.get('next_of_kin_name') or '').strip()
        if 'kin_mobile' in data or 'kin1_mobile' in data or 'next_of_kin_phone' in data or 'next_of_kin_mobile' in data:
            member_vals['kin_mobile'] = (data.get('kin_mobile') or data.get('kin1_mobile') or data.get('next_of_kin_phone') or data.get('next_of_kin_mobile') or '').strip()
        if 'kin_document_type' in data:
            member_vals['kin_document_type'] = (data.get('kin_document_type') or '').strip()
        if 'kin_document_number' in data:
            member_vals['kin_document_number'] = (data.get('kin_document_number') or '').strip()
        if 'kin_document_country_id' in data:
            k_cid = data.get('kin_document_country_id')
            if k_cid:
                k_country = request.env['res.country'].sudo().browse(int(k_cid))
                if not k_country.exists():
                    return send_json({'code': 'INVALID_COUNTRY', 'message': 'Next of kin document country not found.'}, status=400)
                member_vals['kin_document_country_id'] = k_country.id
            else:
                member_vals['kin_document_country_id'] = False

        # 3. Residence & contact details
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

        if len(new_password) < 4:
            return send_json({
                'code': 'WEAK_PASSWORD',
                'message': 'New password must be at least 4 characters long.',
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

    @http.route('/api/saami/auth/forgot-password', type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False)
    def forgot_password(self):
        """
        Public endpoint to request a 6-digit password reset OTP code.
        """
        preflight = handle_cors(['POST', 'OPTIONS'])
        if preflight:
            return preflight

        data = get_json_body()
        if not data:
            return send_json({'code': 'BAD_REQUEST', 'message': 'JSON payload is required.'}, status=400)

        login = (data.get('login') or data.get('email') or '').strip().lower()
        if not login:
            return send_json({'code': 'VALIDATION_ERROR', 'message': 'Email address (login) is required.'}, status=400)

        forwarded_for = (request.httprequest.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
        ip_addr = forwarded_for or request.httprequest.remote_addr

        ok, code, msg = request.env['saami.password.reset'].sudo()._request_reset(login, ip_addr=ip_addr)
        if not ok and code == 'RATE_LIMITED':
            return send_json({
                'code': 'RATE_LIMITED',
                'message': msg or 'Too many requests. Please try again later.',
            }, status=429)
        if not ok and code == 'MEMBER_SUSPENDED':
            return send_json({
                'code': 'MEMBER_SUSPENDED',
                'message': msg or 'Your membership has been suspended. Please contact support.',
            }, status=403)

        return send_json({
            'code': 'SUCCESS',
            'message': 'If this email is registered, a code has been sent.',
        }, status=200)

    @http.route('/api/saami/auth/verify-reset-code', type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False)
    def verify_reset_code(self):
        """
        Public endpoint to verify a 6-digit password reset code and issue a short-lived reset_token.
        """
        preflight = handle_cors(['POST', 'OPTIONS'])
        if preflight:
            return preflight

        data = get_json_body()
        if not data:
            return send_json({'code': 'BAD_REQUEST', 'message': 'JSON payload is required.'}, status=400)

        login = (data.get('login') or data.get('email') or '').strip().lower()
        code = str(data.get('code') or '').strip()
        if not login or not code:
            return send_json({'code': 'VALIDATION_ERROR', 'message': 'The code is invalid or has expired.'}, status=400)

        ok, res_code, msg, reset_token = request.env['saami.password.reset'].sudo()._verify_reset_code(login, code)
        if not ok and res_code == 'MEMBER_SUSPENDED':
            return send_json({'code': 'MEMBER_SUSPENDED', 'message': msg}, status=403)
        if not ok:
            return send_json({'code': 'VALIDATION_ERROR', 'message': msg}, status=400)

        return send_json({
            'code': 'SUCCESS',
            'reset_token': reset_token,
        }, status=200)

    @http.route('/api/saami/auth/reset-password', type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False)
    def reset_password(self):
        """
        Public endpoint to set a new password using reset_token (or code).
        """
        preflight = handle_cors(['POST', 'OPTIONS'])
        if preflight:
            return preflight

        data = get_json_body()
        if not data:
            return send_json({'code': 'BAD_REQUEST', 'message': 'JSON payload is required.'}, status=400)

        login = (data.get('login') or data.get('email') or '').strip().lower()
        reset_token = str(data.get('reset_token') or '').strip()
        code = str(data.get('code') or '').strip()
        new_password = data.get('new_password') or ''

        if len(new_password) < 8:
            return send_json({
                'code': 'VALIDATION_ERROR',
                'message': 'New password must be at least 8 characters long.',
            }, status=400)

        if not login or (not reset_token and not code):
            return send_json({
                'code': 'VALIDATION_ERROR',
                'message': 'The code is invalid or has expired.',
            }, status=400)

        ok, res_code, msg = request.env['saami.password.reset'].sudo()._verify_and_reset(
            login, new_password, code=code or None, reset_token=reset_token or None,
        )
        if not ok and res_code == 'MEMBER_SUSPENDED':
            return send_json({'code': 'MEMBER_SUSPENDED', 'message': msg}, status=403)
        if not ok:
            return send_json({'code': 'VALIDATION_ERROR', 'message': msg}, status=400)

        return send_json({'code': 'SUCCESS', 'message': msg}, status=200)

    @http.route('/api/saami/auth/verify-email', type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False)
    def verify_email(self):
        """
        Public endpoint to verify a newly registered user's email with the 6-digit OTP.
        """
        preflight = handle_cors(['POST', 'OPTIONS'])
        if preflight:
            return preflight

        data = get_json_body()
        if not data:
            return send_json({'code': 'BAD_REQUEST', 'message': 'JSON payload is required.'}, status=400)

        login = (data.get('login') or data.get('email') or '').strip().lower()
        code = str(data.get('code') or '').strip()
        if not login or not code:
            return send_json({'code': 'VALIDATION_ERROR', 'message': 'The code is invalid or has expired.'}, status=400)

        ok, res_code, msg = request.env['saami.password.reset'].sudo()._verify_email_otp(login, code)
        if not ok:
            return send_json({'code': 'VALIDATION_ERROR', 'message': msg}, status=400)

        return send_json({'code': 'SUCCESS', 'message': msg}, status=200)

    @http.route('/api/saami/auth/resend-verification', type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False)
    def resend_verification(self):
        """
        Public endpoint to resend the 6-digit email verification code (30s cooldown).
        """
        preflight = handle_cors(['POST', 'OPTIONS'])
        if preflight:
            return preflight

        data = get_json_body()
        if not data:
            return send_json({'code': 'BAD_REQUEST', 'message': 'JSON payload is required.'}, status=400)

        login = (data.get('login') or data.get('email') or '').strip().lower()
        if not login:
            return send_json({'code': 'VALIDATION_ERROR', 'message': 'Email address (login) is required.'}, status=400)

        forwarded_for = (request.httprequest.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
        ip_addr = forwarded_for or request.httprequest.remote_addr

        ok, code, msg = request.env['saami.password.reset'].sudo()._request_email_verification(login, ip_addr=ip_addr)
        if not ok and code == 'RATE_LIMITED':
            return send_json({
                'code': 'RATE_LIMITED',
                'message': msg or 'Too many requests. Please try again later.',
            }, status=429)

        return send_json({
            'code': 'SUCCESS',
            'message': 'If this email is registered and unverified, a verification code has been sent.',
        }, status=200)

    # -------------------------------------------------------------------------
    # PUBLIC AVATAR / PHOTO STREAMING ENDPOINTS (TAAKULO PATTERN)
    # -------------------------------------------------------------------------
    @http.route('/api/saami/user/<int:partner_id>/avatar', type='http', auth='none', methods=['GET', 'OPTIONS'], csrf=False)
    def get_user_avatar(self, partner_id, **kwargs):
        preflight = handle_cors(['GET', 'OPTIONS'])
        if preflight:
            return preflight

        partner = request.env['res.partner'].sudo().search([('id', '=', partner_id)], limit=1)
        if not partner or not partner.image_1920:
            return request.not_found()

        return request.env['ir.binary']._get_image_stream_from(
            partner.sudo(), 'image_1920'
        ).get_response()

    @http.route('/api/saami/member/<int:member_id>/photo', type='http', auth='none', methods=['GET', 'OPTIONS'], csrf=False)
    def get_member_photo(self, member_id, **kwargs):
        preflight = handle_cors(['GET', 'OPTIONS'])
        if preflight:
            return preflight

        member = request.env['saami.member'].sudo().search([('id', '=', member_id)], limit=1)
        if not member:
            return request.not_found()

        if member.photo:
            return request.env['ir.binary']._get_image_stream_from(member.sudo(), 'photo').get_response()
        elif member.partner_id and member.partner_id.image_1920:
            return request.env['ir.binary']._get_image_stream_from(member.partner_id.sudo(), 'image_1920').get_response()

        return request.not_found()

    @http.route('/api/saami/application/<int:app_id>/photo', type='http', auth='none', methods=['GET', 'OPTIONS'], csrf=False)
    def get_application_photo(self, app_id, **kwargs):
        preflight = handle_cors(['GET', 'OPTIONS'])
        if preflight:
            return preflight

        app = request.env['saami.member.application'].sudo().search([('id', '=', app_id)], limit=1)
        if not app:
            return request.not_found()

        if app.photo:
            return request.env['ir.binary']._get_image_stream_from(app.sudo(), 'photo').get_response()
        elif app.partner_id and app.partner_id.image_1920:
            return request.env['ir.binary']._get_image_stream_from(app.partner_id.sudo(), 'image_1920').get_response()

        return request.not_found()

    @http.route('/api/saami/member/<int:member_id>/identity', type='http', auth='none', methods=['GET', 'OPTIONS'], csrf=False)
    def get_member_identity(self, member_id, **kwargs):
        preflight = handle_cors(['GET', 'OPTIONS'])
        if preflight:
            return preflight

        member = request.env['saami.member'].sudo().search([('id', '=', member_id)], limit=1)
        if not member or not member.identity_file:
            return request.not_found()

        return request.env['ir.binary']._get_stream_from(member.sudo(), 'identity_file').get_response()

    @http.route('/api/saami/application/<int:app_id>/identity', type='http', auth='none', methods=['GET', 'OPTIONS'], csrf=False)
    def get_application_identity(self, app_id, **kwargs):
        preflight = handle_cors(['GET', 'OPTIONS'])
        if preflight:
            return preflight

        app = request.env['saami.member.application'].sudo().search([('id', '=', app_id)], limit=1)
        if not app or not app.identity_file:
            return request.not_found()

        return request.env['ir.binary']._get_stream_from(app.sudo(), 'identity_file').get_response()
