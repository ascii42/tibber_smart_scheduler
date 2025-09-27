"""Constants for Tibber Smart Scheduler."""

DOMAIN = "tibber_smart_scheduler"
CONF_TIBBER_SENSOR = "tibber_sensor"

# Platforms - MUST include sensor for the new entities
PLATFORMS = ["switch", "sensor"]

# Device modes
DEVICE_MODES = {
    "active_scheduler": "Active Scheduler",
    "smart_delay": "Smart Delay", 
    "price_protection": "Price Protection",
    "hybrid": "Hybrid Mode",
    "monitor_only": "Monitor Only"
}
