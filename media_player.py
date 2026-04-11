"""Support for Devialet Expert integrated amplifiers."""
from __future__ import annotations

from datetime import datetime
import logging

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
)
from homeassistant.components.media_player.const import MediaPlayerState
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DATA_NETWORK_CONTROLLER,
    DISPATCH_DEVICE_DISCOVERED,
    DISPATCH_DEVICE_UPDATE,
    DOMAIN,
    MANUFACTURER,
    MODEL,
    UNAVAILABLE_TIMEOUT_S,
)
from .devialet_expert import Device

_LOGGER = logging.getLogger(__name__)

SUPPORT_DEVIALET = (
    MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.SELECT_SOURCE
)


async def async_setup_entry(
    hass: HomeAssistant, config: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Devialet Expert media player entities."""
    nc = hass.data[DATA_NETWORK_CONTROLLER]

    @callback
    def init_device(device: Device):
        """Register the Devialet device."""
        _LOGGER.info("Devialet device '%s' discovered", device.name)
        async_add_entities([DevialetDevice(device)])

    # Create entities for already-discovered devices.
    for device in nc.get_devices():
        init_device(device)

    # Listen for any devices discovered later.
    config.async_on_unload(
        async_dispatcher_connect(hass, DISPATCH_DEVICE_DISCOVERED, init_device)
    )


class DevialetDevice(MediaPlayerEntity):
    """Representation of a Devialet Expert amplifier."""

    _attr_device_class = MediaPlayerDeviceClass.RECEIVER
    _attr_should_poll = False
    _attr_icon = "mdi:amplifier"

    def __init__(self, device: Device) -> None:
        self._device = device
        self._last_update = datetime.now()

    @property
    def state(self) -> MediaPlayerState | None:
        if self._device.power:
            return MediaPlayerState.IDLE
        return MediaPlayerState.OFF

    @property
    def volume_step(self) -> float | None:
        return 1 / 255

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._device.name)},
            name=self._device.name,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    @property
    def available(self) -> bool:
        elapsed = (datetime.now() - self._last_update).total_seconds()
        return elapsed < UNAVAILABLE_TIMEOUT_S

    @property
    def name(self) -> str:
        return self._device.name

    @property
    def unique_id(self) -> str:
        return self._device.name

    @property
    def volume_level(self) -> float | None:
        return self._device.volume_as_float()

    @property
    def is_volume_muted(self) -> bool | None:
        return self._device.muted

    @property
    def source_list(self) -> list[str] | None:
        return self._device.get_sources()

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        return SUPPORT_DEVIALET

    @property
    def source(self) -> str | None:
        return self._device.get_source()

    async def async_added_to_hass(self) -> None:
        @callback
        def device_update(device: Device, new_state: bool) -> None:
            if self._device.name != device.name:
                return
            self._last_update = datetime.now()
            self.async_write_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, DISPATCH_DEVICE_UPDATE, device_update)
        )

    async def async_volume_up(self) -> None:
        await self._device.async_volume_up()

    async def async_volume_down(self) -> None:
        await self._device.async_volume_down()

    async def async_set_volume_level(self, volume: float) -> None:
        await self._device.async_set_volume_float(volume)

    async def async_mute_volume(self, mute: bool) -> None:
        await self._device.async_mute(mute)

    async def async_turn_off(self) -> None:
        await self._device.async_turn_off()

    async def async_turn_on(self) -> None:
        await self._device.async_turn_on()

    async def async_select_source(self, source: str) -> None:
        await self._device.async_select_source(source)
