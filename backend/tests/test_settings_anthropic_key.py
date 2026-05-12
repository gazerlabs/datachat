"""Tests for the in-app Anthropic key configuration.

Covers the resolution precedence (DB > env > error), the placeholder-detection
that makes a stock .env.example count as "unset", and the API endpoints'
admin-gating + masking behavior. Anthropic itself is mocked — we never make a
real validation call from CI.
"""

from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# settings_service unit tests
# ---------------------------------------------------------------------------
class TestKeyResolution:
    def test_db_key_takes_precedence_over_env(self, db_session):
        from app.services import settings_service

        with patch.object(settings_service, "ANTHROPIC_API_KEY", "sk-env"):
            settings_service.save_anthropic_key(db_session, "sk-db")
            assert settings_service.resolve_anthropic_key(db_session) == "sk-db"

    def test_env_used_when_db_unset(self, db_session):
        from app.services import settings_service

        with patch.object(settings_service, "ANTHROPIC_API_KEY", "sk-env-real"):
            assert settings_service.resolve_anthropic_key(db_session) == "sk-env-real"

    def test_placeholder_env_treated_as_unset(self, db_session):
        from app.services import settings_service

        with patch.object(settings_service, "ANTHROPIC_API_KEY", "sk-ant-..."):
            assert settings_service.resolve_anthropic_key(db_session) is None

    def test_blank_env_treated_as_unset(self, db_session):
        from app.services import settings_service

        with patch.object(settings_service, "ANTHROPIC_API_KEY", ""):
            assert settings_service.resolve_anthropic_key(db_session) is None

    def test_require_raises_when_unconfigured(self, db_session):
        from app.services import settings_service

        with patch.object(settings_service, "ANTHROPIC_API_KEY", ""):
            with pytest.raises(settings_service.NoApiKeyError):
                settings_service.require_anthropic_key(db_session)


class TestStatus:
    def test_unconfigured_status(self, db_session):
        from app.services import settings_service

        with patch.object(settings_service, "ANTHROPIC_API_KEY", "sk-ant-..."):
            s = settings_service.status(db_session)
        assert s == {
            "configured": False,
            "effective": False,
            "source": None,
            "masked": None,
            "updated_at": None,
        }

    def test_env_only_status(self, db_session):
        from app.services import settings_service

        with patch.object(settings_service, "ANTHROPIC_API_KEY", "sk-ant-api03-xxxxxxxxxxxxxx-yyyy"):
            s = settings_service.status(db_session)
        assert s["configured"] is False
        assert s["effective"] is True
        assert s["source"] == "env"
        assert s["masked"] is not None
        assert "…" in s["masked"]
        assert s["masked"].endswith("yyyy")

    def test_db_status(self, db_session):
        from app.services import settings_service

        settings_service.save_anthropic_key(db_session, "sk-ant-api03-zzzzzzzzz-aaaa")
        with patch.object(settings_service, "ANTHROPIC_API_KEY", ""):
            s = settings_service.status(db_session)
        assert s["configured"] is True
        assert s["effective"] is True
        assert s["source"] == "database"
        assert s["masked"].endswith("aaaa")
        assert s["updated_at"] is not None  # ISO timestamp string


class TestSaveValidation:
    def test_rejects_empty(self, db_session):
        from app.services import settings_service

        with pytest.raises(settings_service.InvalidApiKeyError):
            settings_service.save_anthropic_key(db_session, "")

    def test_rejects_placeholder(self, db_session):
        from app.services import settings_service

        with pytest.raises(settings_service.InvalidApiKeyError, match="placeholder"):
            settings_service.save_anthropic_key(db_session, "sk-ant-...")

    def test_replace_existing(self, db_session):
        from app.services import settings_service

        settings_service.save_anthropic_key(db_session, "sk-first")
        settings_service.save_anthropic_key(db_session, "sk-second")
        assert settings_service.get_anthropic_key_from_db(db_session) == "sk-second"

    def test_delete_existing(self, db_session):
        from app.services import settings_service

        settings_service.save_anthropic_key(db_session, "sk-x")
        assert settings_service.delete_anthropic_key(db_session) is True
        assert settings_service.get_anthropic_key_from_db(db_session) is None
        # Second delete is a no-op.
        assert settings_service.delete_anthropic_key(db_session) is False


# ---------------------------------------------------------------------------
# /api/settings/anthropic-key endpoints
# ---------------------------------------------------------------------------
class TestAnthropicKeyAPI:
    async def test_get_returns_status(self, authed_client):
        with patch("app.services.settings_service.ANTHROPIC_API_KEY", "sk-ant-..."):
            resp = await authed_client.get("/api/settings/anthropic-key")
        assert resp.status_code == 200
        body = resp.json()
        assert body["configured"] is False
        assert body["effective"] is False

    async def test_put_validates_then_saves(self, authed_client):
        # Stub validate_key directly — the AuthenticationError constructor
        # requires a real httpx.Response, which is more setup than the test
        # benefits from. We're verifying the route's wiring, not the SDK's.
        with patch(
            "app.services.settings_service.validate_key",
            new=AsyncMock(return_value=None),
        ):
            resp = await authed_client.put(
                "/api/settings/anthropic-key",
                json={"api_key": "sk-ant-api03-real-key-here-1234"},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["configured"] is True
        assert body["source"] == "database"

    async def test_put_rejects_invalid_key(self, authed_client):
        from app.services.settings_service import InvalidApiKeyError

        with patch(
            "app.services.settings_service.validate_key",
            new=AsyncMock(side_effect=InvalidApiKeyError("invalid x-api-key")),
        ):
            resp = await authed_client.put(
                "/api/settings/anthropic-key",
                json={"api_key": "sk-ant-totally-bad"},
            )
        assert resp.status_code == 400
        assert "Anthropic rejected" in resp.json()["detail"]

    async def test_delete_clears_db_key(self, authed_client):
        # Seed via PUT so we exercise the same engine as the DELETE call.
        with patch(
            "app.services.settings_service.validate_key",
            new=AsyncMock(return_value=None),
        ):
            put = await authed_client.put(
                "/api/settings/anthropic-key",
                json={"api_key": "sk-ant-stored"},
            )
            assert put.status_code == 200, put.text
            assert put.json()["configured"] is True

            # Same authed_client session — engine is the same one the seed
            # PUT just wrote to.
            resp = await authed_client.delete("/api/settings/anthropic-key")
        assert resp.status_code == 200, resp.text
        assert resp.json()["configured"] is False
