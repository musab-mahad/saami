# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.addons.web.controllers.utils import ensure_db
from datetime import datetime
from dateutil.relativedelta import relativedelta


class SaamiDashboardController(http.Controller):

    @http.route("/saami/get_dashboard_metrics", type="json", auth="user")
    def get_dashboard_metrics(self, **kwargs):
        ensure_db()
        env = request.env

        start_date_str = kwargs.get("start_date")
        end_date_str = kwargs.get("end_date")

        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date() if start_date_str else (datetime.now().date() - relativedelta(months=6))
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date() if end_date_str else datetime.now().date()
        except ValueError:
            start_date = datetime.now().date() - relativedelta(months=6)
            end_date = datetime.now().date()

        date_domain = [("date", ">=", start_date), ("date", "<=", end_date)]

        Member = env["saami.member"]
        Application = env["saami.member.application"]
        Tracker = env["saami.contribution.tracker"]
        Transaction = env["saami.contribution.transaction"]

        # Card 1: Active Members
        total_active_members = Member.search_count([("state", "=", "active")])

        # Card 2: Pending Applications (all uncompleted/active applications)
        pending_applications = Application.search_count([("state", "not in", ("approved", "rejected", "cancelled"))])

        # Card 3: Total Capital Contributed (all-time active members)
        total_contributions = sum(Member.search([("state", "=", "active")]).mapped("total_contributions"))

        # Card 4: Contributions Collected in Selected Period
        period_txs = Transaction.search(date_domain + [("state", "=", "paid"), ("transaction_type", "=", "monthly_contribution")])
        period_contributions = sum(period_txs.mapped("amount"))

        # Card 5: Registration Fees Collected in Selected Period
        period_reg_txs = Transaction.search(date_domain + [("state", "=", "paid"), ("transaction_type", "=", "registration_fee")])
        period_registration_fees = sum(period_reg_txs.mapped("amount"))

        currency = env.company.currency_id.symbol or "$"

        return {
            "total_active_members": total_active_members,
            "pending_applications": pending_applications,
            "total_contributions": total_contributions,
            "period_contributions": period_contributions,
            "period_registration_fees": period_registration_fees,
            "currency": currency,
        }
