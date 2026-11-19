# -*- coding: utf-8 -*-
from odoo import models, fields, api
import secrets


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    saami_jwt_secret = fields.Char(
        string='Saami JWT Secret',
        config_parameter='saami.jwt_secret',
        help="Secret key used to sign and verify JSON Web Tokens for Saami APIs.",
    )
    saami_jwt_expiration_hours = fields.Integer(
        string='JWT Expiration (Hours)',
        default=24,
        config_parameter='saami.jwt_expiration_hours',
        help="Validity duration of issued access tokens in hours.",
    )

    @api.model
    def get_values(self):
        res = super().get_values()
        ICP = self.env['ir.config_parameter'].sudo()
        secret = ICP.get_param('saami.jwt_secret')
        if not secret:
            secret = secrets.token_urlsafe(48)
            ICP.set_param('saami.jwt_secret', secret)
        res.update(
            saami_jwt_secret=secret,
            saami_jwt_expiration_hours=int(ICP.get_param('saami.jwt_expiration_hours', 24)),
        )
        return res
