"""Hub client helpers (no network)."""

from __future__ import annotations

import pytest

from coup.hub_client import HubError, validate_full_name, validate_local_name


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
