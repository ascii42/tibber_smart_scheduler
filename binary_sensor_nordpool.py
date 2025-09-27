"""Binary sensor for nordpool_planner compatibility - Low Cost Period."""

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

class TibberLowCostBinarySensor(BinarySensorEntity):
    """Binary sensor indicating low cost period (like nordpool_planner)."""
    
    def __init__(self, coordinator, device_name: str):
        """Initialize the binary sensor."""
        self._coordinator = coordinator
        self._device_name = device_name
        self._attr_name = f"Tibber {device_name.title()} Low Cost"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{device_name}_low_cost"
        self._attr_icon = "mdi:currency-eur-off"
        self._attr_device_class = "power"
        
    @property
    def is_on(self) -> bool:
        """Return true if in low cost period."""
        # Initialize calculator if needed
        if not hasattr(self._coordinator, '_nordpool_calculator'):
            from .nordpool_calculation import NordpoolPlannerCalculator
            self._coordinator._nordpool_calculator = NordpoolPlannerCalculator(self._coordinator)
        
        calc = self._coordinator._nordpool_calculator
        return calc.is_in_low_cost_period(self._device_name)
    
    @property
    def extra_state_attributes(self) -> dict:
        """Return nordpool_planner style attributes."""
        if not hasattr(self._coordinator, '_nordpool_calculator'):
            from .nordpool_calculation import NordpoolPlannerCalculator
            self._coordinator._nordpool_calculator = NordpoolPlannerCalculator(self._coordinator)
        
        calc = self._coordinator._nordpool_calculator
        return calc.get_nordpool_attributes(self._device_name)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tibber binary sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    binary_sensors = []
    
    # Create low cost binary sensor for each device (nordpool_planner style)
    for device_name in coordinator.devices:
        binary_sensors.append(TibberLowCostBinarySensor(coordinator, device_name))
    
    if binary_sensors:
        async_add_entities(binary_sensors)
