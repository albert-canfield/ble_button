# /config/custom_components/ble_button/clicks.py

from __future__ import annotations

import time
from collections.abc import Callable, Hashable
from datetime import datetime

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from .const import (
    CLICK_DOUBLE,
    CLICK_LONG,
    CLICK_SINGLE,
    CLICK_TRIPLE,
    HOLD_MAX_EXTRA_WAIT,
    HOLD_REPEAT_GAP,
    LONG_PRESS_FALLBACK_WINDOW,
    LONG_PRESS_TIME,
)

_CLICK_TYPE_BY_COUNT = {1: CLICK_SINGLE, 2: CLICK_DOUBLE}
_MIN_RECHECK = 0.05


class ClickDetector:
    """Turn presses into single / double / triple / long clicks.

    Brand-independent rules:
    - Presses are counted until the button stays quiet for ``window`` seconds;
      the count becomes the click type (3 or more is a triple click).
    - Long press: many buttons keep repeating the packet of a press while it
      is held. When every advert is reported through ``note_activity``
      (``tracks_activity``), one receiver hearing the current press's packet
      repeat for LONG_PRESS_TIME is a long press. Spans are measured per
      receiver, so proxies that deliver late can't stretch a short click.

    A button profile (decoder.py) can add certainty on top: exact press counts
    (``certain=True``) and the button's own long-press flag (``long_press``).
    Without per-advert tracking, profiles that flag long presses get a longer
    window (LONG_PRESS_FALLBACK_WINDOW) so a hold isn't reported as a single.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        window: float,
        on_click: Callable[[str], None],
    ) -> None:
        self._hass = hass
        self._window = window
        self._on_click = on_click
        self.tracks_activity = False
        self._count = 0
        self._may_be_held = False
        self._holding = False
        self._press_key: Hashable | None = None
        # Receiver -> [first, last] time it heard the current press's packet.
        self._heard: dict[str, list[float]] = {}
        self._window_closed_at: float | None = None
        self._cancel_window: CALLBACK_TYPE | None = None

    @property
    def counting(self) -> bool:
        """Whether a click sequence is in progress."""
        return self._count > 0

    @property
    def spans(self) -> dict[str, float]:
        """How long each receiver has heard the current press's packet."""
        return {source: round(last - first, 3) for source, (first, last) in self._heard.items()}

    @callback
    def note_activity(self, source: str, key: Hashable) -> None:
        """Record one advert (repeats included) heard by ``source``."""
        if key != self._press_key:
            return
        now = time.monotonic()
        heard = self._heard.get(source)
        if heard is None or now - heard[1] > HOLD_REPEAT_GAP:
            self._heard[source] = [now, now]
            return
        heard[1] = now
        if self._count and heard[1] - heard[0] >= LONG_PRESS_TIME:
            self.long_press()

    @callback
    def press(
        self,
        presses: int,
        key: Hashable,
        source: str,
        *,
        certain: bool = False,
        may_be_held: bool = False,
    ) -> bool:
        """Count presses; False if this is just a payload change during a hold."""
        now = time.monotonic()
        if self._holding:
            if not certain and self._still_hearing(now):
                return False
            self._holding = False

        self._count += presses
        self._may_be_held = self._may_be_held or may_be_held
        self._press_key = key
        self._heard = {source: [now, now]}
        self._window_closed_at = None

        window = self._window
        if self._may_be_held and not self.tracks_activity:
            window = max(window, LONG_PRESS_FALLBACK_WINDOW)
        self._schedule(window)
        return True

    @callback
    def long_press(self) -> None:
        """Report a long press (once per hold), dropping counted presses."""
        if self._holding:
            return
        self.cancel()
        self._holding = True
        self._on_click(CLICK_LONG)

    @callback
    def cancel(self) -> None:
        """Forget the current sequence without reporting it."""
        self._stop_timer()
        self._count = 0
        self._may_be_held = False
        self._window_closed_at = None

    def _repeating(self, now: float) -> list[float]:
        """Last-heard times of receivers still hearing this press repeat."""
        return [
            last
            for first, last in self._heard.values()
            if last > first and now - last < HOLD_REPEAT_GAP
        ]

    def _still_hearing(self, now: float) -> bool:
        return bool(self._repeating(now))

    @callback
    def _async_window_closed(self, _now: datetime) -> None:
        self._cancel_window = None
        now = time.monotonic()
        if self._window_closed_at is None:
            self._window_closed_at = now

        if (
            self.tracks_activity
            and self._still_hearing(now)
            and now - self._window_closed_at < HOLD_MAX_EXTRA_WAIT
        ):
            # A receiver still hears this press repeating: it may be held.
            # Wait until it either reaches LONG_PRESS_TIME or goes quiet.
            quiet_at = min(self._repeating(now)) + HOLD_REPEAT_GAP
            self._schedule(max(quiet_at - now, _MIN_RECHECK))
            return

        count = self._count
        self.cancel()
        if count:
            self._on_click(_CLICK_TYPE_BY_COUNT.get(count, CLICK_TRIPLE))

    @callback
    def _schedule(self, delay: float) -> None:
        self._stop_timer()
        self._cancel_window = async_call_later(
            self._hass, delay, self._async_window_closed
        )

    @callback
    def _stop_timer(self) -> None:
        if self._cancel_window is not None:
            self._cancel_window()
            self._cancel_window = None
