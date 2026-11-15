import os
import subprocess
import pytest
from fastapi.testclient import TestClient

import backend.config as cfg
from backend.config import parse_allowed_origins
from backend.main import app
from backend.routers.auth import get_cookie_security_params


@pytest.fixture
def client():
    return TestClient(app)


def test_parse_allowed_origins():
    """Verify origin string sanitization: drops wildcards, trims slashes and whitespace."""
    raw = " https://frontend.vercel.app/ , http://localhost:5173, *, https://example.com/api*, , https://sub.domain.org/ "
    parsed = parse_allowed_origins(raw)
    assert parsed == [
        "https://frontend.vercel.app",
        "http://localhost:5173",
        "https://sub.domain.org",
    ]

    # Empty cases
    assert parse_allowed_origins("") == []
    assert parse_allowed_origins("   ") == []
    assert parse_allowed_origins("*") == []


def test_cors_preflight_allowed(client):
    """CORS preflight allowed for origins listed in ALLOWED_ORIGINS."""
    orig_origins = cfg.ALLOWED_ORIGINS
    try:
        cfg.ALLOWED_ORIGINS = ["https://frontend.vercel.app"]

        response = client.options(
            "/api/auth/login",
            headers={
                "Origin": "https://frontend.vercel.app",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type, ngrok-skip-browser-warning",
            },
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "https://frontend.vercel.app"
        assert response.headers.get("access-control-allow-credentials") == "true"
        allow_headers = response.headers.get("access-control-allow-headers", "").lower()
        assert "content-type" in allow_headers
        assert "ngrok-skip-browser-warning" in allow_headers
    finally:
        cfg.ALLOWED_ORIGINS = orig_origins


def test_cors_preflight_rejected_for_unlisted_origin(client):
    """CORS preflight does not grant access for unlisted origin."""
    orig_origins = cfg.ALLOWED_ORIGINS
    try:
        cfg.ALLOWED_ORIGINS = ["https://frontend.vercel.app"]

        response = client.options(
            "/api/auth/login",
            headers={
                "Origin": "https://evil.untrusted.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        allow_origin = response.headers.get("access-control-allow-origin")
        assert allow_origin != "https://evil.untrusted.com"
    finally:
        cfg.ALLOWED_ORIGINS = orig_origins


def test_cookie_attributes_same_origin_mode(client):
    """When CROSS_SITE_COOKIES=False, cookies use SameSite=Lax."""
    orig_cross = cfg.CROSS_SITE_COOKIES
    orig_sec = cfg.COOKIE_SECURE
    try:
        cfg.CROSS_SITE_COOKIES = False
        cfg.COOKIE_SECURE = False

        samesite, secure = get_cookie_security_params(None)
        assert samesite == "lax"
        assert secure is False

        # Attempt login with test admin credentials to inspect Set-Cookie headers
        resp = client.post(
            "/api/auth/login",
            json={"email": cfg.ADMIN_EMAIL, "password": cfg.ADMIN_PASSWORD},
        )
        assert resp.status_code == 200
        cookie_header = resp.headers.get("set-cookie", "")
        assert "samesite=lax" in cookie_header.lower()
        # In non-secure same-origin test mode, secure flag is not forced
        assert "samesite=none" not in cookie_header.lower()
    finally:
        cfg.CROSS_SITE_COOKIES = orig_cross
        cfg.COOKIE_SECURE = orig_sec


def test_cookie_attributes_cross_site_mode(client):
    """When CROSS_SITE_COOKIES=True, cookies use SameSite=None and Secure=True."""
    orig_cross = cfg.CROSS_SITE_COOKIES
    orig_origins = cfg.ALLOWED_ORIGINS
    try:
        cfg.CROSS_SITE_COOKIES = True
        cfg.ALLOWED_ORIGINS = ["https://frontend.vercel.app"]

        samesite, secure = get_cookie_security_params(None)
        assert samesite == "none"
        assert secure is True

        resp = client.post(
            "/api/auth/login",
            json={"email": cfg.ADMIN_EMAIL, "password": cfg.ADMIN_PASSWORD},
            headers={"Origin": "https://frontend.vercel.app"},
        )
        assert resp.status_code == 200
        cookie_header = resp.headers.get("set-cookie", "")
        assert "samesite=none" in cookie_header.lower()
        assert "secure" in cookie_header.lower()
    finally:
        cfg.CROSS_SITE_COOKIES = orig_cross
        cfg.ALLOWED_ORIGINS = orig_origins


def test_csrf_origin_check_cross_site_mode(client):
    """When CROSS_SITE_COOKIES=True, state-changing requests without or with untrusted Origin fail with 403."""
    orig_cross = cfg.CROSS_SITE_COOKIES
    orig_origins = cfg.ALLOWED_ORIGINS
    try:
        cfg.CROSS_SITE_COOKIES = True
        cfg.ALLOWED_ORIGINS = ["https://frontend.vercel.app"]

        # Missing Origin on state-changing request -> 403
        r_missing = client.post(
            "/api/auth/login",
            json={"email": "any@example.com", "password": "wrong"},
        )
        assert r_missing.status_code == 403
        assert "CSRF check failed" in r_missing.json().get("detail", "")

        # Untrusted Origin on state-changing request -> 403
        r_untrusted = client.post(
            "/api/auth/login",
            json={"email": "any@example.com", "password": "wrong"},
            headers={"Origin": "https://malicious-site.com"},
        )
        assert r_untrusted.status_code == 403
        assert "CSRF check failed" in r_untrusted.json().get("detail", "")

        # Trusted Origin on state-changing request -> passes CSRF check (e.g. 401 for bad creds)
        r_trusted = client.post(
            "/api/auth/login",
            json={"email": "any@example.com", "password": "wrong"},
            headers={"Origin": "https://frontend.vercel.app"},
        )
        assert r_trusted.status_code == 401

        # Read-only GET request without Origin header -> allowed (not 403)
        r_get = client.get("/health")
        assert r_get.status_code == 200

        # Read-only GET request with untrusted Origin -> allowed (not 403)
        r_get_untrusted = client.get("/health", headers={"Origin": "https://malicious-site.com"})
        assert r_get_untrusted.status_code == 200

        # When CROSS_SITE_COOKIES is False, missing Origin is NOT rejected with 403
        cfg.CROSS_SITE_COOKIES = False
        r_disabled = client.post(
            "/api/auth/login",
            json={"email": "any@example.com", "password": "wrong"},
        )
        assert r_disabled.status_code == 401
    finally:
        cfg.CROSS_SITE_COOKIES = orig_cross
        cfg.ALLOWED_ORIGINS = orig_origins


def test_frontend_url_builders():
    """Verify frontend getApiBaseUrl, buildApiUrl, and buildFileUrl with and without base URL."""
    node_script = """
    import { getApiBaseUrl, buildApiUrl, buildFileUrl } from './frontend/src/api.js';

    // 1. Without base URL (default same-origin mode)
    if (getApiBaseUrl() !== '') throw new Error('Default base should be empty');
    if (buildApiUrl('/conversations') !== '/api/conversations') throw new Error('buildApiUrl /conversations failed');
    if (buildApiUrl('conversations') !== '/api/conversations') throw new Error('buildApiUrl conversations failed');
    if (buildApiUrl('/api/conversations') !== '/api/conversations') throw new Error('buildApiUrl /api/conversations failed');
    if (buildApiUrl('') !== '/api') throw new Error('buildApiUrl empty failed');
    if (buildFileUrl('/uploads/docs/spec.pdf') !== '/uploads/docs/spec.pdf') throw new Error('buildFileUrl relative failed');
    if (buildFileUrl('https://cdn.example.com/pic.png') !== 'https://cdn.example.com/pic.png') throw new Error('buildFileUrl absolute failed');

    // 2. With custom / env base URL (cross-origin mode)
    const custom = 'https://backend.ngrok-free.app/';
    if (getApiBaseUrl(custom) !== 'https://backend.ngrok-free.app') throw new Error('getApiBaseUrl trailing slash trim failed');
    if (buildApiUrl('/conversations', custom) !== 'https://backend.ngrok-free.app/api/conversations') throw new Error('custom buildApiUrl failed');
    if (buildApiUrl('conversations', custom) !== 'https://backend.ngrok-free.app/api/conversations') throw new Error('custom buildApiUrl relative failed');
    if (buildApiUrl('/api/conversations', custom) !== 'https://backend.ngrok-free.app/api/conversations') throw new Error('custom buildApiUrl /api/ duplicate failed');
    if (buildApiUrl('', custom) !== 'https://backend.ngrok-free.app/api') throw new Error('custom buildApiUrl empty failed');
    if (buildFileUrl('/uploads/docs/spec.pdf', custom) !== 'https://backend.ngrok-free.app/uploads/docs/spec.pdf') throw new Error('custom buildFileUrl failed');
    if (buildFileUrl('https://cdn.example.com/pic.png', custom) !== 'https://cdn.example.com/pic.png') throw new Error('custom buildFileUrl absolute passthrough failed');

    console.log('ALL_URL_TESTS_PASSED');
    """

    res = subprocess.run(
        ["node", "--input-type=module", "-e", node_script],
        cwd=os.path.normpath(os.path.join(os.path.dirname(__file__), "..")),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Node script error: {res.stderr}"
    assert "ALL_URL_TESTS_PASSED" in res.stdout
