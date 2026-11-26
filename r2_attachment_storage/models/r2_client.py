import logging
import threading
import uuid

from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
except ImportError:
    boto3 = None
    Config = None
    ClientError = Exception

R2_PREFIX = 'r2/'
_CLIENT_CACHE = {}
_CLIENT_LOCK = threading.Lock()


def _as_bool(value, default=False):
    if value is None or value is False or value == '':
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def get_r2_config(env):
    """Read Cloudflare R2 configuration from ir.config_parameter."""
    params = env['ir.config_parameter'].sudo()
    prefix = (params.get_param('r2_storage.key_prefix') or '').strip().strip('/')

    return {
        'enabled': _as_bool(params.get_param('r2_storage.enabled'), default=False),
        'account_id': (params.get_param('r2_storage.account_id') or '').strip(),
        'access_key_id': (params.get_param('r2_storage.access_key_id') or '').strip(),
        'secret_access_key': (params.get_param('r2_storage.secret_access_key') or '').strip(),
        'bucket_name': (params.get_param('r2_storage.bucket_name') or '').strip(),
        'key_prefix': prefix,
        'fallback_local': _as_bool(params.get_param('r2_storage.fallback_local'), default=True),
        'allow_delete': _as_bool(params.get_param('r2_storage.allow_delete'), default=True),
    }


def is_r2_configured(cfg):
    """Return True when all required R2 connection parameters are present."""
    return bool(
        cfg.get('account_id')
        and cfg.get('access_key_id')
        and cfg.get('secret_access_key')
        and cfg.get('bucket_name')
    )


def get_s3_client(cfg):
    """Return a cached boto3 S3 client configured for Cloudflare R2."""
    if boto3 is None:
        raise UserError(_('The "boto3" Python package is required for Cloudflare R2 storage.'))
    if not is_r2_configured(cfg):
        raise UserError(_('Cloudflare R2 credentials are incomplete. Please check Settings -> Cloudflare R2.'))

    cache_key = (cfg['account_id'], cfg['access_key_id'], cfg['secret_access_key'])
    with _CLIENT_LOCK:
        client = _CLIENT_CACHE.get(cache_key)
        if client is None:
            endpoint_url = f"https://{cfg['account_id']}.r2.cloudflarestorage.com"
            client = boto3.client(
                's3',
                endpoint_url=endpoint_url,
                aws_access_key_id=cfg['access_key_id'],
                aws_secret_access_key=cfg['secret_access_key'],
                config=Config(
                    signature_version='s3v4',
                    retries={'max_attempts': 3, 'mode': 'standard'},
                ),
                region_name='auto',
            )
            _CLIENT_CACHE[cache_key] = client
        return client


def is_r2_fname(fname):
    """Return True if store_fname points to an R2 object."""
    return bool(fname and fname.startswith(R2_PREFIX))


def build_store_fname(checksum, key_prefix=''):
    """Build portable store_fname for R2 (never dependent on cr.dbname)."""
    shard = f"{checksum[:2]}/{checksum}"
    clean_prefix = (key_prefix or '').strip().strip('/')
    if clean_prefix:
        return f"{R2_PREFIX}{clean_prefix}/{shard}"
    return f"{R2_PREFIX}{shard}"


def extract_object_key(store_fname):
    """Extract the R2 bucket object key from store_fname."""
    if not is_r2_fname(store_fname):
        return store_fname
    return store_fname[len(R2_PREFIX):]


def _is_not_found_error(exc):
    if not isinstance(exc, ClientError):
        return False
    code = str(exc.response.get('Error', {}).get('Code', ''))
    status = exc.response.get('ResponseMetadata', {}).get('HTTPStatusCode')
    return code in ('404', 'NoSuchKey', 'NotFound') or status == 404


def r2_object_exists(cfg, object_key):
    """Check whether an object already exists in R2."""
    client = get_s3_client(cfg)
    try:
        client.head_object(Bucket=cfg['bucket_name'], Key=object_key)
        return True
    except ClientError as exc:
        if _is_not_found_error(exc):
            return False
        raise


def r2_put_object(cfg, object_key, data, content_type=None):
    """Upload bytes to R2."""
    client = get_s3_client(cfg)
    kwargs = {
        'Bucket': cfg['bucket_name'],
        'Key': object_key,
        'Body': data,
    }
    if content_type:
        kwargs['ContentType'] = content_type
    client.put_object(**kwargs)


def r2_get_object(cfg, object_key):
    """Fetch object bytes from R2; return None if not found."""
    client = get_s3_client(cfg)
    try:
        response = client.get_object(Bucket=cfg['bucket_name'], Key=object_key)
        return response['Body'].read()
    except ClientError as exc:
        if _is_not_found_error(exc):
            return None
        raise


def r2_delete_object(cfg, object_key):
    """Delete an object from R2 (ignores missing keys)."""
    client = get_s3_client(cfg)
    try:
        client.delete_object(Bucket=cfg['bucket_name'], Key=object_key)
    except ClientError as exc:
        if not _is_not_found_error(exc):
            raise


def r2_generate_presigned_url(cfg, object_key, filename=None, mimetype=None, as_attachment=False, expires_in=86400):
    """Generate a locally signed Cloudflare R2 download URL (no network round-trip)."""
    client = get_s3_client(cfg)
    params = {
        'Bucket': cfg['bucket_name'],
        'Key': object_key,
    }
    if mimetype:
        params['ResponseContentType'] = mimetype
    if filename:
        disposition = 'attachment' if as_attachment else 'inline'
        safe_name = str(filename).replace('"', '_').replace('\n', '_').replace('\r', '_')
        params['ResponseContentDisposition'] = f'{disposition}; filename="{safe_name}"'

    return client.generate_presigned_url(
        'get_object',
        Params=params,
        ExpiresIn=expires_in,
    )


def r2_test_connection(cfg):
    """Verify R2 bucket access and read/write/delete permissions."""
    client = get_s3_client(cfg)
    bucket = cfg['bucket_name']
    client.head_bucket(Bucket=bucket)
    probe_key = f".odoo_r2_probe/{uuid.uuid4().hex}"
    client.put_object(Bucket=bucket, Key=probe_key, Body=b'ok', ContentType='text/plain')
    client.delete_object(Bucket=bucket, Key=probe_key)
    return True
