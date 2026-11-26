from odoo import models
from odoo.tools.image import image_guess_size_from_field_name


class IrBinary(models.AbstractModel):
    _inherit = 'ir.binary'

    def _get_image_stream_from(
        self, record, field_name='raw', filename=None, filename_field='name',
        mimetype=None, default_mimetype='image/png', placeholder=None,
        width=0, height=0, crop=False, quality=0,
    ):
        guessed_w, guessed_h = image_guess_size_from_field_name(field_name)
        needs_resize = bool(width or height or crop or guessed_w or guessed_h)
        target = self.with_context(r2_force_proxy=True) if needs_resize else self
        return super(IrBinary, target)._get_image_stream_from(
            record,
            field_name=field_name,
            filename=filename,
            filename_field=filename_field,
            mimetype=mimetype,
            default_mimetype=default_mimetype,
            placeholder=placeholder,
            width=width,
            height=height,
            crop=crop,
            quality=quality,
        )
