"""Tests for core/config.py — production safety gates."""

import importlib
import os

import pytest


@pytest.fixture(autouse=True, scope="module")
def _restore_test_config_after_module():
    """Reload-based tests below leave app.core.config in whatever state the
    last test set. Restore the canonical test-env config after the module so
    later test files (which import config indirectly) see consistent values."""
    yield
    os.environ["ENV"] = "development"
    os.environ["ENCRYPTION_KEY"] = "test-encryption-key"
    os.environ["DISABLE_AUTH"] = "false"
    from app.core import config
    importlib.reload(config)


@pytest.fixture()
def reset_env(monkeypatch):
    """Clear env vars the config module reads so each test starts clean.
    Also neutralize load_dotenv at the source so .env can't repopulate them
    when we reload the config module (which calls `from dotenv import
    load_dotenv` and then `load_dotenv(override=True)` at import time)."""
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: None)
    for var in ("ENV", "DISABLE_AUTH", "ENCRYPTION_KEY"):
        monkeypatch.delenv(var, raising=False)
    yield monkeypatch


def _reload_config():
    from app.core import config
    return importlib.reload(config)


class TestDisableAuthGate:
    def test_disable_auth_allowed_in_development(self, reset_env):
        reset_env.setenv("ENV", "development")
        reset_env.setenv("DISABLE_AUTH", "true")
        reset_env.setenv("ENCRYPTION_KEY", "test-key")

        config = _reload_config()
        assert config.DISABLE_AUTH is True
        assert config.IS_PRODUCTION is False

    def test_disable_auth_refused_in_production(self, reset_env):
        reset_env.setenv("ENV", "production")
        reset_env.setenv("DISABLE_AUTH", "true")
        reset_env.setenv("ENCRYPTION_KEY", "real-key")

        with pytest.raises(RuntimeError, match="DISABLE_AUTH=true is not allowed"):
            _reload_config()

    def test_disable_auth_false_in_production_ok(self, reset_env):
        reset_env.setenv("ENV", "production")
        reset_env.setenv("DISABLE_AUTH", "false")
        reset_env.setenv("ENCRYPTION_KEY", "real-key")

        config = _reload_config()
        assert config.DISABLE_AUTH is False
        assert config.IS_PRODUCTION is True


class TestEncryptionKeyGate:
    def test_default_key_allowed_in_development(self, reset_env):
        reset_env.setenv("ENV", "development")

        config = _reload_config()
        assert config.ENCRYPTION_KEY == "dev-encryption-key-change-in-production"
        assert config.IS_PRODUCTION is False

    def test_explicit_key_used_in_development(self, reset_env):
        reset_env.setenv("ENV", "development")
        reset_env.setenv("ENCRYPTION_KEY", "my-custom-key")

        config = _reload_config()
        assert config.ENCRYPTION_KEY == "my-custom-key"

    def test_missing_key_refused_in_production(self, reset_env):
        reset_env.setenv("ENV", "production")

        with pytest.raises(RuntimeError, match="ENCRYPTION_KEY must be set"):
            _reload_config()

    def test_default_key_refused_in_production(self, reset_env):
        reset_env.setenv("ENV", "production")
        reset_env.setenv("ENCRYPTION_KEY", "dev-encryption-key-change-in-production")

        with pytest.raises(RuntimeError, match="ENCRYPTION_KEY must be set"):
            _reload_config()

    def test_real_key_accepted_in_production(self, reset_env):
        reset_env.setenv("ENV", "production")
        reset_env.setenv("ENCRYPTION_KEY", "a-real-random-key-from-secrets-token_urlsafe")

        config = _reload_config()
        assert config.ENCRYPTION_KEY == "a-real-random-key-from-secrets-token_urlsafe"


class TestEnvDefault:
    def test_env_defaults_to_development(self, reset_env):
        config = _reload_config()
        assert config.ENV == "development"
        assert config.IS_PRODUCTION is False

    def test_env_normalized_to_lowercase(self, reset_env):
        reset_env.setenv("ENV", "PRODUCTION")
        reset_env.setenv("ENCRYPTION_KEY", "real-key")

        config = _reload_config()
        assert config.ENV == "production"
        assert config.IS_PRODUCTION is True
