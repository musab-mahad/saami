from odoo import _, api, fields, models
from odoo.exceptions import UserError

from . import r2_client


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    r2_enabled = fields.Boolean(
        string='Enable Cloudflare R2 Storage',
        config_parameter='r2_storage.enabled',
        help='Store media, images, and document attachments in Cloudflare R2 (JS/CSS web assets stay local).',
    )
    r2_account_id = fields.Char(
        string='Cloudflare Account ID',
        config_parameter='r2_storage.account_id',
        help='Your Cloudflare Account ID used in https://<account_id>.r2.cloudflarestorage.com.',
    )
    r2_access_key_id = fields.Char(
        string='R2 Access Key ID',
        config_parameter='r2_storage.access_key_id',
    )
    r2_secret_access_key = fields.Char(
        string='R2 Secret Access Key',
        config_parameter='r2_storage.secret_access_key',
    )
    r2_bucket_name = fields.Char(
        string='R2 Bucket Name',
        config_parameter='r2_storage.bucket_name',
    )
    r2_key_prefix = fields.Char(
        string='Key Prefix',
        config_parameter='r2_storage.key_prefix',
        help='Optional folder prefix inside the bucket (do not use DB name if you want DB restores to keep working).',
    )
    r2_public_url = fields.Char(
        string='Public / Custom Domain URL',
        config_parameter='r2_storage.public_url',
        help='Optional custom public domain (e.g. https://cdn.example.com). Leave blank to use private presigned URLs.',
    )
    r2_serve_mode = fields.Selection(
        selection=[
            ('proxy', 'Proxy All Requests Through Odoo'),
            ('presigned', 'Presigned / Public URL Redirect'),
        ],
        string='Serving Mode',
        default='proxy',
        config_parameter='r2_storage.serve_mode',
    )
    r2_presigned_expiry = fields.Integer(
        string='Presigned URL Expiry (Seconds)',
        default=300,
        config_parameter='r2_storage.presigned_expiry',
    )
    r2_fallback_local = fields.Boolean(
        string='Fallback to Local Filestore on Read',
        default=True,
        config_parameter='r2_storage.fallback_local',
        help='If an attachment is not found in R2, attempt to read it from the local filestore.',
    )
    r2_allow_delete = fields.Boolean(
        string='Allow R2 Object Deletion (GC)',
        default=True,
        config_parameter='r2_storage.allow_delete',
        help='Uncheck on staging/cloned databases so they cannot delete live production objects in R2.',
    )

    def set_values(self):
        super().set_values()
        if self.r2_enabled:
            cfg = r2_client.get_r2_config(self.env)
            if not r2_client.is_r2_configured(cfg):
                raise UserError(_(
                    'Please fill in Cloudflare Account ID, Access Key ID, Secret Access Key, '
                    'and Bucket Name before enabling Cloudflare R2 Storage.'
                ))

    def _current_r2_cfg(self):
        """Build R2 config dict from current unsaved form values (falling back to saved params)."""
        self.ensure_one()
        saved = r2_client.get_r2_config(self.env)
        return {
            **saved,
            'account_id': (self.r2_account_id or saved['account_id'] or '').strip(),
            'access_key_id': (self.r2_access_key_id or saved['access_key_id'] or '').strip(),
            'secret_access_key': (self.r2_secret_access_key or saved['secret_access_key'] or '').strip(),
            'bucket_name': (self.r2_bucket_name or saved['bucket_name'] or '').strip(),
            'key_prefix': (self.r2_key_prefix or saved['key_prefix'] or '').strip().strip('/'),
            'public_url': (self.r2_public_url or saved['public_url'] or '').strip().rstrip('/'),
        }

    def action_r2_test_connection(self):
        self.ensure_one()
        cfg = self._current_r2_cfg()
        try:
            r2_client.r2_test_connection(cfg)
        except Exception as exc:
            raise UserError(_('Cloudflare R2 connection failed: %s') % str(exc)) from exc

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Cloudflare R2 Connected'),
                'message': _('Successfully verified read, write, and delete access on bucket "%s".') % cfg['bucket_name'],
                'type': 'success',
                'sticky': False,
            },
        }

    def action_r2_migrate_to_r2(self):
        self.ensure_one()
        self.set_values()
        cfg = r2_client.get_r2_config(self.env)
        if not (cfg['enabled'] and r2_client.is_r2_configured(cfg)):
            raise UserError(_('Enable Cloudflare R2 Storage and configure credentials before migrating.'))

        Attachment = self.env['ir.attachment'].sudo()
        domain = [
            ('type', '=', 'binary'),
            '!', ('url', '=like', '/web/assets/%'),
            ('mimetype', 'not in', [
                'text/css',
                'text/scss',
                'text/x-scss',
                'text/less',
                'text/javascript',
                'application/javascript',
                'application/x-javascript',
            ]),
            '|', ('res_field', '=', False), ('res_field', '!=', False),
            '|', ('db_datas', '!=', False),
            '&', ('store_fname', '!=', False), ('store_fname', 'not like', 'r2/%'),
        ]
        attachments = Attachment.search(domain)
        if attachments:
            attachments._migrate()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Migration Complete'),
                'message': _('Migrated %d attachment(s) to Cloudflare R2.') % len(attachments),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_r2_migrate_to_local(self):
        self.ensure_one()
        Attachment = self.env['ir.attachment'].sudo()
        domain = [
            ('type', '=', 'binary'),
            ('store_fname', '=like', 'r2/%'),
            '|', ('res_field', '=', False), ('res_field', '!=', False),
        ]
        attachments = Attachment.search(domain)
        if attachments:
            attachments.with_context(r2_skip=True)._migrate()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Migration Complete'),
                'message': _('Migrated %d attachment(s) back to local filestore.') % len(attachments),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_r2_run_gc_now(self):
        self.ensure_one()
        self.set_values()
        cfg = r2_client.get_r2_config(self.env)
        if not cfg.get('allow_delete'):
            raise UserError(_('Enable "Allow R2 Object Deletion (GC)" first before running R2 cleanup.'))
        if not r2_client.is_r2_configured(cfg):
            raise UserError(_('Configure R2 credentials before running R2 cleanup.'))

        checked, deleted, referenced = self.env['r2.gc.queue'].sudo()._run_gc()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('R2 Cleanup Complete'),
                'message': _(
                    'Checked %d queued key(s): deleted %d from R2, %d still referenced in Odoo.'
                ) % (checked, deleted, referenced),
                'type': 'success',
                'sticky': False,
            },
        }
