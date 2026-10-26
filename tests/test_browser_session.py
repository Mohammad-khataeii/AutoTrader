from fastapi.testclient import TestClient

from autotrader.api.main import create_app
from autotrader.api.session import COOKIE, LIFETIME, issue, valid
from autotrader.config import Settings


def test_signed_session_expires_and_rejects_tampering_and_password_rotation(monkeypatch):
    from autotrader.api import session
    settings = Settings(_env_file=None)
    token = issue(settings)
    assert valid(token, settings)
    assert not valid(token[:-4]+'aaaa', settings)
    assert not valid('malformed', settings)
    changed = Settings(dashboard_password='rotated-fixture-password', _env_file=None)
    assert not valid(token, changed)
    now = session.time.time()
    monkeypatch.setattr(session.time, 'time', lambda: now+LIFETIME+1)
    assert not valid(token, settings)


def test_http_only_session_survives_client_and_server_restart_and_logout(monkeypatch, tmp_path):
    monkeypatch.setenv('DATABASE_URL', f'sqlite+aiosqlite:///{tmp_path / "session.db"}')
    app = create_app()
    with TestClient(app) as client:
        assert client.get('/api/session').status_code == 401
        response = client.post('/api/session', auth=('admin', 'change-me'))
        assert response.status_code == 200
        cookie = response.headers['set-cookie'].lower()
        assert 'httponly' in cookie and 'samesite=strict' in cookie and 'max-age=604800' in cookie
        assert 'change-me' not in cookie
        token = client.cookies.get(COOKIE)
        assert client.get('/api/session').status_code == 200
        assert client.get('/api/overview/summary').status_code == 200
        assert client.post('/api/session').status_code == 403  # Cookie writes require CSRF proof.
        renewed = client.post('/api/session', headers={'X-CSRF-Token': response.json()['csrf_token']})
        assert renewed.status_code == 200
        token = client.cookies.get(COOKIE)
    with TestClient(create_app()) as reopened:
        reopened.cookies.set(COOKIE, token)
        assert reopened.get('/api/session').status_code == 200
        assert reopened.get('/api/overview/summary').status_code == 200
        # Install a host cookie exactly as a browser would receive it.
        reopened.cookies.clear()
        reopened.post('/api/session', auth=('admin','change-me'))
        assert reopened.delete('/api/session').status_code == 200
        assert reopened.get('/api/session').status_code == 401
        assert reopened.get('/api/overview/summary').status_code == 401
