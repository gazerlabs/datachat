"""Tests for user-id sanitization in local_duckdb_persistent.get_user_db_path.

The function builds a filesystem path under base_dir from the user_id. If a
user_id ever contained path-traversal characters, the file could land outside
base_dir. Replace-based scrubbing didn't survive all permutations; the new
strict allowlist rejects anything outside [A-Za-z0-9_-]."""

import os

import pytest

from app.connections.local_duckdb_persistent import get_user_db_path


class TestPathSafety:
    def test_clerk_id_accepted(self, tmp_path):
        path = get_user_db_path(str(tmp_path), "user_2abcDEF123")
        assert path.startswith(str(tmp_path))
        assert path.endswith("user_2abcDEF123.duckdb")

    def test_dev_user_accepted(self, tmp_path):
        path = get_user_db_path(str(tmp_path), "dev_user")
        assert path.endswith("dev_user.duckdb")

    def test_test_fixture_id_accepted(self, tmp_path):
        path = get_user_db_path(str(tmp_path), "test-user-1")
        assert path.endswith("test-user-1.duckdb")

    @pytest.mark.parametrize(
        "evil",
        [
            "../etc/passwd",
            "....//....//etc/passwd",
            "/absolute/path",
            "foo/bar",
            "foo\\bar",
            "foo.bar",
            "",
            "user\x00bad",
            "user with space",
            "user;rm -rf /",
        ],
    )
    def test_rejects_path_unsafe_id(self, tmp_path, evil):
        with pytest.raises(ValueError, match="Invalid user_id"):
            get_user_db_path(str(tmp_path), evil)

    def test_safe_path_stays_under_base_dir(self, tmp_path):
        # Property check: for any accepted id, the resolved path is under base_dir.
        accepted_ids = [
            "user_abc",
            "ABC123",
            "test-user-99",
            "X" * 200,  # long but charset-clean is fine
        ]
        for uid in accepted_ids:
            resolved = get_user_db_path(str(tmp_path), uid)
            assert os.path.abspath(resolved).startswith(
                os.path.abspath(str(tmp_path))
            )
