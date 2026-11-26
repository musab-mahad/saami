from odoo import api, models

from . import r2_client

EXCLUDED_URL_PREFIXES = ('/web/assets/',)


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    @api.model
    def _is_r2_active(self):
        if self.env.context.get('r2_skip'):
            return False
        cfg = r2_client.get_r2_config(self.env)
        return cfg['enabled'] and r2_client.is_r2_configured(cfg)

    @api.model
    def _is_r2_excluded_values(self, values):
        url = values.get('url') or ''
        return any(url.startswith(prefix) for prefix in EXCLUDED_URL_PREFIXES)

    def _is_r2_excluded_record(self, vals=None):
        self.ensure_one()
        url = (vals or {}).get('url') if vals and 'url' in vals else self.url
        return bool(url and any(url.startswith(prefix) for prefix in EXCLUDED_URL_PREFIXES))

    @api.model
    def _storage(self):
        if self._is_r2_active():
            return 'r2'
        return super()._storage()

    @api.model
    def _get_storage_domain(self):
        storage = self._storage()
        if storage == 'r2':
            # Migrate DB attachments and non-asset local filestore attachments to R2
            return [
                '!', ('url', '=like', '/web/assets/%'),
                '|',
                ('db_datas', '!=', False),
                '&', ('store_fname', '!=', False), ('store_fname', 'not like', 'r2/%'),
            ]
        return super()._get_storage_domain()

    @api.model_create_multi
    def create(self, vals_list):
        if not self._is_r2_active() or not any(self._is_r2_excluded_values(v) for v in vals_list):
            return super().create(vals_list)

        created = self.browse()
        for vals in vals_list:
            target = self.with_context(r2_skip=True) if self._is_r2_excluded_values(vals) else self
            created |= super(IrAttachment, target).create([vals])
        return created

    def write(self, vals):
        if not self or not self._is_r2_active():
            return super().write(vals)

        excluded = self.filtered(lambda rec: rec._is_r2_excluded_record(vals))
        included = self - excluded
        if excluded and included:
            res_ex = super(IrAttachment, excluded.with_context(r2_skip=True)).write(vals)
            res_in = super(IrAttachment, included).write(vals)
            return res_ex and res_in
        if excluded:
            return super(IrAttachment, excluded.with_context(r2_skip=True)).write(vals)
        return super().write(vals)
