"""Tests for the consulting-inquiry endpoint, focused on HTML-escape of
user-controlled fields before they hit the Resend webhook payload."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture()
def with_resend(monkeypatch):
    """Force RESEND_API_KEY to be set so the email branch executes."""
    monkeypatch.setattr("app.api.demo.RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr("app.api.demo.RESEND_FROM_EMAIL", "datachat <test@example.com>")
    monkeypatch.setattr("app.api.demo.NOTIFICATION_EMAIL", "ops@example.com")


@pytest.fixture()
def mock_httpx_post():
    """Patch httpx.AsyncClient so we capture the outbound Resend payload
    without making a real request."""
    with patch("app.api.demo.httpx.AsyncClient") as client_cls:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "ok"
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        client_cls.return_value = mock_client
        yield mock_client


class TestConsultingInquiryEscape:
    async def test_html_in_message_is_escaped(self, client, with_resend, mock_httpx_post):
        payload = {
            "name": "Alice",
            "email": "alice@example.com",
            "company": "Evil Corp",
            "message": "<img src=x onerror=alert(1)> hi",
        }
        resp = await client.post("/api/consulting-inquiry", json=payload)
        assert resp.status_code == 200

        sent_payload = mock_httpx_post.post.call_args.kwargs["json"]
        html_body = sent_payload["html"]
        assert "<img src=x onerror=alert(1)>" not in html_body
        assert "&lt;img src=x onerror=alert(1)&gt;" in html_body

    async def test_html_in_name_is_escaped(self, client, with_resend, mock_httpx_post):
        payload = {
            "name": "<script>alert(1)</script>",
            "email": "x@example.com",
            "company": "co",
            "message": "hi",
        }
        resp = await client.post("/api/consulting-inquiry", json=payload)
        assert resp.status_code == 200

        html_body = mock_httpx_post.post.call_args.kwargs["json"]["html"]
        assert "<script>" not in html_body
        assert "&lt;script&gt;" in html_body

    async def test_plain_text_unchanged(self, client, with_resend, mock_httpx_post):
        payload = {
            "name": "Alice",
            "email": "alice@example.com",
            "company": "Acme",
            "message": "Hello, can we talk?",
        }
        resp = await client.post("/api/consulting-inquiry", json=payload)
        assert resp.status_code == 200

        html_body = mock_httpx_post.post.call_args.kwargs["json"]["html"]
        assert "Alice" in html_body
        assert "Hello, can we talk?" in html_body
