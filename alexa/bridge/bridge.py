"""Local bridge between AWS IoT Core and Devialet Expert amplifiers.

Runs on the local network (Raspberry Pi, NAS, any always-on Linux box) and:
  1. Discovers Devialet Expert devices via UDP broadcast
  2. Reports device state to AWS IoT Device Shadow
  3. Receives commands from IoT Shadow delta and forwards them to the Devialet

Usage:
    python bridge.py --config config.yaml
"""

import argparse
import asyncio
import json
import logging
import signal
import sys
from pathlib import Path

# Allow importing devialet_expert from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from devialet_expert import NetworkController, Device  # noqa: E402

from awscrt import io, mqtt  # noqa: E402
from awsiot import mqtt_connection_builder  # noqa: E402
from awsiot.iotshadow import (  # noqa: E402
    IotShadowClient,
    ShadowDeltaUpdatedSubscriptionRequest,
    ShadowState,
    UpdateShadowRequest,
)

import yaml  # noqa: E402

logger = logging.getLogger('devialet-bridge')

MAX_VOLUME_INT = 175


class DevialetBridge:
    """Bridge between AWS IoT Core and local Devialet Expert devices."""

    def __init__(self, config):
        self.config = config
        self.thing_name = config['iot']['thing_name']
        self.mqtt_connection = None
        self.shadow_client = None
        self.network_controller = None
        self.device = None
        self.loop = None
        self._running = True

    # ------------------------------------------------------------------
    # AWS IoT
    # ------------------------------------------------------------------

    def connect_iot(self):
        """Establish MQTT connection to AWS IoT Core."""
        logger.info("Connecting to AWS IoT Core at %s ...",
                     self.config['iot']['endpoint'])

        event_loop_group = io.EventLoopGroup(1)
        host_resolver = io.DefaultHostResolver(event_loop_group)
        client_bootstrap = io.ClientBootstrap(event_loop_group, host_resolver)

        self.mqtt_connection = mqtt_connection_builder.mtls_from_path(
            endpoint=self.config['iot']['endpoint'],
            cert_filepath=self.config['iot']['cert_path'],
            pri_key_filepath=self.config['iot']['key_path'],
            ca_filepath=self.config['iot']['root_ca_path'],
            client_bootstrap=client_bootstrap,
            client_id=self.thing_name,
            clean_session=False,
            keep_alive_secs=30,
        )

        connect_future = self.mqtt_connection.connect()
        connect_future.result(timeout=10)
        logger.info("Connected to AWS IoT Core")

        self.shadow_client = IotShadowClient(self.mqtt_connection)
        self._subscribe_to_shadow_delta()

    def _subscribe_to_shadow_delta(self):
        """Subscribe to shadow delta events (desired != reported)."""
        logger.info("Subscribing to shadow delta for thing '%s' ...",
                     self.thing_name)

        future, _ = self.shadow_client.subscribe_to_shadow_delta_updated_events(
            request=ShadowDeltaUpdatedSubscriptionRequest(
                thing_name=self.thing_name,
            ),
            qos=mqtt.QoS.AT_LEAST_ONCE,
            callback=self._on_shadow_delta,
        )
        future.result(timeout=10)
        logger.info("Subscribed to shadow delta")

    def _on_shadow_delta(self, event):
        """Called from the CRT thread when the shadow delta changes."""
        try:
            delta = event.state
            logger.info("Shadow delta: %s", json.dumps(delta))

            if self.device is None:
                logger.warning("No Devialet device available; ignoring delta")
                return

            if self.loop is not None:
                asyncio.run_coroutine_threadsafe(
                    self._process_delta(delta), self.loop,
                )
        except Exception:
            logger.error("Error in shadow delta callback", exc_info=True)

    async def _process_delta(self, delta):
        """Translate shadow delta into Devialet UDP commands."""
        try:
            if 'power' in delta:
                logger.info("CMD power=%s", delta['power'])
                await self.device.async_set_power_state(delta['power'])

            if 'volume' in delta:
                vol = max(0, min(MAX_VOLUME_INT, int(delta['volume'])))
                logger.info("CMD volume=%d", vol)
                await self.device.async_set_volume_int(vol)

            if 'muted' in delta:
                logger.info("CMD mute=%s", delta['muted'])
                await self.device.async_mute(delta['muted'])

            if 'source' in delta:
                logger.info("CMD source=%s", delta['source'])
                try:
                    await self.device.async_select_source(delta['source'])
                except ValueError as exc:
                    logger.error("Invalid source: %s", exc)
        except Exception:
            logger.error("Error processing delta", exc_info=True)

    def update_shadow_reported(self, state):
        """Push the reported state to the IoT shadow."""
        try:
            request = UpdateShadowRequest(
                thing_name=self.thing_name,
                state=ShadowState(reported=state),
            )
            future = self.shadow_client.publish_update_shadow(
                request=request,
                qos=mqtt.QoS.AT_LEAST_ONCE,
            )
            future.result(timeout=10)
            logger.debug("Shadow reported state updated")
        except Exception:
            logger.error("Failed to update shadow", exc_info=True)

    # ------------------------------------------------------------------
    # Devialet
    # ------------------------------------------------------------------

    @staticmethod
    def _device_state(device):
        """Serialise a Device to a shadow-compatible dict."""
        return {
            'power': device.power,
            'volume': device.volume_as_int(),
            'muted': device.muted,
            'source': device.get_source(),
            'sources': device.get_sources(),
            'name': device.name,
            'ip_address': device.ip_address,
        }

    async def on_new_device(self, device):
        target = self.config.get('devialet', {}).get('device_name')
        if target and device.name != target:
            logger.info("Ignoring device '%s' (configured for '%s')",
                         device.name, target)
            return

        logger.info("Tracking Devialet '%s' at %s",
                     device.name, device.ip_address)
        self.device = device

        state = self._device_state(device)
        await asyncio.get_running_loop().run_in_executor(
            None, self.update_shadow_reported, state,
        )

    async def on_device_update(self, device, new_state):
        if self.device is None or device.name != self.device.name:
            return
        if not new_state:
            return  # heartbeat only, no state change

        logger.info("State: power=%s vol=%d muted=%s src=%s",
                     device.power, device.volume, device.muted,
                     device.get_source())

        state = self._device_state(device)
        await asyncio.get_running_loop().run_in_executor(
            None, self.update_shadow_reported, state,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self):
        """Start the bridge and run until stopped."""
        self.loop = asyncio.get_running_loop()

        # AWS IoT (blocking CRT calls, run in thread pool)
        await self.loop.run_in_executor(None, self.connect_iot)

        # Devialet UDP listener
        self.network_controller = NetworkController()
        self.network_controller.add_listener_on_new_device(self.on_new_device)
        self.network_controller.add_listener_on_device_update(
            self.on_device_update)
        await self.network_controller.listen()

        logger.info("Bridge running — listening for Devialet devices on LAN")

        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

        await self.network_controller.close()
        if self.mqtt_connection:
            self.mqtt_connection.disconnect().result(timeout=5)
        logger.info("Bridge stopped")

    def stop(self):
        self._running = False


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------

def load_config(path):
    with open(path, 'r') as fh:
        return yaml.safe_load(fh)


def main():
    parser = argparse.ArgumentParser(
        description='Devialet Expert <-> AWS IoT Bridge')
    parser.add_argument('--config', '-c', default='config.yaml',
                        help='Path to config file (default: config.yaml)')
    parser.add_argument('--log-level', '-l', default='INFO',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        help='Logging level')
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s %(name)s %(levelname)s %(message)s',
    )

    config = load_config(args.config)
    bridge = DevialetBridge(config)

    def on_signal(sig, _frame):
        logger.info("Received signal %s — shutting down", sig)
        bridge.stop()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    asyncio.run(bridge.run())


if __name__ == '__main__':
    main()
