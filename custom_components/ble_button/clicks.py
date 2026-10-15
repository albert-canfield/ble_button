# /config/custom_components/ble_button/clicks.py

from __future__ import annotations

import time
from collections.abc import Callable
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


class ClickDetector:
    """Turn presses into single / double / triple / long clicks.

    Brand-independent rules:
    - Presses are counted until the button stays quiet for ``window`` seconds;
      the count becomes the click type (3 or more is a triple click).
    - Long press: many buttons keep repeating their packet while held. When
      every advert is reported through ``note_activity`` (``tracks_activity``),
      a button still transmitting LONG_PRESS_TIME after a press is held: that
      is a long press, and payload changes during the hold aren't new presses.

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
        self._last_activity = 0.0
        self._continuous = False
        self._repeats = 0
        self._window_closed_at: float | None = None
        self._cancel_window: CALLBACK_TYPE | None = None
        self._cancel_hold_check: CALLBACK_TYPE | None = None

    @callback
    def note_activity(self) -> None:
        """Record one advert from the button (repeats included)."""
        now = time.monotonic()
        if now - self._last_activity > HOLD_REPEAT_GAP:
            # The button went quiet in between: any hold is over.
            self._continuous = False
            self._holding = False
        self._last_activity = now
        self._repeats += 1

    @callback
    def press(
        self, presses: int = 1, *, certain: bool = False, may_be_held: bool = False
    ) -> bool:
        """Count presses; False if this is just a payload change during a hold."""
        if self._holding:
            if not certain:
                return False
            self._holding = False

        now = time.monotonic()
        self._count += presses
        self._may_be_held = self._may_be_held or may_be_held
        self._last_activity = now
        self._continuous = True
        self._repeats = 0
        self._window_closed_at = None

        window = self._window
        if self._may_be_held and not self.tracks_activity:
            window = max(window, LONG_PRESS_FALLBACK_WINDOW)
        self._cancel_window = self._restart(
            self._cancel_window, window, self._async_window_closed
        )
        if self.tracks_activity:
            self._cancel_hold_check = self._restart(
                self._cancel_hold_check, LONG_PRESS_TIME, self._async_hold_check
            )
        return True

    @callback
    def long_press(self) -> None:
        """Report a long press (once per hold), dropping counted presses."""
        if self._holding:
            return
        self._stop_timers()
        self._count = 0
        self._may_be_held = False
        self._holding = True
        self._on_click(CLICK_LONG)

    @callback
    def cancel(self) -> None:
        """Forget the current sequence without reporting it."""
        self._stop_timers()
        self._count = 0
        self._may_be_held = False
        self._window_closed_at = None

    def _still_transmitting(self, now: float) -> bool:
        return now - self._last_activity < HOLD_REPEAT_GAP

    @callback
    def _async_hold_check(self, _now: datetime) -> None:
        self._cancel_hold_check = None
        if self._continuous and self._still_transmitting(time.monotonic()):
            self.long_press()

    @callback
    def _async_window_closed(self, _now: datetime) -> None:
        self._cancel_window = None
        now = time.monotonic()
        if self._window_closed_at is None:
            self._window_closed_at = now

        if (
            self._cancel_hold_check is not None
            and self._repeats
            and self._still_transmitting(now)
            and now - self._window_closed_at < HOLD_MAX_EXTRA_WAIT
        ):
            # Repeating since the press and the long-press check hasn't run:
            # it may be held. Wait for that check (or the button's own
            # long-press flag), or for the repeats to stop.
            self._cancel_window = self._restart(
                None,
                HOLD_REPEAT_GAP - (now - self._last_activity),
                self._async_window_closed,
            )
            return

        count = self._count
        self.cancel()
        if count:
            self._on_click(_CLICK_TYPE_BY_COUNT.get(count, CLICK_TRIPLE))

    def _restart(
        self,
        cancel: CALLBACK_TYPE | None,
        delay: float,
        action: Callable[[datetime], None],
    ) -> CALLBACK_TYPE:
        if cancel is not None:
            cancel()
        return async_call_later(self._hass, delay, action)

    @callback
    def _stop_timers(self) -> None:
        for cancel in (self._cancel_window, self._cancel_hold_check):
            if cancel is not None:
                cancel()
        self._cancel_window = None
        self._cancel_hold_check = None
