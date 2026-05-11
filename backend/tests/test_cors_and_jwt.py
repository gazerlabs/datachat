"""Tests for the CORS default and JWT issuer/audience verification."""

import importlib
import os

import pytest


@pytest.fixture()
def reset_env(monkeypatch):
    """Clear the env vars these tests read so each starts clean. Neutralize
    load_dotenv so .env can't repopulate them when we reload config."""
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: None)
    for var in ("ALLOWED_ORIGINS", "FRONTEND_URL", "CLERK_JWT_AUDIENCE"):
        monkeypatch.delenv(var, raising=False)
    yield monkeypatch


def _reload_config():
    from app.core import config
    return importlib.reload(config)


class TestCorsDefault:
    def test_defaults_to_frontend_url_not_wildcard(self, reset_env):
        reset_env.setenv("FRONTEND_URL", "https://app.example.com")

        config = _reload_config()
        assert config.ALLOWED_ORIGINS == ["https://app.example.com"]
        assert "*" not in config.ALLOWED_ORIGINS

    def test_explicit_origins_list_respected(self, reset_env):
        reset_env.setenv("ALLOWED_ORIGINS", "https://a.example.com,https://b.example.com")

        config = _reload_config()
        assert config.ALLOWED_ORIGINS == [
            "https://a.example.com",
            "https://b.example.com",
        ]

    def test_explicit_wildcard_still_accepted_for_dev(self, reset_env):
        reset_env.setenv("ALLOWED_ORIGINS", "*")

        config = _reload_config()
        assert config.ALLOWED_ORIGINS == ["*"]

    def test_empty_entries_stripped(self, reset_env):
        reset_env.setenv("ALLOWED_ORIGINS", "https://a.example.com, , https://b.example.com,")

        config = _reload_config()
        assert config.ALLOWED_ORIGINS == [
            "https://a.example.com",
            "https://b.example.com",
        ]


class TestJwtVerificationOptions:
    def test_audience_unset_skips_audience_verification(self, reset_env):
        config = _reload_config()
        assert config.CLERK_JWT_AUDIENCE is None

    def test_audience_set_enables_verification(self, reset_env):
        reset_env.setenv("CLERK_JWT_AUDIENCE", "datachat-api")

        config = _reload_config()
        assert config.CLERK_JWT_AUDIENCE == "datachat-api"


# Restore canonical test-env config after this module so other test files
# (which import config indirectly) see consistent values.
@pytest.fixture(autouse=True, scope="module")
def _restore_test_config_after_module():
    yield
    os.environ["ENCRYPTION_KEY"] = "test-encryption-key"
    os.environ["DISABLE_AUTH"] = "false"
    os.environ.pop("CLERK_JWT_AUDIENCE", None)
    os.environ.pop("ALLOWED_ORIGINS", None)
    os.environ.pop("FRONTEND_URL", None)
    from app.core import config
    importlib.reload(config)
