"""
πNAD - Supabase JWT Authentication Middleware
==============================================
Middleware para validar tokens JWT de Supabase en Flask endpoints.
"""

import os
import jwt
import requests
from functools import wraps
from flask import request, jsonify, g
from typing import Optional, Dict, Any, Tuple
from utils.config import CONFIG


# Supabase JWT configuration
SUPABASE_URL = CONFIG.supabase.url
SUPABASE_ANON_KEY = CONFIG.supabase.anon_key

# Supabase JWKS endpoint (for token verification)
JWKS_URL = f"{SUPABASE_URL}/.well-known/jwks.json"

# Cache for JWKS (to avoid fetching on every request)
_jwks_cache = None
_jwks_cache_time = 0
JWKS_CACHE_TTL = 3600  # 1 hour


def get_jwks() -> Dict[str, Any]:
    """Fetch JWKS from Supabase with caching."""
    global _jwks_cache, _jwks_cache_time
    
    import time
    now = time.time()
    
    # Return cached JWKS if still valid
    if _jwks_cache and (now - _jwks_cache_time) < JWKS_CACHE_TTL:
        return _jwks_cache
    
    try:
        response = requests.get(JWKS_URL, timeout=5)
        response.raise_for_status()
        _jwks_cache = response.json()
        _jwks_cache_time = now
        return _jwks_cache
    except Exception as e:
        print(f"Error fetching JWKS: {e}")
        # Return cached JWKS even if expired as fallback
        return _jwks_cache or {}


def verify_supabase_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify a Supabase JWT token and return the decoded payload.
    
    Args:
        token: JWT token string (without 'Bearer ' prefix)
    
    Returns:
        Decoded token payload if valid, None otherwise
    """
    try:
        # Decode header to get kid
        header = jwt.get_unverified_header(token)
        kid = header.get('kid')
        
        if not kid:
            print("Token missing 'kid' in header")
            return None
        
        # Get JWKS and find matching key
        jwks = get_jwks()
        if not jwks or 'keys' not in jwks:
            print("Failed to fetch JWKS")
            return None
        
        # Find the key with matching kid
        rsa_key = None
        for key in jwks['keys']:
            if key.get('kid') == kid:
                # Construct RSA key from JWKS
                rsa_key = {
                    'kty': key['kty'],
                    'kid': key['kid'],
                    'use': key['use'],
                    'n': key['n'],
                    'e': key['e']
                }
                break
        
        if not rsa_key:
            print(f"No matching key found for kid: {kid}")
            return None
        
        # Verify token
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=['RS256'],
            audience='authenticated',
            issuer=f"{SUPABASE_URL}/auth/v1"
        )
        
        return payload
        
    except jwt.ExpiredSignatureError:
        print("Token has expired")
        return None
    except jwt.InvalidTokenError as e:
        print(f"Invalid token: {e}")
        return None
    except Exception as e:
        print(f"Error verifying token: {e}")
        return None


def get_user_from_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Get user information from a Supabase token.
    
    Args:
        token: JWT token string
    
    Returns:
        User information dict if valid, None otherwise
    """
    payload = verify_supabase_token(token)
    if not payload:
        return None
    
    return {
        'user_id': payload.get('sub'),
        'email': payload.get('email'),
        'role': payload.get('role', 'authenticated'),
        'aud': payload.get('aud'),
        'exp': payload.get('exp'),
        'iat': payload.get('iat')
    }


def supabase_auth_required(f):
    """
    Decorator to require Supabase authentication for Flask endpoints.
    
    Usage:
        @app.route('/api/protected')
        @supabase_auth_required
        def protected_endpoint():
            user = g.user
            return jsonify({'user': user})
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get Authorization header
        auth_header = request.headers.get('Authorization')
        
        if not auth_header:
            return jsonify({
                'error': 'Missing Authorization header',
                'message': 'Authorization header is required'
            }), 401
        
        # Extract token (remove 'Bearer ' prefix if present)
        token = auth_header
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
        
        # Verify token
        user_info = get_user_from_token(token)
        
        if not user_info:
            return jsonify({
                'error': 'Invalid or expired token',
                'message': 'The provided token is invalid or has expired'
            }), 401
        
        # Store user info in Flask's g object for use in the endpoint
        g.user = user_info
        g.user_id = user_info['user_id']
        g.user_email = user_info['email']
        
        return f(*args, **kwargs)
    
    return decorated_function


def validate_supabase_token(token: str) -> tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    Validate a Supabase token and return (is_valid, user_info, error_message).
    
    Args:
        token: JWT token string
    
    Returns:
        Tuple of (is_valid, user_info, error_message)
    """
    user_info = get_user_from_token(token)
    
    if user_info:
        return True, user_info, None
    
    return False, None, 'Invalid or expired token'


def optional_supabase_auth(f):
    """
    Decorator to optionally use Supabase authentication.
    If token is provided and valid, user info will be in g.user.
    If no token or invalid, the endpoint still runs but g.user will be None.
    
    Usage:
        @app.route('/api/optional')
        @optional_supabase_auth
        def optional_endpoint():
            if g.user:
                return jsonify({'user': g.user, 'authenticated': True})
            return jsonify({'authenticated': False})
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from flask import g
        g.user = None
        g.user_id = None
        g.user_email = None
        
        auth_header = request.headers.get('Authorization')
        
        if auth_header:
            token = auth_header
            if auth_header.startswith('Bearer '):
                token = auth_header[7:]
            
            user_info = get_user_from_token(token)
            if user_info:
                g.user = user_info
                g.user_id = user_info['user_id']
                g.user_email = user_info['email']
        
        return f(*args, **kwargs)
    
    return decorated_function
