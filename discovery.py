"""Discovery service for Devialet Expert."""
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    DATA_NETWORK_CONTROLLER,
    DISPATCH_DEVICE_DISCOVERED,
    DISPATCH_DEVICE_UPDATE,
)
from .devialet_expert import NetworkController

_LOGGER = logging.getLogger(__name__)


async def async_start_network_controller(hass: HomeAssistant):
    """Start the Devialet Expert network controller."""
    if nc := hass.data.get(DATA_NETWORK_CONTROLLER):
        # Already started
        return nc
    _LOGGER.info("Starting Devialet Expert Network Controller")

    nc = NetworkController()
    hass.data[DATA_NETWORK_CONTROLLER] = nc

    async def on_new_device(device):
        async_dispatcher_send(hass, DISPATCH_DEVICE_DISCOVERED, device)

    async def on_device_update(device, new_state):
        async_dispatcher_send(hass, DISPATCH_DEVICE_UPDATE, device, new_state)

    nc.add_listener_on_new_device(on_new_device)
    nc.add_listener_on_device_update(on_device_update)
    await nc.listen()

    return nc


async def async_stop_network_controller(hass: HomeAssistant):
    """Stop the network controller."""
    if not (nc := hass.data.get(DATA_NETWORK_CONTROLLER)):
        return

    await nc.close()
    del hass.data[DATA_NETWORK_CONTROLLER]

    _LOGGER.info("Stopped Devialet Expert Network Controller")
