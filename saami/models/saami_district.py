# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _


class SaamiDistrict(models.Model):
    _name = 'saami.district'
    _description = 'Saami District'
    _order = 'state_id, name'

    name = fields.Char(string='District Name', required=True, index=True)
    state_id = fields.Many2one(
        'res.country.state',
        string='Region',
        required=True,
        domain="[('country_id.code', '=', 'SO')]",
        index=True,
        ondelete='restrict',
    )
    code = fields.Char(string='Code')
    active = fields.Boolean(default=True)

    member_count = fields.Integer(string='Members', compute='_compute_counts')
    application_count = fields.Integer(string='Applications', compute='_compute_counts')

    _sql_constraints = [
        ('district_state_unique', 'unique(name, state_id)', 'A district with this name already exists in this region!'),
    ]

    def _compute_counts(self):
        for rec in self:
            rec.member_count = self.env['saami.member'].search_count([('district_id', '=', rec.id)])
            rec.application_count = self.env['saami.member.application'].search_count([('district_id', '=', rec.id)])
