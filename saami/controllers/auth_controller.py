# -*- coding: utf-8 -*-
import logging
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


class SaamiAuthController(http.Controller):

    @http.route('/api/saami/auth/login', type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False)
    def login(self):
        preflight = handle_cors(['POST', 'OPTIONS'])
        if preflight:
            return preflight

        data = get_json_body()
        if not data:
            return send_json({'code': 'BAD_REQUEST', 'message': 'JSON payload is required.'}, status=400)

        login = (data.get('login') or data.get('email') or '').strip().lower()
        password = data.get('password') or ''

        if not login or not password:
            return send_json({
                'code': 'VALIDATION_ERROR',
                'message': 'Login and password are required.',
            }, status=400)

        # Authenticate against Odoo database
        try:
            uid = request.session.authenticate(request.session.db, login, password)
        except AccessDenied:
            return send_json({
                'code': 'AUTH_FAILED',
                'message': 'Invalid login credentials.',
            }, status=401)
        except Exception as e:
            _logger.error("Authentication error: %s", str(e))
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

        return send_json({
            'code': 'SUCCESS',
            'message': 'Logged in successfully.',
            'token': token,
            'user': {
                'id': user.id,
                'name': user.name,
                'email': user.login,
                'status': status,
                'member_number': member_number,
                'application_number': application_number,
            }
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

        status = 'guest'
        details = {}

        if member:
            status = member.state
            details = {
                'type': 'member',
                'member_number': member.name,
                'full_name': member.full_name,
                'mobile': member.mobile,
                'email': member.email,
                'district': member.district,
                'region': member.state_id.name if member.state_id else False,
                'country': member.country_id.name if member.country_id else False,
                'total_contributions': member.total_contributions,
                'currency': member.currency_id.name,
                'state': member.state,
            }
        elif application:
            status = application.state
            details = {
                'type': 'application',
                'application_number': application.name,
                'full_name': application.full_name,
                'mobile': application.mobile,
                'email': application.email,
                'district': application.district,
                'region': application.state_id.name if application.state_id else False,
                'country': application.country_id.name if application.country_id else False,
                'state': application.state,
                'invoice_id': application.invoice_id.id if application.invoice_id else False,
            }

        return send_json({
            'code': 'SUCCESS',
            'status': status,
            'user': {
                'id': user.id,
                'name': user.name,
                'email': user.login,
            },
            'profile': details,
        }, status=200)
