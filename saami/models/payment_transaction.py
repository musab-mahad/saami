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
    saami_fulfilled = fields.Boolean(
        string='Saami Fulfilled',
        default=False,
        copy=False,
    )
    saami_payer_phone = fields.Char(
        string='Saami Payer Phone',
        copy=False,
    )

    def _set_done(self, **kwargs):
        """
        Hook into payment.transaction success:
        1. If registration fee -> advance application to pending_approval and reconcile invoice.
        2. If monthly contribution -> record saami.contribution.transaction and update tracker.
        """
        _logger.info(
            "Saami _set_done triggered for tx %s (purpose=%s, amount=%s, provider=%s)",
            self.mapped('reference'),
            self.mapped('saami_payment_purpose'),
            self.mapped('amount'),
            self.mapped('provider_code'),
        )
        res = super()._set_done(**kwargs)
        self._process_saami_fulfillment()
        return res

    def _register_saami_invoice_payment(self, invoice, skip_saami_sync=False):
        """Register an invoice payment using the transaction's provider journal and method line."""
        self.ensure_one()
        if not invoice or invoice.payment_state not in ('not_paid', 'partial'):
            _logger.info(
                "Skipping payment registration for invoice %s (state=%s, payment_state=%s, residual=%s)",
                invoice.name if invoice else None,
                invoice.state if invoice else None,
                invoice.payment_state if invoice else None,
                invoice.amount_residual if invoice else None,
            )
            return self.env['account.payment']

        ctx = {
            'active_model': 'account.move',
            'active_ids': invoice.ids,
        }
        if skip_saami_sync:
            ctx['skip_saami_sync'] = True

        register_vals = {
            'amount': self.amount,
            'payment_date': fields.Date.context_today(self),
        }
        journal = self.provider_id.journal_id
        if journal:
            register_vals['journal_id'] = journal.id
            method_line = journal.inbound_payment_method_line_ids.filtered(
                lambda l: l.payment_provider_id == self.provider_id or l.code == self.provider_code
            )[:1]
            if method_line:
                register_vals['payment_method_line_id'] = method_line.id

        _logger.info(
            "Registering payment for invoice %s (tx=%s, journal=%s, method_line=%s, amount=%s)",
            invoice.name,
            self.reference,
            journal.name if journal else 'default',
            register_vals.get('payment_method_line_id', 'default'),
            self.amount,
        )
        payment_register = self.env['account.payment.register'].sudo().with_context(**ctx).create(register_vals)
        payments = payment_register._create_payments()
        invoice.invalidate_recordset(['payment_state', 'amount_residual'])
        _logger.info(
            "Payment registered for invoice %s: payments=%s, payment_state=%s, amount_residual=%s",
            invoice.name,
            payments.mapped('name'),
            invoice.payment_state,
            invoice.amount_residual,
        )
        return payments

    def _process_saami_fulfillment(self):
        for tx in self:
            if tx.saami_fulfilled:
                _logger.info("Skipping Saami fulfillment for tx %s: already fulfilled.", tx.reference)
                continue

            # Case 1: Registration Fee Payment
            if tx.saami_application_id:
                app = tx.saami_application_id
                _logger.info("Fulfilling Saami registration payment for application %s (tx=%s)", app.name, tx.reference)
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
                    'payer_phone': tx.saami_payer_phone or (app.mobile if app else False),
                    'external_reference': tx.reference,
                    'invoice_id': app.invoice_id.id if app.invoice_id else False,
                    'state': 'paid',
                })
                # Auto-register payment to mark the registration invoice as paid/reconciled
                if app.invoice_id:
                    try:
                        tx._register_saami_invoice_payment(app.invoice_id)
                    except Exception as e:
                        _logger.warning("Could not auto-register payment for registration invoice %s: %s", app.invoice_id.name, e, exc_info=True)

                if app.invoice_id and app.invoice_id.payment_state in ('paid', 'in_payment') and app.invoice_id.amount_residual <= 0:
                    app.write({'state': 'pending_approval'})
                    _logger.info("Application %s transitioned to pending_approval (invoice %s state=%s, residual=%s)",
                                 app.name, app.invoice_id.name, app.invoice_id.payment_state, app.invoice_id.amount_residual)
                    if hasattr(app, 'with_delay'):
                        app.sudo().with_delay()._send_payment_received_email()
                    else:
                        app.sudo()._send_payment_received_email()
                elif app.invoice_id and app.invoice_id.amount_residual > 0:
                    _logger.warning(
                        "Application %s remains %s after payment (invoice %s payment_state=%s, amount_residual=%s)",
                        app.name, app.state, app.invoice_id.name, app.invoice_id.payment_state, app.invoice_id.amount_residual,
                    )
                    if hasattr(app, 'with_delay'):
                        app.sudo().with_delay()._send_partial_payment_received_email()
                    else:
                        app.sudo()._send_partial_payment_received_email()
                tx.saami_fulfilled = True

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
                    'payer_phone': tx.saami_payer_phone or (member.mobile if member else False),
                    'external_reference': tx.reference,
                    'invoice_id': invoice.id if invoice else False,
                    'state': 'paid',
                })

                # 3. Register payment on the invoice (with context to avoid duplicate tx creation)
                if invoice:
                    try:
                        tx._register_saami_invoice_payment(invoice, skip_saami_sync=True)
                    except Exception as e:
                        _logger.warning("Could not auto-register payment for contribution invoice %s: %s", invoice.name, e, exc_info=True)

                # Recompute tracker
                tracker._compute_actual_amount()
                tracker._compute_state()
                tx.saami_fulfilled = True

                # Send contribution receipt email (async via queue_job)
                if hasattr(tx_record, 'with_delay'):
                    tx_record.with_delay()._send_contribution_paid_email()
                else:
                    tx_record._send_contribution_paid_email()
