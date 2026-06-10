#!/usr/bin/env python3
"""macOS menu bar remote control for Devialet Expert amplifiers.

Shows the amp's state in the menu bar and provides power, volume, mute, and
source controls. Discovers the amp automatically via UDP status broadcasts.

Usage:
    pip3 install -r requirements.txt
    python3 devialet_menubar.py
"""

import asyncio
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from devialet_expert import NetworkController, MAX_VOLUME_INT  # noqa: E402

import rumps  # noqa: E402

# Consider the amp gone if no broadcast for this long (it sends ~every 300ms).
OFFLINE_AFTER_S = 10
UI_REFRESH_S = 1.0


class DevialetMenuBar(rumps.App):
    def __init__(self):
        super().__init__("Devialet", title="◎ —")
        self.loop = None
        self.device = None
        self._last_seen = 0.0
        self._sources_cache = []

        self.status_item = rumps.MenuItem("Searching for Devialet…")
        self.power_item = rumps.MenuItem("Turn On", callback=self.on_power)
        self.mute_item = rumps.MenuItem("Mute", callback=self.on_mute)
        self.vol_up_item = rumps.MenuItem(
            "Volume Up", callback=self.on_vol_up, key="+")
        self.vol_down_item = rumps.MenuItem(
            "Volume Down", callback=self.on_vol_down, key="-")
        self.vol_slider = rumps.SliderMenuItem(
            value=0, min_value=0, max_value=MAX_VOLUME_INT,
            callback=self.on_slider, dimensions=(180, 20))
        self.source_menu = rumps.MenuItem("Source")

        self.menu = [
            self.status_item,
            None,
            self.power_item,
            self.mute_item,
            None,
            self.vol_up_item,
            self.vol_down_item,
            self.vol_slider,
            None,
            self.source_menu,
            None,
        ]

        rumps.Timer(self.refresh, UI_REFRESH_S).start()
        threading.Thread(target=self._asyncio_thread, daemon=True).start()

    # ------------------------------------------------------------------
    # Background asyncio thread: UDP discovery + status
    # ------------------------------------------------------------------

    def _asyncio_thread(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._async_main())

    async def _async_main(self):
        nc = NetworkController()
        nc.add_listener_on_new_device(self._on_new_device)
        nc.add_listener_on_device_update(self._on_device_update)
        await nc.listen()
        # The status listener does all the work; just keep the loop alive.
        while True:
            await asyncio.sleep(3600)

    async def _on_new_device(self, device):
        if self.device is None:
            self.device = device
            self._last_seen = time.time()

    async def _on_device_update(self, device, new_state):
        # NetworkController mutates our Device object in place; we only
        # need to track liveness here. The UI timer reads the state.
        if self.device is not None and device.name == self.device.name:
            self._last_seen = time.time()

    # ------------------------------------------------------------------
    # UI refresh (runs on the main/Cocoa thread via rumps.Timer)
    # ------------------------------------------------------------------

    def refresh(self, _timer):
        device = self.device
        online = device is not None and (
            time.time() - self._last_seen < OFFLINE_AFTER_S)

        if not online:
            self.title = "◎ —"
            self.status_item.title = "Searching for Devialet…"
            return

        if device.power:
            db = (device.volume - 195) / 2.0
            self.title = f"◎ {db:g} dB" if not device.muted else "◎ muted"
        else:
            self.title = "◎ off"

        self.status_item.title = f"{device.name} @ {device.ip_address}"
        self.power_item.title = "Turn Off" if device.power else "Turn On"
        self.mute_item.title = "Unmute" if device.muted else "Mute"
        self.vol_slider.value = min(device.volume, MAX_VOLUME_INT)

        sources = device.get_sources()
        if sources != self._sources_cache:
            self._sources_cache = list(sources)
            self.source_menu.clear()
            for name in sources:
                self.source_menu.add(
                    rumps.MenuItem(name, callback=self.on_source))
        current = device.get_source()
        for name in self._sources_cache:
            self.source_menu[name].state = 1 if name == current else 0

    # ------------------------------------------------------------------
    # Menu callbacks (main thread) -> asyncio commands (background thread)
    # ------------------------------------------------------------------

    def _send(self, coro):
        if self.loop is not None:
            asyncio.run_coroutine_threadsafe(coro, self.loop)
        else:
            coro.close()

    def on_power(self, _item):
        if self.device:
            self._send(self.device.async_set_power_state(not self.device.power))

    def on_mute(self, _item):
        if self.device:
            self._send(self.device.async_mute(not self.device.muted))

    def on_vol_up(self, _item):
        if self.device:
            self._send(self.device.async_volume_up())

    def on_vol_down(self, _item):
        if self.device:
            self._send(self.device.async_volume_down())

    def on_slider(self, slider):
        if self.device:
            target = round(slider.value)
            if target != self.device.volume:
                self._send(self.device.async_set_volume_int(target))

    def on_source(self, item):
        if self.device:
            self._send(self.device.async_select_source(item.title))


if __name__ == '__main__':
    DevialetMenuBar().run()
