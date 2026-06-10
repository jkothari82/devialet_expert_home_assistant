#!/usr/bin/env python3
"""Command-line remote control for Devialet Expert amplifiers.

The quickest way to prove software control works. Discovers the amp via its
UDP status broadcasts, then sends commands over UDP.

Usage:
    python3 devialet_cli.py status              # discover and show state
    python3 devialet_cli.py on                  # power on
    python3 devialet_cli.py off                 # power off
    python3 devialet_cli.py mute                # mute
    python3 devialet_cli.py unmute              # unmute
    python3 devialet_cli.py vol 120             # set volume (0-175 int)
    python3 devialet_cli.py vol -- -30.5db      # set volume in dB
    python3 devialet_cli.py vol up              # one step up
    python3 devialet_cli.py vol down            # one step down
    python3 devialet_cli.py source "Optical 1"  # select input
    python3 devialet_cli.py watch               # stream state changes
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from devialet_expert import NetworkController  # noqa: E402

DISCOVERY_TIMEOUT_S = 10


async def discover_device(name=None, timeout=DISCOVERY_TIMEOUT_S):
    """Listen for status broadcasts until a Devialet is found.

    Returns (device, network_controller). The controller must be kept open
    while sending commands and closed by the caller.
    """
    nc = NetworkController()
    found = asyncio.Event()
    holder = {}

    async def on_new(device):
        if name and device.name != name:
            return
        holder['device'] = device
        found.set()

    nc.add_listener_on_new_device(on_new)
    await nc.listen()

    try:
        await asyncio.wait_for(found.wait(), timeout)
    except asyncio.TimeoutError:
        await nc.close()
        print(f"No Devialet found after {timeout}s. Check that:")
        print("  - The amp is plugged in (it broadcasts even in standby)")
        print("  - This machine is on the same network/VLAN as the amp")
        print("  - UDP port 45454 is not blocked or in use")
        sys.exit(1)

    return holder['device'], nc


async def wait_for_update(nc, device, timeout=2.0):
    """Wait briefly for the next status broadcast to confirm the command."""
    updated = asyncio.Event()

    async def on_update(dev, new_state):
        if dev.name == device.name and new_state:
            updated.set()

    nc.add_listener_on_device_update(on_update)
    try:
        await asyncio.wait_for(updated.wait(), timeout)
    except asyncio.TimeoutError:
        pass


def print_status(device):
    print(f"Name:    {device.name}")
    print(f"IP:      {device.ip_address}")
    print(f"Power:   {'on' if device.power else 'off'}")
    print(f"Volume:  {device.volume_as_int()} ({device.volume_as_db()})")
    print(f"Muted:   {device.muted}")
    print(f"Source:  {device.get_source()}")
    print(f"Sources: {', '.join(device.get_sources())}")


async def run(args):
    device, nc = await discover_device(name=args.device)

    try:
        if args.command == 'status':
            print_status(device)

        elif args.command == 'on':
            await device.async_turn_on()
            await wait_for_update(nc, device)
            print(f"Power: {'on' if device.power else 'off'}")

        elif args.command == 'off':
            await device.async_turn_off()
            await wait_for_update(nc, device)
            print(f"Power: {'on' if device.power else 'off'}")

        elif args.command == 'mute':
            await device.async_mute(True)
            await wait_for_update(nc, device)
            print(f"Muted: {device.muted}")

        elif args.command == 'unmute':
            await device.async_mute(False)
            await wait_for_update(nc, device)
            print(f"Muted: {device.muted}")

        elif args.command == 'vol':
            value = args.value
            if value == 'up':
                await device.async_volume_up()
            elif value == 'down':
                await device.async_volume_down()
            elif value.lower().endswith('db'):
                await device.async_set_volume_db(float(value[:-2]))
            else:
                await device.async_set_volume_int(int(value))
            await wait_for_update(nc, device)
            print(f"Volume: {device.volume_as_int()} ({device.volume_as_db()})")

        elif args.command == 'source':
            await device.async_select_source(args.value)
            await wait_for_update(nc, device)
            print(f"Source: {device.get_source()}")

        elif args.command == 'watch':
            print_status(device)
            print("--- watching for changes (Ctrl+C to stop) ---")
            changed = asyncio.Event()

            async def on_update(dev, new_state):
                if new_state:
                    changed.set()

            nc.add_listener_on_device_update(on_update)
            while True:
                await changed.wait()
                changed.clear()
                print(f"power={'on' if device.power else 'off'} "
                      f"vol={device.volume_as_int()} ({device.volume_as_db()}) "
                      f"muted={device.muted} source={device.get_source()}")
    finally:
        await nc.close()


def main():
    parser = argparse.ArgumentParser(
        description='Devialet Expert command-line remote')
    parser.add_argument('--device', '-d', default=None,
                        help='Device name (default: first one found)')
    parser.add_argument('--verbose', '-v', action='store_true')

    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('status', help='Show current state')
    sub.add_parser('on', help='Power on')
    sub.add_parser('off', help='Power off')
    sub.add_parser('mute', help='Mute')
    sub.add_parser('unmute', help='Unmute')
    vol = sub.add_parser('vol', help='Set volume: 0-175, "-30.5db", up, down')
    vol.add_argument('value')
    source = sub.add_parser('source', help='Select input source by name')
    source.add_argument('value')
    sub.add_parser('watch', help='Stream state changes')

    args = parser.parse_args()
    logging.basicConfig(level='DEBUG' if args.verbose else 'WARNING')

    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
