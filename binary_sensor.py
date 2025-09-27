"""Binary sensors for Tibber scheduler."""

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

class TibberPlannerBinarySensor(BinarySensorEntity):
    """Binary sensor for low/high cost periods."""
    
    def __init__(self, coordinator, device_name: str, planner_type: str = "low_cost"):
        """Initialize the binary sensor."""
        self._coordinator = coordinator
        self._device_name = device_name
        self._planner_type = planner_type
        self._attr_name = f"Tibber {device_name.title()} {planner_type.replace('_', ' ').title()}"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{device_name}_{planner_type}"
        
        if planner_type == "low_cost":
            self._attr_icon = "mdi:currency-eur-off"
        elif planner_type == "high_cost":
            self._attr_icon = "mdi:currency-eur"
        else:
            self._attr_icon = "mdi:timer-star"
    
    @property
    def is_on(self) -> bool:
        """Return true if in the optimal period."""
        device_config = self._coordinator.devices.get(self._device_name, {})
        if not device_config.get("enabled", True):
            return False
        
        tibber_state = self.hass.states.get(self._coordinator.tibber_sensor)
        if not tibber_state:
            return False
        
        try:
            current_price = float(tibber_state.state)
            avg_price = tibber_state.attributes.get('avg_price', current_price)
            min_price = tibber_state.attributes.get('min_price', current_price)
            max_price = tibber_state.attributes.get('max_price', current_price)
            
            if self._planner_type == "low_cost":
                # True if price is in bottom 30% or below average
                return current_price <= min_price * 1.1 or current_price <= avg_price * 0.9
            elif self._planner_type == "high_cost":
                # True if price is in top 30% or above average
                return current_price >= max_price * 0.9 or current_price >= avg_price * 1.1
            else:  # optimal_start
                # True if device should start now
                schedule = self._coordinator.current_schedules.get(self._device_name, [])
                return len(schedule) > 0
                
        except (ValueError, TypeError):
            return False
    
    @property
    def extra_state_attributes(self) -> dict:
        """Return nordpool_planner style attributes."""
        tibber_state = self.hass.states.get(self._coordinator.tibber_sensor)
        if not tibber_state:
            return {}
        
        device_config = self._coordinator.devices.get(self._device_name, {})
        
        try:
            current_price = float(tibber_state.state)
            avg_price = tibber_state.attributes.get('avg_price', current_price)
            min_price = tibber_state.attributes.get('min_price', current_price)
            
            # nordpool_planner style attributes
            return {
                'current_price': round(current_price, 4),
                'now_cost_rate': round(current_price / avg_price if avg_price > 0 else 1.0, 2),
                'best_average': round(min_price, 4),
                'hours_to_optimal': self._calculate_hours_to_optimal(),
                'search_length': device_config.get('search_length', 11),
                'duration': device_config.get('duration', 120) // 60,
                'price_level': tibber_state.attributes.get('price_level', 'NORMAL'),
                'ranking': tibber_state.attributes.get('intraday_price_ranking', 12),
                'device_name': self._device_name,
                'planner_type': self._planner_type
            }
        except (ValueError, TypeError):
            return {}
    
    def _calculate_hours_to_optimal(self) -> float:
        """Calculate hours until next optimal period."""
        schedule = self._coordinator.current_schedules.get(self._device_name, [])
        if not schedule:
            return 0.0
        
        from datetime import datetime
        next_start = schedule[0].get('start_time')
        if next_start and isinstance(next_start, datetime):
            hours_diff = (next_start - datetime.now()).total_seconds() / 3600
            return round(max(0.0, hours_diff), 1)
        
        return 0.0

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry, 
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tibber binary sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    binary_sensors = []
    
    # Create binary sensors for each device
    for device_name in coordinator.devices:
        binary_sensors.append(TibberPlannerBinarySensor(coordinator, device_name, "low_cost"))
        binary_sensors.append(TibberPlannerBinarySensor(coordinator, device_name, "high_cost"))
        binary_sensors.append(TibberPlannerBinarySensor(coordinator, device_name, "optimal_start"))
    
    async_add_entities(binary_sensors)
