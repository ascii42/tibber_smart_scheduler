"""Cached forecast sensors with program detection data."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SENSOR_TYPES = {
    "next_start": {
        "name": "Next Start",
        "icon": "mdi:clock-start",
        "device_class": "timestamp",
        "unit_of_measurement": None,
    },
    "next_stop": {
        "name": "Next Stop",
        "icon": "mdi:clock-end", 
        "device_class": "timestamp",
        "unit_of_measurement": None,
    },
    "current_price": {
        "name": "Current Price", 
        "icon": "mdi:currency-eur",
        "device_class": "monetary",
        "unit_of_measurement": "€/kWh",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "optimal_window": {
        "name": "Optimal Window",
        "icon": "mdi:chart-line-variant",
        "device_class": None,
        "unit_of_measurement": None,
    },
    "minutes_until_start": {
        "name": "Minutes Until Start",
        "icon": "mdi:timer-sand",
        "device_class": "duration",
        "unit_of_measurement": "min",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "program_analytics": {
        "name": "Program Analytics",
        "icon": "mdi:chart-bar",
        "device_class": None,
        "unit_of_measurement": None,
    },
    "last_program": {
        "name": "Last Program",
        "icon": "mdi:history",
        "device_class": "timestamp",
        "unit_of_measurement": None,
    },
    "programs_today": {
        "name": "Programs Today",
        "icon": "mdi:counter",
        "device_class": None,
        "unit_of_measurement": "programs",
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    "runtime_today": {
        "name": "Runtime Today",
        "icon": "mdi:timer",
        "device_class": "duration",
        "unit_of_measurement": "min",
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    "power_price_correlation": {
        "name": "Power Price Correlation",
        "icon": "mdi:chart-scatter-plot",
        "device_class": None,
        "unit_of_measurement": "€/kWh/W",
    },
    "current_consumption_cost": {
        "name": "Current Consumption Cost",
        "icon": "mdi:currency-eur",
        "device_class": "monetary",
        "unit_of_measurement": "€/h",
        "state_class": SensorStateClass.MEASUREMENT,
    },
    "runtime_vs_scheduled_comparison": {
        "name": "Runtime vs Scheduled Comparison",
        "icon": "mdi:compare",
        "device_class": None,
        "unit_of_measurement": None,
    },
    "smart_delay_decision": {
        "name": "Smart Delay Decision",
        "icon": "mdi:traffic-light",
        "device_class": None,
        "unit_of_measurement": None,
    }
}

class TibberSmartSensor(SensorEntity):
    """Cached forecast sensor with program detection."""
    
    def __init__(self, coordinator, device_name: str, sensor_type: str):
        """Initialize sensor."""
        self._coordinator = coordinator
        self._device_name = device_name
        self._sensor_type = sensor_type
        self._attr_name = f"Tibber {device_name.title()} {SENSOR_TYPES[sensor_type]['name']}"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{device_name}_{sensor_type}"
        self._attr_icon = SENSOR_TYPES[sensor_type]["icon"]
        self._attr_device_class = SENSOR_TYPES[sensor_type].get("device_class")
        self._attr_native_unit_of_measurement = SENSOR_TYPES[sensor_type].get("unit_of_measurement")
        self._attr_state_class = SENSOR_TYPES[sensor_type].get("state_class")
        
        # Cache for optimal window calculations
        self._cached_optimal_window = None
        self._cache_timestamp = None
        self._last_price_hash = None
        
    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._coordinator.entry.entry_id)},
            "name": "Tibber Smart Scheduler",
            "manufacturer": "Custom",
            "model": "Smart Price Scheduler",
            "sw_version": "0.6.0",
        }
    
    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        try:
            if self._device_name not in self._coordinator.devices:
                return False
            
            tibber_state = self.hass.states.get(self._coordinator.tibber_sensor)
            if not tibber_state or tibber_state.state in ['unavailable', 'unknown']:
                return False
            
            return True
            
        except Exception as e:
            _LOGGER.error(f"Error checking availability for {self._device_name}_{self._sensor_type}: {e}")
            return False
    
    @property
    def native_value(self) -> StateType:
        """Return the sensor value."""
        try:
            if self._sensor_type == "next_start":
                return self._get_next_start()
            elif self._sensor_type == "next_stop":
                return self._get_next_stop()
            elif self._sensor_type == "current_price":
                return self._get_current_price()
            elif self._sensor_type == "optimal_window":
                return self._get_optimal_window()
            elif self._sensor_type == "minutes_until_start":
                return self._get_minutes_until_start()
            elif self._sensor_type == "program_analytics":
                return self._get_program_analytics()
            elif self._sensor_type == "last_program":
                return self._get_last_program()
            elif self._sensor_type == "programs_today":
                return self._get_programs_today()
            elif self._sensor_type == "runtime_today":
                return self._get_runtime_today()
            elif self._sensor_type == "power_price_correlation":
                return self._get_power_price_correlation()
            elif self._sensor_type == "current_consumption_cost":
                return self._get_current_consumption_cost()
            elif self._sensor_type == "runtime_vs_scheduled_comparison":
                return self._get_runtime_vs_scheduled_comparison()
            elif self._sensor_type == "smart_delay_decision":
                return self._get_smart_delay_decision()

        except Exception as e:
            _LOGGER.error(f"Error getting value for {self._device_name}_{self._sensor_type}: {e}")
            return None
    
    def _get_next_start(self) -> Optional[datetime]:
        """Get next start time - STABLE with caching and proper error handling."""
        try:
            device_state = self._coordinator.device_states.get(self._device_name, {})
            device_config = self._coordinator.devices.get(self._device_name, {})
            current_time = datetime.now()

            # If currently running
            if device_state.get('device_running'):
                return None  # No "next" start if currently running

            # Get device mode to determine behavior
            device_mode = device_config.get('device_mode', 'smart_delay')

            # For Active Scheduler: use locked schedule if available, otherwise fallback to optimal window
            if device_mode == 'active_scheduler':
                scheduled_start = device_state.get('scheduled_start')
                if (scheduled_start and
                    isinstance(scheduled_start, datetime) and
                    device_state.get('schedule_locked') and
                    scheduled_start > current_time):
                    return scheduled_start

                # If no locked schedule, fallback to optimal window calculation
                optimal_window = self._get_cached_optimal_window()
                if (optimal_window and
                    'start_time' in optimal_window and
                    isinstance(optimal_window['start_time'], datetime) and
                    optimal_window['start_time'] > current_time):
                    return optimal_window['start_time']

            # For Smart Delay: use stable cached optimal window
            if device_mode == 'smart_delay':
                optimal_window = self._get_cached_optimal_window()
                if (optimal_window and
                    'start_time' in optimal_window and
                    isinstance(optimal_window['start_time'], datetime) and
                    optimal_window['start_time'] > current_time):
                    return optimal_window['start_time']

            # Fallback to scheduled start for any mode
            scheduled_start = device_state.get('scheduled_start')
            if (scheduled_start and
                isinstance(scheduled_start, datetime) and
                scheduled_start > current_time):
                return scheduled_start

            return None

        except Exception as e:
            _LOGGER.error(f"Error calculating next start for {self._device_name}: {e}")
            return None
    
    def _get_next_stop(self) -> Optional[datetime]:
        """Get next stop time - prevent 'became unknown' by handling edge cases."""
        try:
            device_state = self._coordinator.device_states.get(self._device_name, {})
            device_config = self._coordinator.devices.get(self._device_name, {})
            current_time = datetime.now()

            # If currently running, calculate end time from start time
            if device_state.get('device_running'):
                started_time = device_state.get('started_time')
                if started_time and isinstance(started_time, datetime):
                    duration = device_config.get('duration', 120)
                    end_time = started_time + timedelta(minutes=duration)
                    # Only return if it's still in the future
                    if end_time > current_time:
                        return end_time

            # Use scheduled end if available and valid
            scheduled_end = device_state.get('scheduled_end')
            if (scheduled_end and
                isinstance(scheduled_end, datetime) and
                scheduled_end > current_time):
                return scheduled_end

            # Calculate from next start if available
            next_start = self._get_next_start()
            if next_start and isinstance(next_start, datetime) and next_start > current_time:
                duration = device_config.get('duration', 120)
                calculated_end = next_start + timedelta(minutes=duration)
                # Only return if it makes sense (in the future)
                if calculated_end > current_time:
                    return calculated_end

            # If nothing found, don't return unknown - return None gracefully
            return None

        except Exception as e:
            _LOGGER.error(f"Error calculating next stop for {self._device_name}: {e}")
            return None
    
    def _get_optimal_window(self) -> str:
        """Get optimal window description - CACHED with proper format."""
        optimal_window = self._get_cached_optimal_window()

        if not optimal_window:
            return "No optimal window found"

        start_time = optimal_window['start_time']
        end_time = optimal_window['end_time']
        avg_price = optimal_window['avg_price']
        duration_minutes = optimal_window.get('duration_minutes', 120)

        # Format like: "September 27, 2025 at 2:00 AM - September 27, 2025 at 3:00 AM (1h)"
        # Use %I instead of %-I for compatibility across platforms
        start_formatted = start_time.strftime("%B %d, %Y at %I:%M %p").replace(" 0", " ")
        end_formatted = end_time.strftime("%B %d, %Y at %I:%M %p").replace(" 0", " ")

        # Calculate duration display
        duration_hours = duration_minutes // 60
        duration_mins = duration_minutes % 60

        if duration_hours > 0 and duration_mins > 0:
            duration_str = f"{duration_hours}h {duration_mins}min"
        elif duration_hours > 0:
            duration_str = f"{duration_hours}h"
        else:
            duration_str = f"{duration_mins}min"

        return f"{start_formatted} - {end_formatted} ({duration_str}) avg: {avg_price:.3f}€"
    
    def _get_minutes_until_start(self) -> int:
        """Get minutes until next start."""
        next_start = self._get_next_start()
        if not next_start:
            return 0
        
        minutes_until = max(0, int((next_start - datetime.now()).total_seconds() / 60))
        return minutes_until
    
    def _get_cached_optimal_window(self) -> Optional[dict]:
        """Get optimal window with aggressive caching - prevent excessive refreshing."""
        current_time = datetime.now()

        # Get current price data hash to detect changes
        current_price_hash = self._get_price_data_hash()

        # Very aggressive cache - only recalculate when truly necessary
        cache_duration = 14400  # 4 hours for maximum stability

        # Check if cache is still valid
        if (self._cached_optimal_window and
            self._cache_timestamp and
            (current_time - self._cache_timestamp).total_seconds() < cache_duration):

            # For smart_delay, prioritize cache stability over price changes
            device_config = self._coordinator.devices.get(self._device_name, {})
            device_mode = device_config.get('device_mode', 'smart_delay')

            if device_mode == 'smart_delay':
                # Return cached result if still in future - ignore price hash changes for stability
                if self._cached_optimal_window['start_time'] > current_time:
                    return self._cached_optimal_window
            else:
                # For other modes, check price hash too
                if (self._last_price_hash == current_price_hash and
                    self._cached_optimal_window['start_time'] > current_time):
                    return self._cached_optimal_window

        # Only recalculate if cache is truly expired or start time has passed
        if (not self._cached_optimal_window or
            not self._cache_timestamp or
            (current_time - self._cache_timestamp).total_seconds() >= cache_duration or
            (self._cached_optimal_window and self._cached_optimal_window['start_time'] <= current_time)):

            _LOGGER.debug(f"Recalculating optimal window for {self._device_name} (cache truly expired)")
            self._cached_optimal_window = self._calculate_fresh_optimal_window()
            self._cache_timestamp = current_time
            self._last_price_hash = current_price_hash

        return self._cached_optimal_window
    
    def _get_price_data_hash(self) -> str:
        """Get hash of current price data to detect changes."""
        try:
            tibber_state = self.hass.states.get(self._coordinator.tibber_sensor)
            if not tibber_state:
                return "no_data"
            
            today_prices = tibber_state.attributes.get('today', [])
            tomorrow_prices = tibber_state.attributes.get('tomorrow', [])
            
            # Create simple hash based on number of prices and first/last values
            hash_data = f"{len(today_prices)}_{len(tomorrow_prices)}"
            if today_prices:
                hash_data += f"_{today_prices[0].get('total', 0)}_{today_prices[-1].get('total', 0)}"
            
            return hash_data
            
        except Exception:
            return "error"
    
    def _calculate_fresh_optimal_window(self) -> Optional[dict]:
        """Calculate optimal window from fresh forecast data with smart Tibber timing handling."""
        try:
            device_config = self._coordinator.devices.get(self._device_name, {})
            duration_minutes = device_config.get('duration', 120)
            search_length = device_config.get('search_length', 8)
            run_same_day = device_config.get('same_day_only', False)

            # Get Tibber price forecast
            tibber_state = self.hass.states.get(self._coordinator.tibber_sensor)
            if not tibber_state:
                return None

            today_prices = tibber_state.attributes.get('today', [])
            tomorrow_prices = tibber_state.attributes.get('tomorrow', [])

            if not today_prices:
                return None

            current_time = datetime.now()
            current_hour = current_time.hour

            # Handle Tibber's 1pm-3pm tomorrow data availability
            has_tomorrow_data = bool(tomorrow_prices)
            is_afternoon = 13 <= current_hour <= 15  # 1pm-3pm window

            _LOGGER.debug(f"Tibber data status - Today: {len(today_prices)} hours, Tomorrow: {len(tomorrow_prices)} hours, Current hour: {current_hour}")

            # Smart data combination based on availability and settings
            if run_same_day and current_hour < 20:  # Same day priority before 8pm
                # Only use today's remaining hours for same-day runs
                _LOGGER.info(f"Same-day mode for {self._device_name} - using only today's data")
                all_prices = today_prices
                # Limit search to remaining today hours
                max_search = min(search_length, 24 - current_hour)
                search_length = max(1, max_search)
            elif has_tomorrow_data:
                # Normal mode with tomorrow data available
                _LOGGER.debug(f"Tomorrow data available for {self._device_name} - using both days")
                all_prices = today_prices + tomorrow_prices
            else:
                # No tomorrow data yet - work with today only
                remaining_today_hours = 24 - current_hour
                if remaining_today_hours < duration_minutes // 60:
                    # Not enough time today and no tomorrow data
                    if current_hour < 15:  # Before 3pm
                        _LOGGER.info(f"Waiting for tomorrow data for {self._device_name} (current hour: {current_hour})")
                        return None
                    else:
                        # After 3pm with no tomorrow data - something's wrong
                        _LOGGER.warning(f"No tomorrow data available after 3pm for {self._device_name}")

                _LOGGER.info(f"Working with today's data only for {self._device_name} - {remaining_today_hours}h remaining")
                all_prices = today_prices
                search_length = min(search_length, remaining_today_hours)
            price_forecast = []
            
            for price_point in all_prices:
                try:
                    time_str = price_point['starts_at']
                    price_time = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                    if price_time.tzinfo:
                        price_time = price_time.replace(tzinfo=None)
                    
                    price_forecast.append({
                        'time': price_time,
                        'price': float(price_point['total'])
                    })
                except Exception:
                    continue
            
            if not price_forecast:
                return None
            
            # Find optimal window with smart search bounds
            search_end = current_time + timedelta(hours=search_length)

            # For same-day mode or when no tomorrow data, limit to end of today
            if run_same_day or not has_tomorrow_data:
                end_of_today = current_time.replace(hour=23, minute=59, second=59)
                search_end = min(search_end, end_of_today)
                _LOGGER.debug(f"Limited search to end of today: {search_end.strftime('%H:%M')}")

            relevant_prices = [
                p for p in price_forecast
                if current_time + timedelta(minutes=5) <= p['time'] <= search_end
            ]

            _LOGGER.debug(f"Found {len(relevant_prices)} relevant prices for {self._device_name} (search: {current_time.strftime('%H:%M')} to {search_end.strftime('%H:%M')})")
            
            duration_hours = max(1, duration_minutes // 60)
            if len(relevant_prices) < duration_hours:
                return None
            
            # Find cheapest consecutive period
            best_window = None
            best_avg_price = float('inf')
            
            for i in range(len(relevant_prices) - duration_hours + 1):
                window_prices = relevant_prices[i:i + duration_hours]
                avg_price = sum(p['price'] for p in window_prices) / len(window_prices)
                
                if avg_price < best_avg_price:
                    best_avg_price = avg_price
                    start_time = window_prices[0]['time']
                    end_time = start_time + timedelta(minutes=duration_minutes)
                    
                    best_window = {
                        'start_time': start_time,
                        'end_time': end_time,
                        'avg_price': avg_price,
                        'duration_minutes': duration_minutes
                    }
            
            return best_window
            
        except Exception as e:
            _LOGGER.error(f"Error calculating fresh optimal window: {e}")
            return None
    
    def _get_current_price(self) -> float:
        """Get current price from Tibber sensor."""
        try:
            tibber_state = self.hass.states.get(self._coordinator.tibber_sensor)
            if tibber_state and tibber_state.state not in ['unavailable', 'unknown']:
                return round(float(tibber_state.state), 3)
        except (ValueError, TypeError):
            pass
        return None
    
    def _get_program_analytics(self) -> str:
        """Get program analytics summary."""
        try:
            analytics = self._coordinator.get_program_analytics(self._device_name)
            if 'error' in analytics:
                return "No programs recorded"
            
            total = analytics.get('total_programs', 0)
            completed = analytics.get('completed_programs', 0)
            avg_duration = analytics.get('avg_duration_minutes', 0)
            
            return f"{completed}/{total} programs, avg {avg_duration:.0f}min"
            
        except Exception as e:
            return "Error getting analytics"
    
    def _get_last_program(self) -> datetime:
        """Get last program detection time."""
        try:
            device_state = self._coordinator.device_states.get(self._device_name, {})
            history = device_state.get('program_history', [])
            
            if not history:
                return None
            
            last_program = history[-1]
            detection_time = last_program.get('detection_time')
            
            if isinstance(detection_time, datetime):
                return detection_time
            elif isinstance(detection_time, str):
                return datetime.fromisoformat(detection_time)
                
        except Exception as e:
            _LOGGER.error(f"Error getting last program: {e}")
            
        return None
    
    def _get_programs_today(self) -> int:
        """Get number of programs run today."""
        device_state = self._coordinator.device_states.get(self._device_name, {})
        return device_state.get('runs_today', 0)

    def _get_runtime_today(self) -> int:
        """Get total runtime today in minutes."""
        device_state = self._coordinator.device_states.get(self._device_name, {})
        current_time = datetime.now()

        # Get base runtime from completed runs
        total_runtime = device_state.get('total_runtime_today', 0)

        # Add current runtime if device is running
        if device_state.get('device_running'):
            started_time = device_state.get('started_time')
            if started_time and isinstance(started_time, datetime):
                current_run_minutes = (current_time - started_time).total_seconds() / 60
                total_runtime += current_run_minutes

        return int(total_runtime)

    def _get_power_price_correlation(self) -> float:
        """Get power consumption vs price correlation (combined entity)."""
        try:
            # Get current power reading
            device_config = self._coordinator.devices.get(self._device_name, {})
            power_sensor = device_config.get('power_sensor')

            if not power_sensor or power_sensor == 'none':
                return None

            power_state = self.hass.states.get(power_sensor)
            if not power_state or power_state.state in ['unavailable', 'unknown']:
                return None

            current_power = float(power_state.state)

            # Get current price
            current_price = self._get_current_price()
            if not current_price:
                return None

            # Calculate correlation (power in W * price in €/kWh = cost rate in €/h)
            if current_power > 0:
                correlation = (current_power / 1000) * current_price  # Convert W to kW
                return round(correlation, 4)

            return 0.0

        except (ValueError, TypeError, AttributeError):
            return None

    def _get_current_consumption_cost(self) -> float:
        """Get current consumption cost in €/h."""
        try:
            # Get current power reading
            device_config = self._coordinator.devices.get(self._device_name, {})
            power_sensor = device_config.get('power_sensor')

            if not power_sensor or power_sensor == 'none':
                return None

            power_state = self.hass.states.get(power_sensor)
            if not power_state or power_state.state in ['unavailable', 'unknown']:
                return None

            current_power = float(power_state.state)

            # Get current price
            current_price = self._get_current_price()
            if not current_price:
                return None

            # Calculate hourly cost (power in kW * price in €/kWh)
            hourly_cost = (current_power / 1000) * current_price
            return round(hourly_cost, 3)

        except (ValueError, TypeError, AttributeError):
            return None

    def _get_runtime_vs_scheduled_comparison(self) -> str:
        """Compare current runtime window price vs scheduled optimal window."""
        try:
            current_time = datetime.now()
            device_state = self._coordinator.device_states.get(self._device_name, {})
            device_config = self._coordinator.devices.get(self._device_name, {})

            # Get current price
            current_price = self._get_current_price()
            if not current_price:
                return "Price unavailable"

            # Check if device is currently running
            if device_state.get('device_running'):
                started_time = device_state.get('started_time')
                if started_time:
                    duration_minutes = (current_time - started_time).total_seconds() / 60

                    # Get optimal window for comparison
                    optimal_window = self._get_cached_optimal_window()
                    if optimal_window:
                        optimal_price = optimal_window['avg_price']
                        savings = current_price - optimal_price

                        if savings > 0:
                            return f"Running now at {current_price:.3f}€ vs optimal {optimal_price:.3f}€ (+{savings:.3f}€ more expensive)"
                        else:
                            return f"Running now at {current_price:.3f}€ vs optimal {optimal_price:.3f}€ ({abs(savings):.3f}€ savings)"
                    else:
                        return f"Running now at {current_price:.3f}€ (no optimal window for comparison)"

            # If not running, compare current price vs optimal window
            optimal_window = self._get_cached_optimal_window()
            if optimal_window:
                optimal_price = optimal_window['avg_price']
                start_time = optimal_window['start_time']
                savings = current_price - optimal_price

                time_until_optimal = int((start_time - current_time).total_seconds() / 60)

                if time_until_optimal > 0:
                    if savings > 0:
                        return f"Wait {time_until_optimal}min for {abs(savings):.3f}€ savings (now: {current_price:.3f}€, optimal: {optimal_price:.3f}€)"
                    else:
                        return f"Current price {current_price:.3f}€ is better than optimal {optimal_price:.3f}€"
                else:
                    return f"Optimal window missed - current: {current_price:.3f}€ vs optimal: {optimal_price:.3f}€"

            return "No optimal window available"

        except Exception as e:
            _LOGGER.error(f"Error calculating runtime vs scheduled comparison: {e}")
            return "Calculation error"

    def _get_smart_delay_decision(self) -> str:
        """Show when and why smart_delay will trigger device start."""
        try:
            current_time = datetime.now()
            device_state = self._coordinator.device_states.get(self._device_name, {})
            device_config = self._coordinator.devices.get(self._device_name, {})

            # Check device mode
            device_mode = device_config.get('device_mode', 'smart_delay')
            if device_mode not in ['smart_delay', 'price_protection', 'hybrid']:
                return f"Mode: {device_mode} (auto-start not supported)"

            if not device_config.get('enabled', True):
                return "Device disabled"

            if not device_state.get('scheduler_enabled', True):
                return "Automation disabled"

            if device_state.get('device_running'):
                return "Currently running"

            # Get current price and thresholds
            current_price = self._get_current_price()
            if not current_price:
                return "No price data available"

            # Check Tibber data availability
            tibber_state = self.hass.states.get(self._coordinator.tibber_sensor)
            today_prices = tibber_state.attributes.get('today', []) if tibber_state else []
            tomorrow_prices = tibber_state.attributes.get('tomorrow', []) if tibber_state else []
            current_hour = current_time.hour

            # Show data availability status
            data_status = f"📊 Data: Today({len(today_prices)}h)"
            if tomorrow_prices:
                data_status += f", Tomorrow({len(tomorrow_prices)}h)"
            elif 13 <= current_hour <= 15:
                data_status += " | ⏳ Waiting for tomorrow data (1pm-3pm)"
            elif current_hour > 15:
                data_status += " | ⚠️ Tomorrow data missing"

            price_threshold = device_config.get('price_threshold', 0.30)
            use_cost_rate = device_config.get('use_cost_rate_attribute', False)
            run_same_day = device_config.get('same_day_only', False)

            # Check current price condition
            if use_cost_rate:
                tibber_state = self.hass.states.get(self._coordinator.tibber_sensor)
                if tibber_state:
                    current_rate = tibber_state.attributes.get('current_cost_rate', 'NORMAL')
                    cutoff_rate = device_config.get('cost_rate_cutoff', 'HIGH')
                    return f"Cost rate mode: {current_rate} (cutoff: {cutoff_rate})"
            else:
                price_status = "✅ CHEAP" if current_price <= price_threshold else "❌ EXPENSIVE"
                immediate_start = "Would start now" if current_price <= price_threshold else "Waiting for cheaper price"

            # Get optimal window info
            optimal_window = self._get_cached_optimal_window()

            # Add same-day indicator
            mode_indicator = "🔄 Same-day mode | " if run_same_day else ""

            if optimal_window:
                start_time = optimal_window['start_time']
                avg_price = optimal_window['avg_price']
                time_until = int((start_time - current_time).total_seconds() / 60)

                if time_until <= 5 and time_until >= -5:
                    return f"🚀 AUTO START NOW - Optimal window active (avg: {avg_price:.3f}€) | {data_status}"
                elif time_until > 0:
                    return f"{mode_indicator}⏰ AUTO START in {time_until}min at {start_time.strftime('%H:%M')} (avg: {avg_price:.3f}€) | Current: {current_price:.3f}€ {price_status} | {data_status}"
                else:
                    return f"{mode_indicator}⚠️ Optimal window missed | Current: {current_price:.3f}€ {price_status} | {immediate_start} | {data_status}"
            else:
                # No optimal window found
                if run_same_day and current_hour > 20:
                    return f"🔄 Same-day deadline passed | Current: {current_price:.3f}€ {price_status} | {data_status}"
                elif not tomorrow_prices and current_hour < 15:
                    return f"⏳ Waiting for tomorrow data (1pm-3pm) | Current: {current_price:.3f}€ {price_status} | {data_status}"
                else:
                    return f"{mode_indicator}No optimal window found | Current: {current_price:.3f}€ {price_status} | {immediate_start} | {data_status}"

        except Exception as e:
            _LOGGER.error(f"Error calculating smart delay decision: {e}")
            return "Error calculating decision"
    
    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes."""
        try:
            device_config = self._coordinator.devices.get(self._device_name, {})
            device_state = self._coordinator.device_states.get(self._device_name, {})
            
            attributes = {
                'device_name': self._device_name,
                'sensor_type': self._sensor_type,
                'device_mode': device_config.get('device_mode', 'smart_delay'),
                'enabled': device_config.get('enabled', True),
            }
            
            # Add sensor-specific attributes
            if self._sensor_type == "optimal_window":
                optimal_window = self._get_cached_optimal_window()
                if optimal_window:
                    attributes.update({
                        'optimal_start_time': optimal_window['start_time'].isoformat(),
                        'optimal_end_time': optimal_window['end_time'].isoformat(),
                        'optimal_avg_price': round(optimal_window['avg_price'], 4),
                        'window_found': True,
                        'duration_minutes': optimal_window['duration_minutes'],
                        'cache_time': self._cache_timestamp.isoformat() if self._cache_timestamp else None,
                    })
                else:
                    attributes['window_found'] = False
                    
            elif self._sensor_type == "program_analytics":
                analytics = self._coordinator.get_program_analytics(self._device_name)
                if 'error' not in analytics:
                    attributes.update({
                        'total_programs': analytics.get('total_programs', 0),
                        'completed_programs': analytics.get('completed_programs', 0),
                        'avg_duration_minutes': round(analytics.get('avg_duration_minutes', 0), 1),
                        'avg_cost_euros': round(analytics.get('avg_cost_euros', 0), 3),
                        'accuracy_duration': round(analytics.get('accuracy_duration', 0), 2),
                        'most_common_hour': analytics.get('most_common_start_hour', 0),
                    })
                    
            elif self._sensor_type == "last_program":
                history = device_state.get('program_history', [])
                if history:
                    last_program = history[-1]
                    attributes.update({
                        'program_id': last_program.get('program_id'),
                        'detection_method': 'power_spike',
                        'actual_duration': last_program.get('actual_duration'),
                        'estimated_duration': last_program.get('estimated_duration'),
                        'mode': last_program.get('mode'),
                    })

            elif self._sensor_type == "runtime_today":
                attributes.update({
                    'total_runtime_minutes': device_state.get('total_runtime_today', 0),
                    'runs_today': device_state.get('runs_today', 0),
                    'average_runtime_per_run': (device_state.get('total_runtime_today', 0) / max(1, device_state.get('runs_today', 1))) if device_state.get('runs_today', 0) > 0 else 0,
                })

            elif self._sensor_type == "power_price_correlation":
                device_config = self._coordinator.devices.get(self._device_name, {})
                power_sensor = device_config.get('power_sensor')
                if power_sensor and power_sensor != 'none':
                    power_state = self.hass.states.get(power_sensor)
                    if power_state and power_state.state not in ['unavailable', 'unknown']:
                        try:
                            current_power = float(power_state.state)
                            current_price = self._get_current_price()
                            # Get optimal window price for comparison
                            optimal_window = self._get_cached_optimal_window()
                            optimal_price = optimal_window['avg_price'] if optimal_window else None
                            optimal_cost_per_hour = round((current_power / 1000) * optimal_price, 3) if optimal_price else None
                            potential_savings = round((current_power / 1000) * (current_price - optimal_price), 3) if optimal_price else None

                            attributes.update({
                                'current_power_watts': current_power,
                                'current_price_eur_kwh': current_price,
                                'optimal_price_eur_kwh': optimal_price,
                                'power_sensor_entity': power_sensor,
                                'cost_per_hour_current': round((current_power / 1000) * current_price, 3) if current_price else None,
                                'cost_per_hour_optimal': optimal_cost_per_hour,
                                'potential_savings_per_hour': potential_savings,
                                'comparison_status': 'cheaper' if optimal_price and current_price <= optimal_price else 'more_expensive' if optimal_price else 'no_comparison',
                            })
                        except (ValueError, TypeError):
                            pass

            elif self._sensor_type == "current_consumption_cost":
                device_config = self._coordinator.devices.get(self._device_name, {})
                power_sensor = device_config.get('power_sensor')
                if power_sensor and power_sensor != 'none':
                    attributes.update({
                        'power_sensor_entity': power_sensor,
                        'calculation_method': 'power_watts / 1000 * price_eur_per_kwh',
                    })

            elif self._sensor_type == "runtime_vs_scheduled_comparison":
                optimal_window = self._get_cached_optimal_window()
                if optimal_window:
                    attributes.update({
                        'optimal_start_time': optimal_window['start_time'].isoformat(),
                        'optimal_avg_price': optimal_window['avg_price'],
                        'current_price': self._get_current_price(),
                        'comparison_method': 'current_vs_optimal_pricing',
                    })

            elif self._sensor_type == "smart_delay_decision":
                current_price = self._get_current_price()
                optimal_window = self._get_cached_optimal_window()

                attributes.update({
                    'device_mode': device_config.get('device_mode', 'smart_delay'),
                    'device_enabled': device_config.get('enabled', True),
                    'automation_enabled': device_state.get('scheduler_enabled', True),
                    'device_running': device_state.get('device_running', False),
                    'current_price': current_price,
                    'price_threshold': device_config.get('price_threshold', 0.30),
                    'use_cost_rate_attribute': device_config.get('use_cost_rate_attribute', False),
                    'same_day_only': device_config.get('same_day_only', False),
                    'search_length_hours': device_config.get('search_length', 8),
                })

                if current_price:
                    attributes['price_cheap'] = current_price <= device_config.get('price_threshold', 0.30)

                if optimal_window:
                    current_time = datetime.now()
                    time_until_start = int((optimal_window['start_time'] - current_time).total_seconds() / 60)
                    attributes.update({
                        'optimal_start_time': optimal_window['start_time'].isoformat(),
                        'optimal_avg_price': optimal_window['avg_price'],
                        'minutes_until_optimal': max(0, time_until_start),
                        'in_optimal_window': -5 <= time_until_start <= 5,
                    })

                # Add Tibber sensor info and data availability
                tibber_state = self.hass.states.get(self._coordinator.tibber_sensor)
                if tibber_state:
                    today_prices = tibber_state.attributes.get('today', [])
                    tomorrow_prices = tibber_state.attributes.get('tomorrow', [])
                    current_hour = datetime.now().hour

                    attributes.update({
                        'tibber_sensor_state': tibber_state.state,
                        'current_cost_rate': tibber_state.attributes.get('current_cost_rate', 'UNKNOWN'),
                        'today_prices_available': len(today_prices),
                        'tomorrow_prices_available': len(tomorrow_prices),
                        'tibber_data_refresh_window': '13:00-15:00 (next day data)',
                        'current_hour': current_hour,
                        'expecting_tomorrow_data': 13 <= current_hour <= 15 and len(tomorrow_prices) == 0,
                    })

            return attributes
            
        except Exception as e:
            _LOGGER.error(f"Error getting attributes for {self._device_name}_{self._sensor_type}: {e}")
            return {}

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tibber sensor entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    sensors = []
    
    # Create sensors for each device
    for device_name in coordinator.devices:
        for sensor_type in SENSOR_TYPES:
            sensors.append(TibberSmartSensor(coordinator, device_name, sensor_type))
    
    async_add_entities(sensors, True)
    
    _LOGGER.info(f"Added {len(sensors)} sensor entities for {len(coordinator.devices)} devices")
