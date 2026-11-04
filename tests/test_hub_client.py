"""Hub client helpers (no network)."""

from __future__ import annotations

import os

import pytest

from coup.hub_client import (
    HubError,
    load_repo_dotenv,
    new_player_uid,
    validate_full_name,
    validate_local_name,
    validate_player_uid,
)


def test_load_repo_dotenv_does_not_override(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "COUP_MASTER_URL=https://example.test\nCOUP_MASTER_API_KEY=from-file\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("COUP_MASTER_API_KEY", "already-set")
    monkeypatch.delenv("COUP_MASTER_URL", raising=False)
    load_repo_dotenv(env_file)
    assert os.environ["COUP_MASTER_URL"] == "https://example.test"
    assert os.environ["COUP_MASTER_API_KEY"] == "already-set"


def test_name_charset():
    validate_local_name("Milo_1-bot")
    with pytest.raises(HubError):
        validate_local_name("bad name")
    with pytest.raises(HubError):
        validate_local_name("bad.name")
    with pytest.raises(HubError):
        validate_local_name("-leading")
    with pytest.raises(HubError):
        validate_local_name("template")


def test_full_name():
    validate_full_name("Ada Lovelace")
    validate_full_name("Mary-Jane O'Brien")
    validate_full_name("Jean Claude Van Damme")
    with pytest.raises(HubError, match="first and last name"):
        validate_full_name("")
    with pytest.raises(HubError, match="last name"):
        validate_full_name("Ada")
    with pytest.raises(HubError, match="letters, spaces"):
        validate_full_name("Ada_Lovelace")


def test_player_uid():
    uid = new_player_uid()
    assert uid.startswith("p_")
    validate_player_uid(uid)
    with pytest.raises(HubError, match="required"):
        validate_player_uid("")
    with pytest.raises(HubError, match="p_"):
        validate_player_uid("u_" + ("0" * 24))
    with pytest.raises(HubError, match="hex"):
        validate_player_uid("p_ABCDEF0123456789abcdef01")
