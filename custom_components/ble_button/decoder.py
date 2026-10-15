# /config/custom_components/ble_button/decoder.py

"""Decoders for buttons whose advertisement says more than "I was pressed".

Without a decoder every changed advertisement counts as one press. With one,
the press counter in the payload tells presses apart (and reveals presses that
were missed), and a long-press flag can be reported as such.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DecodedAdvert:
    """What a known button format tells us about one advertisement."""

    protocol: str
    counter: int
    long_press: bool


# Manufacturer ID 0x5348 ("HS"), 14-byte payload, captured from a real button:
#
#   43 58 | 33 59 aa 38 c1 a4 | 0b | 14 | 01 00 00 | 34
#   "CX"  | MAC, reversed      | ?  | flags         | press counter
#
# Every press increments the counter (the button repeats each packet a few
# times). Holding the button ~2.5 s re-sends the same counter with flag bit
# 0x80 set (0x14 -> 0x84).
HS_MANUFACTURER_ID = 0x5348
HS_PAYLOAD_LENGTH = 14
HS_PREFIX = b"CX"
HS_FLAGS_INDEX = 9
HS_COUNTER_INDEX = 13
HS_LONG_PRESS_FLAG = 0x80


def decode(manufacturer_data: Mapping[int, bytes]) -> DecodedAdvert | None:
    """Decode a known button advertisement, or None for unknown formats."""
    payload = manufacturer_data.get(HS_MANUFACTURER_ID)
    if (
        payload is not None
        and len(payload) == HS_PAYLOAD_LENGTH
        and payload.startswith(HS_PREFIX)
    ):
        return DecodedAdvert(
            protocol="hs_counter",
            counter=payload[HS_COUNTER_INDEX],
            long_press=bool(payload[HS_FLAGS_INDEX] & HS_LONG_PRESS_FLAG),
        )
    return None
