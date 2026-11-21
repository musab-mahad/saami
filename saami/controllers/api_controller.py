# -*- coding: utf-8 -*-
import logging
from odoo import http, fields, _
from odoo.http import request

from .jwt_utils import send_json, handle_cors, get_json_body, require_jwt

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
    # 0. METADATA: SOMALI REGIONS & DISTRICTS
    # -------------------------------------------------------------------------
    @http.route('/api/saami/locations', type='http', auth='none', methods=['GET', 'OPTIONS'], csrf=False)
    def get_locations(self):
        """
        Public endpoint returning official Somali regions and their districts for frontend selection.
        """
        preflight = handle_cors(['GET', 'OPTIONS'])
        if preflight:
            return preflight

        try:
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
                'regions': regions_data,
            })
        except Exception as e:
            _logger.error("Locations error: %s", str(e))
            return send_json({'code': 'SERVER_ERROR', 'message': str(e)}, status=500)

    # -------------------------------------------------------------------------
    # 1. PUBLIC REGISTRATION
    # -------------------------------------------------------------------------
    @http.route('/api/saami/register', type='http', auth='none', methods=['POST', 'OPTIONS'], csrf=False)
    def register(self):
        """
        Public applicant registration endpoint:
        Creates res.partner, res.users (portal), and saami.member.application.
        Automatically generates the registration fee invoice.
        """
        preflight = handle_cors(['POST', 'OPTIONS'])
        if preflight:
            return preflight

        data = get_json_body()
        if not data:
            return send_json({'code': 'BAD_REQUEST', 'message': 'JSON payload is required.'}, status=400)

        required_fields = ['first_name', 'middle_name', 'last_name', 'mother_name', 'mobile', 'email', 'password', 'date_of_birth', 'gender', 'education_level', 'country_id', 'state_id', 'district_id', 'residence_address', 'kin1_name', 'kin1_mobile', 'kin1_address']
        missing = [f for f in required_fields if not data.get(f)]
        if missing:
            return send_json({'code': 'VALIDATION_ERROR', 'message': f"Missing required fields: {', '.join(missing)}"}, status=400)

        email = data['email'].strip().lower()
        Users = request.env['res.users'].sudo()
        if Users.search([('login', '=', email)], limit=1):
            return send_json({'code': 'EMAIL_EXISTS', 'message': 'An account with this email already exists.'}, status=400)

        try:
            bot_env = get_saami_bot_env()
            company = bot_env.company
            state_id = int(data['state_id'])
            district_id = int(data['district_id'])
            district_rec = bot_env['saami.district'].browse(district_id)
            district_name = district_rec.name if district_rec.exists() else (data.get('district') or '')

            # 1. Create Partner
            full_name = f"{data['first_name']} {data['middle_name']} {data['last_name']}".strip()
            partner = bot_env['res.partner'].create({
                'name': full_name,
                'email': email,
                'phone': data['mobile'],
                'street': data['residence_address'],
                'country_id': int(data['country_id']),
                'state_id': state_id,
                'city': district_name,
                'company_id': company.id,
            })

            # 2. Create Portal User
            portal_group = bot_env.ref('base.group_portal')
            user = bot_env['res.users'].create({
                'name': full_name,
                'login': email,
                'email': email,
                'password': data['password'],
                'partner_id': partner.id,
                'company_id': company.id,
                'company_ids': [(6, 0, [company.id])],
                'groups_id': [(6, 0, [portal_group.id])],
            })

            # 3. Create Application
            app_vals = {
                'partner_id': partner.id,
                'user_id': user.id,
                'first_name': data['first_name'],
                'middle_name': data['middle_name'],
                'last_name': data['last_name'],
                'mother_name': data['mother_name'],
                'mobile': data['mobile'],
                'email': email,
                'date_of_birth': data['date_of_birth'],
                'gender': data['gender'],
                'education_level': data['education_level'],
                'country_id': int(data['country_id']),
                'state_id': state_id,
                'district_id': district_id,
                'district': district_name,
                'residence_address': data['residence_address'],
                'bank_name': data.get('bank_name'),
                'bank_address': data.get('bank_address'),
                'bank_account_no': data.get('bank_account_no'),
                'kin1_name': data['kin1_name'],
                'kin1_address': data['kin1_address'],
                'kin1_mobile': data['kin1_mobile'],
                'kin2_name': data.get('kin2_name'),
                'kin2_address': data.get('kin2_address'),
                'kin2_mobile': data.get('kin2_mobile'),
                'photo': data.get('photo'),
                'identity_file': data.get('identity_file'),
                'state': 'pending_payment',
            }
            application = bot_env['saami.member.application'].create(app_vals)

            # 4. Generate Registration Invoice
            application.action_create_registration_invoice()

            return send_json({
                'code': 'SUCCESS',
                'message': 'Registration submitted successfully. Please proceed with registration fee payment.',
                'application_number': application.name,
                'status': application.state,
                'invoice_id': application.invoice_id.id if application.invoice_id else False,
                'amount_due': application.invoice_id.amount_residual if application.invoice_id else 0.0,
            }, status=201)

        except Exception as e:
            _logger.error("Registration error: %s", str(e), exc_info=True)
            return send_json({'code': 'SERVER_ERROR', 'message': str(e)}, status=500)

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
        phone = data.get('phone') or user.partner_id.phone
        if not phone:
            return send_json({'code': 'VALIDATION_ERROR', 'message': 'Mobile phone number is required for USSD payment.'}, status=400)

        app = request.env['saami.member.application'].sudo().search([('partner_id', '=', user.partner_id.id)], limit=1)
        if not app:
            return send_json({'code': 'NOT_FOUND', 'message': 'No application found for this account.'}, status=404)

        if app.state in ('approved', 'pending_approval'):
            return send_json({'code': 'ALREADY_PAID', 'message': 'Registration fee is already submitted.'}, status=400)

        if not app.invoice_id:
            app.action_create_registration_invoice()

        invoice = app.invoice_id
        provider = request.env['payment.provider'].sudo().search([('code', '=', 'waafipay'), ('state', '!=', 'disabled')], limit=1)
        if not provider:
            return send_json({'code': 'CONFIG_ERROR', 'message': 'WaafiPay provider is not active.'}, status=500)

        # Create payment.transaction
        reference = f"REG-{app.name}-{fields.Datetime.now().strftime('%Y%m%d%H%M%S')}"
        tx = request.env['payment.transaction'].sudo().create({
            'amount': invoice.amount_residual or invoice.amount_total,
            'currency_id': invoice.currency_id.id,
            'provider_id': provider.id,
            'reference': reference,
            'partner_id': user.partner_id.id,
            'saami_application_id': app.id,
            'saami_payment_purpose': 'registration_fee',
            'invoice_ids': [(4, invoice.id)],
            'operation': 'offline',
        })

        res = tx._waafipay_create_ussd_push(phone, description=f"Saami Registration Fee - {app.name}")
        return send_json({
            'code': 'SUCCESS' if res.get('success') else 'PAYMENT_FAILED',
            'result': res,
            'application_status': app.state,
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
                'currency_id': prod_config.currency_id.id if prod_config else member.currency_id.id,
            })

        provider = request.env['payment.provider'].sudo().search([('code', '=', 'waafipay'), ('state', '!=', 'disabled')], limit=1)
        if not provider:
            return send_json({'code': 'CONFIG_ERROR', 'message': 'WaafiPay provider is not active.'}, status=500)

        reference = f"CONTR-{member.name}-{fields.Datetime.now().strftime('%Y%m%d%H%M%S')}"
        tx = request.env['payment.transaction'].sudo().create({
            'amount': amount,
            'currency_id': member.currency_id.id,
            'provider_id': provider.id,
            'reference': reference,
            'partner_id': user.partner_id.id,
            'saami_tracker_id': tracker.id,
            'saami_payment_purpose': 'monthly_contribution',
            'operation': 'offline',
        })

        res = tx._waafipay_create_ussd_push(phone, description=f"Saami Capital Contribution - {member.name}")
        return send_json({
            'code': 'SUCCESS' if res.get('success') else 'PAYMENT_FAILED',
            'result': res,
            'tracker': {
                'month': tracker.month_name,
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
        Tx = request.env['saami.contribution.transaction'].sudo()

        domain = ['|', ('partner_id', '=', user.partner_id.id), ('member_id', '=', member.id if member else False)]
        transactions = Tx.search(domain, order='date desc, id desc')

        tx_list = []
        for t in transactions:
            tx_list.append({
                'id': t.id,
                'reference': t.name,
                'date': str(t.date),
                'type': t.transaction_type,
                'type_label': dict(t._fields['transaction_type'].selection).get(t.transaction_type),
                'amount': t.amount,
                'currency': t.currency_id.symbol or t.currency_id.name,
                'payment_method': t.payment_method,
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
