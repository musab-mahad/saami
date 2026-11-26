import base64
from io import BytesIO
from unittest.mock import patch

from botocore.exceptions import ClientError
from PIL import Image

from odoo.tests.common import TransactionCase, tagged


class FakeBody:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


class FakeS3Client:
    """In-memory S3/R2 fake for TransactionCase tests."""

    def __init__(self):
        self.objects = {}

    def _not_found(self):
        return ClientError(
            {'Error': {'Code': 'NoSuchKey', 'Message': 'Not Found'}, 'ResponseMetadata': {'HTTPStatusCode': 404}},
            'GetObject',
        )

    def head_bucket(self, Bucket):
        return {}

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise self._not_found()
        return {'ContentLength': len(self.objects[(Bucket, Key)][0])}

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.objects[(Bucket, Key)] = (Body, ContentType)
        return {}

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise self._not_found()
        return {'Body': FakeBody(self.objects[(Bucket, Key)][0])}

    def delete_object(self, Bucket, Key):
        self.objects.pop((Bucket, Key), None)
        return {}

    def generate_presigned_url(self, ClientMethod, Params, ExpiresIn):
        return f"https://fake-r2.example.com/{Params['Bucket']}/{Params['Key']}?exp={ExpiresIn}"


@tagged('post_install', '-at_install', 'r2_attachment_storage')
class TestR2AttachmentStorage(TransactionCase):

    def setUp(self):
        super().setUp()
        self.fake_s3 = FakeS3Client()
        params = self.env['ir.config_parameter'].sudo()
        params.set_param('r2_storage.enabled', 'True')
        params.set_param('r2_storage.account_id', 'acc123')
        params.set_param('r2_storage.access_key_id', 'key123')
        params.set_param('r2_storage.secret_access_key', 'sec123')
        params.set_param('r2_storage.bucket_name', 'saami-bucket')
        params.set_param('r2_storage.key_prefix', 'media')
        params.set_param('r2_storage.serve_mode', 'presigned')
        params.set_param('r2_storage.presigned_expiry', '300')
        params.set_param('r2_storage.fallback_local', 'True')
        params.set_param('r2_storage.allow_delete', 'False')

    def _make_png_bytes(self, color=(255, 0, 0), size=(64, 64)):
        buf = BytesIO()
        Image.new('RGB', size, color=color).save(buf, format='PNG')
        return buf.getvalue()

    def test_01_upload_dedup_read_and_asset_exclusion(self):
        with patch('odoo.addons.r2_attachment_storage.models.r2_client.get_s3_client', return_value=self.fake_s3):
            Attachment = self.env['ir.attachment'].sudo()
            payload = b'hello r2 attachment'
            att1 = Attachment.create({'name': 'doc1.txt', 'raw': payload, 'mimetype': 'text/plain'})
            att2 = Attachment.create({'name': 'doc2.txt', 'raw': payload, 'mimetype': 'text/plain'})

            self.assertTrue(att1.store_fname.startswith('r2/media/'))
            self.assertEqual(att1.store_fname, att2.store_fname)
            self.assertEqual(len(self.fake_s3.objects), 1)
            self.assertEqual(att1.raw, payload)

            # Web asset bundles must remain in local filestore
            asset = Attachment.create({
                'name': 'bundle.js',
                'url': '/web/assets/1/bundle.js',
                'raw': b'console.log(1);',
                'mimetype': 'application/javascript',
            })
            self.assertFalse(asset.store_fname.startswith('r2/'))

    def test_02_stream_presigned_and_resized_image(self):
        with patch('odoo.addons.r2_attachment_storage.models.r2_client.get_s3_client', return_value=self.fake_s3):
            png = self._make_png_bytes(size=(200, 200))
            att = self.env['ir.attachment'].sudo().create({
                'name': 'photo.png',
                'raw': png,
                'mimetype': 'image/png',
            })

            # Full stream uses presigned URL redirect
            full_stream = att._to_http_stream()
            self.assertEqual(full_stream.type, 'url')
            self.assertIn('fake-r2.example.com/saami-bucket/media/', full_stream.url)

            # Resized image stream forces proxy data so ir.binary can resize
            resized_stream = self.env['ir.binary']._get_image_stream_from(att, width=50, height=50)
            self.assertEqual(resized_stream.type, 'data')
            resized_img = Image.open(BytesIO(resized_stream.data))
            self.assertEqual(resized_img.size, (50, 50))

    def test_03_gc_respects_allow_delete_and_ref_count(self):
        with patch('odoo.addons.r2_attachment_storage.models.r2_client.get_s3_client', return_value=self.fake_s3):
            Attachment = self.env['ir.attachment'].sudo()
            Queue = self.env['r2.gc.queue'].sudo()

            att1 = Attachment.create({'name': 'a.bin', 'raw': b'same-bytes'})
            att2 = Attachment.create({'name': 'b.bin', 'raw': b'same-bytes'})
            fname = att1.store_fname

            # With allow_delete=False, unlinking does not enqueue or delete
            att1.unlink()
            self.assertEqual(Queue.search_count([('store_fname', '=', fname)]), 0)
            self.assertEqual(len(self.fake_s3.objects), 1)

            # Enable allow_delete=True, unlink att2 -> enqueues and deletes
            self.env['ir.config_parameter'].sudo().set_param('r2_storage.allow_delete', 'True')
            att2.unlink()
            self.assertEqual(Queue.search_count([('store_fname', '=', fname)]), 1)
            deleted = Queue._cron_gc_r2_objects()
            self.assertEqual(deleted, 1)
            self.assertEqual(len(self.fake_s3.objects), 0)

    def test_04_migrate_local_to_r2_and_back(self):
        with patch('odoo.addons.r2_attachment_storage.models.r2_client.get_s3_client', return_value=self.fake_s3):
            Attachment = self.env['ir.attachment'].sudo()
            # Create a local attachment while R2 is skipped
            local_att = Attachment.with_context(r2_skip=True).create({
                'name': 'legacy.txt',
                'raw': b'legacy-content',
                'mimetype': 'text/plain',
            })
            self.assertFalse(local_att.store_fname.startswith('r2/'))

            settings = self.env['res.config.settings'].create({})
            settings.action_r2_migrate_to_r2()
            local_att.invalidate_recordset()
            self.assertTrue(local_att.store_fname.startswith('r2/media/'))
            self.assertEqual(local_att.raw, b'legacy-content')

            settings.action_r2_migrate_to_local()
            local_att.invalidate_recordset()
            self.assertFalse(local_att.store_fname.startswith('r2/'))
            self.assertEqual(local_att.raw, b'legacy-content')
