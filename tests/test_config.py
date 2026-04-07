from __future__ import annotations

import os
from pathlib import Path

import pytest

from twitter_cleaner.config import Config


class TestConfig:
    def test_username_from_env(self, monkeypatch):
        monkeypatch.setenv("TWITTER_USERNAME", "alice")
        assert Config().username == "alice"

    def test_username_empty_when_env_missing(self, monkeypatch):
        monkeypatch.delenv("TWITTER_USERNAME", raising=False)
        assert Config().username == ""

    def test_explicit_username(self):
        cfg = Config(username="bob")
        assert cfg.username == "bob"

    def test_defaults(self):
        cfg = Config(username="x")
        assert cfg.headless is False
        assert cfg.dry_run is False
        assert cfg.stealth is True
        assert cfg.min_delay == 3.0
        assert cfg.max_delay == 6.0

    def test_db_file_path(self):
        cfg = Config(state_dir=Path("/tmp/tc"))
        assert cfg.db_file == Path("/tmp/tc/progress.db")

    def test_session_file_path(self):
        cfg = Config(state_dir=Path("/tmp/tc"))
        assert cfg.session_file == Path("/tmp/tc/session.json")

    def test_ensure_state_dir_creates_directory(self, tmp_path):
        d = tmp_path / "new_state"
        cfg = Config(state_dir=d)
        cfg.ensure_state_dir()
        assert d.is_dir()

    def test_ensure_state_dir_idempotent(self, tmp_path):
        d = tmp_path / "state"
        cfg = Config(state_dir=d)
        cfg.ensure_state_dir()
        cfg.ensure_state_dir()  # should not raise
        assert d.is_dir()

    def test_validate_passes_with_username(self):
        Config(username="alice").validate()  # no exception

    def test_validate_raises_without_username(self, monkeypatch):
        monkeypatch.delenv("TWITTER_USERNAME", raising=False)
        with pytest.raises(ValueError, match="TWITTER_USERNAME"):
            Config().validate()

    def test_custom_delays(self):
        cfg = Config(username="x", min_delay=1.0, max_delay=2.0)
        assert cfg.min_delay == 1.0
        assert cfg.max_delay == 2.0

    def test_dry_run_flag(self):
        assert Config(username="x", dry_run=True).dry_run is True
