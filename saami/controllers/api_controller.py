# -*- coding: utf-8 -*-
import logging
from odoo import http, fields, _
from odoo.http import request

from .jwt_utils import send_json, handle_cors, get_json_body, get_request_payload, parse_base64_file, require_jwt
from .auth_controller import _get_api_base_url, _build_registration_summary

_logger = logging.getLogger(__name__)


def get_saami_bot_env():
    """ Initialize and return request environment bound to Saami Bot (or root). """
    sudo_env = request.env(su=True)
    bot = sudo_env.ref('saami.user_saami_bot', raise_if_not_found=False) or sudo_env.ref('base.user_root')
    company = bot.company_id or sudo_env['res.company'].search([], limit=1)
    request.update_env(user=bot.id, su=True)
    request.update_context(allowed_company_ids=[company.id])
    return request.env


class SaamiApiController(http.Controller):

    # -------------------------------------------------------------------------
    # 0. METADATA: COUNTRIES, SOMALI REGIONS & DISTRICTS
    # -------------------------------------------------------------------------
    @http.route('/api/saami/countries', type='http', auth='none', methods=['GET', 'OPTIONS'], csrf=False)
    def get_countries(self):
        """
        Public endpoint returning countries for frontend selection.
        """
        preflight = handle_cors(['GET', 'OPTIONS'])
        if preflight:
            return preflight

        try:
            countries = request.env['res.country'].sudo().search([], order='name asc')
            country_list = [{
                'id': c.id,
                'name': c.name,
                'code': c.code,
                'phone_code': c.phone_code,
            } for c in countries]

            return send_json({
                'code': 'SUCCESS',
                'count': len(country_list),
                'countries': country_list,
            })
        except Exception as e:
            _logger.error("Countries error: %s", str(e))
            return send_json({'code': 'SERVER_ERROR', 'message': str(e)}, status=500)

    @http.route('/api/saami/locations', type='http', auth='none', methods=['GET', 'OPTIONS'], csrf=False)
    def get_locations(self):
        """
        Public endpoint returning official Somali regions and their districts for frontend selection.
        """
        preflight = handle_cors(['GET', 'OPTIONS'])
        if preflight:
            return preflight

        try:
            Country = request.env['res.country'].sudo()
            somalia = Country.search([('code', '=', 'SO')], limit=1)

            State = request.env['res.country.state'].sudo()
            somalia_states = State.search([('country_id.code', '=', 'SO')], order='name asc')

            District = request.env['saami.district'].sudo()
            all_districts = District.search([('active', '=', True)], order='name asc')

            dist_by_state = {}
            for d in all_districts:
                dist_by_state.setdefault(d.state_id.id, []).append({
                    'id': d.id,
                    'name': d.name,
                    'code': d.code or '',
                })

            regions_data = []
            for s in somalia_states:
                regions_data.append({
                    'id': s.id,
                    'name': s.name,
                    'code': s.code,
                    'districts': dist_by_state.get(s.id, []),
                })

            return send_json({
                'code': 'SUCCESS',
                'country': {
                    'id': somalia.id if somalia else False,
                    'name': somalia.name if somalia else 'Somalia',
                    'code': somalia.code if somalia else 'SO',
                    'phone_code': somalia.phone_code if somalia else 252,
                },
                'regions': regions_data,
            })
        except Exception as e:
            _logger.error("Locations error: %s", str(e))
            return send_json({'code': 'SERVER_ERROR', 'message': str(e)}, status=500)

    # -------------------------------------------------------------------------
    # 1. PUBLIC ACCOUNT REGISTRATION (BARE MINIMUM + EMAIL VERIFICATION)
    # -------------------------------------------------------------------------
    @http.route('/api/saami/register', type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False)
    def register(self):
        """
        Bare-minimum public signup: full_name, email, password only.
        Creates partner, unverified portal user, and a draft application.
        Sends a 6-digit email verification code; does NOT return a JWT.
        """
        preflight = handle_cors(['POST', 'OPTIONS'])
        if preflight:
            return preflight

        data = get_json_body()
        if not data:
            return send_json({'code': 'BAD_REQUEST', 'message': 'JSON payload is required.'}, status=400)

        full_name = (data.get('full_name') or data.get('name') or '').strip()
        email = (data.get('email') or data.get('login') or '').strip().lower()
        password = data.get('password') or ''

        missing = []
        if not full_name:
            missing.append('full_name')
        if not email:
            missing.append('email')
        if not password:
            missing.append('password')
        if missing:
            return send_json({'code': 'VALIDATION_ERROR', 'message': f"Missing required fields: {', '.join(missing)}"}, status=400)

        if len(password) < 8:
            return send_json({'code': 'VALIDATION_ERROR', 'message': 'Password must be at least 8 characters long.'}, status=400)

        bot_env = get_saami_bot_env()
        Application = bot_env['saami.member.application']
        Users = bot_env['res.users']

        existing_app = Application.search([('email', '=ilike', email)], limit=1)
        existing_user = Users.search([('login', '=ilike', email)], limit=1)

        if existing_app and existing_app.state not in ('cancelled',):
            return send_json({'code': 'EMAIL_EXISTS', 'message': 'An account or active application with this email already exists.'}, status=400)
        if existing_user:
            return send_json({'code': 'EMAIL_EXISTS', 'message': 'An account with this email already exists.'}, status=400)

        try:
            company = bot_env.company
            portal_group = bot_env.ref('base.group_portal')

            partner = bot_env['res.partner'].create({
                'name': full_name,
                'email': email,
                'company_id': company.id,
            })

            user = bot_env['res.users'].with_context(
                no_reset_password=True,
                mail_create_nosubscribe=True,
                mail_create_nolog=True,
                signup_valid=False,
            ).create({
                'name': full_name,
                'login': email,
                'email': email,
                'password': password,
                'partner_id': partner.id,
                'company_id': company.id,
                'company_ids': [(6, 0, [company.id])],
                'groups_id': [(6, 0, [portal_group.id])],
                'saami_email_verified': False,
            })

            bot_env['saami.member.application'].create({
                'partner_id': partner.id,
                'user_id': user.id,
                'full_name': full_name,
                'email': email,
                'state': 'draft',
            })

            forwarded_for = (request.httprequest.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
            ip_addr = forwarded_for or request.httprequest.remote_addr
            bot_env['saami.password.reset'].sudo()._request_email_verification(
                email, ip_addr=ip_addr, skip_rate_limit=True,
            )

            return send_json({
                'code': 'SUCCESS',
                'message': 'Account created. Please check your email for the 6-digit verification code.',
            }, status=201)

        except Exception as e:
            _logger.error("Registration error: %s", str(e), exc_info=True)
            return send_json({'code': 'SERVER_ERROR', 'message': str(e)}, status=500)

    # -------------------------------------------------------------------------
    # 1B. KYC DRAFT, UNIFIED SAVE (DATA + DOCS), AND SUBMIT
    # -------------------------------------------------------------------------
    def _serialize_kyc(self, app):
        base_url = _get_api_base_url()
        inv = app.invoice_id
        photo_url = f"{base_url}/api/saami/application/{app.id}/photo" if (app.photo or app.partner_id.image_1920) else None
        identity_url = f"{base_url}/api/saami/application/{app.id}/identity" if app.identity_file else None
        return {
            'code': 'SUCCESS',
            'status': app.state,
            'can_edit': app.state in ('draft', 'rejected'),
            'rejection_reason': app.rejection_reason or None,
            'application_id': app.id,
            'application_number': app.name,
            'kyc': {
                'first_name': app.first_name or None,
                'middle_name': app.middle_name or None,
                'last_name': app.last_name or None,
                'full_name': app.full_name or None,
                'mother_name': app.mother_name or None,
                'gender': app.gender or None,
                'date_of_birth': str(app.date_of_birth) if app.date_of_birth else None,
                'mobile': app.mobile or None,
                'email': app.email or None,
                'education_level': app.education_level or None,
                'country_id': app.country_id.id if app.country_id else None,
                'country': app.country_id.name if app.country_id else None,
                'region_id': app.state_id.id if app.state_id else None,
                'region': app.state_id.name if app.state_id else None,
                'district_id': app.district_id.id if app.district_id else None,
                'district': app.district_id.name if app.district_id else (app.district or None),
                'residence_address': app.residence_address or None,
                'next_of_kin': {
                    'name': app.kin_name or None,
                    'mobile': app.kin_mobile or None,
                    'document_type': app.kin_document_type or None,
                    'document_country_id': app.kin_document_country_id.id if app.kin_document_country_id else None,
                    'document_country': app.kin_document_country_id.name if app.kin_document_country_id else None,
                    'document_number': app.kin_document_number or None,
                },
                'id_document_type': app.id_document_type or None,
                'id_document_country_id': app.id_document_country_id.id if app.id_document_country_id else None,
                'id_document_country': app.id_document_country_id.name if app.id_document_country_id else None,
                'id_document_number': app.id_document_number or None,
                'image_url': photo_url,
                'identity_url': identity_url,
            },
            'registration': _build_registration_summary(app),
        }

    def _get_user_application(self, user):
        return request.env['saami.member.application'].sudo().search([
            '|', ('user_id', '=', user.id), ('partner_id', '=', user.partner_id.id)
        ], limit=1)

    @http.route('/api/saami/kyc', type='http', auth='none', methods=['GET', 'PUT', 'POST', 'PATCH', 'OPTIONS'], csrf=False)
    @require_jwt
    def kyc(self, user):
        """
        GET: Return current KYC draft/status and registration fee state.
        PUT/POST/PATCH: Unified draft save for any partial KYC fields and/or photo & identity_file
        (supports both multipart/form-data and JSON).
        """
        app = self._get_user_application(user)
        if not app:
            return send_json({'code': 'NOT_FOUND', 'message': 'No application found for this account.'}, status=404)

        if request.httprequest.method == 'GET':
            return send_json(self._serialize_kyc(app), status=200)

        if app.state not in ('draft', 'rejected'):
            return send_json({
                'code': 'FORBIDDEN',
                'message': f"Application cannot be edited while in '{app.state}' status.",
            }, status=403)

        data = get_request_payload()
        if not data:
            return send_json({'code': 'BAD_REQUEST', 'message': 'JSON or multipart/form-data payload is required.'}, status=400)

        app_vals = {}
        partner_vals = {}

        # Personal text fields
        for field_name in ('first_name', 'middle_name', 'last_name', 'mother_name', 'gender', 'date_of_birth', 'education_level', 'residence_address', 'mobile'):
            if field_name in data:
                val = data.get(field_name)
                if isinstance(val, str):
                    val = val.strip()
                app_vals[field_name] = val or False

        if 'mobile' in app_vals and app_vals['mobile']:
            partner_vals['phone'] = app_vals['mobile']
        if 'residence_address' in app_vals and app_vals['residence_address']:
            partner_vals['street'] = app_vals['residence_address']

        # Location references
        if 'country_id' in data:
            cid = data.get('country_id')
            if cid:
                country = request.env['res.country'].sudo().browse(int(cid))
                if not country.exists():
                    return send_json({'code': 'INVALID_COUNTRY', 'message': 'Country not found.'}, status=400)
                app_vals['country_id'] = country.id
                partner_vals['country_id'] = country.id
            else:
                app_vals['country_id'] = False

        if 'state_id' in data or 'region_id' in data:
            sid = data.get('state_id') if 'state_id' in data else data.get('region_id')
            if sid:
                state_rec = request.env['res.country.state'].sudo().browse(int(sid))
                if not state_rec.exists():
                    return send_json({'code': 'INVALID_REGION', 'message': 'Region not found.'}, status=400)
                app_vals['state_id'] = state_rec.id
                partner_vals['state_id'] = state_rec.id
            else:
                app_vals['state_id'] = False

        if 'district_id' in data:
            did = data.get('district_id')
            if did:
                district_rec = request.env['saami.district'].sudo().browse(int(did))
                if not district_rec.exists():
                    return send_json({'code': 'INVALID_DISTRICT', 'message': 'District not found.'}, status=400)
                app_vals['district_id'] = district_rec.id
                app_vals['district'] = district_rec.name
                partner_vals['city'] = district_rec.name
            else:
                app_vals['district_id'] = False
                app_vals['district'] = False

        # Next of kin (1 person)
        kin_map = {
            'kin_name': ('kin_name', 'kin1_name'),
            'kin_mobile': ('kin_mobile', 'kin1_mobile'),
            'kin_document_type': ('kin_document_type',),
            'kin_document_number': ('kin_document_number',),
        }
        for target_field, keys in kin_map.items():
            for k in keys:
                if k in data:
                    val = data.get(k)
                    app_vals[target_field] = val.strip() if isinstance(val, str) else (val or False)
                    break

        if 'kin_document_country_id' in data:
            k_cid = data.get('kin_document_country_id')
            if k_cid:
                k_country = request.env['res.country'].sudo().browse(int(k_cid))
                if not k_country.exists():
                    return send_json({'code': 'INVALID_COUNTRY', 'message': 'Next of kin document country not found.'}, status=400)
                app_vals['kin_document_country_id'] = k_country.id
            else:
                app_vals['kin_document_country_id'] = False

        # Optional member ID metadata
        if 'id_document_type' in data:
            app_vals['id_document_type'] = (data.get('id_document_type') or '').strip() or False
        if 'id_document_number' in data:
            app_vals['id_document_number'] = (data.get('id_document_number') or '').strip() or False
        if 'id_document_country_id' in data:
            m_cid = data.get('id_document_country_id')
            if m_cid:
                m_country = request.env['res.country'].sudo().browse(int(m_cid))
                if not m_country.exists():
                    return send_json({'code': 'INVALID_COUNTRY', 'message': 'Member ID document country not found.'}, status=400)
                app_vals['id_document_country_id'] = m_country.id
            else:
                app_vals['id_document_country_id'] = False

        # Documents (photo & identity_file)
        if 'photo' in data and data.get('photo'):
            photo_b64 = parse_base64_file(data.get('photo'))
            if not photo_b64:
                return send_json({'code': 'VALIDATION_ERROR', 'message': 'Invalid profile photo format.'}, status=400)
            app_vals['photo'] = photo_b64
            partner_vals['image_1920'] = photo_b64

        if 'identity_file' in data and data.get('identity_file'):
            identity_b64 = parse_base64_file(data.get('identity_file'))
            if not identity_b64:
                return send_json({'code': 'VALIDATION_ERROR', 'message': 'Invalid identity document format.'}, status=400)
            app_vals['identity_file'] = identity_b64
            app_vals['identity_filename'] = (
                data.get('identity_file_filename')
                or data.get('identity_filename')
                or f"identity_{app.email or app.name}.png"
            )

        if app_vals:
            app.write(app_vals)
        if partner_vals and app.partner_id:
            app.partner_id.sudo().write(partner_vals)

        return send_json(self._serialize_kyc(app), status=200)

    @http.route('/api/saami/kyc/submit', type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False)
    @require_jwt
    def submit_kyc(self, user):
        """
        Validate all required KYC fields + paid registration fee, then move application to pending_approval.
        """
        app = self._get_user_application(user)
        if not app:
            return send_json({'code': 'NOT_FOUND', 'message': 'No application found for this account.'}, status=404)

        if app.state not in ('draft', 'rejected'):
            return send_json({
                'code': 'FORBIDDEN',
                'message': f"Application cannot be submitted while in '{app.state}' status.",
            }, status=403)

        missing = app._get_missing_kyc_fields()
        if missing:
            return send_json({
                'code': 'VALIDATION_ERROR',
                'message': f"Missing required KYC fields: {', '.join(missing)}",
                'missing_fields': missing,
            }, status=400)

        inv = app.invoice_id
        if not inv or inv.payment_state not in ('paid', 'in_payment') or inv.amount_residual > 0:
            return send_json({
                'code': 'PAYMENT_REQUIRED',
                'message': 'Please complete the registration fee payment before submitting.',
            }, status=400)

        app.action_submit()
        res = self._serialize_kyc(app)
        res['message'] = 'KYC submitted successfully and is now pending approval.'
        return send_json(res, status=200)

    # -------------------------------------------------------------------------
    # 2. PAY REGISTRATION FEE (VIA WAAFIPAY USSD PUSH)
    # -------------------------------------------------------------------------
    @http.route('/api/saami/pay/registration', type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False)
    @require_jwt
    def pay_registration(self, user):
        """
        Trigger USSD push payment for registration fee.
        """
        data = get_json_body()
        phone = (data.get('phone') or '').strip()
        if not phone:
            return send_json({'code': 'VALIDATION_ERROR', 'message': 'Mobile phone number is required for USSD payment.'}, status=400)

        app = self._get_user_application(user)
        if not app:
            return send_json({'code': 'NOT_FOUND', 'message': 'No application found for this account.'}, status=404)

        if app.state in ('approved', 'pending_approval'):
            return send_json({'code': 'ALREADY_PAID', 'message': 'Application has already been submitted.'}, status=400)

        if app.invoice_id and app.invoice_id.payment_state in ('paid', 'in_payment') and app.invoice_id.amount_residual <= 0:
            return send_json({'code': 'ALREADY_PAID', 'message': 'Registration fee is already paid in full.'}, status=400)

        if not app.invoice_id:
            app.action_create_registration_invoice()

        invoice = app.invoice_id
        provider = request.env['payment.provider'].sudo().search([('code', '=', 'waafipay'), ('state', '!=', 'disabled')], limit=1)
        if not provider:
            return send_json({'code': 'CONFIG_ERROR', 'message': 'WaafiPay provider is not active.'}, status=500)

        payment_method = provider.payment_method_ids.filtered(lambda m: m.code == 'waafipay')[:1] or request.env.ref('payment_waafipay.payment_method_waafipay', raise_if_not_found=False)
        if not payment_method:
            return send_json({'code': 'CONFIG_ERROR', 'message': 'WaafiPay payment method is not configured on provider.'}, status=500)
        if payment_method not in provider.payment_method_ids:
            provider.payment_method_ids = [(4, payment_method.id)]

        # Create payment.transaction (full registration fee + processing fee)
        base_amount = invoice.amount_residual or invoice.amount_total
        fee_pct, fee_amount, total_payable = provider._waafipay_compute_fee(base_amount)
        reference = f"REG-{app.name}-{fields.Datetime.now().strftime('%Y%m%d%H%M%S')}"
        tx = request.env['payment.transaction'].sudo().create({
            'amount': total_payable,
            'currency_id': invoice.currency_id.id,
            'provider_id': provider.id,
            'payment_method_id': payment_method.id,
            'reference': reference,
            'partner_id': user.partner_id.id,
            'saami_application_id': app.id,
            'saami_payment_purpose': 'registration_fee',
            'saami_payer_phone': phone,
            'saami_base_amount': base_amount,
            'saami_processing_fee_percentage': fee_pct,
            'saami_processing_fee_amount': fee_amount,
            'invoice_ids': [(4, invoice.id)],
            'operation': 'offline',
        })

        res = tx._waafipay_create_ussd_push(phone, description=f"Saami Registration Fee - {app.name}")
        return send_json({
            'code': 'SUCCESS' if res.get('success') else 'PAYMENT_FAILED',
            'result': res,
            'payer_phone': phone,
            'base_amount': base_amount,
            'processing_fee_percentage': fee_pct,
            'processing_fee_amount': fee_amount,
            'total_charged': total_payable,
            'created_at': tx.create_date.strftime('%Y-%m-%d %H:%M:%S') if tx.create_date else None,
            'application_status': app.state,
            'registration': _build_registration_summary(app),
        }, status=200 if res.get('success') else 400)

    # -------------------------------------------------------------------------
    # 3. PAY MONTHLY CAPITAL CONTRIBUTION (VIA WAAFIPAY USSD PUSH)
    # -------------------------------------------------------------------------
    @http.route('/api/saami/pay/contribution', type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False)
    @require_jwt
    def pay_contribution(self, user):
        """
        Trigger USSD push payment for monthly capital contribution.
        """
        data = get_json_body()
        amount = float(data.get('amount') or 0.0)
        phone = data.get('phone') or user.partner_id.phone

        if amount <= 0.0:
            return send_json({'code': 'VALIDATION_ERROR', 'message': 'Contribution amount must be greater than zero.'}, status=400)
        if not phone:
            return send_json({'code': 'VALIDATION_ERROR', 'message': 'Mobile phone number is required for USSD payment.'}, status=400)

        member = request.env['saami.member'].sudo().search([('partner_id', '=', user.partner_id.id), ('state', '=', 'active')], limit=1)
        if not member:
            return send_json({'code': 'FORBIDDEN', 'message': 'Only active members can make capital contributions.'}, status=403)

        # Get or create current month tracker
        today_month = fields.Date.today().replace(day=1)
        Tracker = request.env['saami.contribution.tracker'].sudo()
        tracker = Tracker.search([('member_id', '=', member.id), ('date', '=', today_month)], limit=1)
        if not tracker:
            prod_config = request.env['saami.product'].sudo().search([('purpose', '=', 'contribution'), ('is_active', '=', True)], limit=1)
            tracker = Tracker.create({
                'member_id': member.id,
                'date': today_month,
                'expected_amount': prod_config.amount if prod_config else amount,
                'currency_id': member.currency_id.id or (prod_config.currency_id.id if prod_config else request.env.company.currency_id.id),
            })

        provider = request.env['payment.provider'].sudo().search([('code', '=', 'waafipay'), ('state', '!=', 'disabled')], limit=1)
        if not provider:
            return send_json({'code': 'CONFIG_ERROR', 'message': 'WaafiPay provider is not active.'}, status=500)

        payment_method = provider.payment_method_ids.filtered(lambda m: m.code == 'waafipay')[:1] or request.env.ref('payment_waafipay.payment_method_waafipay', raise_if_not_found=False)
        if not payment_method:
            return send_json({'code': 'CONFIG_ERROR', 'message': 'WaafiPay payment method is not configured on provider.'}, status=500)
        if payment_method not in provider.payment_method_ids:
            provider.payment_method_ids = [(4, payment_method.id)]

        reference = f"CONTR-{member.name}-{fields.Datetime.now().strftime('%Y%m%d%H%M%S')}"
        tx = request.env['payment.transaction'].sudo().create({
            'amount': amount,
            'currency_id': member.currency_id.id,
            'provider_id': provider.id,
            'payment_method_id': payment_method.id,
            'reference': reference,
            'partner_id': user.partner_id.id,
            'saami_tracker_id': tracker.id,
            'saami_payment_purpose': 'monthly_contribution',
            'saami_payer_phone': phone,
            'operation': 'offline',
        })

        res = tx._waafipay_create_ussd_push(phone, description=f"Saami Capital Contribution - {member.name}")
        return send_json({
            'code': 'SUCCESS' if res.get('success') else 'PAYMENT_FAILED',
            'result': res,
            'payer_phone': phone,
            'created_at': tx.create_date.strftime('%Y-%m-%d %H:%M:%S') if tx.create_date else None,
            'period': tracker.month_name or (tracker.date.strftime('%B %Y') if tracker.date else None),
            'tracker': {
                'month': tracker.month_name,
                'expected': tracker.expected_amount,
                'actual_paid': tracker.actual_amount,
                'status': tracker.state,
            }
        }, status=200 if res.get('success') else 400)

    # -------------------------------------------------------------------------
    # 4. MEMBER TRANSACTIONS HISTORY
    # -------------------------------------------------------------------------
    @http.route('/api/saami/transactions', type='http', auth='none', methods=['GET', 'OPTIONS'], csrf=False)
    @require_jwt
    def get_transactions(self, user):
        """
        List all contribution and registration transactions for this user.
        """
        member = request.env['saami.member'].sudo().search([('partner_id', '=', user.partner_id.id)], limit=1)
        app = request.env['saami.member.application'].sudo().search([
            '|', ('user_id', '=', user.id), ('partner_id', '=', user.partner_id.id)
        ], limit=1)
        Tx = request.env['saami.contribution.transaction'].sudo()

        conditions = [('partner_id', '=', user.partner_id.id)]
        if member:
            conditions.append(('member_id', '=', member.id))
        if app:
            conditions.append(('application_id', '=', app.id))

        if len(conditions) == 1:
            domain = conditions
        elif len(conditions) == 2:
            domain = ['|'] + conditions
        else:
            domain = ['|', '|'] + conditions

        transactions = Tx.search(domain, order='date desc, id desc')

        tx_list = []
        for t in transactions:
            tx_list.append({
                'id': t.id,
                'reference': t.name,
                'date': str(t.date),
                'created_at': t.create_date.strftime('%Y-%m-%d %H:%M:%S') if t.create_date else None,
                'type': t.transaction_type,
                'type_label': dict(t._fields['transaction_type'].selection).get(t.transaction_type),
                'amount': t.amount,
                'processing_fee_percentage': t.processing_fee_percentage or 0.0,
                'processing_fee_amount': t.processing_fee_amount or 0.0,
                'total_charged': t.total_charged or t.amount,
                'currency': t.currency_id.symbol or t.currency_id.name,
                'payment_method': t.payment_method,
                'payer_phone': t.payer_phone or None,
                'period': (
                    t.tracker_id.month_name or t.tracker_id.date.strftime('%B %Y')
                    if t.transaction_type == 'monthly_contribution' and t.tracker_id and (t.tracker_id.month_name or t.tracker_id.date)
                    else None
                ),
                'external_reference': t.external_reference,
                'status': t.state,
            })

        return send_json({
            'code': 'SUCCESS',
            'count': len(tx_list),
            'transactions': tx_list,
        }, status=200)

    # -------------------------------------------------------------------------
    # 5. MEMBER CONTRIBUTIONS TRACKER HISTORY
    # -------------------------------------------------------------------------
    @http.route('/api/saami/contributions', type='http', auth='none', methods=['GET', 'OPTIONS'], csrf=False)
    @require_jwt
    def get_contributions(self, user):
        """
        List monthly contribution periods and balances for the active member.
        """
        member = request.env['saami.member'].sudo().search([('partner_id', '=', user.partner_id.id)], limit=1)
        if not member:
            return send_json({'code': 'NOT_FOUND', 'message': 'No member profile found for this account.'}, status=404)

        trackers = request.env['saami.contribution.tracker'].sudo().search([('member_id', '=', member.id)], order='date desc')
        tracker_list = []
        for trk in trackers:
            tracker_list.append({
                'id': trk.id,
                'month': trk.month_name,
                'date': str(trk.date),
                'expected': trk.expected_amount,
                'actual_paid': trk.actual_amount,
                'status': trk.state,
                'currency': trk.currency_id.symbol or trk.currency_id.name,
            })

        return send_json({
            'code': 'SUCCESS',
            'member_number': member.name,
            'total_contributions': member.total_contributions,
            'currency': member.currency_id.symbol or member.currency_id.name,
            'trackers': tracker_list,
        }, status=200)
