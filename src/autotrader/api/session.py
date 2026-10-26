"""Signed browser sessions; credentials remain out of browser storage."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response

COOKIE = 'personal_plan_session'
LIFETIME = 7 * 24 * 3600


def signature(value: str, settings: Any) -> str:
    key = hashlib.sha256(('personal-plan-browser-session-v1:' + settings.dashboard_username + ':' +
        settings.dashboard_password.get_secret_value()).encode()).digest()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


def issue(settings: Any) -> str:
    body = f'{int(time.time())}.{secrets.token_urlsafe(24)}'
    return body + '.' + signature(body, settings)


def valid(token: str, settings: Any) -> bool:
    try:
        issued, nonce, signed = token.split('.')
        elapsed = time.time() - int(issued)
        return len(nonce) == 32 and 0 <= elapsed < LIFETIME and hmac.compare_digest(
            signed, signature(issued + '.' + nonce, settings))
    except (ValueError, TypeError):
        return False


def csrf(token: str, settings: Any) -> str:
    return signature('csrf:' + token, settings)


def cookie_user(request: Request, settings: Any, *, check_write: bool = True) -> str | None:
    token = request.cookies.get(COOKIE, '')
    if not valid(token, settings):
        return None
    if (check_write and request.method not in {'GET', 'HEAD', 'OPTIONS'} and
        not hmac.compare_digest(request.headers.get('x-csrf-token', ''), csrf(token, settings))):
        raise HTTPException(403, 'Session write verification failed; refresh and try again')
    return str(settings.dashboard_username)


def install(app: FastAPI, settings: Any, require_user: Any) -> None:
    @app.post('/api/session')
    async def login(request: Request, response: Response, user: str = Depends(require_user)) -> dict[str, Any]:
        token = issue(settings)
        response.set_cookie(COOKIE, token, max_age=LIFETIME, httponly=True,
            secure=request.url.scheme == 'https', samesite='strict', path='/')
        response.headers['Cache-Control'] = 'no-store'
        return {'username': user, 'csrf_token': csrf(token, settings), 'expires_in': LIFETIME}

    @app.get('/api/session')
    async def restore(request: Request, response: Response) -> dict[str, Any]:
        user = cookie_user(request, settings)
        if user is None:
            raise HTTPException(401, 'Sign in required', headers={'Cache-Control': 'no-store'})
        response.headers['Cache-Control'] = 'no-store'
        return {'username': user, 'csrf_token': csrf(request.cookies[COOKIE], settings)}

    @app.delete('/api/session')
    async def logout(response: Response) -> dict[str, bool]:
        response.delete_cookie(COOKIE, path='/', httponly=True, samesite='strict')
        response.headers['Cache-Control'] = 'no-store'
        return {'signed_out': True}
