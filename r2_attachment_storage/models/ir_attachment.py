import logging

from odoo import api, fields, models
from odoo.http import Stream, request

from . import r2_client

_logger = logging.getLogger(__name__)
EXCLUDED_URL_PREFIXES = ('/web/assets/',)
EXCLUDED_MIMETYPES = (
    'text/css',
    'text/scss',
    'text/x-scss',
    'text/less',
    'text/javascript',
    'application/javascript',
    'application/x-javascript',
)
DEFAULT_R2_URL_EXPIRY = 86400  # 24 hours


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    r2_direct_url = fields.Char(
        string='Cloudflare R2 URL',
        compute='_compute_r2_direct_url',
    )

    @api.depends('store_fname', 'name', 'mimetype')
    def _compute_r2_direct_url(self):
        for attach in self:
            attach.r2_direct_url = attach.get_r2_direct_url() or False

    def get_r2_direct_url(self, expires_in=DEFAULT_R2_URL_EXPIRY, filename=None, as_attachment=False):
        """Return a signed Cloudflare R2 URL for this attachment if stored in R2, else None."""
        self.ensure_one()
        if not r2_client.is_r2_fname(self.store_fname):
            return None
        cfg = r2_client.get_r2_config(self.env)
        if not r2_client.is_r2_configured(cfg):
            return None
        object_key = r2_client.extract_object_key(self.store_fname)
        return r2_client.r2_generate_presigned_url(
            cfg,
            object_key,
            filename=filename or self.name,
            mimetype=self.mimetype,
            as_attachment=as_attachment,
            expires_in=expires_in,
        )

    @api.model
    def get_field_r2_url(self, record, field_name, expires_in=DEFAULT_R2_URL_EXPIRY, filename=None, as_attachment=False):
        """Return a signed Cloudflare R2 URL for a Binary/Image field's attachment without reading bytes."""
        if not record or not record.id:
            return None
        attachment = self.sudo().search([
            ('res_model', '=', record._name),
            ('res_id', '=', record.id),
            ('res_field', '=', field_name),
        ], limit=1)
        if not attachment:
            return None
        return attachment.get_r2_direct_url(
            expires_in=expires_in,
            filename=filename,
            as_attachment=as_attachment,
        )

    @api.model
    def _is_r2_active(self):
        if self.env.context.get('r2_skip'):
            return False
        cfg = r2_client.get_r2_config(self.env)
        return cfg['enabled'] and r2_client.is_r2_configured(cfg)

    @api.model
    def _is_r2_excluded_values(self, values):
        url = values.get('url') or ''
        mimetype = (values.get('mimetype') or '').split(';')[0].strip().lower()
        return any(url.startswith(prefix) for prefix in EXCLUDED_URL_PREFIXES) or mimetype in EXCLUDED_MIMETYPES

    def _is_r2_excluded_record(self, vals=None):
        self.ensure_one()
        url = (vals or {}).get('url') if vals and 'url' in vals else self.url
        mimetype = ((vals or {}).get('mimetype') if vals and 'mimetype' in vals else self.mimetype) or ''
        mimetype = mimetype.split(';')[0].strip().lower()
        return bool(
            (url and any(url.startswith(prefix) for prefix in EXCLUDED_URL_PREFIXES))
            or mimetype in EXCLUDED_MIMETYPES
        )

    @api.model
    def _storage(self):
        if self._is_r2_active():
            return 'r2'
        return super()._storage()

    @api.model
    def _get_storage_domain(self):
        storage = self._storage()
        if storage == 'r2':
            return [
                '!', ('url', '=like', '/web/assets/%'),
                ('mimetype', 'not in', list(EXCLUDED_MIMETYPES)),
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

    def _get_datas_related_values(self, data, mimetype):
        if self._storage() == 'r2' and mimetype:
            return super(IrAttachment, self.with_context(r2_mimetype=mimetype))._get_datas_related_values(data, mimetype)
        return super()._get_datas_related_values(data, mimetype)

    @api.model
    def _file_write(self, bin_value, checksum):
        if self._storage() != 'r2':
            return super()._file_write(bin_value, checksum)

        cfg = r2_client.get_r2_config(self.env)
        fname = r2_client.build_store_fname(checksum, cfg['key_prefix'])
        object_key = r2_client.extract_object_key(fname)
        if not r2_client.r2_object_exists(cfg, object_key):
            r2_client.r2_put_object(
                cfg,
                object_key,
                bin_value,
                content_type=self.env.context.get('r2_mimetype'),
            )
        return fname

    @api.model
    def _file_read(self, fname):
        if not r2_client.is_r2_fname(fname):
            return super()._file_read(fname)

        cfg = r2_client.get_r2_config(self.env)
        object_key = r2_client.extract_object_key(fname)
        if r2_client.is_r2_configured(cfg):
            try:
                data = r2_client.r2_get_object(cfg, object_key)
                if data is not None:
                    return data
            except Exception:
                _logger.warning("Failed reading R2 object %s", object_key, exc_info=True)

        if cfg.get('fallback_local'):
            parts = object_key.rsplit('/', 2)
            if len(parts) >= 2:
                local_fname = '/'.join(parts[-2:])
                local_data = super()._file_read(local_fname)
                if local_data:
                    return local_data
        return b''

    @api.model
    def _is_xhr_or_non_get_request(self):
        if not request or not getattr(request, 'httprequest', None):
            return False
        http_req = request.httprequest
        if http_req.method != 'GET':
            return True
        if http_req.headers.get('Sec-Fetch-Mode') == 'cors':
            return True
        if http_req.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return True
        return False

    def _to_http_stream(self):
        self.ensure_one()
        if not r2_client.is_r2_fname(self.store_fname):
            return super()._to_http_stream()

        # Proxy XHR/POST backend downloads and resized images through Odoo to avoid CORS;
        # redirect direct GET requests straight to Cloudflare R2.
        force_proxy = bool(self.env.context.get('r2_force_proxy')) or self._is_xhr_or_non_get_request()
        if not force_proxy:
            as_attachment = bool(
                request and str(request.params.get('download', '')).lower() in ('1', 'true')
            )
            direct_url = self.get_r2_direct_url(as_attachment=as_attachment)
            if direct_url:
                return Stream(
                    type='url',
                    url=direct_url,
                    mimetype=self.mimetype,
                    download_name=self.name,
                    etag=self.checksum,
                    public=self.public,
                    max_age=max(DEFAULT_R2_URL_EXPIRY - 60, 0),
                )

        data = self.raw or b''
        return Stream(
            type='data',
            data=data,
            size=len(data),
            mimetype=self.mimetype,
            download_name=self.name,
            etag=self.checksum,
            last_modified=self.write_date,
            public=self.public,
        )

    @api.autovacuum
    def _gc_file_store(self):
        return super(IrAttachment, self.with_context(r2_skip=True))._gc_file_store()

    @api.model
    def _file_delete(self, fname):
        if not r2_client.is_r2_fname(fname):
            return super()._file_delete(fname)

        cfg = r2_client.get_r2_config(self.env)
        if cfg.get('allow_delete'):
            self.env['r2.gc.queue'].enqueue(fname)
