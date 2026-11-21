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
                    'application_id': app.id,
                    'partner_id': app.partner_id.id if app.partner_id else False,
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

                if app.invoice_id and app.invoice_id.payment_state in ('paid', 'in_payment') and app.invoice_id.amount_residual <= 0:
                    app.write({'state': 'pending_approval'})
                    if hasattr(app, 'with_delay'):
                        app.sudo().with_delay()._send_payment_received_email()
                    else:
                        app.sudo()._send_payment_received_email()
                elif app.invoice_id and app.invoice_id.amount_residual > 0:
                    if hasattr(app, 'with_delay'):
                        app.sudo().with_delay()._send_partial_payment_received_email()
                    else:
                        app.sudo()._send_partial_payment_received_email()

            # Case 2: Monthly Capital Contribution
            elif tx.saami_tracker_id:
                tracker = tx.saami_tracker_id
                member = tracker.member_id
                _logger.info("Fulfilling Saami monthly contribution for member %s (%s)", member.name, tracker.month_name)

                # 1. Look for existing unpaid/partial invoice on this tracker
                open_invoice = tracker.invoice_ids.filtered(
                    lambda inv: inv.state == 'posted' and inv.payment_state in ('not_paid', 'partial')
                )[:1]

                invoice = open_invoice
                if not invoice:
                    contrib_prod = self.env['saami.product'].sudo().search([
                        ('purpose', '=', 'contribution'),
                        ('is_active', '=', True)
                    ], limit=1)
                    try:
                        invoice_vals = {
                            'move_type': 'out_invoice',
                            'partner_id': member.partner_id.id,
                            'invoice_date': fields.Date.context_today(tx),
                            'date': fields.Date.context_today(tx),
                            'ref': f"Contribution - {member.name} ({tracker.month_name}) - {tx.reference}",
                            'invoice_line_ids': [(0, 0, {
                                'product_id': contrib_prod.product_id.id if contrib_prod and contrib_prod.product_id else False,
                                'name': contrib_prod.description or f"{member.name} Monthly Capital Contribution - {tracker.month_name}",
                                'quantity': 1.0,
                                'price_unit': tx.amount,
                            })],
                        }
                        invoice = self.env['account.move'].sudo().create(invoice_vals)
                        invoice.action_post()
                        tx.invoice_ids = [(4, invoice.id)]
                        tracker.sudo().write({'invoice_ids': [(4, invoice.id)]})
                    except Exception as e:
                        _logger.error("Could not create/post invoice for contribution: %s", e)

                # 2. Create paid contribution transaction first to link with invoice
                tx_record = self.env['saami.contribution.transaction'].sudo().create({
                    'member_id': member.id,
                    'tracker_id': tracker.id,
                    'transaction_type': 'monthly_contribution',
                    'date': fields.Date.context_today(tx),
                    'amount': tx.amount,
                    'currency_id': tx.currency_id.id,
                    'payment_method': tx.provider_code or 'online',
                    'external_reference': tx.reference,
                    'invoice_id': invoice.id if invoice else False,
                    'state': 'paid',
                })

                # 3. Register payment on the invoice (with context to avoid duplicate tx creation)
                if invoice and invoice.payment_state in ('not_paid', 'partial'):
                    try:
                        payment_register = self.env['account.payment.register'].sudo().with_context(
                            active_model='account.move',
                            active_ids=invoice.ids,
                            skip_saami_sync=True,
                        ).create({
                            'amount': tx.amount,
                            'payment_date': fields.Date.context_today(tx),
                        })
                        payment_register._create_payments()
                    except Exception as e:
                        _logger.warning("Could not auto-register payment for contribution invoice %s: %s", invoice.name, e)

                # Recompute tracker
                tracker._compute_actual_amount()
                tracker._compute_state()

                # Send contribution receipt email (async via queue_job)
                if hasattr(tx_record, 'with_delay'):
                    tx_record.with_delay()._send_contribution_paid_email()
                else:
                    tx_record._send_contribution_paid_email()
