"""WORKING Configuration Flow - Complete Fix for All Issues."""

import voluptuous as vol
import logging
from homeassistant import config_entries
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv
from homeassistant.const import CONF_NAME, CONF_ENTITIES

from .const import DOMAIN, CONF_TIBBER_SENSOR

_LOGGER = logging.getLogger(__name__)

# Fixed device modes
DEVICE_MODES = {
    "active_scheduler": "Active Scheduler",
    "smart_delay": "Smart Delay", 
    "price_protection": "Price Protection",
    "hybrid": "Hybrid Mode",
    "monitor_only": "Monitor Only"
}

# Fixed schedule types
SCHEDULE_TYPES = {
    "cheapest_hours": "Cheapest Hours",
    "avoid_peak": "Avoid Peak Prices",
    "price_threshold": "Price Threshold"
}

class TibberSchedulerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tibber Smart Scheduler."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        _LOGGER.info("Config flow: Starting user step")
        errors = {}

        if user_input is not None:
            _LOGGER.info(f"Config flow: Received user input: {user_input}")
            tibber_sensor = user_input.get(CONF_TIBBER_SENSOR)
            
            # Validate sensor exists
            if not tibber_sensor:
                errors[CONF_TIBBER_SENSOR] = "sensor_required"
            elif self.hass.states.get(tibber_sensor) is None:
                errors[CONF_TIBBER_SENSOR] = "sensor_not_found"
            else:
                _LOGGER.info(f"Config flow: Creating entry with sensor: {tibber_sensor}")
                return self.async_create_entry(
                    title="Tibber Smart Scheduler",
                    data={CONF_TIBBER_SENSOR: tibber_sensor}
                )

        # Get ALL sensors - comprehensive approach for Tibber sensors
        try:
            all_sensors = []
            tibber_sensors = []
            
            for entity_id in self.hass.states.async_entity_ids("sensor"):
                try:
                    state = self.hass.states.get(entity_id)
                    if state:
                        # Get friendly name for display
                        friendly_name = state.attributes.get("friendly_name", entity_id)
                        entity_lower = entity_id.lower()
                        friendly_lower = friendly_name.lower()
                        
                        # Prioritize Tibber sensors (including "strompreis")
                        if any(keyword in entity_lower or keyword in friendly_lower for keyword in [
                            "tibber", "strompreis", "electricity_price", "current_price", 
                            "spot_price", "energy_price", "kwh_price", "nordpool"
                        ]):
                            tibber_sensors.append(entity_id)
                            _LOGGER.info(f"Found Tibber sensor: {entity_id} ({friendly_name})")
                        
                        # Include all sensors that have numeric states
                        try:
                            if state.state not in ["unavailable", "unknown", "None", ""]:
                                float(state.state)  # Test if numeric
                                all_sensors.append(entity_id)
                        except (ValueError, TypeError):
                            # Also include sensors that might have price data but non-numeric states
                            if any(keyword in entity_lower or keyword in friendly_lower for keyword in [
                                "price", "cost", "rate", "tariff", "energy"
                            ]):
                                all_sensors.append(entity_id)
                                
                except Exception as e:
                    _LOGGER.debug(f"Skipping sensor {entity_id}: {e}")
                    continue
            
            # Prioritize Tibber sensors at the top
            final_sensors = tibber_sensors + [s for s in all_sensors if s not in tibber_sensors]
            
            _LOGGER.info(f"Config flow: Found {len(tibber_sensors)} Tibber sensors, {len(final_sensors)} total sensors")
            _LOGGER.info(f"Config flow: Tibber sensors: {tibber_sensors}")
            
            if not final_sensors:
                final_sensors = ["sensor.example_price"]  # Fallback
            
            all_sensors = final_sensors
                
        except Exception as e:
            _LOGGER.error(f"Config flow: Error getting sensors: {e}")
            all_sensors = ["sensor.example_price"]

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_TIBBER_SENSOR): vol.In(all_sensors),
            }),
            errors=errors,
            description_placeholders={
                "sensor_count": str(len(all_sensors))
            }
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return TibberSchedulerOptionsFlow(config_entry)


class TibberSchedulerOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow - WORKING VERSION."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options - FIXED."""
        _LOGGER.info("Options flow: Starting init step")
        
        # Direct menu with working buttons
        if user_input is not None:
            action = user_input.get("menu_action")
            _LOGGER.info(f"Options flow: Selected action: {action}")
            
            if action == "add_device":
                return await self.async_step_add_device()
            elif action == "edit_device": 
                return await self.async_step_edit_device()
            elif action == "remove_device":
                return await self.async_step_remove_device()
        
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("menu_action"): vol.In({
                    "add_device": "Add New Device",
                    "edit_device": "Edit Device",
                    "remove_device": "Remove Device"
                }),
            }),
        )

    async def async_step_add_device(self, user_input=None):
        """Add a new device - WORKING VERSION."""
        _LOGGER.info("Options flow: Add device step")
        errors = {}
        
        if user_input is not None:
            _LOGGER.info(f"Options flow: Add device input: {user_input}")
            
            try:
                # Validate required fields
                if not user_input.get(CONF_NAME):
                    errors[CONF_NAME] = "name_required"
                elif not user_input.get(CONF_ENTITIES):
                    errors[CONF_ENTITIES] = "entities_required"
                else:
                    # Add device to coordinator
                    coordinator = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
                    if coordinator:
                        await coordinator.add_device(user_input)
                        _LOGGER.info(f"Options flow: Successfully added device {user_input[CONF_NAME]}")
                        return self.async_create_entry(title="", data={})
                    else:
                        _LOGGER.error("Options flow: Coordinator not found")
                        errors["base"] = "coordinator_error"
                        
            except Exception as e:
                _LOGGER.error(f"Options flow: Error adding device: {e}")
                errors["base"] = "add_device_error"

        # Get entities - WORKING approach
        try:
            all_entities = []
            for domain in ["switch", "light", "climate", "fan", "cover", "input_boolean"]:
                domain_entities = self.hass.states.async_entity_ids(domain)
                all_entities.extend(domain_entities)
            
            _LOGGER.info(f"Options flow: Found {len(all_entities)} entities")
            
            if not all_entities:
                all_entities = ["switch.example_device"]  # Fallback
                
        except Exception as e:
            _LOGGER.error(f"Options flow: Error getting entities: {e}")
            all_entities = ["switch.example_device"]

        # Get power sensors - MUCH more comprehensive search with filtering
        try:
            power_sensors = ["none"]  # Always include none option
            
            all_sensors = []
            for entity_id in self.hass.states.async_entity_ids("sensor"):
                try:
                    state = self.hass.states.get(entity_id)
                    if state:
                        friendly_name = state.attributes.get("friendly_name", "")
                        entity_lower = entity_id.lower()
                        friendly_lower = friendly_name.lower()
                        
                        # Check if it's a power sensor
                        power_keywords = [
                            "power", "watt", "consumption", "energy", "load", "current_power",
                            "active_power", "instantaneous", "demand", "usage", "draw",
                            "leistung", "verbrauch", "strom", "energie"  # German keywords
                        ]
                        
                        if any(keyword in entity_lower or keyword in friendly_lower for keyword in power_keywords):
                            # Additional validation - check unit or reasonable values
                            try:
                                unit = state.attributes.get("unit_of_measurement", "")
                                if unit.lower() in ["w", "watt", "watts", "kw", "kilowatt", "kilowatts"]:
                                    all_sensors.append({
                                        'entity_id': entity_id,
                                        'friendly_name': friendly_name or entity_id,
                                        'unit': unit,
                                        'type': 'power'
                                    })
                                elif state.state not in ["unavailable", "unknown", "None", ""]:
                                    value = float(state.state)
                                    if 0 <= value <= 50000:  # Reasonable power range
                                        all_sensors.append({
                                            'entity_id': entity_id,
                                            'friendly_name': friendly_name or entity_id,
                                            'unit': unit,
                                            'type': 'power_estimated'
                                        })
                            except (ValueError, TypeError):
                                continue
                                
                except Exception as e:
                    _LOGGER.debug(f"Skipping sensor {entity_id}: {e}")
                    continue
            
            # Sort sensors by type and name for better UX
            all_sensors.sort(key=lambda x: (x['type'], x['friendly_name']))
            
            # Create searchable dropdown options
            for sensor in all_sensors:
                entity_id = sensor['entity_id']
                friendly_name = sensor['friendly_name']
                unit = sensor['unit']
                
                # Create searchable display name
                if friendly_name != entity_id:
                    display_name = f"{friendly_name} ({entity_id})"
                else:
                    display_name = entity_id
                    
                if unit:
                    display_name += f" [{unit}]"
                    
                power_sensors.append(entity_id)
            
            _LOGGER.info(f"Options flow: Found {len(power_sensors)-1} power sensors")
            
        except Exception as e:
            _LOGGER.error(f"Options flow: Error getting power sensors: {e}")
            power_sensors = ["none"]

        return self.async_show_form(
            step_id="add_device",
            data_schema=vol.Schema({
                # === BASIC CONFIGURATION ===
                vol.Required(CONF_NAME): cv.string,
                vol.Required(CONF_ENTITIES): cv.multi_select(all_entities),
                vol.Required("device_mode", default="smart_delay"): vol.In(DEVICE_MODES),
                vol.Optional("enabled", default=True): cv.boolean,
                
                # === POWER-BASED DETECTION (ENHANCED) ===
                vol.Optional("power_sensor", default="none"): vol.In(power_sensors),
                vol.Optional("min_power_detection", default=15): vol.All(vol.Coerce(int), vol.Range(min=1, max=1000)),
                vol.Optional("max_power_detection", default=3000): vol.All(vol.Coerce(int), vol.Range(min=100, max=20000)),
                vol.Optional("power_change_threshold", default=50): vol.All(vol.Coerce(int), vol.Range(min=5, max=500)),
                vol.Optional("min_runtime_minutes", default=5): vol.All(vol.Coerce(int), vol.Range(min=1, max=120)),
                
                # === RECORDING & LOGGING ===
                vol.Optional("recording_enabled", default=True): cv.boolean,
                vol.Optional("recording_interval", default="5min"): vol.In({
                    "disabled": "Disabled",
                    "1min": "Every Minute",
                    "5min": "Every 5 Minutes", 
                    "15min": "Every 15 Minutes",
                    "1hour": "Every Hour"
                }),
                vol.Optional("max_recording_days", default=30): vol.All(vol.Coerce(int), vol.Range(min=1, max=365)),
                vol.Optional("record_power_data", default=True): cv.boolean,
                vol.Optional("record_price_data", default=True): cv.boolean,
                vol.Optional("export_csv_enabled", default=False): cv.boolean,
                
                # === PRICE THRESHOLDS (ENHANCED) ===
                vol.Optional("price_threshold", default=0.30): vol.All(vol.Coerce(float), vol.Range(min=0.01, max=5.0)),
                vol.Optional("price_cutoff_threshold", default=0.40): vol.All(vol.Coerce(float), vol.Range(min=0.01, max=5.0)),
                vol.Optional("price_resume_threshold", default=0.25): vol.All(vol.Coerce(float), vol.Range(min=0.01, max=5.0)),
                vol.Optional("use_cost_rate_attribute", default=False): cv.boolean,
                vol.Optional("cost_rate_cutoff", default="HIGH"): vol.In({
                    "VERY_HIGH": "Very High",
                    "HIGH": "High", 
                    "NORMAL": "Normal or below"
                }),
                vol.Optional("cost_rate_resume", default="NORMAL"): vol.In({
                    "VERY_LOW": "Very Low",
                    "LOW": "Low",
                    "NORMAL": "Normal or below"
                }),
                
                # === OPTIMAL SCHEDULING (ENHANCED) ===
                vol.Optional("duration", default=120): vol.All(vol.Coerce(int), vol.Range(min=15, max=1440)),
                vol.Optional("search_length", default=8): vol.All(vol.Coerce(int), vol.Range(min=1, max=48)),
                vol.Optional("schedule_type", default="cheapest_hours"): vol.In({
                    "cheapest_hours": "Cheapest Hours",
                    "cheapest_consecutive": "Cheapest Consecutive Block",
                    "avoid_peak": "Avoid Peak Prices",
                    "price_threshold": "Price Threshold",
                    "ranking_based": "Ranking Based",
                    "time_slots": "Predefined Time Slots"
                }),
                vol.Optional("priority", default="medium"): vol.In({
                    "low": "Low Priority",
                    "medium": "Medium Priority", 
                    "high": "High Priority"
                }),
                vol.Optional("max_price_factor", default=1.2): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=5.0)),
                vol.Optional("same_day_only", default=False): cv.boolean,
                vol.Optional("predefined_time_slots", default=""): cv.string,
                vol.Optional("allow_split_runs", default=True): cv.boolean,
                vol.Optional("max_splits", default=3): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
                
                # === TIME WINDOW CONSTRAINTS ===
                vol.Optional("time_window_start", default="00:00"): cv.string,
                vol.Optional("time_window_end", default="23:59"): cv.string,
                vol.Optional("blackout_periods", default=""): cv.string,
                vol.Optional("preferred_periods", default=""): cv.string,
                
                # === POWER CONSUMPTION FILTERING ===
                vol.Optional("power_filtering_enabled", default=False): cv.boolean,
                vol.Optional("home_power_sensor", default="none"): vol.In(power_sensors),  # Reuse power sensors list
                vol.Optional("max_power_threshold", default=3000): vol.All(vol.Coerce(int), vol.Range(min=100, max=50000)),
                vol.Optional("device_power_consumption", default=2000): vol.All(vol.Coerce(int), vol.Range(min=50, max=20000)),
                vol.Optional("power_safety_margin", default=200): vol.All(vol.Coerce(int), vol.Range(min=0, max=1000)),
                vol.Optional("allow_manual_when_over_threshold", default=True): cv.boolean,
                
                # === MONITORING & ALERTS ===
                vol.Optional("efficiency_monitoring", default=True): cv.boolean,
                vol.Optional("cost_tracking", default=True): cv.boolean,
                vol.Optional("performance_analysis", default=True): cv.boolean,
                vol.Optional("anomaly_detection", default=False): cv.boolean,
                vol.Optional("notify_on_start", default=False): cv.boolean,
                vol.Optional("notify_on_completion", default=False): cv.boolean,
                vol.Optional("notify_on_price_spike", default=False): cv.boolean,
                
                # === ADVANCED OPTIONS ===
                vol.Optional("auto_resume_after_cutoff", default=True): cv.boolean,
                vol.Optional("max_delay_hours", default=8): vol.All(vol.Coerce(int), vol.Range(min=1, max=48)),
                vol.Optional("grace_period_minutes", default=5): vol.All(vol.Coerce(int), vol.Range(min=0, max=60)),
                vol.Optional("warmup_time_minutes", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=60)),
                vol.Optional("cooldown_time_minutes", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=60)),
            }),
            errors=errors,
            description_placeholders={
                "entity_count": str(len(all_entities)),
                "power_sensor_count": str(len(power_sensors)-1)
            }
        )

    async def async_step_edit_device(self, user_input=None):
        """Edit an existing device."""
        _LOGGER.info("Options flow: Edit device step")
        
        coordinator = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        if not coordinator or not coordinator.devices:
            return self.async_abort(reason="no_devices")

        if user_input is not None:
            device_name = user_input["device_to_edit"]
            _LOGGER.info(f"Options flow: Selected device to edit: {device_name}")
            # Store device name in class for next step
            self._device_name = device_name
            return await self.async_step_edit_device_config()

        device_options = {}
        for name, config in coordinator.devices.items():
            mode = config.get('device_mode', 'unknown')
            device_options[name] = f"{name.title()} ({mode})"
        
        return self.async_show_form(
            step_id="edit_device",
            data_schema=vol.Schema({
                vol.Required("device_to_edit"): vol.In(device_options),
            })
        )

    async def async_step_edit_device_config(self, user_input=None):
        """Edit device configuration."""
        # Get device name from stored value
        device_name = getattr(self, '_device_name', None)
        
        if not device_name:
            _LOGGER.error("Options flow: No device name available for edit")
            return self.async_abort(reason="no_device_name")

        coordinator = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        device_config = coordinator.devices.get(device_name, {})

        if user_input is not None:
            # This is the actual update
            try:
                _LOGGER.info(f"Options flow: Updating device {device_name} with: {user_input}")
                coordinator.devices[device_name].update(user_input)
                await coordinator.async_save_devices()
                _LOGGER.info(f"Options flow: Successfully updated device {device_name}")
                
                # Clear stored device name
                if hasattr(self, '_device_name'):
                    delattr(self, '_device_name')
                    
                return self.async_create_entry(title="", data={})
            except Exception as e:
                _LOGGER.error(f"Options flow: Error updating device: {e}")
                return self.async_abort(reason="update_error")

        # Get entities and sensors (same as add_device)
        try:
            all_entities = []
            for domain in ["switch", "light", "climate", "fan", "cover", "input_boolean"]:
                all_entities.extend(self.hass.states.async_entity_ids(domain))
            
            power_sensors = ["none"]
            for entity_id in self.hass.states.async_entity_ids("sensor"):
                try:
                    state = self.hass.states.get(entity_id)
                    if state and state.state not in ["unavailable", "unknown"]:
                        entity_lower = entity_id.lower()
                        if any(keyword in entity_lower for keyword in ["power", "watt", "consumption", "energy"]):
                            power_sensors.append(entity_id)
                except Exception:
                    continue
                    
        except Exception as e:
            _LOGGER.error(f"Options flow: Error getting entities for edit: {e}")
            all_entities = ["switch.example_device"]
            power_sensors = ["none"]

        return self.async_show_form(
            step_id="edit_device_config",
            data_schema=vol.Schema({
                # === BASIC CONFIGURATION ===
                vol.Required(CONF_ENTITIES, default=device_config.get(CONF_ENTITIES, [])): cv.multi_select(all_entities),
                vol.Required("device_mode", default=device_config.get("device_mode", "smart_delay")): vol.In(DEVICE_MODES),
                vol.Required("enabled", default=device_config.get("enabled", True)): cv.boolean,
                
                # === POWER-BASED DETECTION ===
                vol.Optional("power_sensor", default=device_config.get("power_sensor", "none")): vol.In(power_sensors),
                vol.Optional("min_power_detection", default=device_config.get("min_power_detection", 15)): vol.All(vol.Coerce(int), vol.Range(min=1, max=1000)),
                vol.Optional("max_power_detection", default=device_config.get("max_power_detection", 3000)): vol.All(vol.Coerce(int), vol.Range(min=100, max=20000)),
                vol.Optional("power_change_threshold", default=device_config.get("power_change_threshold", 50)): vol.All(vol.Coerce(int), vol.Range(min=5, max=500)),
                vol.Optional("min_runtime_minutes", default=device_config.get("min_runtime_minutes", 5)): vol.All(vol.Coerce(int), vol.Range(min=1, max=120)),
                
                # === RECORDING & LOGGING ===
                vol.Optional("recording_enabled", default=device_config.get("recording_enabled", True)): cv.boolean,
                vol.Optional("recording_interval", default=device_config.get("recording_interval", "5min")): vol.In({
                    "disabled": "Disabled",
                    "1min": "Every Minute",
                    "5min": "Every 5 Minutes", 
                    "15min": "Every 15 Minutes",
                    "1hour": "Every Hour"
                }),
                vol.Optional("max_recording_days", default=device_config.get("max_recording_days", 30)): vol.All(vol.Coerce(int), vol.Range(min=1, max=365)),
                vol.Optional("record_power_data", default=device_config.get("record_power_data", True)): cv.boolean,
                vol.Optional("record_price_data", default=device_config.get("record_price_data", True)): cv.boolean,
                vol.Optional("export_csv_enabled", default=device_config.get("export_csv_enabled", False)): cv.boolean,
                
                # === PRICE THRESHOLDS (ENHANCED) ===
                vol.Optional("price_threshold", default=device_config.get("price_threshold", 0.30)): vol.All(vol.Coerce(float), vol.Range(min=0.01, max=5.0)),
                vol.Optional("price_cutoff_threshold", default=device_config.get("price_cutoff_threshold", 0.40)): vol.All(vol.Coerce(float), vol.Range(min=0.01, max=5.0)),
                vol.Optional("price_resume_threshold", default=device_config.get("price_resume_threshold", 0.25)): vol.All(vol.Coerce(float), vol.Range(min=0.01, max=5.0)),
                vol.Optional("use_cost_rate_attribute", default=device_config.get("use_cost_rate_attribute", False)): cv.boolean,
                vol.Optional("cost_rate_cutoff", default=device_config.get("cost_rate_cutoff", "HIGH")): vol.In({
                    "VERY_HIGH": "Very High",
                    "HIGH": "High", 
                    "NORMAL": "Normal or below"
                }),
                vol.Optional("cost_rate_resume", default=device_config.get("cost_rate_resume", "NORMAL")): vol.In({
                    "VERY_LOW": "Very Low",
                    "LOW": "Low",
                    "NORMAL": "Normal or below"
                }),
                
                # === OPTIMAL SCHEDULING ===
                vol.Optional("duration", default=device_config.get("duration", 120)): vol.All(vol.Coerce(int), vol.Range(min=15, max=1440)),
                vol.Optional("search_length", default=device_config.get("search_length", 8)): vol.All(vol.Coerce(int), vol.Range(min=1, max=48)),
                vol.Optional("schedule_type", default=device_config.get("schedule_type", "cheapest_hours")): vol.In({
                    "cheapest_hours": "Cheapest Hours",
                    "cheapest_consecutive": "Cheapest Consecutive Block",
                    "avoid_peak": "Avoid Peak Prices",
                    "price_threshold": "Price Threshold",
                    "ranking_based": "Ranking Based",
                    "time_slots": "Predefined Time Slots"
                }),
                vol.Optional("priority", default=device_config.get("priority", "medium")): vol.In({
                    "low": "Low Priority",
                    "medium": "Medium Priority", 
                    "high": "High Priority"
                }),
                vol.Optional("max_price_factor", default=device_config.get("max_price_factor", 1.2)): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=5.0)),
                vol.Optional("same_day_only", default=device_config.get("same_day_only", False)): cv.boolean,
                vol.Optional("predefined_time_slots", default=device_config.get("predefined_time_slots", "")): cv.string,
                vol.Optional("allow_split_runs", default=device_config.get("allow_split_runs", True)): cv.boolean,
                vol.Optional("max_splits", default=device_config.get("max_splits", 3)): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
                
                # === TIME WINDOW CONSTRAINTS ===
                vol.Optional("time_window_start", default=device_config.get("time_window_start", "00:00")): cv.string,
                vol.Optional("time_window_end", default=device_config.get("time_window_end", "23:59")): cv.string,
                vol.Optional("blackout_periods", default=device_config.get("blackout_periods", "")): cv.string,
                vol.Optional("preferred_periods", default=device_config.get("preferred_periods", "")): cv.string,
                
                # === POWER CONSUMPTION FILTERING ===
                vol.Optional("power_filtering_enabled", default=device_config.get("power_filtering_enabled", False)): cv.boolean,
                vol.Optional("home_power_sensor", default=device_config.get("home_power_sensor", "none")): vol.In(power_sensors),
                vol.Optional("max_power_threshold", default=device_config.get("max_power_threshold", 3000)): vol.All(vol.Coerce(int), vol.Range(min=100, max=50000)),
                vol.Optional("device_power_consumption", default=device_config.get("device_power_consumption", 2000)): vol.All(vol.Coerce(int), vol.Range(min=50, max=20000)),
                vol.Optional("power_safety_margin", default=device_config.get("power_safety_margin", 200)): vol.All(vol.Coerce(int), vol.Range(min=0, max=1000)),
                vol.Optional("allow_manual_when_over_threshold", default=device_config.get("allow_manual_when_over_threshold", True)): cv.boolean,
                
                # === MONITORING & ALERTS ===
                vol.Optional("efficiency_monitoring", default=device_config.get("efficiency_monitoring", True)): cv.boolean,
                vol.Optional("cost_tracking", default=device_config.get("cost_tracking", True)): cv.boolean,
                vol.Optional("performance_analysis", default=device_config.get("performance_analysis", True)): cv.boolean,
                vol.Optional("anomaly_detection", default=device_config.get("anomaly_detection", False)): cv.boolean,
                vol.Optional("notify_on_start", default=device_config.get("notify_on_start", False)): cv.boolean,
                vol.Optional("notify_on_completion", default=device_config.get("notify_on_completion", False)): cv.boolean,
                vol.Optional("notify_on_price_spike", default=device_config.get("notify_on_price_spike", False)): cv.boolean,
                
                # === ADVANCED OPTIONS ===
                vol.Optional("auto_resume_after_cutoff", default=device_config.get("auto_resume_after_cutoff", True)): cv.boolean,
                vol.Optional("max_delay_hours", default=device_config.get("max_delay_hours", 8)): vol.All(vol.Coerce(int), vol.Range(min=1, max=48)),
                vol.Optional("grace_period_minutes", default=device_config.get("grace_period_minutes", 5)): vol.All(vol.Coerce(int), vol.Range(min=0, max=60)),
                vol.Optional("warmup_time_minutes", default=device_config.get("warmup_time_minutes", 0)): vol.All(vol.Coerce(int), vol.Range(min=0, max=60)),
                vol.Optional("cooldown_time_minutes", default=device_config.get("cooldown_time_minutes", 0)): vol.All(vol.Coerce(int), vol.Range(min=0, max=60)),
            }),
            description_placeholders={"device_name": device_name.title()}
        )

    async def async_step_remove_device(self, user_input=None):
        """Remove a device."""
        _LOGGER.info("Options flow: Remove device step")
        
        coordinator = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        if not coordinator or not coordinator.devices:
            return self.async_abort(reason="no_devices")

        if user_input is not None:
            device_name = user_input["device_to_remove"]
            try:
                await coordinator.remove_device(device_name)
                _LOGGER.info(f"Options flow: Successfully removed device {device_name}")
                return self.async_create_entry(title="", data={})
            except Exception as e:
                _LOGGER.error(f"Options flow: Error removing device: {e}")
                return self.async_abort(reason="remove_error")

        device_options = {}
        for name, config in coordinator.devices.items():
            mode = config.get('device_mode', 'unknown')
            device_options[name] = f"{name.title()} ({mode})"
        
        return self.async_show_form(
            step_id="remove_device",
            data_schema=vol.Schema({
                vol.Required("device_to_remove"): vol.In(device_options),
            }),
            description_placeholders={
                "device_count": str(len(coordinator.devices))
            }
        )
