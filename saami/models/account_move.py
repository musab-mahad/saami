# -*- coding: utf-8 -*-
from odoo import models, api, _


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_post(self):
        res = super(AccountMove, self).action_post()
        Application = self.env['saami.member.application'].sudo()
        for move in self:
            apps = Application.search([
                ('invoice_id', '=', move.id),
                ('state', '=', 'draft')
            ])
            for app in apps:
                if move.payment_state in ('paid', 'in_payment'):
                    app.state = 'pending_approval'
                else:
                    app.state = 'pending_payment'
        return res

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
