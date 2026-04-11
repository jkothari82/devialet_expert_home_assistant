"""Constants for the Devialet Expert integration."""
from typing import Final

DOMAIN: Final = "devialet_expert"
DEFAULT_SCAN_INTERVAL: Final = 5
UNAVAILABLE_TIMEOUT_S: Final = 60
MANUFACTURER: Final = "Devialet"
MODEL: Final = "Expert"

DATA_NETWORK_CONTROLLER = "devialet_expert_network_controller"

DISPATCH_DEVICE_DISCOVERED = "devialet_expert_device_discovered"
DISPATCH_DEVICE_UPDATE = "devialet_expert_device_update"
