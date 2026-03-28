"""
orchestrator/credentials.py — AO3 credential management.

Reads and writes AO3 login credentials in FanFicFare's personal.ini.
FanFicFare discovers this file automatically from the standard Windows
location; no CLI flag is needed.

The GUI settings dialog calls write_ao3_credentials() when the user saves
updated credentials. The sync flow calls has_ao3_credentials() at startup
to warn the user before attempting downloads.
"""

from __future__ import annotations

import configparser

from orchestrator import config

_SECTION = "archiveofourown.org"


def has_ao3_credentials() -> bool:
    """Return True if the personal.ini contains a non-empty username and password."""
    creds = read_ao3_credentials()
    return creds is not None


def read_ao3_credentials() -> tuple[str, str] | None:
    """
    Read AO3 username and password from personal.ini.

    Returns (username, password) if both are present, None otherwise.
    """
    path = config.AO3_PERSONAL_INI_PATH
    if not path.exists():
        return None
    cfg = configparser.ConfigParser()
    cfg.read(path, encoding="utf-8")
    if not cfg.has_section(_SECTION):
        return None
    username = cfg.get(_SECTION, "username", fallback="").strip()
    password = cfg.get(_SECTION, "password", fallback="").strip()
    if not username or not password:
        return None
    return (username, password)


def write_ao3_credentials(username: str, password: str) -> None:
    """
    Write AO3 credentials to personal.ini, creating the file and directory
    if they do not exist. Preserves any existing keys in the file.

    Also ensures is_adult=true is set, since it is required to download
    Mature/Explicit-rated stories on AO3.
    """
    path = config.AO3_PERSONAL_INI_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    cfg = configparser.ConfigParser()
    if path.exists():
        cfg.read(path, encoding="utf-8")
    if not cfg.has_section(_SECTION):
        cfg.add_section(_SECTION)

    cfg.set(_SECTION, "username", username)
    cfg.set(_SECTION, "password", password)
    cfg.set(_SECTION, "is_adult", "true")

    with path.open("w", encoding="utf-8") as fh:
        cfg.write(fh)
