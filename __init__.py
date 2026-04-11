"""Devialet Expert integration for Home Assistant."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .discovery import async_start_network_controller, async_stop_network_controller

PLATFORMS = [Platform.MEDIA_PLAYER]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Start the Devialet UDP discovery service."""
    await async_start_network_controller(hass)

    async def shutdown_event(event):
        await async_stop_network_controller(hass)

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, shutdown_event)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Devialet Expert config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Devialet Expert config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
