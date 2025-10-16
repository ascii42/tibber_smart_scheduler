"""Cached forecast sensors with program detection data."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .tibber_api import TibberApiClient

_LOGGER = logging.getLogger(__name__)

# Version marker to verify file is loaded
_LOGGER.warning("🔥 TIBBER SENSOR.PY LOADED - VERSION 2025-10-02 09:30 - API CACHE ADDED 🔥")

# Global API cache (shared across all sensor instances)
_API_PRICE_CACHE = None
_API_CACHE_TIMESTAMP = None
_API_CACHE_LOCK = None


def make_aware(dt: datetime) -> datetime:
    """Make a datetime object timezone-aware using Home Assistant's default timezone."""
    if dt.tzinfo is None:
        return dt_util.as_local(dt)
    return dt


async def get_cached_api_forecast(hass: HomeAssistant, api_token: str, home_id: Optional[str] = None) -> Optional[Dict]:
    """Fetch price forecast from Tibber API with global caching."""
    global _API_PRICE_CACHE, _API_CACHE_TIMESTAMP, _API_CACHE_LOCK

    import asyncio
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    # Initialize lock on first use
    if _API_CACHE_LOCK is None:
        _API_CACHE_LOCK = asyncio.Lock()

    current_time = dt_util.now()

    # Check cache validity (15 minutes)
    async with _API_CACHE_LOCK:
        if _API_PRICE_CACHE and _API_CACHE_TIMESTAMP:
            age = current_time - _API_CACHE_TIMESTAMP
            if age < timedelta(minutes=15):
                _LOGGER.debug(f"Using cached API data (age: {age.total_seconds():.0f}s)")
                return _API_PRICE_CACHE

        # Fetch fresh data
        try:
            session = async_get_clientsession(hass)
            client = TibberApiClient(api_token, session=session)
            price_info = await client.get_price_info(home_id=home_id)

            if price_info:
                formatted_data = client.format_price_data(price_info)

                # Update cache
                _API_PRICE_CACHE = formatted_data
                _API_CACHE_TIMESTAMP = current_time

                today_count = len(formatted_data.get("today", []))
                tomorrow_count = len(formatted_data.get("tomorrow", []))
                _LOGGER.info(f"✅ Fetched fresh price data from Tibber API: {today_count} today, {tomorrow_count} tomorrow")

                return formatted_data
            else:
                _LOGGER.warning("Tibber API returned no price info")
                return None
        except Exception as e:
            _LOGGER.error(f"Error fetching from Tibber API: {e}")
            return None


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
        "state_class": None,
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
        "state_class": None,
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
            # Debug logging for availability checks
            _LOGGER.debug(f"Checking availability for {self._device_name}_{self._sensor_type}")

            # Check if device exists in coordinator
            if self._device_name not in self._coordinator.devices:
                _LOGGER.warning(f"Device {self._device_name} not found in coordinator devices: {list(self._coordinator.devices.keys())}")
                return False

            # For next_start and next_stop sensors, always available if device exists
            if self._sensor_type in ['next_start', 'next_stop']:
                _LOGGER.debug(f"{self._device_name}_{self._sensor_type} available (timestamp sensor)")
                return True

            # For optimal_window sensor, always available
            if self._sensor_type == 'optimal_window':
                _LOGGER.debug(f"{self._device_name}_{self._sensor_type} available (optimal window)")
                return True

            # For other sensors, check Tibber sensor availability
            tibber_state = self.hass.states.get(self._coordinator.tibber_sensor)
            if not tibber_state or tibber_state.state in ['unavailable', 'unknown']:
                _LOGGER.debug(f"{self._device_name}_{self._sensor_type} unavailable (Tibber sensor issue)")
                return False

            _LOGGER.debug(f"{self._device_name}_{self._sensor_type} available")
            return True

        except Exception as e:
            _LOGGER.error(f"Error checking availability for {self._device_name}_{self._sensor_type}: {e}")
            return False
    
    @property
    def native_value(self) -> StateType:
        """Return the sensor value."""
        try:
            if self._sensor_type == "next_start":
                next_start = self._get_next_start()
                return next_start
            elif self._sensor_type == "next_stop":
                next_stop = self._get_next_stop()
                return next_stop
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
        """Get next start time - ROBUST with better error handling."""
        try:
            device_state = self._coordinator.device_states.get(self._device_name, {})
            device_config = self._coordinator.devices.get(self._device_name, {})
            current_time = dt_util.now()

            # If currently running, return when it might start again (next day)
            if device_state.get('device_running'):
                tomorrow = current_time.replace(hour=6, minute=0, second=0, microsecond=0) + timedelta(days=1)
                return make_aware(tomorrow)

            # Get device mode to determine behavior
            device_mode = device_config.get('device_mode', 'smart_delay')

            # Check for scheduled start first (works for all modes)
            scheduled_start = device_state.get('scheduled_start')
            if (scheduled_start and
                isinstance(scheduled_start, datetime) and
                scheduled_start > current_time):
                return make_aware(scheduled_start)

            # Try optimal window calculation for all modes
            optimal_window = self._get_cached_optimal_window()

            if (optimal_window and
                'start_time' in optimal_window and
                isinstance(optimal_window['start_time'], datetime) and
                optimal_window['start_time'] > current_time):
                return make_aware(optimal_window['start_time'])

            # ALWAYS return a valid datetime - never None for timestamp sensors
            next_hour = current_time.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            return make_aware(next_hour)

        except Exception as e:
            _LOGGER.error(f"Error calculating next start for {self._device_name}: {e}")
            # Return a valid fallback datetime even on error
            current_time = dt_util.now()
            return make_aware(current_time.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
    
    def _get_next_stop(self) -> Optional[datetime]:
        """Get next stop time - prevent 'became unknown' by handling edge cases."""
        try:
            device_state = self._coordinator.device_states.get(self._device_name, {})
            device_config = self._coordinator.devices.get(self._device_name, {})
            current_time = dt_util.now()

            _LOGGER.debug(f"Calculating next stop for {self._device_name}")

            # If currently running, calculate end time from start time
            if device_state.get('device_running'):
                started_time = device_state.get('started_time')
                if started_time and isinstance(started_time, datetime):
                    duration = device_config.get('duration', 120)
                    end_time = started_time + timedelta(minutes=duration)
                    # Only return if it's still in the future
                    if end_time > current_time:
                        _LOGGER.debug(f"{self._device_name} next stop (currently running): {end_time}")
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
                    _LOGGER.debug(f"{self._device_name} next stop calculated from next start: {calculated_end}")
                    return make_aware(calculated_end)

            # ALWAYS return a valid datetime - calculate from fallback next start
            next_start = self._get_next_start()
            if next_start:
                duration = device_config.get('duration', 120)
                return make_aware(next_start + timedelta(minutes=duration))
            else:
                # Final fallback
                current_time = dt_util.now()
                next_hour = current_time.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
                duration = device_config.get('duration', 120)
                return make_aware(next_hour + timedelta(minutes=duration))

        except Exception as e:
            _LOGGER.error(f"Error calculating next stop for {self._device_name}: {e}")
            # Return a valid fallback datetime even on error
            current_time = dt_util.now()
            next_hour = current_time.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            return make_aware(next_hour + timedelta(minutes=120))  # Default 2 hour duration
    
    def _get_optimal_window(self) -> str:
        """Get optimal window description - CACHED with proper format."""
        optimal_window = self._get_cached_optimal_window()

        if not optimal_window:
            # Check if this is due to missing price data
            tibber_state = self.hass.states.get(self._coordinator.tibber_sensor)
            if not tibber_state:
                _LOGGER.error(f"Optimal window: Tibber sensor {self._coordinator.tibber_sensor} unavailable")
                return "Tibber sensor unavailable"

            if tibber_state.state in ['unavailable', 'unknown']:
                _LOGGER.warning(f"Optimal window: Tibber sensor state is {tibber_state.state}")
                return "Waiting for price data"

            today_prices = tibber_state.attributes.get('today', [])
            if not today_prices:
                # Check if we can use fallback data
                if 'min_price' in tibber_state.attributes and 'off_peak_1' in tibber_state.attributes:
                    _LOGGER.info(f"Optimal window: Using price level data from {self._coordinator.tibber_sensor}")
                    return "Using price levels (limited forecast)"
                else:
                    _LOGGER.error(f"Optimal window: No forecast data available. Attributes: {list(tibber_state.attributes.keys())}")
                    return "No price data available"

            _LOGGER.warning(f"Optimal window: Price data exists ({len(today_prices)} prices) but _get_cached_optimal_window() returned None")
            return "No optimal window calculated"

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
        """Get minutes until next start - STABLE using locked window."""
        # Use the same stable cached window to prevent jumping
        optimal_window = self._get_cached_optimal_window()
        current_time = dt_util.now()

        if (optimal_window and
            'start_time' in optimal_window and
            optimal_window['start_time'] > current_time):
            # Make sure both datetimes have timezone info for comparison
            start_time = make_aware(optimal_window['start_time']) if isinstance(optimal_window['start_time'], datetime) else optimal_window['start_time']
            minutes_until = max(0, int((start_time - current_time).total_seconds() / 60))
            return minutes_until

        # Fallback to next_start calculation
        next_start = self._get_next_start()
        if not next_start:
            return 0

        minutes_until = max(0, int((next_start - current_time).total_seconds() / 60))
        return minutes_until
    
    def _get_cached_optimal_window(self) -> Optional[dict]:
        """Get optimal window with DAILY LOCK based on Tibber data publication schedule."""
        current_time = dt_util.now()
        current_hour = current_time.hour

        # DAILY LOCK SYSTEM: Once calculated, lock until next day's data publication
        if (self._cached_optimal_window and
            self._cache_timestamp):

            # Check if we're in the same "day cycle" (before next Tibber data publication)
            cache_date = self._cache_timestamp.date()
            current_date = current_time.date()

            # Tibber publishes new data between 1pm-4pm for next day
            # Lock the window until the next day at 1pm (when new data might be available)
            if cache_date == current_date and current_hour < 13:
                # Same day, before 1pm - keep locked
                _LOGGER.debug(f"DAILY LOCK: Using cached window for {self._device_name} (same day, before 1pm)")
                return self._cached_optimal_window
            elif cache_date == current_date and current_hour >= 13:
                # Same day, after 1pm - keep locked unless start time passed
                if self._cached_optimal_window['start_time'] > current_time:
                    _LOGGER.debug(f"DAILY LOCK: Using cached window for {self._device_name} (same day, start time future)")
                    return self._cached_optimal_window
            elif (current_date - cache_date).days == 1 and current_hour < 13:
                # Next day, before 1pm - keep using yesterday's calculation
                if self._cached_optimal_window['start_time'] > current_time:
                    _LOGGER.debug(f"DAILY LOCK: Using cached window for {self._device_name} (next day, before 1pm)")
                    return self._cached_optimal_window

            # Only allow recalculation after start time has passed AND we're in data refresh window
            start_time = self._cached_optimal_window['start_time']
            if start_time <= current_time:
                # Start time has passed
                time_since_start = (current_time - start_time).total_seconds()
                if time_since_start < 1800:  # Within 30 minutes of start time
                    _LOGGER.debug(f"GRACE PERIOD: Holding window for {self._device_name} (started {time_since_start/60:.0f}min ago)")
                    return self._cached_optimal_window

        # ABSOLUTE LAST RESORT - only if no cache exists
        if not self._cached_optimal_window or not self._cache_timestamp:
            _LOGGER.warning(f"EMERGENCY RECALC: {self._device_name} - No cached window exists")

            # Try to calculate fresh window
            fresh_window = self._calculate_fresh_optimal_window()

            if fresh_window:
                # Successfully calculated - cache it
                self._cached_optimal_window = fresh_window
                self._cache_timestamp = current_time
                self._last_price_hash = self._get_price_data_hash()
                _LOGGER.info(f"✅ Optimal window calculated and locked for {self._device_name}")
            else:
                # Failed to calculate - use default fallback window
                if not self._cached_optimal_window:
                    # Create a default window for next off-peak period
                    _LOGGER.warning(f"⚠️ Using fallback window for {self._device_name} (sensor unavailable)")
                    self._cached_optimal_window = self._create_fallback_window()
                    self._cache_timestamp = current_time

        return self._cached_optimal_window

    def _create_fallback_window(self) -> dict:
        """Create a stable fallback window for next off-peak period when sensor unavailable."""
        current_time = dt_util.now()
        device_config = self._coordinator.devices.get(self._device_name, {})
        duration_minutes = device_config.get('duration', 120)
        run_same_day = device_config.get('same_day_only', False)

        # Determine next off-peak period (00:00-06:00 or 22:00-00:00)
        current_hour = current_time.hour
        end_of_today = dt_util.as_local(current_time.replace(hour=23, minute=59, second=59, microsecond=999999))

        if current_hour < 6:
            # Currently in morning off-peak (00:00-06:00)
            # Schedule for 01:00 today if we're before that, otherwise tomorrow (unless same_day_only)
            start_time = dt_util.as_local(current_time.replace(hour=1, minute=0, second=0, microsecond=0))
            if start_time <= current_time:
                # Already past 01:00
                if run_same_day:
                    # Same-day mode: can't schedule for tomorrow, use next available hour today
                    start_time = dt_util.as_local(current_time.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
                else:
                    # Use tomorrow 01:00
                    start_time = dt_util.as_local((current_time + timedelta(days=1)).replace(hour=1, minute=0, second=0, microsecond=0))
        elif current_hour < 22:
            # During day (06:00-22:00), schedule for evening off-peak at 22:30
            start_time = dt_util.as_local(current_time.replace(hour=22, minute=30, second=0, microsecond=0))
        else:
            # Currently in evening off-peak (22:00-00:00)
            # Schedule for 22:30 today if we're before that, otherwise tomorrow 01:00 (unless same_day_only)
            start_time = dt_util.as_local(current_time.replace(hour=22, minute=30, second=0, microsecond=0))
            if start_time <= current_time:
                # Already past 22:30
                if run_same_day:
                    # Same-day mode: can't use tomorrow, use next available slot before midnight
                    start_time = dt_util.as_local(current_time.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
                    # Make sure we don't go past midnight
                    if start_time > end_of_today:
                        start_time = dt_util.as_local(current_time + timedelta(minutes=5))  # Start in 5 minutes
                else:
                    # Use tomorrow morning
                    start_time = dt_util.as_local((current_time + timedelta(days=1)).replace(hour=1, minute=0, second=0, microsecond=0))

        end_time = dt_util.as_local(start_time + timedelta(minutes=duration_minutes))

        _LOGGER.info(f"📅 Created fallback window for {self._device_name}: {start_time.strftime('%Y-%m-%d %H:%M')} - {end_time.strftime('%H:%M')} (off-peak)")

        return {
            'start_time': start_time,
            'end_time': end_time,
            'avg_price': 0.20,  # Default fallback price
            'duration_minutes': duration_minutes,
            'is_fallback': True,
            'split_windows': [{
                'start_time': start_time,
                'end_time': end_time,
                'duration_minutes': duration_minutes
            }]
        }

    async def _fetch_from_tibber_api(self, api_token: str) -> Optional[dict]:
        """Fetch price data from Tibber API."""
        try:
            # Use Home Assistant's aiohttp session
            from homeassistant.helpers.aiohttp_client import async_get_clientsession
            session = async_get_clientsession(self.hass)

            # Get optional home_id from config
            home_id = self._coordinator.entry.data.get("tibber_home_id")

            client = TibberApiClient(api_token, session=session)
            price_info = await client.get_price_info(home_id=home_id)
            # Don't close - we're using HA's shared session

            if price_info:
                formatted_data = client.format_price_data(price_info)
                return formatted_data

            return None

        except Exception as e:
            _LOGGER.error(f"Error fetching from Tibber API: {e}")
            return None

    def _generate_forecast_from_price_levels(self, tibber_state) -> list:
        """Generate price forecast from off_peak/peak time ranges (fallback for sensors without 'today')."""
        try:
            current_time = dt_util.now()
            current_price = float(tibber_state.state)

            # Get price levels from attributes
            min_price = tibber_state.attributes.get('min_price', current_price * 0.7)
            avg_price = tibber_state.attributes.get('avg_price', current_price)
            max_price = tibber_state.attributes.get('max_price', current_price * 1.3)

            # Get time ranges (format: "HH:MM-HH:MM")
            off_peak_1 = tibber_state.attributes.get('off_peak_1', '00:00-06:00')
            peak = tibber_state.attributes.get('peak', '06:00-22:00')
            off_peak_2 = tibber_state.attributes.get('off_peak_2', '22:00-24:00')

            _LOGGER.info(f"Generating forecast: off_peak_1={off_peak_1}, peak={peak}, off_peak_2={off_peak_2}")

            # Build 24-hour forecast with 15-minute intervals (96 points)
            forecast = []
            base_date = current_time.replace(hour=0, minute=0, second=0, microsecond=0)

            for i in range(96):  # 24 hours * 4 (15-min intervals)
                interval_time = base_date + timedelta(minutes=i * 15)
                hour_min = interval_time.strftime('%H:%M')

                # Determine price based on time range
                if self._time_in_range(hour_min, off_peak_1) or self._time_in_range(hour_min, off_peak_2):
                    price = min_price
                elif self._time_in_range(hour_min, peak):
                    price = max_price
                else:
                    price = avg_price

                # Ensure timezone-aware datetime for starts_at
                if interval_time.tzinfo is None:
                    interval_time = dt_util.as_local(interval_time)

                forecast.append({
                    'starts_at': interval_time.isoformat(),
                    'total': price
                })

            return forecast

        except Exception as e:
            _LOGGER.error(f"Error generating forecast from price levels: {e}")
            return []

    def _time_in_range(self, time_str: str, range_str: str) -> bool:
        """Check if time is within range (e.g., '14:30' in '14:00-18:00')."""
        try:
            if not range_str or '-' not in range_str:
                return False

            start_str, end_str = range_str.split('-')
            time_val = int(time_str.replace(':', ''))
            start_val = int(start_str.replace(':', ''))
            end_val = int(end_str.replace(':', ''))

            # Handle midnight wraparound (e.g., 22:00-24:00 or 00:00-06:00)
            if end_val == 2400:
                end_val = 0
                return start_val <= time_val or time_val <= end_val

            return start_val <= time_val < end_val

        except Exception:
            return False

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

            # Fallback: use current price if no forecast
            if not today_prices:
                hash_data = f"{tibber_state.state}_{tibber_state.attributes.get('min_price', 0)}"

            return hash_data

        except Exception:
            return "error"
    
    def _calculate_fresh_optimal_window(self) -> Optional[dict]:
        """Calculate optimal window with proper split-run support for long durations."""
        try:
            import traceback
            device_config = self._coordinator.devices.get(self._device_name, {})
            duration_minutes = device_config.get('duration', 120)
            search_length = device_config.get('search_length', 8)
            run_same_day = device_config.get('same_day_only', False)
            allow_split_runs = device_config.get('allow_split_runs', True)
            strict_mode = device_config.get('strict_mode', False)

            # Get Tibber price forecast
            tibber_state = self.hass.states.get(self._coordinator.tibber_sensor)
            if not tibber_state:
                _LOGGER.debug(f"Tibber sensor {self._coordinator.tibber_sensor} not found (may still be loading)")
                return None

            # Log available attributes for debugging
            _LOGGER.info(f"Tibber sensor {self._coordinator.tibber_sensor} attributes: {list(tibber_state.attributes.keys())}")

            today_prices = tibber_state.attributes.get('today', [])
            tomorrow_prices = tibber_state.attributes.get('tomorrow', [])

            # Handle case where data might be stored as string (JSON)
            if isinstance(today_prices, str):
                try:
                    import json
                    today_prices = json.loads(today_prices)
                    _LOGGER.info(f"Parsed 'today' from JSON string")
                except Exception as e:
                    _LOGGER.error(f"Failed to parse 'today' JSON: {e}")
                    today_prices = []

            if isinstance(tomorrow_prices, str):
                try:
                    import json
                    tomorrow_prices = json.loads(tomorrow_prices)
                    _LOGGER.info(f"Parsed 'tomorrow' from JSON string")
                except Exception as e:
                    _LOGGER.error(f"Failed to parse 'tomorrow' JSON: {e}")
                    tomorrow_prices = []

            # Debug: Log the actual data structure
            if today_prices:
                _LOGGER.info(f"✅ Found {len(today_prices)} today prices. Sample: {today_prices[0] if today_prices else 'empty'}")
            else:
                _LOGGER.warning(f"⚠️ 'today' attribute is empty or missing. Type: {type(today_prices)}, Value: {today_prices}")

            # Try alternative attribute names if standard ones not found
            if not today_prices:
                # Check for common alternative attribute names
                alt_attrs = ['raw_today', 'prices_today', 'hourly_prices', 'price_data']
                for attr in alt_attrs:
                    if attr in tibber_state.attributes:
                        today_prices = tibber_state.attributes.get(attr, [])
                        _LOGGER.info(f"Using alternative attribute '{attr}' for today's prices")
                        break

            if not tomorrow_prices:
                alt_attrs = ['raw_tomorrow', 'prices_tomorrow']
                for attr in alt_attrs:
                    if attr in tibber_state.attributes:
                        tomorrow_prices = tibber_state.attributes.get(attr, [])
                        _LOGGER.info(f"Using alternative attribute '{attr}' for tomorrow's prices")
                        break

            if not today_prices:
                # Try to use pre-fetched cached API data (non-blocking)
                global _API_PRICE_CACHE
                if _API_PRICE_CACHE:
                    today_prices = _API_PRICE_CACHE.get("today", [])
                    tomorrow_prices = _API_PRICE_CACHE.get("tomorrow", [])
                    if today_prices:
                        _LOGGER.info(f"{self._device_name}: Using cached API data: {len(today_prices)} today, {len(tomorrow_prices)} tomorrow")
                    else:
                        _LOGGER.debug(f"{self._device_name}: Cached API data available but empty")

                # Fallback 2: Try to generate forecast from available data
                if not today_prices:
                    _LOGGER.warning(
                        f"{self._device_name}: No 'today' forecast in {self._coordinator.tibber_sensor}. "
                        f"Attempting to use available price data: {list(tibber_state.attributes.keys())}"
                    )

                    # Try to create forecast from off_peak/peak data
                    today_prices = self._generate_forecast_from_price_levels(tibber_state)

                    if not today_prices:
                        _LOGGER.error(
                            f"{self._device_name}: Cannot generate price forecast. "
                            f"Sensor has: {list(tibber_state.attributes.keys())}"
                        )
                        return None

                    _LOGGER.info(f"{self._device_name}: Generated {len(today_prices)} price points from available data")

            _LOGGER.info(f"{self._device_name}: Found {len(today_prices)} today prices, {len(tomorrow_prices)} tomorrow prices from {self._coordinator.tibber_sensor}")

            # Parse price data into simple format
            price_forecast = []
            current_time = dt_util.now()

            # Process today's prices
            for price_point in today_prices:
                try:
                    # Support both snake_case and camelCase
                    time_str = price_point.get('starts_at') or price_point.get('startsAt')
                    if not time_str:
                        _LOGGER.debug(f"Price point missing time field: {price_point.keys()}")
                        continue

                    price_time = datetime.fromisoformat(time_str.replace('Z', '+00:00'))

                    # Ensure timezone-aware
                    if price_time.tzinfo is None:
                        price_time = dt_util.as_local(price_time)
                    else:
                        # Convert to local timezone
                        price_time = dt_util.as_local(price_time)

                    price_forecast.append({
                        'time': price_time,
                        'price': float(price_point['total'])
                    })
                except Exception as e:
                    _LOGGER.debug(f"Error parsing price point: {e}")
                    continue

            # Process tomorrow's prices if available
            if not run_same_day and tomorrow_prices:
                for price_point in tomorrow_prices:
                    try:
                        # Support both snake_case and camelCase
                        time_str = price_point.get('starts_at') or price_point.get('startsAt')
                        if not time_str:
                            _LOGGER.debug(f"Price point missing time field: {price_point.keys()}")
                            continue

                        price_time = datetime.fromisoformat(time_str.replace('Z', '+00:00'))

                        # Ensure timezone-aware
                        if price_time.tzinfo is None:
                            price_time = dt_util.as_local(price_time)
                        else:
                            # Convert to local timezone
                            price_time = dt_util.as_local(price_time)

                        price_forecast.append({
                            'time': price_time,
                            'price': float(price_point['total'])
                        })
                    except Exception as e:
                        _LOGGER.debug(f"Error parsing price point: {e}")
                        continue

            # Filter to future hours only
            next_hour = current_time.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            price_forecast = [p for p in price_forecast if p['time'] >= next_hour]

            # Filter to same day only if requested
            if run_same_day:
                end_of_today = current_time.replace(hour=23, minute=59, second=59, microsecond=999999)
                price_forecast = [p for p in price_forecast if p['time'] <= end_of_today]
                _LOGGER.info(f"{self._device_name}: Same-day mode enabled - filtered to {len(price_forecast)} periods before midnight")

            if not price_forecast:
                return None

            # Sort by time
            price_forecast.sort(key=lambda x: x['time'])

            # Apply strict mode filtering if enabled
            if strict_mode:
                price_threshold = device_config.get('price_threshold', 0.30)
                price_forecast = [p for p in price_forecast if p['price'] <= price_threshold]

                if not price_forecast:
                    _LOGGER.info(f"No periods below price threshold {price_threshold} for {self._device_name}")
                    return None

            # Calculate optimal window(s)
            if duration_minutes <= 60 or not allow_split_runs:
                # Single window for short durations or no split allowed
                return self._find_single_optimal_window(price_forecast, duration_minutes)
            else:
                # Split run for long durations
                return self._find_split_optimal_windows(price_forecast, duration_minutes)

        except Exception as e:
            _LOGGER.error(f"Error calculating optimal window for {self._device_name}: {e}")
            _LOGGER.error(f"Traceback: {traceback.format_exc()}")
            return None

    def _find_single_optimal_window(self, price_forecast: list, duration_minutes: int) -> Optional[dict]:
        """Find single optimal window for the given duration (supports 15-min intervals)."""
        if not price_forecast:
            return None

        # Detect time interval (15 minutes or 60 minutes)
        if len(price_forecast) >= 2:
            interval_minutes = int((price_forecast[1]['time'] - price_forecast[0]['time']).total_seconds() / 60)
        else:
            interval_minutes = 60  # Default to hourly

        _LOGGER.info(f"Detected {interval_minutes}-minute price intervals")

        # Calculate how many intervals we need
        periods_needed = max(1, (duration_minutes + interval_minutes - 1) // interval_minutes)

        if len(price_forecast) < periods_needed:
            return None

        best_window = None
        best_avg_price = float('inf')

        # Find cheapest consecutive period
        for i in range(len(price_forecast) - periods_needed + 1):
            window_prices = price_forecast[i:i + periods_needed]
            avg_price = sum(p['price'] for p in window_prices) / len(window_prices)

            if avg_price < best_avg_price:
                best_avg_price = avg_price
                start_time = window_prices[0]['time']
                end_time = start_time + timedelta(minutes=duration_minutes)

                best_window = {
                    'start_time': start_time,
                    'end_time': end_time,
                    'avg_price': avg_price,
                    'duration_minutes': duration_minutes,
                    'split_windows': [{
                        'start_time': start_time,
                        'end_time': end_time,
                        'duration_minutes': duration_minutes
                    }]
                }

        return best_window

    def _find_split_optimal_windows(self, price_forecast: list, duration_minutes: int) -> Optional[dict]:
        """Find multiple optimal windows for split runs (e.g., 300 minutes -> multiple smaller windows)."""
        if not price_forecast:
            return None

        # Detect time interval (15 minutes or 60 minutes)
        if len(price_forecast) >= 2:
            interval_minutes = int((price_forecast[1]['time'] - price_forecast[0]['time']).total_seconds() / 60)
        else:
            interval_minutes = 60  # Default to hourly

        # Strategy: Find cheapest intervals that sum to total duration
        max_split_duration = 60  # Split into max 1-hour chunks
        total_chunks_needed = (duration_minutes + max_split_duration - 1) // max_split_duration  # Ceiling division

        # But we need to consider the actual interval granularity
        periods_per_chunk = max(1, max_split_duration // interval_minutes)
        total_periods_needed = (duration_minutes + interval_minutes - 1) // interval_minutes

        if len(price_forecast) < total_periods_needed:
            return None

        # Sort all available periods by price
        sorted_by_price = sorted(price_forecast, key=lambda x: x['price'])

        # Take the cheapest periods up to what we need
        selected_windows = sorted_by_price[:total_chunks_needed]

        # Sort selected windows back by time
        selected_windows.sort(key=lambda x: x['time'])

        # Create split windows
        split_windows = []
        total_duration = 0

        for i, window in enumerate(selected_windows):
            # Calculate duration for this chunk
            remaining_duration = duration_minutes - total_duration
            chunk_duration = min(max_split_duration, remaining_duration)

            split_windows.append({
                'start_time': window['time'],
                'end_time': window['time'] + timedelta(minutes=chunk_duration),
                'duration_minutes': chunk_duration
            })

            total_duration += chunk_duration

            if total_duration >= duration_minutes:
                break

        if not split_windows:
            return None

        # Calculate overall average price
        avg_price = sum(w['price'] for w in selected_windows[:len(split_windows)]) / len(split_windows)

        # Return first window as main window with split info
        first_window = split_windows[0]

        return {
            'start_time': first_window['start_time'],
            'end_time': first_window['end_time'],
            'avg_price': avg_price,
            'duration_minutes': first_window['duration_minutes'],
            'split_windows': split_windows,
            'is_split_run': True,
            'total_duration_minutes': duration_minutes
        }


    def _get_planned_hours_visualization(self, optimal_window: dict) -> list:
        """Create visualization data for planned usage hours on price graph."""
        try:
            planned_hours = []

            if optimal_window.get('is_split'):
                # Handle split runs
                split_windows = optimal_window.get('split_windows', [])
                for i, window in enumerate(split_windows):
                    start_hour = window['start_time'].hour
                    duration_hours = window['duration_minutes'] // 60

                    for hour_offset in range(duration_hours):
                        hour = start_hour + hour_offset
                        if hour < 24:  # Only today's hours for now
                            planned_hours.append({
                                'hour': hour,
                                'split_part': i + 1,
                                'total_splits': len(split_windows),
                                'type': 'split_run'
                            })
            else:
                # Handle single window
                start_hour = optimal_window['start_time'].hour
                duration_hours = optimal_window['duration_minutes'] // 60

                for hour_offset in range(duration_hours):
                    hour = start_hour + hour_offset
                    if hour < 24:  # Only today's hours for now
                        planned_hours.append({
                            'hour': hour,
                            'type': 'single_run'
                        })

            return planned_hours

        except Exception as e:
            _LOGGER.error(f"Error creating planned hours visualization: {e}")
            return []
    
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
    
    def _get_last_program(self) -> Optional[datetime]:
        """Get last program detection time."""
        try:
            device_state = self._coordinator.device_states.get(self._device_name, {})
            history = device_state.get('program_history', [])

            _LOGGER.debug(f"Getting last program for {self._device_name}, history count: {len(history)}")

            if not history:
                _LOGGER.debug(f"No program history for {self._device_name}")
                return None

            last_program = history[-1]
            detection_time = last_program.get('detection_time')

            _LOGGER.debug(f"Last program detection_time for {self._device_name}: {detection_time} (type: {type(detection_time)})")

            if isinstance(detection_time, datetime):
                return detection_time
            elif isinstance(detection_time, str):
                try:
                    return datetime.fromisoformat(detection_time)
                except ValueError as e:
                    _LOGGER.error(f"Error parsing detection_time string '{detection_time}': {e}")
                    return None

        except Exception as e:
            _LOGGER.error(f"Error getting last program for {self._device_name}: {e}")

        return None
    
    def _get_programs_today(self) -> int:
        """Get number of programs run today."""
        device_state = self._coordinator.device_states.get(self._device_name, {})
        return device_state.get('runs_today', 0)

    def _get_runtime_today(self) -> int:
        """Get total runtime today in minutes."""
        device_state = self._coordinator.device_states.get(self._device_name, {})
        current_time = dt_util.now()

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
            current_time = dt_util.now()
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
            current_time = dt_util.now()
            device_state = self._coordinator.device_states.get(self._device_name, {})
            device_config = self._coordinator.devices.get(self._device_name, {})

            # Check device mode
            device_mode = device_config.get('device_mode', 'smart_delay')
            if device_mode not in ['smart_delay', 'price_protection', 'hybrid', 'active_scheduler']:
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

            # Add learned program profiles to all sensors
            program_profiles = device_state.get('program_profiles', {})
            if program_profiles:
                attributes['learned_programs'] = len(program_profiles)
                attributes['program_profiles'] = {
                    key: {
                        'name': profile['name'],
                        'runs': profile['run_count'],
                        'avg_duration': f"{profile['avg_duration']:.0f} min",
                        'last_run': profile.get('last_run'),
                    }
                    for key, profile in program_profiles.items()
                }

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
                    'strict_mode': device_config.get('strict_mode', False),
                    'use_cost_rate_attribute': device_config.get('use_cost_rate_attribute', False),
                    'same_day_only': device_config.get('same_day_only', False),
                    'search_length_hours': device_config.get('search_length', 8),
                    'allow_split_runs': device_config.get('allow_split_runs', True),
                })

                if current_price:
                    attributes['price_cheap'] = current_price <= device_config.get('price_threshold', 0.30)

                if optimal_window:
                    current_time = dt_util.now()
                    time_until_start = int((optimal_window['start_time'] - current_time).total_seconds() / 60)
                    attributes.update({
                        'optimal_start_time': optimal_window['start_time'].isoformat(),
                        'optimal_end_time': optimal_window['end_time'].isoformat(),
                        'optimal_avg_price': optimal_window['avg_price'],
                        'minutes_until_optimal': max(0, time_until_start),
                        'in_optimal_window': -5 <= time_until_start <= 5,
                    })

                    # Add split window details if in split mode
                    if optimal_window.get('is_split'):
                        split_windows = optimal_window.get('split_windows', [])
                        attributes['is_split_run'] = True
                        attributes['total_split_windows'] = len(split_windows)
                        attributes['split_windows'] = [
                            {
                                'window_number': i + 1,
                                'start_time': window['start_time'].isoformat(),
                                'end_time': window['end_time'].isoformat(),
                                'duration_minutes': window['duration_minutes']
                            }
                            for i, window in enumerate(split_windows)
                        ]

                # Add optimal window visualization data
                if optimal_window:
                    planned_hours = self._get_planned_hours_visualization(optimal_window)
                    if planned_hours:
                        attributes.update({
                            'planned_usage_hours': planned_hours,
                            'cheapest_hours_overlay': True,
                        })

                # Add Tibber sensor info and data availability
                tibber_state = self.hass.states.get(self._coordinator.tibber_sensor)
                if tibber_state:
                    today_prices = tibber_state.attributes.get('today', [])
                    tomorrow_prices = tibber_state.attributes.get('tomorrow', [])
                    current_hour = dt_util.now().hour

                    # Enhanced diagnostic information
                    available_attrs = list(tibber_state.attributes.keys())
                    has_price_attrs = any(attr in available_attrs for attr in ['today', 'tomorrow', 'hourly_prices_today', 'raw_today'])

                    attributes.update({
                        'tibber_sensor_entity': self._coordinator.tibber_sensor,
                        'tibber_sensor_state': tibber_state.state,
                        'tibber_sensor_available': tibber_state.state not in ['unavailable', 'unknown'],
                        'current_cost_rate': tibber_state.attributes.get('current_cost_rate', 'UNKNOWN'),
                        'today_prices_available': len(today_prices),
                        'tomorrow_prices_available': len(tomorrow_prices),
                        'has_price_attributes': has_price_attrs,
                        'available_attributes': available_attrs[:10],  # First 10 to avoid too much data
                        'tibber_data_refresh_window': '13:00-15:00 (next day data)',
                        'current_hour': current_hour,
                        'expecting_tomorrow_data': 13 <= current_hour <= 15 and len(tomorrow_prices) == 0,
                        'price_data_diagnostic': f"Sensor: {tibber_state.state}, Today: {len(today_prices)}, Tomorrow: {len(tomorrow_prices)}, Attrs: {has_price_attrs}"
                    })
                else:
                    attributes.update({
                        'tibber_sensor_entity': self._coordinator.tibber_sensor,
                        'tibber_sensor_state': 'NOT_FOUND',
                        'tibber_sensor_available': False,
                        'price_data_diagnostic': f"Sensor {self._coordinator.tibber_sensor} not found in Home Assistant"
                    })

            return attributes
            
        except Exception as e:
            _LOGGER.error(f"Error getting attributes for {self._device_name}_{self._sensor_type}: {e}")
            return {}

class TibberApiStatusSensor(SensorEntity):
    """Sensor to show Tibber API connection status."""

    def __init__(self, coordinator):
        """Initialize the API status sensor."""
        self._coordinator = coordinator
        self._attr_name = "Tibber API Status"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_api_status"
        self._attr_icon = "mdi:api"
        self._last_check = None
        self._last_result = None

    @property
    def state(self) -> str:
        """Return the state of the sensor."""
        api_token = self._coordinator.entry.data.get("tibber_api_token")

        if not api_token:
            return "Not Configured"

        # Check if we have successfully used API recently
        if self._last_result == "success":
            return "Connected"
        elif self._last_result == "failed":
            return "Failed"
        else:
            return "Checking..."

    @property
    def extra_state_attributes(self):
        """Return additional attributes."""
        api_token = self._coordinator.entry.data.get("tibber_api_token")

        attributes = {
            "api_token_configured": bool(api_token),
            "integration": "Tibber Smart Scheduler",
        }

        if api_token:
            # Mask token in display
            masked_token = f"{api_token[:10]}...{api_token[-4:]}" if len(api_token) > 14 else "***"
            attributes["token_preview"] = masked_token

        if self._last_check:
            attributes["last_check"] = self._last_check.isoformat()

        if self._last_result:
            attributes["last_result"] = self._last_result

        # Check sensor data source
        tibber_state = self.hass.states.get(self._coordinator.tibber_sensor)
        if tibber_state:
            has_today = bool(tibber_state.attributes.get("today"))
            has_tomorrow = bool(tibber_state.attributes.get("tomorrow"))

            attributes["sensor_has_forecast"] = has_today
            attributes["data_source"] = "Sensor" if has_today else ("API" if api_token else "Fallback")

            if has_today:
                attributes["forecast_points_today"] = len(tibber_state.attributes.get("today", []))
                attributes["forecast_points_tomorrow"] = len(tibber_state.attributes.get("tomorrow", []))

        return attributes

    async def async_update(self):
        """Update the sensor by testing API connection."""
        api_token = self._coordinator.entry.data.get("tibber_api_token")

        if not api_token:
            self._last_result = None
            return

        # Test API connection
        try:
            from homeassistant.helpers.aiohttp_client import async_get_clientsession
            session = async_get_clientsession(self.hass)

            client = TibberApiClient(api_token, session=session)
            price_info = await client.get_price_info()

            self._last_check = dt_util.now()

            if price_info:
                today_count = len(price_info.get("today", []))
                tomorrow_count = len(price_info.get("tomorrow", []))

                if today_count > 0:
                    self._last_result = "success"
                    _LOGGER.debug(f"API check successful: {today_count} today, {tomorrow_count} tomorrow")
                else:
                    self._last_result = "failed"
                    _LOGGER.warning("API returned but no price data")
            else:
                self._last_result = "failed"
                _LOGGER.warning("API check failed - no price info")

        except Exception as e:
            self._last_check = dt_util.now()
            self._last_result = "failed"
            _LOGGER.debug(f"API check error: {e}")

    @property
    def icon(self) -> str:
        """Return icon based on status."""
        state = self.state
        if state == "Connected":
            return "mdi:api-check"
        elif state == "Failed":
            return "mdi:api-off"
        elif state == "Not Configured":
            return "mdi:api"
        else:
            return "mdi:api-clock"


class TibberForecastSensor(SensorEntity):
    """Sensor to display cached API forecast data."""

    def __init__(self, coordinator):
        """Initialize the forecast sensor."""
        self._coordinator = coordinator
        self._attr_name = "Tibber Forecast Data"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_forecast"
        self._attr_icon = "mdi:chart-line"

    @property
    def state(self):
        """Return the state of the sensor."""
        global _API_PRICE_CACHE, _API_CACHE_TIMESTAMP
        if _API_PRICE_CACHE:
            today_count = len(_API_PRICE_CACHE.get("today", []))
            tomorrow_count = len(_API_PRICE_CACHE.get("tomorrow", []))
            return f"{today_count} today, {tomorrow_count} tomorrow"
        return "No data"

    @property
    def extra_state_attributes(self):
        """Return forecast data as attributes."""
        global _API_PRICE_CACHE, _API_CACHE_TIMESTAMP

        attributes = {}

        if _API_CACHE_TIMESTAMP:
            attributes["last_updated"] = _API_CACHE_TIMESTAMP.isoformat()
            age = (dt_util.now() - _API_CACHE_TIMESTAMP).total_seconds() / 60
            attributes["cache_age_minutes"] = round(age, 1)

        if _API_PRICE_CACHE:
            today = _API_PRICE_CACHE.get("today", [])
            tomorrow = _API_PRICE_CACHE.get("tomorrow", [])

            if today:
                attributes["today_prices"] = len(today)
                attributes["today_min"] = min(p["total"] for p in today)
                attributes["today_max"] = max(p["total"] for p in today)
                attributes["today_avg"] = sum(p["total"] for p in today) / len(today)
                # Show first few price points
                attributes["today_sample"] = today[:5]

            if tomorrow:
                attributes["tomorrow_prices"] = len(tomorrow)
                attributes["tomorrow_min"] = min(p["total"] for p in tomorrow)
                attributes["tomorrow_max"] = max(p["total"] for p in tomorrow)
                attributes["tomorrow_avg"] = sum(p["total"] for p in tomorrow) / len(tomorrow)
                attributes["tomorrow_sample"] = tomorrow[:5]

        return attributes


class TibberPriceDetailSensor(SensorEntity):
    """Sensor for detailed Tibber price information (energy, tax, etc)."""

    def __init__(self, coordinator, detail_type: str):
        """Initialize the price detail sensor."""
        self._coordinator = coordinator
        self._detail_type = detail_type
        self._attr_unique_id = f"{coordinator.entry.entry_id}_price_{detail_type}"

        detail_config = {
            "energy": {"name": "Energy Cost", "icon": "mdi:lightning-bolt", "unit": None},
            "tax": {"name": "Tax", "icon": "mdi:currency-eur", "unit": None},
            "total": {"name": "Current Total Price", "icon": "mdi:cash", "unit": None},
            "level": {"name": "Price Level", "icon": "mdi:chart-line", "unit": None},
        }

        config = detail_config.get(detail_type, {})
        self._attr_name = f"Tibber {config.get('name', detail_type.title())}"
        self._attr_icon = config.get('icon', 'mdi:currency-eur')
        self._attr_native_unit_of_measurement = config.get('unit')
        self._current_data = None

    @property
    def state(self):
        """Return the state of the sensor."""
        if not self._current_data:
            return None

        if self._detail_type == "level":
            return self._current_data.get("level", "NORMAL")
        else:
            value = self._current_data.get(self._detail_type)
            if value is not None:
                return round(value, 4) if isinstance(value, (int, float)) else value
        return None

    @property
    def extra_state_attributes(self):
        """Return additional attributes."""
        if not self._current_data:
            return {}

        return {
            "currency": self._current_data.get("currency", "EUR"),
            "starts_at": self._current_data.get("starts_at"),
            "level": self._current_data.get("level", "NORMAL"),
            "integration": "Tibber Smart Scheduler",
        }

    async def async_update(self):
        """Update the sensor by fetching from Tibber API."""
        api_token = self._coordinator.entry.data.get("tibber_api_token")
        if not api_token:
            # Try to get from sensor instead
            tibber_state = self.hass.states.get(self._coordinator.tibber_sensor)
            if tibber_state:
                today_prices = tibber_state.attributes.get("today", [])
                if today_prices:
                    # Use current hour price
                    current_time = dt_util.now()
                    for price in today_prices:
                        price_time_str = price.get("starts_at") or price.get("startsAt")
                        if price_time_str:
                            price_time = datetime.fromisoformat(price_time_str.replace('Z', '+00:00'))
                            price_time = dt_util.as_local(price_time)
                            if price_time.hour == current_time.hour:
                                self._current_data = price
                                return
            return

        try:
            from homeassistant.helpers.aiohttp_client import async_get_clientsession
            session = async_get_clientsession(self.hass)

            home_id = self._coordinator.entry.data.get("tibber_home_id")
            client = TibberApiClient(api_token, session=session)
            price_info = await client.get_price_info(home_id=home_id)

            if price_info:
                formatted = client.format_price_data(price_info)
                self._current_data = formatted.get("current")

        except Exception as e:
            _LOGGER.debug(f"Error updating price detail sensor: {e}")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tibber sensor entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    # Note: API forecast fetching is handled by periodic timer in __init__.py
    _LOGGER.info(f"Setting up sensor platform with {len(coordinator.devices)} devices")

    sensors = []

    # Add global API status sensor
    sensors.append(TibberApiStatusSensor(coordinator))

    # Add forecast data sensor
    sensors.append(TibberForecastSensor(coordinator))

    # Add price visualization sensor
    sensors.append(TibberPriceVisualizationSensor(coordinator))

    # Add price detail sensors
    for detail_type in ["energy", "tax", "total", "level"]:
        sensors.append(TibberPriceDetailSensor(coordinator, detail_type))

    # Create sensors for each device
    for device_name in coordinator.devices:
        for sensor_type in SENSOR_TYPES:
            sensors.append(TibberSmartSensor(coordinator, device_name, sensor_type))

        # Add running program sensor for each device
        sensors.append(TibberRunningProgramSensor(coordinator, device_name))

    async_add_entities(sensors, True)

    # Register service to manually fetch API forecast
    async def handle_fetch_forecast(call):
        """Service to manually trigger API forecast fetch."""
        api_token = entry.data.get("tibber_api_token")
        if api_token:
            home_id = entry.data.get("tibber_home_id")
            await get_cached_api_forecast(hass, api_token, home_id)
            _LOGGER.info("Manual API forecast fetch completed")
        else:
            _LOGGER.warning("No API token configured - cannot fetch forecast")

    hass.services.async_register(DOMAIN, "fetch_forecast", handle_fetch_forecast)
    _LOGGER.info("✅ Registered tibber_smart_scheduler.fetch_forecast service")

    _LOGGER.info(f"Added {len(sensors)} sensor entities for {len(coordinator.devices)} devices")


class TibberPriceVisualizationSensor(SensorEntity):
    """Sensor for visualizing upcoming Tibber prices."""

    def __init__(self, coordinator):
        """Initialize the price visualization sensor."""
        self._coordinator = coordinator
        self._attr_name = "Tibber Price Visualization"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_price_visualization"
        self._attr_icon = "mdi:chart-line"
        self._prices = []

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._coordinator.entry.entry_id)},
            "name": "Tibber Smart Scheduler",
            "manufacturer": "Custom",
            "model": "Smart Price Scheduler with Power Detection",
            "sw_version": "0.6.0",
        }

    @property
    def state(self) -> StateType:
        """Return the number of price points available."""
        return len(self._prices)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return visualization attributes."""
        if not self._prices:
            return {}

        current_time = datetime.now()

        # Calculate statistics
        prices_only = [p['price'] for p in self._prices]
        avg_price = sum(prices_only) / len(prices_only) if prices_only else 0
        min_price = min(prices_only) if prices_only else 0
        max_price = max(prices_only) if prices_only else 0

        # Find current price
        current_price = None
        for p in self._prices:
            if p['time'] <= current_time < p['time'] + timedelta(hours=1):
                current_price = p['price']
                break

        # Prepare chart-friendly data
        chart_labels = []
        chart_prices = []
        chart_colors = []
        optimal_hours = []

        for p in self._prices:
            time_str = p['time'].strftime('%H:%M')
            chart_labels.append(time_str)
            chart_prices.append(round(p['price'], 3))

            # Color code based on price level
            if p['price'] <= avg_price * 0.7:
                chart_colors.append('green')  # Very cheap
                optimal_hours.append(time_str)
            elif p['price'] <= avg_price:
                chart_colors.append('lightgreen')  # Below average
            elif p['price'] <= avg_price * 1.3:
                chart_colors.append('orange')  # Above average
            else:
                chart_colors.append('red')  # Expensive

        return {
            'prices': self._prices,
            'price_count': len(self._prices),
            'current_price': current_price,
            'average_price': round(avg_price, 3),
            'min_price': round(min_price, 3),
            'max_price': round(max_price, 3),
            'optimal_hours': optimal_hours,

            # Chart-friendly format
            'chart_labels': chart_labels,
            'chart_prices': chart_prices,
            'chart_colors': chart_colors,

            # ApexCharts compatible format
            'apexcharts_data': [
                {'x': p['time'].isoformat(), 'y': round(p['price'], 3)}
                for p in self._prices
            ],

            'last_update': current_time.isoformat(),
        }

    async def async_update(self):
        """Update the price data."""
        try:
            # Get price data from Tibber sensor
            tibber_state = self.hass.states.get(self._coordinator.tibber_sensor)
            if not tibber_state:
                return

            today_prices = tibber_state.attributes.get('today', [])
            tomorrow_prices = tibber_state.attributes.get('tomorrow', [])

            prices = []

            # Parse today's prices
            for price_data in today_prices:
                if 'starts_at' in price_data:
                    try:
                        price_time = datetime.fromisoformat(price_data['starts_at'].replace('Z', '+00:00'))
                        if price_time.tzinfo:
                            price_time = price_time.replace(tzinfo=None)

                        prices.append({
                            'time': price_time,
                            'price': float(price_data.get('total', 0)),
                            'day': 'today'
                        })
                    except Exception as e:
                        _LOGGER.debug(f"Error parsing price: {e}")

            # Parse tomorrow's prices
            for price_data in tomorrow_prices:
                if 'starts_at' in price_data:
                    try:
                        price_time = datetime.fromisoformat(price_data['starts_at'].replace('Z', '+00:00'))
                        if price_time.tzinfo:
                            price_time = price_time.replace(tzinfo=None)

                        prices.append({
                            'time': price_time,
                            'price': float(price_data.get('total', 0)),
                            'day': 'tomorrow'
                        })
                    except Exception as e:
                        _LOGGER.debug(f"Error parsing price: {e}")

            # Sort by time
            prices.sort(key=lambda x: x['time'])

            # Filter to upcoming prices only (from current hour)
            current_time = datetime.now()
            current_hour = current_time.replace(minute=0, second=0, microsecond=0)
            self._prices = [p for p in prices if p['time'] >= current_hour]

        except Exception as e:
            _LOGGER.error(f"Error updating price visualization: {e}")


class TibberRunningProgramSensor(SensorEntity):
    """Sensor showing the currently running program for a device."""

    def __init__(self, coordinator, device_name: str):
        """Initialize the running program sensor."""
        self._coordinator = coordinator
        self._device_name = device_name
        self._attr_name = f"{device_name.replace('_', ' ').title()} Running Program"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{device_name}_running_program"
        self._attr_icon = "mdi:play-circle"

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self._coordinator.entry.entry_id)},
            "name": "Tibber Smart Scheduler",
            "manufacturer": "Custom",
            "model": "Smart Price Scheduler with Power Detection",
            "sw_version": "0.6.0",
        }

    @property
    def state(self) -> StateType:
        """Return the program name or 'idle'."""
        device_state = self._coordinator.device_states.get(self._device_name, {})

        if device_state.get('device_running'):
            return device_state.get('program_name', 'Unnamed Program')

        return 'idle'

    @property
    def icon(self) -> str:
        """Return dynamic icon."""
        device_state = self._coordinator.device_states.get(self._device_name, {})

        if device_state.get('device_running'):
            return "mdi:play-circle"

        return "mdi:stop-circle-outline"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return program details."""
        device_state = self._coordinator.device_states.get(self._device_name, {})
        device_config = self._coordinator.devices.get(self._device_name, {})

        attributes = {
            'device_running': device_state.get('device_running', False),
            'program_id': device_state.get('program_id'),
            'program_name': device_state.get('program_name', 'Unnamed Program'),
            'started_time': device_state.get('started_time'),
            'programmed_time': device_state.get('programmed_time'),
            'estimated_duration': device_state.get('estimated_duration', device_config.get('duration', 120)),
        }

        # Calculate runtime and remaining time
        if device_state.get('device_running') and device_state.get('started_time'):
            started = device_state['started_time']
            duration = device_state.get('estimated_duration', device_config.get('duration', 120))
            current_time = datetime.now()

            runtime_minutes = (current_time - started).total_seconds() / 60
            remaining_minutes = max(0, duration - runtime_minutes)
            estimated_end = started + timedelta(minutes=duration)

            attributes.update({
                'runtime_minutes': int(runtime_minutes),
                'remaining_minutes': int(remaining_minutes),
                'estimated_end_time': estimated_end.isoformat(),
                'progress_percent': min(100, int((runtime_minutes / duration) * 100))
            })

        return attributes
