# -*- coding: utf-8 -*-
from odoo import models, fields


class SaamiRejectApplicationWizard(models.TransientModel):
    _name = 'saami.reject.application.wizard'
    _description = 'Reject Saami Member Application Wizard'

    application_id = fields.Many2one(
        'saami.member.application',
        string='Application',
        required=True,
        ondelete='cascade',
    )
    reason = fields.Text(string='Rejection Reason', required=True)

    def action_confirm_reject(self):
        self.ensure_one()
        self.application_id._do_reject(self.reason)
        return {'type': 'ir.actions.act_window_close'}
