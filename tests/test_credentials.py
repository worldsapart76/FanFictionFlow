"""
Unit tests for orchestrator/credentials.py — Milestone 6 supplement.

All file I/O uses tmp_path; config.AO3_PERSONAL_INI_PATH is patched so
no real file is touched.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from orchestrator import credentials


def _patch_ini_path(tmp_path: Path):
    """Return a patch context that redirects the credentials file to tmp_path."""
    ini = tmp_path / "personal.ini"
    return patch("orchestrator.config.AO3_PERSONAL_INI_PATH", ini)


# ---------------------------------------------------------------------------
# read_ao3_credentials
# ---------------------------------------------------------------------------

class TestReadAo3Credentials:
    def test_returns_none_when_file_missing(self, tmp_path):
        with _patch_ini_path(tmp_path):
            assert credentials.read_ao3_credentials() is None

    def test_returns_none_when_section_missing(self, tmp_path):
        ini = tmp_path / "personal.ini"
        ini.write_text("[other_site]\nusername=x\npassword=y\n")
        with _patch_ini_path(tmp_path):
            assert credentials.read_ao3_credentials() is None

    def test_returns_none_when_username_missing(self, tmp_path):
        ini = tmp_path / "personal.ini"
        ini.write_text("[archiveofourown.org]\npassword=secret\n")
        with _patch_ini_path(tmp_path):
            assert credentials.read_ao3_credentials() is None

    def test_returns_none_when_password_missing(self, tmp_path):
        ini = tmp_path / "personal.ini"
        ini.write_text("[archiveofourown.org]\nusername=myuser\n")
        with _patch_ini_path(tmp_path):
            assert credentials.read_ao3_credentials() is None

    def test_returns_none_when_username_blank(self, tmp_path):
        ini = tmp_path / "personal.ini"
        ini.write_text("[archiveofourown.org]\nusername=\npassword=secret\n")
        with _patch_ini_path(tmp_path):
            assert credentials.read_ao3_credentials() is None

    def test_returns_none_when_password_blank(self, tmp_path):
        ini = tmp_path / "personal.ini"
        ini.write_text("[archiveofourown.org]\nusername=myuser\npassword=\n")
        with _patch_ini_path(tmp_path):
            assert credentials.read_ao3_credentials() is None

    def test_returns_tuple_when_both_present(self, tmp_path):
        ini = tmp_path / "personal.ini"
        ini.write_text("[archiveofourown.org]\nusername=myuser\npassword=secret\n")
        with _patch_ini_path(tmp_path):
            result = credentials.read_ao3_credentials()
        assert result == ("myuser", "secret")

    def test_strips_whitespace(self, tmp_path):
        ini = tmp_path / "personal.ini"
        ini.write_text("[archiveofourown.org]\nusername = myuser \npassword = secret \n")
        with _patch_ini_path(tmp_path):
            result = credentials.read_ao3_credentials()
        assert result == ("myuser", "secret")


# ---------------------------------------------------------------------------
# has_ao3_credentials
# ---------------------------------------------------------------------------

class TestHasAo3Credentials:
    def test_false_when_file_missing(self, tmp_path):
        with _patch_ini_path(tmp_path):
            assert credentials.has_ao3_credentials() is False

    def test_false_when_credentials_incomplete(self, tmp_path):
        ini = tmp_path / "personal.ini"
        ini.write_text("[archiveofourown.org]\nusername=myuser\n")
        with _patch_ini_path(tmp_path):
            assert credentials.has_ao3_credentials() is False

    def test_true_when_both_present(self, tmp_path):
        ini = tmp_path / "personal.ini"
        ini.write_text("[archiveofourown.org]\nusername=myuser\npassword=secret\n")
        with _patch_ini_path(tmp_path):
            assert credentials.has_ao3_credentials() is True


# ---------------------------------------------------------------------------
# write_ao3_credentials
# ---------------------------------------------------------------------------

class TestWriteAo3Credentials:
    def test_creates_file_when_missing(self, tmp_path):
        with _patch_ini_path(tmp_path):
            credentials.write_ao3_credentials("user1", "pass1")
        ini = tmp_path / "personal.ini"
        assert ini.exists()

    def test_creates_parent_dir_when_missing(self, tmp_path):
        nested = tmp_path / "a" / "b" / "personal.ini"
        with patch("orchestrator.config.AO3_PERSONAL_INI_PATH", nested):
            credentials.write_ao3_credentials("user1", "pass1")
        assert nested.exists()

    def test_written_credentials_are_readable(self, tmp_path):
        with _patch_ini_path(tmp_path):
            credentials.write_ao3_credentials("user1", "pass1")
            result = credentials.read_ao3_credentials()
        assert result == ("user1", "pass1")

    def test_sets_is_adult_true(self, tmp_path):
        import configparser
        ini = tmp_path / "personal.ini"
        with _patch_ini_path(tmp_path):
            credentials.write_ao3_credentials("user1", "pass1")
        cfg = configparser.ConfigParser()
        cfg.read(ini)
        assert cfg.get("archiveofourown.org", "is_adult") == "true"

    def test_overwrites_existing_credentials(self, tmp_path):
        with _patch_ini_path(tmp_path):
            credentials.write_ao3_credentials("old_user", "old_pass")
            credentials.write_ao3_credentials("new_user", "new_pass")
            result = credentials.read_ao3_credentials()
        assert result == ("new_user", "new_pass")

    def test_preserves_other_keys_in_section(self, tmp_path):
        import configparser
        ini = tmp_path / "personal.ini"
        ini.write_text("[archiveofourown.org]\nextra_key = preserved\n")
        with _patch_ini_path(tmp_path):
            credentials.write_ao3_credentials("user1", "pass1")
        cfg = configparser.ConfigParser()
        cfg.read(ini)
        assert cfg.get("archiveofourown.org", "extra_key") == "preserved"

    def test_preserves_other_sections(self, tmp_path):
        import configparser
        ini = tmp_path / "personal.ini"
        ini.write_text("[other_site]\nkey = value\n")
        with _patch_ini_path(tmp_path):
            credentials.write_ao3_credentials("user1", "pass1")
        cfg = configparser.ConfigParser()
        cfg.read(ini)
        assert cfg.has_section("other_site")
        assert cfg.get("other_site", "key") == "value"
