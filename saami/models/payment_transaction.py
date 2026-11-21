# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    saami_application_id = fields.Many2one(
        'saami.member.application',
        string='Saami Member Application',
        index=True,
    )
    saami_tracker_id = fields.Many2one(
        'saami.contribution.tracker',
        string='Saami Contribution Tracker',
        index=True,
    )
    saami_payment_purpose = fields.Selection([
        ('registration_fee', 'Registration Fee'),
        ('monthly_contribution', 'Monthly Capital Contribution'),
    ], string='Saami Purpose')

    def _set_done(self, **kwargs):
        """
        Hook into payment.transaction success:
        1. If registration fee -> advance application to pending_approval and reconcile invoice.
        2. If monthly contribution -> record saami.contribution.transaction and update tracker.
        """
        res = super()._set_done(**kwargs)
        self._process_saami_fulfillment()
        return res

    def _process_saami_fulfillment(self):
        for tx in self:
            # Case 1: Registration Fee Payment
            if tx.saami_application_id:
                app = tx.saami_application_id
                _logger.info("Fulfilling Saami registration payment for application %s", app.name)
                # Create a transaction record for auditing/receipt
                member = app.member_id or False
                self.env['saami.contribution.transaction'].sudo().create({
                    'member_id': member.id if member else False,
                    'transaction_type': 'registration_fee',
                    'date': fields.Date.context_today(tx),
                    'amount': tx.amount,
                    'currency_id': tx.currency_id.id,
                    'payment_method': tx.provider_code or 'online',
                    'external_reference': tx.reference,
                    'invoice_id': app.invoice_id.id if app.invoice_id else False,
                    'state': 'paid',
                })
                # Auto-register payment to mark the registration invoice as paid/reconciled
                if app.invoice_id and app.invoice_id.payment_state in ('not_paid', 'partial'):
                    try:
                        payment_register = self.env['account.payment.register'].sudo().with_context(
                            active_model='account.move',
                            active_ids=app.invoice_id.ids,
                        ).create({
                            'amount': tx.amount,
                            'payment_date': fields.Date.context_today(tx),
                        })
                        payment_register._create_payments()
                    except Exception as e:
                        _logger.warning("Could not auto-register payment for registration invoice %s: %s", app.invoice_id.name, e)

                app.write({'state': 'pending_approval'})

            # Case 2: Monthly Capital Contribution
            elif tx.saami_tracker_id:
                tracker = tx.saami_tracker_id
                member = tracker.member_id
                _logger.info("Fulfilling Saami monthly contribution for member %s (%s)", member.name, tracker.month_name)

                # Create paid contribution transaction
                tx_record = self.env['saami.contribution.transaction'].sudo().create({
                    'member_id': member.id,
                    'tracker_id': tracker.id,
                    'transaction_type': 'monthly_contribution',
                    'date': fields.Date.context_today(tx),
                    'amount': tx.amount,
                    'currency_id': tx.currency_id.id,
                    'payment_method': tx.provider_code or 'online',
                    'external_reference': tx.reference,
                    'state': 'paid',
                })

                # Recompute tracker
                tracker._compute_actual_amount()
                tracker._compute_state()
