"""An unofficial remote control application for Devialet Expert amplifiers."""

import asyncio
import logging
import math
import socket
from typing import NamedTuple

logger = logging.getLogger(__name__)

STATUS_PORT = 45454
COMMAND_PORT = 45455
MAX_VOLUME_DB = -10
MAX_VOLUME_INT = 175
MIN_STATUS_PACKET_SIZE = 311


def _crc16(data: bytearray):
    """Calculate a CRC-16/CCITT-FALSE from the given bytearray."""
    if data is None:
        return 0
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if (crc & 0x8000) > 0:
                crc = (crc << 1) ^ 0x1021
            else:
                crc = crc << 1
    return crc & 0xFFFF


def _db_convert(db_value):
    """Internal function to convert dB to a 16-bit representation used by set_volume"""
    db_abs = math.fabs(db_value)
    if db_abs == 0:
        retval = 0
    elif db_abs == 0.5:
        retval = 0x3F00
    else:
        retval = (256 >> math.ceil(1 + math.log(db_abs, 2))) + _db_convert(db_abs - 0.5)
    return retval


class Source(NamedTuple):
    name: str
    index: int
    is_enabled: bool
    is_selected: bool


class Device:
    def __init__(self, status_data: bytearray, addr) -> None:
        if len(status_data) < MIN_STATUS_PACKET_SIZE:
            raise ValueError(
                f"Status packet too short: {len(status_data)} bytes "
                f"(need {MIN_STATUS_PACKET_SIZE})"
            )
        self.num_packets: int = 0
        self.num_commands: int = 0
        self.ip_address: str = addr[0]
        self.name: str = status_data[19:50].decode("UTF-8").replace("\x00", "")
        self.sources: list[Source] = []
        self.source: int = (status_data[308] & 0x3C) >> 2
        for i in range(0, 15):
            is_enabled = int(chr(status_data[52 + i * 17]))
            is_selected = i == self.source
            name = (
                status_data[53 + i * 17 : 52 + (i + 1) * 17]
                .decode("UTF-8")
                .replace("\x00", "")
            )
            self.sources.append(Source(name, i, is_enabled, is_selected))
        self.power: bool = (status_data[307] & 0x80) != 0
        self.muted: bool = (status_data[308] & 0x2) != 0
        self.volume: int = status_data[310]

    def update(self, device_update) -> bool:
        """Update this Device object based on a newer UDP status update, provided as a Device.

        Returns True if the update contains any new information.
        """
        has_updated = False
        if device_update.name != self.name:
            # Device name mismatch. Exit early.
            return False
        if device_update.ip_address != self.ip_address:
            self.ip_address = device_update.ip_address
            has_updated = True
        if device_update.source != self.source:
            self.source = device_update.source
            has_updated = True
        if device_update.power != self.power:
            self.power = device_update.power
            has_updated = True
        if device_update.muted != self.muted:
            self.muted = device_update.muted
            has_updated = True
        if device_update.volume != self.volume:
            self.volume = device_update.volume
            has_updated = True
        # Always take the latest source list - these should change, expect for the is_selected indicator. However, that state is tracked above in self.source.
        self.sources = device_update.sources
        return has_updated

    def get_sources(self):
        return [s.name for s in self.sources if s.is_enabled]

    def get_source(self):
        return self.sources[self.source].name

    def volume_as_int(self):
        return self.volume

    def volume_as_float(self):
        """Volume as a float 0-1."""
        return self.volume / 255

    def volume_as_db(self):
        return f"{(self.volume - 195) / 2.0}dB"

    def __repr__(self) -> str:
        return f'Devialet Expert "{self.name}" at {self.ip_address}. Volume: {self.volume_as_int()} {self.volume_as_db()} {self.volume_as_float()} Power: {self.power} Muted: {self.muted} Curr Source: {self.get_source()}'

    async def async_turn_on(self):
        await self.async_set_power_state(True)

    async def async_turn_off(self):
        await self.async_set_power_state(False)

    async def async_toggle_power(self):
        await self.async_set_power_state(not self.power)

    async def async_set_power_state(self, power_state):
        data = bytearray(142)
        data[6] = int(power_state)
        data[7] = 0x01
        await self.async_send_command(data)

    async def async_mute(self, mute_state):
        data = bytearray(142)
        data[6] = int(mute_state)
        data[7] = 0x07
        await self.async_send_command(data)

    async def async_volume_up(self):
        await self.async_set_volume_int(self.volume + 1)

    async def async_volume_down(self):
        await self.async_set_volume_int(self.volume - 1)

    async def async_set_volume_float(self, volume_float):
        if volume_float > 1:
            volume_float = 1
        elif volume_float < 0:
            volume_float = 0
        volume = round(volume_float * 255)
        await self.async_set_volume_int(volume)

    async def async_set_volume_int(self, volume):
        volume = max(0, min(volume, MAX_VOLUME_INT))
        await self.async_set_volume_db((volume - 195) / 2.0)

    async def async_set_volume_db(self, volume_db):
        if volume_db > MAX_VOLUME_DB:
            volume_db = MAX_VOLUME_DB

        volume = _db_convert(volume_db)

        if volume_db < 0:
            volume |= 0x8000

        data = bytearray(142)
        data[6] = 0x00
        data[7] = 0x04
        data[8] = (volume & 0xFF00) >> 8
        data[9] = volume & 0x00FF
        await self.async_send_command(data)

    async def async_select_source(self, new_source_name):
        logger.debug(f"Selecting source {new_source_name}")
        
        new_source = None
        for s in self.sources:
            if s.name == new_source_name:
                new_source = s
                break

        if new_source is None:
            raise ValueError(f"Invalid source {new_source_name}. Options: {self.get_sources()}")

        out_val = 0x4000 | (new_source.index << 5)
        data = bytearray(142)
        data[6] = 0x00
        data[7] = 0x05
        data[8] = (out_val & 0xFF00) >> 8
        if new_source.index > 7:
            data[9] = (out_val & 0x00FF) >> 1
        else:
            data[9] = out_val & 0x00FF
        await self.async_send_command(data)

    async def async_send_command(self, command: bytearray, times: int = 2):
        loop = asyncio.get_running_loop()

        on_close = loop.create_future()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: SendCommandProtocol(command, on_close, times, self),
            remote_addr=(self.ip_address, COMMAND_PORT),
        )

        try:
            await on_close
        finally:
            transport.close()


class SendCommandProtocol:
    def __init__(self, command, on_close, times, device):
        self.command = command
        self.on_close = on_close
        self.times = times
        self.device = device
        self.transport = None

    def prepare_command(self):
        self.command[0] = 0x44
        self.command[1] = 0x72

        if self.device.num_packets > 0xFFFF:
            self.device.num_packets = 0
        if self.device.num_commands > 0xFFFF:
            self.device.num_commands = 0

        self.command[2] = (self.device.num_packets & 0xFF00) >> 8
        self.command[3] = self.device.num_packets & 0x00FF
        self.command[4] = (self.device.num_commands & 0xFF00) >> 8
        self.command[5] = self.device.num_commands & 0x00FF

        crc = _crc16(self.command[0:12])
        self.command[12] = (crc & 0xFF00) >> 8
        self.command[13] = crc & 0x00FF

    def connection_made(self, transport):
        self.transport = transport
        for _ in range(self.times):
            self.prepare_command()
            self.device.num_packets += 1
            self.transport.sendto(self.command)
        self.device.num_commands += 1

    def datagram_received(self, data, addr):
        logger.debug("Unexpected response from device")

    def error_received(self, exc):
        logger.error("Error sending command: %s", exc)

    def connection_lost(self, exc):
        if not self.on_close.done():
            self.on_close.set_result(True)


class StatusProtocol:
    def __init__(self, network_controller) -> None:
        self.network_controller = network_controller

    def connection_made(self, transport):
        self.transport = transport

    def connection_lost(self, transport):
        logger.info("Connection lost")
        # pass

    def error_received(self, exc):
        logger.info("Error")
        # pass

    def datagram_received(self, data, addr):
        # logger.info("datagram_received")
        asyncio.ensure_future(self.network_controller.async_on_status(data, addr))
        # self.network_controller.on_status(Device(data, addr))


class NetworkController:
    def __init__(self) -> None:
        self.devices: dict[str, Device] = {}
        self.status_transport = None
        self.status_protocol = None
        self.on_new_device: list = []
        self.on_device_update: list = []

    async def async_on_status(self, data, addr):
        try:
            device_update = Device(data, addr)
        except (ValueError, UnicodeDecodeError) as exc:
            logger.debug("Ignoring malformed status packet from %s: %s",
                         addr, exc)
            return

        callbacks = []
        if device_update.name not in self.devices:
            self.devices[device_update.name] = device_update
            for listener in self.on_new_device:
                callbacks.append(listener(device_update))
        else:
            new_state = self.devices[device_update.name].update(device_update)
            for listener in self.on_device_update:
                callbacks.append(
                    listener(self.devices[device_update.name], new_state))
        await asyncio.gather(*callbacks)

    async def listen(self):
        """Start a UDP listener for Devialet status broadcasts."""
        logger.info("Starting Devialet UDP status listener on port %d",
                     STATUS_PORT)
        loop = asyncio.get_running_loop()
        (
            self.status_transport,
            self.status_protocol,
        ) = await loop.create_datagram_endpoint(
            lambda: StatusProtocol(self),
            allow_broadcast=True,
            local_addr=("0.0.0.0", STATUS_PORT),
            family=socket.AF_INET,
        )

    async def close(self):
        """Stop the UDP listener."""
        if self.status_transport:
            self.status_transport.close()
            self.status_transport = None
            self.status_protocol = None
            logger.info("Stopped Devialet UDP status listener")

    def add_listener_on_new_device(self, callback):
        self.on_new_device.append(callback)

    def add_listener_on_device_update(self, callback):
        self.on_device_update.append(callback)

    def get_devices(self):
        return list(self.devices.values())
