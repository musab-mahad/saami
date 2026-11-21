# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class ResCountryState(models.Model):
    _inherit = 'res.country.state'

    district_ids = fields.One2many(
        'saami.district',
        'state_id',
        string='Districts',
    )
    district_count = fields.Integer(string='Districts', compute='_compute_saami_counts')
    member_count = fields.Integer(string='Members', compute='_compute_saami_counts')
    application_count = fields.Integer(string='Applications', compute='_compute_saami_counts')

    def _compute_saami_counts(self):
        for rec in self:
            rec.district_count = len(rec.district_ids)
            rec.member_count = self.env['saami.member'].search_count([('state_id', '=', rec.id)])
            rec.application_count = self.env['saami.member.application'].search_count([('state_id', '=', rec.id)])

    def action_view_members(self):
        self.ensure_one()
        return {
            'name': _('Members - %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'saami.member',
            'view_mode': 'list,form',
            'domain': [('state_id', '=', self.id)],
            'context': {'default_state_id': self.id, 'default_country_id': self.country_id.id},
        }

    def action_view_applications(self):
        self.ensure_one()
        return {
            'name': _('Applications - %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'saami.member.application',
            'view_mode': 'list,form',
            'domain': [('state_id', '=', self.id)],
            'context': {'default_state_id': self.id, 'default_country_id': self.country_id.id},
        }

    def action_view_districts(self):
        self.ensure_one()
        return {
            'name': _('Districts - %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'saami.district',
            'view_mode': 'list,form',
            'domain': [('state_id', '=', self.id)],
            'context': {'default_state_id': self.id},
        }
