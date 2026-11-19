# -*- coding: utf-8 -*-
import json
import logging
import secrets
from datetime import datetime, timedelta
from functools import wraps
import jwt

from odoo.http import request

_logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"
DEFAULT_EXPIRATION_HOURS = 24


def get_jwt_secret():
    """
    Fetch JWT secret from ir.config_parameter or auto-generate if missing.
    """
    ICP = request.env['ir.config_parameter'].sudo()
    secret = ICP.get_param('saami.jwt_secret')
    if not secret:
        secret = secrets.token_urlsafe(48)
        ICP.set_param('saami.jwt_secret', secret)
    return str(secret).strip()


def send_json(data, status=200):
    """
    Standard JSON response helper with CORS headers.
    """
    origin = request.httprequest.headers.get('Origin', '*')
    headers = [
        ('Content-Type', 'application/json'),
        ('Access-Control-Allow-Origin', origin),
        ('Access-Control-Allow-Credentials', 'true'),
    ]
    return request.make_response(json.dumps(data), headers=headers, status=status)


def handle_cors(methods=None):
    """
    Handle browser CORS preflight (OPTIONS).
    Returns response if OPTIONS request, otherwise None.
    """
    if methods is None:
        methods = ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS']

    if request.httprequest.method == 'OPTIONS':
        origin = request.httprequest.headers.get('Origin', '*')
        headers = [
            ('Access-Control-Allow-Origin', origin),
            ('Access-Control-Allow-Methods', ', '.join(methods)),
            ('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Requested-With'),
            ('Access-Control-Allow-Credentials', 'true'),
            ('Access-Control-Max-Age', '86400'),
        ]
        return request.make_response('', headers=headers, status=200)
    return None


def get_json_body():
    """
    Extract JSON payload from request body.
    """
    if not request.httprequest.data:
        return {}
    try:
        return json.loads(request.httprequest.data.decode('utf-8'))
    except Exception:
        return None


def generate_jwt(user, extra_payload=None, expires_in_hours=None):
    """
    Generate signed JWT for an authenticated Odoo user.
    """
    if expires_in_hours is None:
        ICP = request.env['ir.config_parameter'].sudo()
        expires_in_hours = int(ICP.get_param('saami.jwt_expiration_hours', DEFAULT_EXPIRATION_HOURS))

    secret = get_jwt_secret()
    payload = {
        'uid': user.id,
        'login': user.login,
        'partner_id': user.partner_id.id,
        'iat': datetime.now(),
        'exp': datetime.now() + timedelta(hours=expires_in_hours),
    }
    if extra_payload and isinstance(extra_payload, dict):
        payload.update(extra_payload)

    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def decode_jwt(token):
    """
    Verify and decode a JWT token.
    Returns (payload, error_message).
    """
    try:
        secret = get_jwt_secret()
        payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
        return payload, None
    except jwt.ExpiredSignatureError:
        return None, "Token has expired."
    except jwt.InvalidTokenError:
        return None, "Invalid token."
    except Exception as e:
        _logger.warning("JWT verification error: %s", str(e))
        return None, "Authentication token verification failed."


def get_current_user():
    """
    Extract Bearer token from Authorization header and return validated user record.
    Also swaps request.env to this user.
    """
    auth_header = request.httprequest.headers.get('Authorization', '')
    if not auth_header or not auth_header.startswith('Bearer '):
        return None

    token = auth_header.split(' ', 1)[1].strip()
    payload, err = decode_jwt(token)
    if not payload:
        return None

    uid = payload.get('uid')
    if not uid:
        return None

    user = request.env['res.users'].sudo().browse(uid)
    if not user.exists() or not user.active:
        return None

    # Switch Odoo request env to authenticated user
    request.update_env(user=user.id)
    return user


def require_jwt(f):
    """
    Decorator to protect API endpoints:
    1. Handles CORS preflight automatically.
    2. Validates Bearer token.
    3. Injects validated `user` as first parameter to the endpoint method.
    """
    @wraps(f)
    def wrapper(self, *args, **kwargs):
        preflight = handle_cors()
        if preflight:
            return preflight

        user = get_current_user()
        if not user:
            return send_json({
                'code': 'UNAUTHORIZED',
                'message': 'Valid authorization token is required.',
            }, status=401)

        return f(self, user, *args, **kwargs)
    return wrapper
