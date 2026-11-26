import logging

from odoo import api, fields, models

from . import r2_client

_logger = logging.getLogger(__name__)


class R2GcQueue(models.Model):
    _name = 'r2.gc.queue'
    _description = 'Cloudflare R2 Garbage Collection Queue'

    store_fname = fields.Char(string='Stored Filename', required=True, index=True)

    @api.model
    def enqueue(self, fname):
        if not fname:
            return
        self.sudo().create({'store_fname': fname})

    @api.model
    def _cron_gc_r2_objects(self, batch_size=200):
        cfg = r2_client.get_r2_config(self.env)
        if not cfg.get('allow_delete') or not r2_client.is_r2_configured(cfg):
            return 0

        queued = self.sudo().search([], limit=batch_size)
        if not queued:
            return 0

        fnames = list({rec.store_fname for rec in queued if rec.store_fname})
        whitelist = set()
        if fnames:
            for chunk in self.env.cr.split_for_in_conditions(fnames):
                self.env.cr.execute(
                    "SELECT store_fname FROM ir_attachment WHERE store_fname IN %s",
                    [chunk],
                )
                whitelist.update(row[0] for row in self.env.cr.fetchall())

        deleted_count = 0
        for fname in fnames:
            if fname in whitelist:
                continue
            try:
                object_key = r2_client.extract_object_key(fname)
                r2_client.r2_delete_object(cfg, object_key)
                deleted_count += 1
            except Exception:
                _logger.warning("Failed to delete R2 object %s during GC", fname, exc_info=True)
                # Keep failed items in queue for retry
                queued = queued.filtered(lambda r, fn=fname: r.store_fname != fn)

        queued.unlink()
        _logger.info("R2 GC processed %d unique keys, deleted %d objects", len(fnames), deleted_count)
        return deleted_count
