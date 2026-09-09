"""Per-source address/name keying — the parsing that decides what matches."""

from __future__ import annotations

from sica_core.ingest.overlays import (
    _coop_addr_key,
    _rezoning_addr_key,
    _sro_addr_key,
)
from sica_core.normalize import addr_key_from_freeform


def test_coop_key_strips_everything_after_first_comma():
    assert _coop_addr_key(
        "100 Main St, Vancouver, BC V6A 1A1"
    ) == addr_key_from_freeform("100 Main St")


def test_sro_key_is_the_address_verbatim():
    assert _sro_addr_key("210 Abbott St.") == addr_key_from_freeform("210 Abbott St.")


def test_rezoning_key_strips_paren_and_splits_on_and():
    # "2165-2195 and 2205-2291 W 45th Av (Dunbar Ryerson United Church)"
    key = _rezoning_addr_key(
        "2165-2195 and 2205-2291 W 45th Av (Dunbar Ryerson United Church)"
    )
    assert key == addr_key_from_freeform("2165-2195")


def test_rezoning_key_splits_on_ampersand_and_semicolon():
    assert _rezoning_addr_key("300 Pine St & 302 Pine St") == addr_key_from_freeform(
        "300 Pine St"
    )
    assert _rezoning_addr_key("300 Pine St; 302 Pine St") == addr_key_from_freeform(
        "300 Pine St"
    )


def test_rezoning_key_plain_name_untouched():
    assert _rezoning_addr_key("300 Pine St (Tower)") == addr_key_from_freeform(
        "300 Pine St"
    )
