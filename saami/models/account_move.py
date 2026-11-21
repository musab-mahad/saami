# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _compute_payment_state(self):
        super()._compute_payment_state()
        self._sync_saami_invoice_payments()

    def _sync_saami_invoice_payments(self):
        """
        When an invoice linked to a contribution tracker is paid directly in Accounting,
        automatically generate the saami.contribution.transaction and recompute the tracker.
        """
        Transaction = self.env['saami.contribution.transaction'].sudo()
        Tracker = self.env['saami.contribution.tracker'].sudo()

        for move in self:
            if move.state == 'posted' and move.payment_state in ('paid', 'in_payment'):
                trackers = Tracker.search([('invoice_ids', 'in', move.id)])
                for trk in trackers:
                    existing_tx = Transaction.search([('invoice_id', '=', move.id), ('state', '=', 'paid')], limit=1)
                    if not existing_tx:
                        paid_amount = move.amount_total - move.amount_residual
                        if paid_amount > 0:
                            Transaction.create({
                                'member_id': trk.member_id.id,
                                'partner_id': trk.member_id.partner_id.id,
                                'tracker_id': trk.id,
                                'transaction_type': 'monthly_contribution',
                                'date': move.invoice_date or fields.Date.today(),
                                'amount': paid_amount,
                                'currency_id': move.currency_id.id,
                                'payment_method': 'account_payment',
                                'external_reference': move.name,
                                'invoice_id': move.id,
                                'state': 'paid',
                            })
                            trk._compute_actual_amount()
                            trk._compute_state()

    def button_draft(self):
        res = super(AccountMove, self).button_draft()
        self._reverse_saami_associations()
        return res

    def button_cancel(self):
        res = super(AccountMove, self).button_cancel()
        self._reverse_saami_associations()
        return res

    def _reverse_saami_associations(self):
        """
        Reverses or cleans up Saami contribution transactions and rolls back
        unapproved member applications whenever an invoice is reset to draft or cancelled.
        """
        Transaction = self.env['saami.contribution.transaction'].sudo()
        Application = self.env['saami.member.application'].sudo()

        for move in self:
            # 1. Clean up or cancel monthly contribution transactions
            txs = Transaction.search([('invoice_id', '=', move.id)])
            trackers_to_update = txs.mapped('tracker_id')
            if txs:
                txs.write({'state': 'cancelled'})
                for tracker in trackers_to_update:
                    tracker._compute_actual_amount()
                    tracker._compute_state()

            # 2. Roll back unapproved member applications if registration invoice is reset/cancelled
            apps = Application.search([
                ('invoice_id', '=', move.id),
                ('state', 'in', ('pending_payment', 'pending_approval'))
            ])
            if apps:
                apps.write({'state': 'draft'})
