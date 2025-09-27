"""Complete Functional Tibber Smart Scheduler - Stable Schedule Version."""

import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_ENTITIES, SERVICE_TURN_ON, SERVICE_TURN_OFF, STATE_ON, STATE_OFF

from .const import DOMAIN, CONF_TIBBER_SENSOR

_LOGGER = logging.getLogger(__name__)

class TibberSmartCoordinator:
    """Enhanced coordinator with stable schedule management."""
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        self.hass = hass
        self.entry = entry
        self.tibber_sensor = entry.data[CONF_TIBBER_SENSOR]
        self.devices = {}
        self.device_states = {}
        self._store = Store(hass, 1, f"tibber_smart_{entry.entry_id}")
        self._unsub_update = None
        self._unsub_state_change = None
        self._unsub_entity_changes = []
        self._async_add_entities = None
        self._scheduled_tasks = {}  # Track scheduled start tasks
        
        _LOGGER.info(f"Coordinator initialized with Tibber sensor: {self.tibber_sensor}")
        
    async def async_load_devices(self):
        """Load devices from storage."""
        try:
            stored_data = await self._store.async_load()
            if stored_data:
                self.devices = stored_data.get("devices", {})
                for device_name in self.devices:
                    self._init_device_state(device_name)
            _LOGGER.info(f"Loaded {len(self.devices)} devices from storage")
        except Exception as e:
            _LOGGER.error(f"Error loading devices: {e}")
            self.devices = {}
        
    def _init_device_state(self, device_name: str):
        """Initialize device state tracking with stable schedule fields."""
        self.device_states[device_name] = {
            'state': 'idle',
            'device_running': False,
            'programmed_time': None,
            'started_time': None,
            'last_power_reading': 0,
            'program_detected': False,
            'waiting_for_cheap_price': False,
            'optimal_start': False,
            'manual_override_until': None,
            'runs_today': 0,
            'total_runtime_today': 0,
            'scheduler_enabled': True,
            
            # Stable scheduling fields
            'scheduled_start': None,
            'scheduled_end': None,
            'schedule_locked': False,
            'schedule_calculated_at': None,
            'schedule_valid_until': None,
            'estimated_cost': None,
            'estimated_duration': None,
            'program_id': None,
            'program_history': [],
            'next_optimal_window': None,
            'last_schedule_check': None
        }
        _LOGGER.debug(f"Initialized state for device: {device_name}")
        
    async def add_device(self, device_config):
        """Add a device with monitoring setup."""
        device_name = device_config[CONF_NAME]
        self.devices[device_name] = device_config
        self._init_device_state(device_name)
        
        # Set up monitoring
        await self._setup_monitoring(device_name)
        
        # Create switch entity
        if self._async_add_entities:
            from .switch import UnifiedTibberSwitch
            new_entity = UnifiedTibberSwitch(self, device_name)
            self._async_add_entities([new_entity])
        
        await self.async_save_devices()
        
        power_sensor = device_config.get('power_sensor', 'none')
        device_mode = device_config.get('device_mode', 'smart_delay')
        _LOGGER.info(f"Added device {device_name} in {device_mode} mode with power sensor: {power_sensor}")
            
    async def _setup_monitoring(self, device_name: str):
        """Set up power sensor and entity monitoring."""
        device_config = self.devices[device_name]
        
        # Monitor controlled entities
        entities = device_config.get(CONF_ENTITIES, [])
        for entity_id in entities:
            _LOGGER.debug(f"Setting up entity monitoring: {entity_id}")
            
            def make_entity_handler(dev_name, ent_id):
                async def entity_changed(event):
                    await self._entity_state_changed(dev_name, ent_id, event)
                return entity_changed
            
            self._unsub_entity_changes.append(
                async_track_state_change_event(
                    self.hass, [entity_id], make_entity_handler(device_name, entity_id)
                )
            )
        
        # Monitor power sensor
        power_sensor = device_config.get('power_sensor')
        if power_sensor and power_sensor != "none":
            _LOGGER.info(f"Setting up power monitoring: {power_sensor} for {device_name}")
            
            def make_power_handler(dev_name):
                async def power_changed(event):
                    await self._power_sensor_changed(dev_name, event)
                return power_changed
            
            self._unsub_entity_changes.append(
                async_track_state_change_event(
                    self.hass, [power_sensor], make_power_handler(device_name)
                )
            )
        else:
            _LOGGER.warning(f"No power sensor configured for {device_name}")

    async def _power_sensor_changed(self, device_name: str, event):
        """Handle power sensor changes - Enhanced with automatic scheduling."""
        new_state = event.data.get('new_state')
        old_state = event.data.get('old_state')
        
        if not new_state or not old_state:
            return
            
        try:
            old_power = float(old_state.state) if old_state.state not in ['unavailable', 'unknown'] else 0
            new_power = float(new_state.state) if new_state.state not in ['unavailable', 'unknown'] else 0
            min_power = self.devices[device_name].get('min_power_detection', 15)
            
            device_state = self.device_states[device_name]
            device_state['last_power_reading'] = new_power
            
            _LOGGER.debug(f"Power change {device_name}: {old_power:.1f}W -> {new_power:.1f}W (threshold: {min_power}W)")
            
            # Detect manual start (power spike above threshold)
            if old_power < min_power and new_power >= min_power:
                await self._handle_manual_start(device_name)
            
            # Detect completion (power drop below threshold)
            elif old_power >= min_power and new_power < min_power:
                await self._handle_completion(device_name)
                
        except (ValueError, TypeError) as e:
            _LOGGER.warning(f"Error parsing power values for {device_name}: {e}")

    async def _handle_manual_start(self, device_name: str):
        """Enhanced manual start detection with optimal rescheduling."""
        device_config = self.devices[device_name]
        device_state = self.device_states[device_name]
        
        # Skip if already being handled or scheduled start
        if device_state['device_running'] or device_state['optimal_start']:
            _LOGGER.debug(f"Device {device_name} already running, ignoring power spike")
            return
        
        # Skip if this is a scheduled start (we turned it on)
        if device_state.get('state') == 'scheduled_running':
            _LOGGER.info(f"SCHEDULED START CONFIRMED: {device_name}")
            device_state['device_running'] = True
            device_state['started_time'] = datetime.now()
            return
        
        _LOGGER.warning(f"PROGRAM DETECTED: {device_name}")
        
        # Record program detection
        program_data = await self._analyze_program_start(device_name)
        device_state.update(program_data)
        
        # Get price information
        price_data = await self._get_price_data()
        if not price_data:
            _LOGGER.error(f"Cannot get price data for {device_name}")
            return
        
        # Handle based on device mode
        device_mode = device_config.get('device_mode', 'smart_delay')
        
        if device_mode == 'active_scheduler':
            # Active scheduler: immediate cutoff and reschedule
            await self._cutoff_and_reschedule(device_name, price_data, program_data)
        elif device_mode == 'smart_delay':
            # Smart delay: check if optimal, otherwise reschedule
            await self._smart_delay_decision(device_name, price_data, program_data)
        else:
            # Fallback: original price check behavior
            await self._check_price_threshold(device_name, price_data)

    async def _analyze_program_start(self, device_name: str) -> dict:
        """Analyze detected program to estimate duration and energy use."""
        device_config = self.devices[device_name]
        device_state = self.device_states[device_name]
        
        current_time = datetime.now()
        
        # Get historical data for better estimates
        history = device_state.get('program_history', [])
        estimated_duration = self._estimate_duration_from_history(history, device_config)
        
        program_id = f"{device_name}_{current_time.strftime('%Y%m%d_%H%M%S')}"
        
        return {
            'program_detected': True,
            'programmed_time': current_time,
            'program_id': program_id,
            'estimated_duration': estimated_duration,
            'detection_method': 'power_spike'
        }

    def _estimate_duration_from_history(self, history: list, device_config: dict) -> int:
        """Estimate duration based on historical data."""
        if not history:
            return device_config.get('duration', 120)
        
        # Use recent programs for estimation
        recent_durations = [
            r.get('actual_duration', 120) for r in history[-10:] 
            if r.get('actual_duration')
        ]
        
        if recent_durations:
            return int(sum(recent_durations) / len(recent_durations))
        
        return device_config.get('duration', 120)

    async def _cutoff_and_reschedule(self, device_name: str, price_data: dict, program_data: dict):
        """Cut off device and reschedule for optimal time (Active Scheduler mode)."""
        device_config = self.devices[device_name]
        device_state = self.device_states[device_name]
        
        # Turn off device immediately
        entities = device_config.get(CONF_ENTITIES, [])
        await self._turn_off_entities(entities)
        
        _LOGGER.info(f"CUT OFF: {device_name} for rescheduling")
        
        # Calculate and lock stable schedule
        await self._calculate_and_lock_schedule(device_name, program_data['estimated_duration'])

    async def _smart_delay_decision(self, device_name: str, price_data: dict, program_data: dict):
        """Smart delay decision: check current conditions vs optimal window."""
        device_config = self.devices[device_name]
        device_state = self.device_states[device_name]
        
        current_price = price_data['current_price']
        
        # Check if we should calculate optimal window (only if significant savings possible)
        optimal_window = await self._get_potential_optimal_window(device_name, program_data['estimated_duration'])
        
        if optimal_window:
            optimal_price = optimal_window.get('avg_price', current_price)
            savings_threshold = device_config.get('savings_threshold', 0.05)  # 5 cents minimum savings
            
            # If optimal window is significantly cheaper, reschedule
            if (optimal_price + savings_threshold) < current_price:
                await self._cutoff_and_reschedule(device_name, price_data, program_data)
                return
        
        # Otherwise, apply normal price threshold check
        await self._check_price_threshold(device_name, price_data)

    async def _calculate_and_lock_schedule(self, device_name: str, duration_minutes: int = None):
        """Calculate optimal window once and lock it until executed - STABLE VERSION."""
        device_state = self.device_states[device_name]
        device_config = self.devices[device_name]
        
        # Don't recalculate if we already have a valid locked schedule
        if (device_state.get('schedule_locked') and 
            device_state.get('scheduled_start') and
            device_state['scheduled_start'] > datetime.now()):
            _LOGGER.debug(f"Schedule already locked for {device_name}")
            return
        
        # Calculate new schedule
        if duration_minutes is None:
            duration_minutes = device_config.get('duration', 120)
            
        optimal_window = await self._find_optimal_window(device_name, duration_minutes)
        
        if optimal_window:
            # Lock the schedule
            device_state['scheduled_start'] = optimal_window['start_time']
            device_state['scheduled_end'] = optimal_window['end_time']
            device_state['schedule_locked'] = True
            device_state['schedule_calculated_at'] = datetime.now()
            device_state['schedule_valid_until'] = optimal_window['start_time'] + timedelta(hours=1)
            device_state['estimated_cost'] = optimal_window.get('estimated_cost', 0)
            device_state['state'] = 'scheduled'
            
            await self._schedule_automatic_start(device_name, optimal_window)
            
            _LOGGER.info(f"LOCKED SCHEDULE: {device_name} at {optimal_window['start_time'].strftime('%H:%M')} "
                        f"(avg price: {optimal_window.get('avg_price', 0):.3f} EUR/kWh)")
        else:
            # No good window found - allow to run now if this was a cutoff
            if device_state.get('program_detected'):
                entities = device_config.get(CONF_ENTITIES, [])
                await self._turn_on_entities(entities)
                device_state['state'] = 'running'
                device_state['device_running'] = True
                device_state['started_time'] = datetime.now()
                _LOGGER.warning(f"NO OPTIMAL WINDOW: {device_name} running immediately")

    async def _get_potential_optimal_window(self, device_name: str, duration_minutes: int) -> Optional[dict]:
        """Get potential optimal window without locking (for comparison)."""
        try:
            device_config = self.devices[device_name]
            search_length = device_config.get('search_length', 4)  # Shorter search for smart delay
            
            # Get Tibber price forecast
            tibber_state = self.hass.states.get(self.tibber_sensor)
            if not tibber_state:
                return None
            
            # Get today/tomorrow prices
            today_prices = tibber_state.attributes.get('today', [])
            tomorrow_prices = tibber_state.attributes.get('tomorrow', [])
            
            if not today_prices:
                return None
            
            # Combine and convert price data
            all_prices = today_prices + tomorrow_prices
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
            
            return await self._find_best_window_in_forecast(price_forecast, duration_minutes, search_length)
            
        except Exception as e:
            _LOGGER.error(f"Error getting potential optimal window: {e}")
            return None

    async def _find_optimal_window(self, device_name: str, duration_minutes: int) -> Optional[dict]:
        """Find optimal window for program execution using forecast."""
        try:
            device_config = self.devices[device_name]
            search_length = device_config.get('search_length', 8)
            
            # Get Tibber price forecast
            tibber_state = self.hass.states.get(self.tibber_sensor)
            if not tibber_state:
                return None
            
            # Get today/tomorrow prices
            today_prices = tibber_state.attributes.get('today', [])
            tomorrow_prices = tibber_state.attributes.get('tomorrow', [])
            
            if not today_prices:
                _LOGGER.warning("No price forecast available")
                return None
            
            # Combine and convert price data
            all_prices = today_prices + tomorrow_prices
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
            
            return await self._find_best_window_in_forecast(price_forecast, duration_minutes, search_length)
            
        except Exception as e:
            _LOGGER.error(f"Error finding optimal window: {e}")
            return None

    async def _find_best_window_in_forecast(self, price_forecast: list, duration_minutes: int, search_length: int) -> Optional[dict]:
        """Find best window in price forecast."""
        if not price_forecast:
            return None
        
        current_time = datetime.now()
        search_end = current_time + timedelta(hours=search_length)
        
        # Filter to search window (only future times)
        relevant_prices = [
            p for p in price_forecast 
            if current_time + timedelta(minutes=10) <= p['time'] <= search_end
        ]
        
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
                
                # Calculate estimated cost
                device_power = 2000  # Default watts
                energy_kwh = (device_power / 1000) * (duration_minutes / 60)
                estimated_cost = avg_price * energy_kwh
                
                best_window = {
                    'start_time': start_time,
                    'end_time': end_time,
                    'avg_price': avg_price,
                    'estimated_cost': estimated_cost,
                    'duration_minutes': duration_minutes
                }
        
        return best_window

    async def _schedule_automatic_start(self, device_name: str, optimal_window: dict):
        """Schedule automatic device start at optimal time."""
        start_time = optimal_window['start_time']
        delay_seconds = (start_time - datetime.now()).total_seconds()
        
        if delay_seconds <= 0:
            # Should start now
            await self._execute_scheduled_start(device_name, optimal_window)
            return
        
        # Cancel any existing scheduled task
        if device_name in self._scheduled_tasks:
            self._scheduled_tasks[device_name].cancel()
        
        # Schedule the start
        task = self.hass.loop.call_later(
            delay_seconds,
            lambda: asyncio.create_task(self._execute_scheduled_start(device_name, optimal_window))
        )
        self._scheduled_tasks[device_name] = task
        
        _LOGGER.info(f"Scheduled {device_name} to start in {delay_seconds/60:.0f} minutes at {start_time.strftime('%H:%M')}")

    async def _execute_scheduled_start(self, device_name: str, optimal_window: dict):
        """Execute scheduled program start."""
        device_config = self.devices[device_name]
        device_state = self.device_states[device_name]
        
        # Check if still scheduled (not manually overridden)
        if device_state.get('state') != 'scheduled':
            _LOGGER.info(f"Scheduled start cancelled for {device_name} - state changed")
            return
        
        # Turn on device
        entities = device_config.get(CONF_ENTITIES, [])
        await self._turn_on_entities(entities)
        
        # Update state
        device_state['state'] = 'scheduled_running'
        device_state['optimal_start'] = True
        device_state['actual_start_time'] = datetime.now()
        device_state['runs_today'] += 1
        
        # Unlock schedule after starting
        device_state['schedule_locked'] = False
        device_state['schedule_calculated_at'] = None
        
        # Schedule automatic stop
        duration_seconds = optimal_window['duration_minutes'] * 60
        self.hass.loop.call_later(
            duration_seconds,
            lambda: asyncio.create_task(self._execute_scheduled_stop(device_name))
        )
        
        _LOGGER.info(f"AUTOMATIC START: {device_name} started at {optimal_window.get('avg_price', 0):.3f} EUR/kWh")

    async def _execute_scheduled_stop(self, device_name: str):
        """Execute scheduled program stop."""
        device_config = self.devices[device_name]
        device_state = self.device_states[device_name]
        
        # Turn off device
        entities = device_config.get(CONF_ENTITIES, [])
        await self._turn_off_entities(entities)
        
        # Record completion
        await self._record_program_completion(device_name)
        
        # Update state
        device_state['state'] = 'idle'
        device_state['device_running'] = False
        device_state['optimal_start'] = False
        device_state['scheduled_start'] = None
        device_state['scheduled_end'] = None
        
        _LOGGER.info(f"AUTOMATIC STOP: {device_name} completed scheduled run")

    async def _record_program_completion(self, device_name: str):
        """Record program completion for learning/analytics."""
        device_state = self.device_states[device_name]
        
        if not device_state.get('program_id'):
            return
        
        completion_time = datetime.now()
        
        # Calculate actual values
        actual_duration = None
        if device_state.get('actual_start_time'):
            actual_duration = (completion_time - device_state['actual_start_time']).total_seconds() / 60
            device_state['total_runtime_today'] += actual_duration
        
        program_record = {
            'program_id': device_state.get('program_id'),
            'detection_time': device_state.get('programmed_time'),
            'scheduled_start': device_state.get('scheduled_start'),
            'actual_start': device_state.get('actual_start_time'),
            'completion_time': completion_time,
            'estimated_duration': device_state.get('estimated_duration'),
            'actual_duration': actual_duration,
            'estimated_cost': device_state.get('estimated_cost'),
            'mode': device_state.get('state'),
            'day_of_week': completion_time.weekday(),
            'time_of_day': completion_time.hour
        }
        
        # Store in program history
        if 'program_history' not in device_state:
            device_state['program_history'] = []
        
        device_state['program_history'].append(program_record)
        
        # Keep only last 50 records
        if len(device_state['program_history']) > 50:
            device_state['program_history'] = device_state['program_history'][-50:]
        
        await self.async_save_devices()
        _LOGGER.debug(f"Recorded program completion for {device_name}")

    async def _check_price_threshold(self, device_name: str, price_data: Dict):
        """Check price threshold and act accordingly (original Smart Delay logic)."""
        device_config = self.devices[device_name]
        device_state = self.device_states[device_name]
        
        if device_config.get('use_cost_rate_attribute', False):
            await self._check_cost_rate_threshold(device_name, price_data)
        else:
            current_price = price_data['current_price']
            price_threshold = device_config.get('price_threshold', 0.30)
            
            _LOGGER.info(f"Price check {device_name}: {current_price:.3f} vs {price_threshold:.3f} EUR/kWh")
            
            if current_price <= price_threshold:
                # Allow to run
                device_state['state'] = 'running'
                device_state['started_time'] = datetime.now()
                device_state['device_running'] = True
                device_state['runs_today'] += 1
                _LOGGER.info(f"ALLOWED: {device_name} runs at {current_price:.3f} EUR/kWh")
            else:
                # Cut off - price too high
                device_state['state'] = 'cut_off'
                device_state['waiting_for_cheap_price'] = True
                
                entities = device_config.get(CONF_ENTITIES, [])
                await self._turn_off_entities(entities)
                
                _LOGGER.warning(f"CUT OFF: {device_name} - price {current_price:.3f} > {price_threshold:.3f} EUR/kWh")

    async def _check_cost_rate_threshold(self, device_name: str, price_data: Dict):
        """Check cost rate threshold instead of price."""
        device_config = self.devices[device_name]
        device_state = self.device_states[device_name]
        
        current_rate = price_data.get('current_cost_rate', 'NORMAL')
        cutoff_rate = device_config.get('cost_rate_cutoff', 'HIGH')
        
        # Rate hierarchy: VERY_LOW=1, LOW=2, NORMAL=3, HIGH=4, VERY_HIGH=5
        rate_levels = {'VERY_LOW': 1, 'LOW': 2, 'NORMAL': 3, 'HIGH': 4, 'VERY_HIGH': 5}
        current_level = rate_levels.get(current_rate, 3)
        cutoff_level = rate_levels.get(cutoff_rate, 4)
        
        _LOGGER.info(f"Cost rate check {device_name}: {current_rate} vs {cutoff_rate}")
        
        if current_level < cutoff_level:
            # Allow to run
            device_state['state'] = 'running'
            device_state['started_time'] = datetime.now()
            device_state['device_running'] = True
            device_state['runs_today'] += 1
            _LOGGER.info(f"ALLOWED: {device_name} runs at cost rate {current_rate}")
        else:
            # Cut off - cost rate too high
            device_state['state'] = 'cut_off'
            device_state['waiting_for_cheap_price'] = True
            
            entities = device_config.get(CONF_ENTITIES, [])
            await self._turn_off_entities(entities)
            
            _LOGGER.warning(f"CUT OFF: {device_name} - cost rate {current_rate} >= {cutoff_rate}")

    async def _handle_completion(self, device_name: str):
        """Handle device completion detection."""
        device_state = self.device_states[device_name]
        
        if not device_state['device_running']:
            return
        
        # Check minimum runtime
        device_config = self.devices[device_name]
        min_runtime = device_config.get('min_runtime_minutes', 5)
        
        if device_state['started_time']:
            runtime = (datetime.now() - device_state['started_time']).total_seconds() / 60
            if runtime < min_runtime:
                _LOGGER.debug(f"Ignoring completion - runtime {runtime:.1f}min < {min_runtime}min")
                return
        
        # Record completion if this was a scheduled run
        if device_state.get('program_id'):
            await self._record_program_completion(device_name)
        
        # Mark as completed
        device_state['state'] = 'idle'
        device_state['device_running'] = False
        device_state['started_time'] = None
        device_state['waiting_for_cheap_price'] = False
        device_state['program_detected'] = False
        device_state['optimal_start'] = False
        
        _LOGGER.info(f"COMPLETED: {device_name} finished")

    # Active Scheduler specific methods
    async def _check_active_scheduler_devices(self):
        """Check and schedule devices in active_scheduler mode with stable scheduling."""
        current_time = datetime.now()
        
        for device_name, device_config in self.devices.items():
            if device_config.get('device_mode') == 'active_scheduler':
                await self._process_active_schedule_stable(device_name, device_config, current_time)

    async def _process_active_schedule_stable(self, device_name: str, device_config: dict, current_time: datetime):
        """Process active scheduling with stable schedule management."""
        device_state = self.device_states[device_name]
        
        # Skip if device is running or overridden
        if (device_state.get('device_running') or 
            device_state.get('manual_override_until')):
            return
        
        # Check if it's time to execute existing locked schedule
        if device_state.get('schedule_locked') and device_state.get('scheduled_start'):
            scheduled_start = device_state['scheduled_start']
            if scheduled_start <= current_time <= scheduled_start + timedelta(minutes=5):
                if device_state.get('state') == 'scheduled':
                    await self._execute_scheduled_start(device_name, {
                        'start_time': scheduled_start,
                        'end_time': device_state.get('scheduled_end'),
                        'duration_minutes': device_config.get('duration', 120)
                    })
                    return
        
        # Create new schedule if none exists or current schedule is expired
        if (not device_state.get('schedule_locked') or
            not device_state.get('scheduled_start') or
            device_state.get('scheduled_start') <= current_time):
            
            # Only recalculate every 30 minutes to avoid constant changes
            last_check = device_state.get('last_schedule_check')
            if last_check and (current_time - last_check).total_seconds() < 1800:  # 30 minutes
                return
            
            device_state['last_schedule_check'] = current_time
            await self._calculate_and_lock_schedule(device_name)

    async def _entity_state_changed(self, device_name: str, entity_id: str, event):
        """Handle entity state changes (fallback when no power sensor)."""
        device_config = self.devices[device_name]
        power_sensor = device_config.get('power_sensor', 'none')
        
        # Only use entity changes if no power sensor
        if power_sensor != 'none':
            return
            
        new_state = event.data.get('new_state')
        old_state = event.data.get('old_state')
        
        if not new_state or not old_state:
            return
        
        device_state = self.device_states[device_name]
        
        # Manual turn ON detected
        if old_state.state == STATE_OFF and new_state.state == STATE_ON:
            if not device_state['device_running'] and not device_state['optimal_start']:
                _LOGGER.info(f"Manual start detected via entity state: {device_name}")
                await self._handle_manual_start(device_name)

    async def _get_price_data(self) -> Optional[Dict]:
        """Get current price data from Tibber sensor."""
        try:
            state = self.hass.states.get(self.tibber_sensor)
            if not state:
                _LOGGER.error(f"Tibber sensor not found: {self.tibber_sensor}")
                return None
                
            price_data = {
                'current_price': float(state.state),
                'current_cost_rate': state.attributes.get('current_cost_rate', 'NORMAL'),
                'timestamp': datetime.now()
            }
            
            _LOGGER.debug(f"Price data: {price_data['current_price']:.3f} EUR/kWh, rate: {price_data['current_cost_rate']}")
            return price_data
            
        except (ValueError, TypeError) as e:
            _LOGGER.error(f"Error getting price data: {e}")
            return None

    async def update_schedules(self):
        """Update schedules - check for delayed devices, optimal windows, AND active scheduling."""
        price_data = await self._get_price_data()
        if not price_data:
            return

        _LOGGER.debug(f"Schedule update - price: {price_data['current_price']:.3f} EUR/kWh")

        # Check Smart Delay devices waiting for cheaper prices
        for device_name, device_state in self.device_states.items():
            if device_state.get('waiting_for_cheap_price'):
                await self._check_resume_conditions(device_name, price_data)

        # Check Smart Delay devices for automatic optimal window starts
        await self._check_smart_delay_auto_starts()

        # Check Active Scheduler devices for scheduling (limited frequency)
        await self._check_active_scheduler_devices()

    async def _check_smart_delay_auto_starts(self):
        """Check if any Smart Delay devices should automatically start now."""
        current_time = datetime.now()

        for device_name, device_config in self.devices.items():
            if not device_config.get('enabled', True):
                continue

            device_mode = device_config.get('device_mode', 'smart_delay')
            # Support smart_delay, price_protection, and hybrid modes for auto-starts
            if device_mode not in ['smart_delay', 'price_protection', 'hybrid']:
                continue

            device_state = self.device_states.get(device_name, {})

            # Skip if device is already running or automation is disabled
            if (device_state.get('device_running') or
                not device_state.get('scheduler_enabled', True)):
                continue

            # Check if we're in an optimal window
            await self._check_optimal_window_start(device_name, current_time)

    async def _check_optimal_window_start(self, device_name: str, current_time: datetime):
        """Check if device should start based on optimal window."""
        try:
            device_config = self.devices[device_name]
            device_state = self.device_states[device_name]

            # Get optimal windows for this device
            optimal_windows = await self._get_optimal_windows_for_device(device_name)
            if not optimal_windows:
                return

            # Check if we're at the start of an optimal window
            for window in optimal_windows:
                window_start = window['start_time']
                window_end = window['end_time']

                # Check if we should start now (within 5 minutes of window start)
                time_until_start = (window_start - current_time).total_seconds() / 60

                if -5 <= time_until_start <= 5 and current_time <= window_end:
                    _LOGGER.info(f"SMART DELAY AUTO START: {device_name} at optimal window {window_start.strftime('%H:%M')}")

                    # Start the device
                    entities = device_config.get('entities', [])
                    if entities:
                        await self._turn_on_entities(entities)

                        # Generate program ID for recording
                        program_id = f"{device_name}_{current_time.strftime('%Y%m%d_%H%M%S')}_auto"

                        # Update device state
                        device_state.update({
                            'device_running': True,
                            'started_time': current_time,
                            'actual_start_time': current_time,
                            'state': 'auto_optimal_start',
                            'scheduled_start': window_start,
                            'scheduled_end': window_end,
                            'optimal_start': True,
                            'program_id': program_id,
                            'programmed_time': current_time,
                            'estimated_duration': device_config.get('duration', 120),
                            'runs_today': device_state.get('runs_today', 0) + 1
                        })

                        _LOGGER.info(f"Auto-started {device_name} in optimal window (avg price: {window.get('avg_price', 0):.3f}€)")
                    break

        except Exception as e:
            _LOGGER.error(f"Error checking optimal window start for {device_name}: {e}")

    async def _check_resume_conditions(self, device_name: str, price_data: Dict):
        """Check if a delayed device can now resume."""
        device_config = self.devices[device_name]
        device_state = self.device_states[device_name]
        
        if device_config.get('use_cost_rate_attribute', False):
            # Check cost rate
            current_rate = price_data.get('current_cost_rate', 'NORMAL')
            resume_rate = device_config.get('cost_rate_resume', 'NORMAL')
            
            rate_levels = {'VERY_LOW': 1, 'LOW': 2, 'NORMAL': 3, 'HIGH': 4, 'VERY_HIGH': 5}
            current_level = rate_levels.get(current_rate, 3)
            resume_level = rate_levels.get(resume_rate, 3)
            
            if current_level <= resume_level:
                await self._resume_device(device_name, f"cost rate {current_rate}")
        else:
            # Check price
            current_price = price_data['current_price']
            resume_threshold = device_config.get('price_resume_threshold', 0.25)
            
            if current_price <= resume_threshold:
                await self._resume_device(device_name, f"price {current_price:.3f} EUR/kWh")

    async def _resume_device(self, device_name: str, reason: str):
        """Resume a delayed device."""
        device_config = self.devices[device_name]
        device_state = self.device_states[device_name]
        
        entities = device_config.get(CONF_ENTITIES, [])
        await self._turn_on_entities(entities)
        
        device_state['state'] = 'running'
        device_state['started_time'] = datetime.now()
        device_state['device_running'] = True
        device_state['waiting_for_cheap_price'] = False
        device_state['runs_today'] += 1
        
        _LOGGER.info(f"RESUMED: {device_name} at {reason}")

    async def _turn_on_entities(self, entities: List[str]):
        """Turn on entities."""
        for entity_id in entities:
            try:
                domain = entity_id.split('.')[0]
                await self.hass.services.async_call(domain, SERVICE_TURN_ON, {'entity_id': entity_id})
                _LOGGER.debug(f"Turned ON: {entity_id}")
            except Exception as e:
                _LOGGER.error(f"Error turning on {entity_id}: {e}")

    async def _turn_off_entities(self, entities: List[str]):
        """Turn off entities."""
        for entity_id in entities:
            try:
                domain = entity_id.split('.')[0]
                await self.hass.services.async_call(domain, SERVICE_TURN_OFF, {'entity_id': entity_id})
                _LOGGER.debug(f"Turned OFF: {entity_id}")
            except Exception as e:
                _LOGGER.error(f"Error turning off {entity_id}: {e}")

    # Service methods
    async def manual_override(self, device_name: str, duration_minutes: int = 60):
        """Temporarily disable automation."""
        device_state = self.device_states[device_name]
        device_state['manual_override_until'] = datetime.now() + timedelta(minutes=duration_minutes)
        
        # Cancel any scheduled tasks
        if device_name in self._scheduled_tasks:
            self._scheduled_tasks[device_name].cancel()
            del self._scheduled_tasks[device_name]
        
        _LOGGER.info(f"Manual override: {device_name} for {duration_minutes} minutes")

    async def force_start_now(self, device_name: str, duration_override: Optional[int] = None):
        """Force start device ignoring all conditions."""
        device_config = self.devices[device_name]
        device_state = self.device_states[device_name]
        
        entities = device_config.get(CONF_ENTITIES, [])
        duration = duration_override or device_config.get('duration', 120)
        
        # Cancel any scheduled tasks
        if device_name in self._scheduled_tasks:
            self._scheduled_tasks[device_name].cancel()
            del self._scheduled_tasks[device_name]
        
        # Unlock schedule
        device_state['schedule_locked'] = False
        device_state['scheduled_start'] = None
        device_state['scheduled_end'] = None
        
        await self._turn_on_entities(entities)
        
        device_state['manual_override_until'] = datetime.now() + timedelta(minutes=duration)
        device_state['device_running'] = True
        device_state['started_time'] = datetime.now()
        device_state['state'] = 'manual_override'
        device_state['runs_today'] += 1
        
        # Schedule turn off
        self.hass.loop.call_later(
            duration * 60,
            lambda: asyncio.create_task(self._turn_off_entities(entities))
        )
        
        _LOGGER.warning(f"FORCE START: {device_name} for {duration} minutes")

    async def cancel_scheduled_program(self, device_name: str):
        """Cancel scheduled program."""
        device_state = self.device_states[device_name]
        
        # Cancel scheduled task
        if device_name in self._scheduled_tasks:
            self._scheduled_tasks[device_name].cancel()
            del self._scheduled_tasks[device_name]
        
        if device_state.get('state') == 'scheduled':
            device_state['state'] = 'idle'
            device_state['scheduled_start'] = None
            device_state['scheduled_end'] = None
            device_state['schedule_locked'] = False
            device_state['program_detected'] = False
            
            _LOGGER.info(f"CANCELLED: Scheduled program for {device_name}")

    async def reset_schedule(self, device_name: str):
        """Reset/recalculate schedule for a device."""
        device_state = self.device_states[device_name]
        
        # Cancel existing scheduled task
        if device_name in self._scheduled_tasks:
            self._scheduled_tasks[device_name].cancel()
            del self._scheduled_tasks[device_name]
        
        # Unlock and reset schedule
        device_state['schedule_locked'] = False
        device_state['scheduled_start'] = None
        device_state['scheduled_end'] = None
        device_state['state'] = 'idle'
        device_state['last_schedule_check'] = None
        
        _LOGGER.info(f"RESET SCHEDULE: {device_name}")
        
        # Immediately recalculate if in active scheduler mode
        device_config = self.devices[device_name]
        if device_config.get('device_mode') == 'active_scheduler':
            await self._calculate_and_lock_schedule(device_name)

    async def set_device_mode(self, device_name: str, mode: str):
        """Set device operation mode."""
        if device_name in self.devices:
            self.devices[device_name]['device_mode'] = mode
            device_state = self.device_states[device_name]
            
            # Cancel any scheduled tasks when changing modes
            if device_name in self._scheduled_tasks:
                self._scheduled_tasks[device_name].cancel()
                del self._scheduled_tasks[device_name]
            
            # Reset state when changing modes
            device_state['device_running'] = False
            device_state['waiting_for_cheap_price'] = False
            device_state['state'] = 'idle'
            device_state['scheduled_start'] = None
            device_state['scheduled_end'] = None
            device_state['schedule_locked'] = False
            device_state['program_detected'] = False
            device_state['last_schedule_check'] = None
            
            await self.async_save_devices()
            _LOGGER.info(f"Device {device_name} mode changed to: {mode}")

    def get_stable_schedule_info(self, device_name: str) -> dict:
        """Get stable schedule information for sensors."""
        device_state = self.device_states.get(device_name, {})
        device_config = self.devices.get(device_name, {})
        
        schedule_info = {
            'scheduled_start': device_state.get('scheduled_start'),
            'scheduled_end': device_state.get('scheduled_end'),
            'schedule_locked': device_state.get('schedule_locked', False),
            'state': device_state.get('state', 'idle'),
            'device_running': device_state.get('device_running', False),
            'estimated_cost': device_state.get('estimated_cost'),
            'estimated_duration': device_state.get('estimated_duration', device_config.get('duration', 120))
        }
        
        return schedule_info

    def get_program_analytics(self, device_name: str) -> dict:
        """Get program analytics for a device."""
        device_state = self.device_states.get(device_name, {})
        history = device_state.get('program_history', [])
        
        if not history:
            return {'error': 'No program history available'}
        
        # Calculate statistics
        completed_programs = [r for r in history if r.get('actual_duration')]
        
        analytics = {
            'total_programs': len(history),
            'completed_programs': len(completed_programs),
            'avg_duration_minutes': 0,
            'avg_cost_euros': 0,
            'total_energy_kwh': 0,
            'most_common_start_hour': 0,
            'weekend_vs_weekday': {'weekend': 0, 'weekday': 0},
            'accuracy_duration': 0,
            'recent_programs': history[-5:] if len(history) >= 5 else history
        }
        
        if completed_programs:
            durations = [r['actual_duration'] for r in completed_programs]
            costs = [r['actual_cost'] for r in completed_programs if r.get('actual_cost')]
            
            analytics['avg_duration_minutes'] = sum(durations) / len(durations)
            
            if costs:
                analytics['avg_cost_euros'] = sum(costs) / len(costs)
            
            # Start time analysis
            start_hours = [r.get('time_of_day', 12) for r in completed_programs]
            if start_hours:
                analytics['most_common_start_hour'] = max(set(start_hours), key=start_hours.count)
            
            # Weekend/weekday distribution
            for r in completed_programs:
                if r.get('day_of_week', 0) >= 5:
                    analytics['weekend_vs_weekday']['weekend'] += 1
                else:
                    analytics['weekend_vs_weekday']['weekday'] += 1
            
            # Duration accuracy
            duration_errors = []
            for r in completed_programs:
                if r.get('estimated_duration') and r.get('actual_duration'):
                    error = abs(r['estimated_duration'] - r['actual_duration']) / r['actual_duration']
                    duration_errors.append(error)
            
            if duration_errors:
                analytics['accuracy_duration'] = 1 - (sum(duration_errors) / len(duration_errors))
        
        return analytics

    async def remove_device(self, device_name):
        """Remove a device."""
        # Cancel any scheduled tasks
        if device_name in self._scheduled_tasks:
            self._scheduled_tasks[device_name].cancel()
            del self._scheduled_tasks[device_name]
        
        if device_name in self.devices:
            del self.devices[device_name]
        if device_name in self.device_states:
            del self.device_states[device_name]
        await self.async_save_devices()
        _LOGGER.info(f"Removed device: {device_name}")

    async def async_save_devices(self):
        """Save devices to storage."""
        try:
            await self._store.async_save({"devices": self.devices})
        except Exception as e:
            _LOGGER.error(f"Error saving devices: {e}")

    async def async_unload(self):
        """Unload coordinator."""
        # Cancel all scheduled tasks
        for task in self._scheduled_tasks.values():
            task.cancel()
        self._scheduled_tasks.clear()
        
        if self._unsub_update:
            self._unsub_update()
        if self._unsub_state_change:
            self._unsub_state_change()
        for unsub in self._unsub_entity_changes:
            unsub()

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tibber Smart Scheduler."""
    coordinator = TibberSmartCoordinator(hass, entry)
    await coordinator.async_load_devices()
    
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    
    # Set up periodic price checks every 5 minutes
    async def update_schedules(now):
        await coordinator.update_schedules()
    
    coordinator._unsub_update = async_track_time_interval(
        hass, update_schedules, timedelta(minutes=5)
    )
    
    # Track price changes for immediate updates
    async def price_changed(event):
        _LOGGER.debug("Price sensor changed - checking delayed devices and schedules")
        await coordinator.update_schedules()
    
    coordinator._unsub_state_change = async_track_state_change_event(
        hass, [coordinator.tibber_sensor], price_changed
    )
    
    # Register services
    async def handle_manual_start(call: ServiceCall):
        entity_id = call.data.get("entity_id")
        duration = call.data.get("duration")
        device_name = entity_id.split(".")[-1].replace("tibber_scheduler_", "")
        if device_name in coordinator.devices:
            await coordinator.force_start_now(device_name, duration)
    
    async def handle_force_start(call: ServiceCall):
        entity_id = call.data.get("entity_id")
        duration = call.data.get("duration")
        device_name = entity_id.split(".")[-1].replace("tibber_scheduler_", "")
        if device_name in coordinator.devices:
            await coordinator.force_start_now(device_name, duration)
    
    async def handle_manual_stop(call: ServiceCall):
        entity_id = call.data.get("entity_id")
        device_name = entity_id.split(".")[-1].replace("tibber_scheduler_", "")
        if device_name in coordinator.devices:
            entities = coordinator.devices[device_name].get(CONF_ENTITIES, [])
            await coordinator._turn_off_entities(entities)
    
    async def handle_manual_override(call: ServiceCall):
        entity_id = call.data.get("entity_id")
        duration = call.data.get("duration", 60)
        device_name = entity_id.split(".")[-1].replace("tibber_scheduler_", "")
        if device_name in coordinator.devices:
            await coordinator.manual_override(device_name, duration)
    
    async def handle_update_schedules(call: ServiceCall):
        await coordinator.update_schedules()
    
    async def handle_set_device_mode(call: ServiceCall):
        entity_id = call.data.get("entity_id")
        mode = call.data.get("mode", "smart_delay")
        device_name = entity_id.split(".")[-1].replace("tibber_scheduler_", "")
        if device_name in coordinator.devices:
            await coordinator.set_device_mode(device_name, mode)
    
    async def handle_cancel_program(call: ServiceCall):
        entity_id = call.data.get("entity_id")
        device_name = entity_id.split(".")[-1].replace("tibber_scheduler_", "")
        if device_name in coordinator.devices:
            await coordinator.cancel_scheduled_program(device_name)
    
    async def handle_reset_schedule(call: ServiceCall):
        entity_id = call.data.get("entity_id")
        device_name = entity_id.split(".")[-1].replace("tibber_scheduler_", "")
        if device_name in coordinator.devices:
            await coordinator.reset_schedule(device_name)
    
    async def handle_get_analytics(call: ServiceCall):
        entity_id = call.data.get("entity_id")
        device_name = entity_id.split(".")[-1].replace("tibber_scheduler_", "")
        if device_name in coordinator.devices:
            analytics = coordinator.get_program_analytics(device_name)
            _LOGGER.info(f"Analytics for {device_name}: {analytics}")
            return analytics
    
    # Register services
    hass.services.async_register(DOMAIN, "manual_start", handle_manual_start)
    hass.services.async_register(DOMAIN, "force_start_now", handle_force_start)
    hass.services.async_register(DOMAIN, "manual_stop", handle_manual_stop)
    hass.services.async_register(DOMAIN, "manual_override", handle_manual_override)
    hass.services.async_register(DOMAIN, "update_schedules", handle_update_schedules)
    hass.services.async_register(DOMAIN, "set_device_mode", handle_set_device_mode)
    hass.services.async_register(DOMAIN, "cancel_scheduled_program", handle_cancel_program)
    hass.services.async_register(DOMAIN, "reset_schedule", handle_reset_schedule)
    hass.services.async_register(DOMAIN, "get_program_analytics", handle_get_analytics)
    
    # Setup switch and sensor platforms
    await hass.config_entries.async_forward_entry_setups(entry, ["switch", "sensor"])
    
    _LOGGER.info(f"Tibber Smart Scheduler loaded - sensor: {coordinator.tibber_sensor}")
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload entry."""
    coordinator = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator:
        await coordinator.async_unload()
    
    # Remove services
    hass.services.async_remove(DOMAIN, "manual_start")
    hass.services.async_remove(DOMAIN, "force_start_now")
    hass.services.async_remove(DOMAIN, "manual_stop")
    hass.services.async_remove(DOMAIN, "manual_override")
    hass.services.async_remove(DOMAIN, "update_schedules")
    hass.services.async_remove(DOMAIN, "set_device_mode")
    hass.services.async_remove(DOMAIN, "cancel_scheduled_program")
    hass.services.async_remove(DOMAIN, "reset_schedule")
    hass.services.async_remove(DOMAIN, "get_program_analytics")
    
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["switch", "sensor"]) 

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    
    return unload_ok
"""Complete Window-Fitting Coordinator with Smart Delay Logic."""

import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_ENTITIES, SERVICE_TURN_ON, SERVICE_TURN_OFF, STATE_ON, STATE_OFF

from .const import DOMAIN, CONF_TIBBER_SENSOR

_LOGGER = logging.getLogger(__name__)

class TibberSmartCoordinator:
    """Enhanced coordinator with window-fitting logic for Smart Delay."""
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry):
        self.hass = hass
        self.entry = entry
        self.tibber_sensor = entry.data[CONF_TIBBER_SENSOR]
        self.devices = {}
        self.device_states = {}
        self._store = Store(hass, 1, f"tibber_smart_{entry.entry_id}")
        self._unsub_update = None
        self._unsub_state_change = None
        self._unsub_entity_changes = []
        self._async_add_entities = None
        self._scheduled_tasks = {}
        
        # Window calculation cache
        self._price_forecast_cache = None
        self._forecast_cache_time = None
        self._optimal_windows_cache = {}
        
        _LOGGER.info(f"Coordinator initialized with Tibber sensor: {self.tibber_sensor}")
        
    async def async_load_devices(self):
        """Load devices from storage."""
        try:
            stored_data = await self._store.async_load()
            if stored_data:
                self.devices = stored_data.get("devices", {})
                for device_name in self.devices:
                    self._init_device_state(device_name)
            _LOGGER.info(f"Loaded {len(self.devices)} devices from storage")
        except Exception as e:
            _LOGGER.error(f"Error loading devices: {e}")
            self.devices = {}
        
    def _init_device_state(self, device_name: str):
        """Initialize device state tracking."""
        self.device_states[device_name] = {
            'state': 'idle',
            'device_running': False,
            'programmed_time': None,
            'started_time': None,
            'last_power_reading': 0,
            'program_detected': False,
            'waiting_for_cheap_price': False,
            'optimal_start': False,
            'manual_override_until': None,
            'runs_today': 0,
            'total_runtime_today': 0,
            'scheduler_enabled': True,
            
            # Enhanced scheduling fields
            'scheduled_start': None,
            'scheduled_end': None,
            'schedule_locked': False,
            'optimal_windows_calculated': None,
            'next_optimal_window': None,
            'estimated_cost': None,
            'estimated_duration': None,
            'program_id': None,
            'program_history': [],
        }
        _LOGGER.debug(f"Initialized state for device: {device_name}")
        
    async def add_device(self, device_config):
        """Add a device with monitoring setup."""
        device_name = device_config[CONF_NAME]
        self.devices[device_name] = device_config
        self._init_device_state(device_name)
        
        await self._setup_monitoring(device_name)
        
        if self._async_add_entities:
            from .switch import UnifiedTibberSwitch
            new_entity = UnifiedTibberSwitch(self, device_name)
            self._async_add_entities([new_entity])
        
        await self.async_save_devices()
        
        power_sensor = device_config.get('power_sensor', 'none')
        device_mode = device_config.get('device_mode', 'smart_delay')
        _LOGGER.info(f"Added device {device_name} in {device_mode} mode with power sensor: {power_sensor}")
            
    async def _setup_monitoring(self, device_name: str):
        """Set up power sensor and entity monitoring."""
        device_config = self.devices[device_name]
        
        # Monitor controlled entities
        entities = device_config.get(CONF_ENTITIES, [])
        for entity_id in entities:
            def make_entity_handler(dev_name, ent_id):
                async def entity_changed(event):
                    await self._entity_state_changed(dev_name, ent_id, event)
                return entity_changed
            
            self._unsub_entity_changes.append(
                async_track_state_change_event(
                    self.hass, [entity_id], make_entity_handler(device_name, entity_id)
                )
            )
        
        # Monitor power sensor
        power_sensor = device_config.get('power_sensor')
        if power_sensor and power_sensor != "none":
            def make_power_handler(dev_name):
                async def power_changed(event):
                    await self._power_sensor_changed(dev_name, event)
                return power_changed
            
            self._unsub_entity_changes.append(
                async_track_state_change_event(
                    self.hass, [power_sensor], make_power_handler(device_name)
                )
            )

    async def _power_sensor_changed(self, device_name: str, event):
        """Handle power sensor changes with window-fitting logic."""
        new_state = event.data.get('new_state')
        old_state = event.data.get('old_state')
        
        if not new_state or not old_state:
            return
            
        try:
            old_power = float(old_state.state) if old_state.state not in ['unavailable', 'unknown'] else 0
            new_power = float(new_state.state) if new_state.state not in ['unavailable', 'unknown'] else 0
            min_power = self.devices[device_name].get('min_power_detection', 15)
            
            device_state = self.device_states[device_name]
            device_state['last_power_reading'] = new_power
            
            # Detect manual start (power spike above threshold)
            if old_power < min_power and new_power >= min_power:
                await self._handle_program_detection(device_name)
            
            # Detect completion (power drop below threshold)
            elif old_power >= min_power and new_power < min_power:
                await self._handle_completion(device_name)
                
        except (ValueError, TypeError) as e:
            _LOGGER.warning(f"Error parsing power values for {device_name}: {e}")

    async def _handle_program_detection(self, device_name: str):
        """Enhanced program detection with window-fitting logic."""
        device_config = self.devices[device_name]
        device_state = self.device_states[device_name]
        
        # Skip if already being handled or scheduled start
        if device_state['device_running'] or device_state['optimal_start']:
            return
        
        # Skip if this is a scheduled start confirmation
        if device_state.get('state') == 'scheduled_running':
            _LOGGER.info(f"SCHEDULED START CONFIRMED: {device_name}")
            device_state['device_running'] = True
            device_state['started_time'] = datetime.now()
            return
        
        _LOGGER.warning(f"PROGRAM DETECTED: {device_name}")
        
        # Record program detection
        current_time = datetime.now()
        program_id = f"{device_name}_{current_time.strftime('%Y%m%d_%H%M%S')}"
        
        device_state.update({
            'program_detected': True,
            'programmed_time': current_time,
            'program_id': program_id,
            'estimated_duration': device_config.get('duration', 120)
        })
        
        # Apply window-fitting logic based on device mode
        device_mode = device_config.get('device_mode', 'smart_delay')
        
        if device_mode == 'active_scheduler':
            # Active scheduler: always cut off and reschedule optimally
            await self._cutoff_and_reschedule_optimal(device_name)
        elif device_mode == 'smart_delay':
            # Smart delay: apply window-fitting logic
            await self._apply_window_fitting_logic(device_name)
        else:
            # Fallback: original price threshold check
            price_data = await self._get_price_data()
            if price_data:
                await self._check_price_threshold(device_name, price_data)

    async def _apply_window_fitting_logic(self, device_name: str):
        """Apply window-fitting logic for Smart Delay mode."""
        device_config = self.devices[device_name]
        device_state = self.device_states[device_name]
        
        current_time = datetime.now()
        duration_minutes = device_config.get('duration', 120)
        
        _LOGGER.info(f"Applying window-fitting logic for {device_name} (duration: {duration_minutes}min)")
        
        # Get optimal windows for today
        optimal_windows = await self._get_optimal_windows_for_device(device_name)
        
        if not optimal_windows:
            _LOGGER.info(f"No optimal windows found for {device_name} - checking price threshold")
            price_data = await self._get_price_data()
            if price_data:
                await self._check_price_threshold(device_name, price_data)
            return
        
        # Check if currently in an optimal window
        current_window = self._find_current_window(optimal_windows, current_time)
        if current_window:
            window_remaining = (current_window['end_time'] - current_time).total_seconds() / 60
            
            if window_remaining >= duration_minutes:
                # Perfect: program fits in current optimal window
                device_state['state'] = 'running'
                device_state['device_running'] = True
                device_state['started_time'] = current_time
                device_state['runs_today'] += 1
                _LOGGER.info(f"ALLOWED IN OPTIMAL WINDOW: {device_name} (fits in current window)")
                return
            else:
                _LOGGER.info(f"Current window too small: {window_remaining:.0f}min < {duration_minutes}min")
        
        # Find next suitable window
        suitable_window = self._find_suitable_window(optimal_windows, duration_minutes, current_time)
        
        if suitable_window:
            savings_potential = await self._calculate_savings_potential(device_name, current_time, suitable_window)
            min_savings = device_config.get('min_savings_euros', 0.05)
            
            if savings_potential >= min_savings:
                # Cut off and reschedule for optimal window
                entities = device_config.get(CONF_ENTITIES, [])
                await self._turn_off_entities(entities)
                
                await self._schedule_for_window(device_name, suitable_window)
                
                _LOGGER.info(f"CUT OFF AND RESCHEDULED: {device_name} for {suitable_window['start_time'].strftime('%H:%M')} "
                           f"(saving {savings_potential:.3f}€)")
                return
            else:
                _LOGGER.info(f"Savings too small ({savings_potential:.3f}€ < {min_savings:.3f}€) - allowing now")
        
        # No suitable window or insufficient savings - allow to run now
        device_state['state'] = 'running'
        device_state['device_running'] = True
        device_state['started_time'] = current_time
        device_state['runs_today'] += 1
        _LOGGER.info(f"ALLOWED NOW: {device_name} (no better alternative)")

    async def _get_optimal_windows_for_device(self, device_name: str) -> List[Dict]:
        """Get optimal windows for a specific device with caching."""
        device_config = self.devices[device_name]
        
        # Check cache
        cache_key = f"{device_name}_{device_config.get('duration', 120)}"
        if (self._optimal_windows_cache.get(cache_key) and 
            self._forecast_cache_time and
            (datetime.now() - self._forecast_cache_time).total_seconds() < 3600):
            return self._optimal_windows_cache[cache_key]
        
        # Get fresh forecast
        price_forecast = await self._get_price_forecast()
        if not price_forecast:
            return []
        
        # Calculate optimal windows
        optimal_windows = self._calculate_optimal_windows(
            price_forecast, 
            device_config.get('duration', 120),
            device_config.get('price_percentile_threshold', 0.3)  # Bottom 30% of prices
        )
        
        # Cache result
        self._optimal_windows_cache[cache_key] = optimal_windows
        _LOGGER.debug(f"Calculated {len(optimal_windows)} optimal windows for {device_name}")
        
        return optimal_windows

    def _calculate_optimal_windows(self, price_forecast: List[Dict], duration_minutes: int, percentile_threshold: float) -> List[Dict]:
        """Calculate optimal windows based on price percentiles."""
        if not price_forecast:
            return []

        # Filter to current time onwards (include today + tomorrow)
        current_time = datetime.now()

        # Include all future prices from current time to end of tomorrow
        future_prices = [
            p for p in price_forecast
            if p['time'] >= current_time
        ]

        if not future_prices:
            return []

        # Calculate price threshold (bottom percentile) from all available future prices
        all_prices = [p['price'] for p in future_prices]
        all_prices.sort()
        threshold_index = int(len(all_prices) * percentile_threshold)
        price_threshold = all_prices[threshold_index]
        
        # Find consecutive low-price periods
        optimal_windows = []
        current_window = None
        
        for price_point in future_prices:
            if price_point['price'] <= price_threshold:
                if current_window is None:
                    # Start new window
                    current_window = {
                        'start_time': price_point['time'],
                        'end_time': price_point['time'] + timedelta(hours=1),
                        'avg_price': price_point['price'],
                        'price_points': [price_point]
                    }
                else:
                    # Extend current window
                    current_window['end_time'] = price_point['time'] + timedelta(hours=1)
                    current_window['price_points'].append(price_point)
                    # Recalculate average
                    current_window['avg_price'] = sum(p['price'] for p in current_window['price_points']) / len(current_window['price_points'])
            else:
                if current_window:
                    # End current window if it's long enough
                    window_duration = (current_window['end_time'] - current_window['start_time']).total_seconds() / 60
                    if window_duration >= duration_minutes:
                        optimal_windows.append(current_window)
                    current_window = None
        
        # Don't forget the last window
        if current_window:
            window_duration = (current_window['end_time'] - current_window['start_time']).total_seconds() / 60
            if window_duration >= duration_minutes:
                optimal_windows.append(current_window)
            else:
                # Add shorter windows for potential split runs
                optimal_windows.append(current_window)

        # Handle split runs: if no single window is large enough, collect smaller windows
        if not any(self._get_window_duration(w) >= duration_minutes for w in optimal_windows):
            # Add all cheap periods, even if shorter than full duration
            split_windows = []
            current_window = None

            for price_point in future_prices:
                if price_point['price'] <= price_threshold:
                    if current_window is None:
                        current_window = {
                            'start_time': price_point['time'],
                            'end_time': price_point['time'] + timedelta(hours=1),
                            'avg_price': price_point['price'],
                            'price_points': [price_point],
                            'split_run': True
                        }
                    else:
                        current_window['end_time'] = price_point['time'] + timedelta(hours=1)
                        current_window['price_points'].append(price_point)
                        current_window['avg_price'] = sum(p['price'] for p in current_window['price_points']) / len(current_window['price_points'])
                else:
                    if current_window:
                        # Add window regardless of duration for split runs
                        current_window['split_run'] = True
                        split_windows.append(current_window)
                        current_window = None

            # Add the last window for split runs
            if current_window:
                current_window['split_run'] = True
                split_windows.append(current_window)

            # If we found split windows, prefer them over empty results
            if split_windows and not optimal_windows:
                optimal_windows = split_windows

        return optimal_windows

    def _get_window_duration(self, window: Dict) -> float:
        """Get window duration in minutes."""
        return (window['end_time'] - window['start_time']).total_seconds() / 60

    def _find_current_window(self, optimal_windows: List[Dict], current_time: datetime) -> Optional[Dict]:
        """Find if current time is within an optimal window."""
        for window in optimal_windows:
            if window['start_time'] <= current_time <= window['end_time']:
                return window
        return None

    def _find_suitable_window(self, optimal_windows: List[Dict], duration_minutes: int, current_time: datetime) -> Optional[Dict]:
        """Find next suitable window that can fit the program duration or earliest split run."""
        future_windows = [w for w in optimal_windows if w['start_time'] > current_time]

        if not future_windows:
            return None

        # First, try to find a window that can fit the full duration
        for window in future_windows:
            window_duration = (window['end_time'] - window['start_time']).total_seconds() / 60
            if window_duration >= duration_minutes:
                return window

        # If no single window fits, return the earliest window for split runs
        # Sort by start time and return the earliest
        future_windows.sort(key=lambda w: w['start_time'])
        earliest_window = future_windows[0]

        # Mark it as the start of a split run sequence
        earliest_window['is_split_start'] = True
        return earliest_window

    async def _calculate_savings_potential(self, device_name: str, current_time: datetime, target_window: Dict) -> float:
        """Calculate potential cost savings by moving to target window."""
        device_config = self.devices[device_name]
        
        # Get current price
        price_data = await self._get_price_data()
        if not price_data:
            return 0.0
        
        current_price = price_data['current_price']
        target_price = target_window['avg_price']
        
        # Calculate savings
        duration_hours = device_config.get('duration', 120) / 60
        device_power_kw = device_config.get('device_power_consumption', 2000) / 1000
        energy_kwh = device_power_kw * duration_hours
        
        savings = (current_price - target_price) * energy_kwh
        return max(0, savings)

    async def _schedule_for_window(self, device_name: str, window: Dict):
        """Schedule device to start at optimal window."""
        device_state = self.device_states[device_name]
        device_config = self.devices[device_name]
        
        # Update state
        device_state['state'] = 'scheduled'
        device_state['scheduled_start'] = window['start_time']
        device_state['scheduled_end'] = window['start_time'] + timedelta(minutes=device_config.get('duration', 120))
        device_state['schedule_locked'] = True
        device_state['estimated_cost'] = window['avg_price'] * (device_config.get('device_power_consumption', 2000) / 1000) * (device_config.get('duration', 120) / 60)
        
        # Schedule automatic start
        delay_seconds = (window['start_time'] - datetime.now()).total_seconds()
        
        if delay_seconds > 0:
            # Cancel any existing task
            if device_name in self._scheduled_tasks:
                self._scheduled_tasks[device_name].cancel()
            
            task = self.hass.loop.call_later(
                delay_seconds,
                lambda: asyncio.create_task(self._execute_scheduled_start(device_name, {
                    'start_time': window['start_time'],
                    'end_time': device_state['scheduled_end'],
                    'duration_minutes': device_config.get('duration', 120)
                }))
            )
            self._scheduled_tasks[device_name] = task
            
            _LOGGER.info(f"Scheduled {device_name} to start in {delay_seconds/60:.0f} minutes")

    async def _cutoff_and_reschedule_optimal(self, device_name: str):
        """Cut off device and reschedule for absolute optimal time (Active Scheduler)."""
        device_config = self.devices[device_name]
        device_state = self.device_states[device_name]
        
        # Turn off device immediately
        entities = device_config.get(CONF_ENTITIES, [])
        await self._turn_off_entities(entities)
        
        # Find single best window
        optimal_window = await self._find_single_optimal_window(device_name)
        if optimal_window:
            await self._schedule_for_window(device_name, optimal_window)
        else:
            # No optimal window - allow to run now
            device_state['state'] = 'running'
            device_state['device_running'] = True
            device_state['started_time'] = datetime.now()
            await self._turn_on_entities(entities)

    async def _find_single_optimal_window(self, device_name: str) -> Optional[Dict]:
        """Find single best optimal window for device."""
        device_config = self.devices[device_name]
        duration_minutes = device_config.get('duration', 120)
        search_length = device_config.get('search_length', 8)
        
        price_forecast = await self._get_price_forecast()
        if not price_forecast:
            return None
        
        current_time = datetime.now()
        search_end = current_time + timedelta(hours=search_length)
        
        # Filter to search window
        relevant_prices = [
            p for p in price_forecast 
            if current_time + timedelta(minutes=10) <= p['time'] <= search_end
        ]
        
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
                
                best_window = {
                    'start_time': start_time,
                    'end_time': start_time + timedelta(minutes=duration_minutes),
                    'avg_price': avg_price,
                    'price_points': window_prices
                }
        
        return best_window

    async def _get_price_forecast(self) -> Optional[List[Dict]]:
        """Get price forecast with caching."""
        current_time = datetime.now()
        
        # Check cache
        if (self._price_forecast_cache and 
            self._forecast_cache_time and
            (current_time - self._forecast_cache_time).total_seconds() < 1800):  # 30 min cache
            return self._price_forecast_cache
        
        # Get fresh forecast
        try:
            tibber_state = self.hass.states.get(self.tibber_sensor)
            if not tibber_state:
                return None
            
            today_prices = tibber_state.attributes.get('today', [])
            tomorrow_prices = tibber_state.attributes.get('tomorrow', [])
            
            if not today_prices:
                return None
            
            # Combine and convert
            all_prices = today_prices + tomorrow_prices
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
            
            # Cache result
            self._price_forecast_cache = price_forecast
            self._forecast_cache_time = current_time
            
            _LOGGER.debug(f"Cached price forecast with {len(price_forecast)} data points")
            return price_forecast
            
        except Exception as e:
            _LOGGER.error(f"Error getting price forecast: {e}")
            return None

    # Sensor interface methods
    def get_stable_optimal_window(self, device_name: str) -> Optional[Dict]:
        """Get stable optimal window for sensors - uses cached data."""
        device_state = self.device_states.get(device_name, {})
        
        # Return locked schedule if available
        if (device_state.get('schedule_locked') and 
            device_state.get('scheduled_start') and
            device_state.get('scheduled_start') > datetime.now()):
            return {
                'start_time': device_state['scheduled_start'],
                'end_time': device_state.get('scheduled_end'),
                'avg_price': device_state.get('estimated_cost', 0) / (self.devices[device_name].get('device_power_consumption', 2000) / 1000) / (self.devices[device_name].get('duration', 120) / 60),
                'locked': True
            }

        cache_key = f"{device_name}_{self.devices[device_name].get('duration', 120)}" 
        # Return cached optimal windows calculation
        optimal_windows = self._optimal_windows_cache.get(f"{device_name}_{self.devices[device_name].get('duration', 120)}")
        if optimal_windows:
            future_windows = [w for w in optimal_windows if w['start_time'] > datetime.now()]
            if future_windows:
                return {
                    'start_time': future_windows[0]['start_time'],
                    'end_time': future_windows[0]['end_time'],
                    'avg_price': future_windows[0]['avg_price'],
                    'locked': False
                }
        
        return None

    async def _execute_scheduled_start(self, device_name: str, window_data: dict):
        """Execute scheduled program start."""
        device_config = self.devices[device_name]
        device_state = self.device_states[device_name]
        
        if device_state.get('state') != 'scheduled':
            return
        
        # Turn on device
        entities = device_config.get(CONF_ENTITIES, [])
        await self._turn_on_entities(entities)
        
        # Update state
        device_state['state'] = 'scheduled_running'
        device_state['optimal_start'] = True
        device_state['actual_start_time'] = datetime.now()
        device_state['runs_today'] += 1
        device_state['schedule_locked'] = False
        
        # Schedule stop
        duration_seconds = window_data['duration_minutes'] * 60
        self.hass.loop.call_later(
            duration_seconds,
            lambda: asyncio.create_task(self._execute_scheduled_stop(device_name))
        )
        
        _LOGGER.info(f"WINDOW START: {device_name} started in optimal window")

    async def _execute_scheduled_stop(self, device_name: str):
        """Execute scheduled stop."""
        device_config = self.devices[device_name]
        device_state = self.device_states[device_name]
        
        entities = device_config.get(CONF_ENTITIES, [])
        await self._turn_off_entities(entities)
        
        await self._record_program_completion(device_name)
        
        device_state['state'] = 'idle'
        device_state['device_running'] = False
        device_state['optimal_start'] = False
        device_state['scheduled_start'] = None
        device_state['scheduled_end'] = None
        
        _LOGGER.info(f"WINDOW STOP: {device_name} completed optimal window run")

    async def _record_program_completion(self, device_name: str):
        """Record program completion."""
        device_state = self.device_states[device_name]
        
        if not device_state.get('program_id'):
            return
        
        completion_time = datetime.now()
        actual_duration = None
        
        if device_state.get('actual_start_time'):
            actual_duration = (completion_time - device_state['actual_start_time']).total_seconds() / 60
            device_state['total_runtime_today'] += actual_duration
        
        program_record = {
            'program_id': device_state.get('program_id'),
            'detection_time': device_state.get('programmed_time'),
            'scheduled_start': device_state.get('scheduled_start'),
            'actual_start': device_state.get('actual_start_time'),
            'completion_time': completion_time,
            'estimated_duration': device_state.get('estimated_duration'),
            'actual_duration': actual_duration,
            'estimated_cost': device_state.get('estimated_cost'),
            'mode': device_state.get('state'),
            'window_used': True if device_state.get('optimal_start') else False
        }
        
        if 'program_history' not in device_state:
            device_state['program_history'] = []
        
        device_state['program_history'].append(program_record)
        
        # Keep last 50 records
        if len(device_state['program_history']) > 50:
            device_state['program_history'] = device_state['program_history'][-50:]
        
        await self.async_save_devices()

    # [Continue with remaining methods - _check_price_threshold, _turn_on_entities, etc. - keeping existing implementations]
    
    async def _check_price_threshold(self, device_name: str, price_data: Dict):
        """Check price threshold (fallback logic)."""
        device_config = self.devices[device_name]
        device_state = self.device_states[device_name]
        
        current_price = price_data['current_price']
        price_threshold = device_config.get('price_threshold', 0.30)
        
        if current_price <= price_threshold:
            device_state['state'] = 'running'
            device_state['started_time'] = datetime.now()
            device_state['device_running'] = True
            device_state['runs_today'] += 1
            _LOGGER.info(f"ALLOWED: {device_name} at {current_price:.3f} EUR/kWh")
        else:
            device_state['state'] = 'cut_off'
            device_state['waiting_for_cheap_price'] = True
            entities = device_config.get(CONF_ENTITIES, [])
            await self._turn_off_entities(entities)
            _LOGGER.warning(f"CUT OFF: {device_name} - price {current_price:.3f} > {price_threshold:.3f}")

    async def _turn_on_entities(self, entities: List[str]):
        """Turn on entities."""
        for entity_id in entities:
            try:
                domain = entity_id.split('.')[0]
                await self.hass.services.async_call(domain, SERVICE_TURN_ON, {'entity_id': entity_id})
            except Exception as e:
                _LOGGER.error(f"Error turning on {entity_id}: {e}")

    async def _turn_off_entities(self, entities: List[str]):
        """Turn off entities."""
        for entity_id in entities:
            try:
                domain = entity_id.split('.')[0]
                await self.hass.services.async_call(domain, SERVICE_TURN_OFF, {'entity_id': entity_id})
            except Exception as e:
                _LOGGER.error(f"Error turning off {entity_id}: {e}")

    async def _get_price_data(self) -> Optional[Dict]:
        """Get current price data."""
        try:
            state = self.hass.states.get(self.tibber_sensor)
            if not state:
                return None
                
            return {
                'current_price': float(state.state),
                'current_cost_rate': state.attributes.get('current_cost_rate', 'NORMAL'),
                'timestamp': datetime.now()
            }
        except (ValueError, TypeError) as e:
            _LOGGER.error(f"Error getting price data: {e}")
            return None

    async def _handle_completion(self, device_name: str):
        """Handle device completion detection."""
        device_state = self.device_states[device_name]
        
        if not device_state['device_running']:
            return
        
        device_config = self.devices[device_name]
        min_runtime = device_config.get('min_runtime_minutes', 5)
        
        if device_state['started_time']:
            runtime = (datetime.now() - device_state['started_time']).total_seconds() / 60
            if runtime < min_runtime:
                return
        
        if device_state.get('program_id'):
            await self._record_program_completion(device_name)
        
        device_state['state'] = 'idle'
        device_state['device_running'] = False
        device_state['started_time'] = None
        device_state['waiting_for_cheap_price'] = False
        device_state['program_detected'] = False
        device_state['optimal_start'] = False
        
        _LOGGER.info(f"COMPLETED: {device_name} finished")

    async def _entity_state_changed(self, device_name: str, entity_id: str, event):
        """Handle entity state changes (fallback when no power sensor)."""
        device_config = self.devices[device_name]
        power_sensor = device_config.get('power_sensor', 'none')
        
        if power_sensor != 'none':
            return
            
        new_state = event.data.get('new_state')
        old_state = event.data.get('old_state')
        
        if not new_state or not old_state:
            return
        
        device_state = self.device_states[device_name]
        
        if old_state.state == STATE_OFF and new_state.state == STATE_ON:
            if not device_state['device_running'] and not device_state['optimal_start']:
                await self._handle_program_detection(device_name)

    # Service methods
    async def force_start_now(self, device_name: str, duration_override: Optional[int] = None):
        """Force start device ignoring all conditions."""
        device_config = self.devices[device_name]
        device_state = self.device_states[device_name]
        
        entities = device_config.get(CONF_ENTITIES, [])
        duration = duration_override or device_config.get('duration', 120)
        
        # Cancel scheduled tasks
        if device_name in self._scheduled_tasks:
            self._scheduled_tasks[device_name].cancel()
            del self._scheduled_tasks[device_name]
        
        # Clear schedule
        device_state['schedule_locked'] = False
        device_state['scheduled_start'] = None
        device_state['scheduled_end'] = None
        
        await self._turn_on_entities(entities)
        
        device_state['manual_override_until'] = datetime.now() + timedelta(minutes=duration)
        device_state['device_running'] = True
        device_state['started_time'] = datetime.now()
        device_state['state'] = 'manual_override'
        device_state['runs_today'] += 1
        
        self.hass.loop.call_later(
            duration * 60,
            lambda: asyncio.create_task(self._turn_off_entities(entities))
        )
        
        _LOGGER.warning(f"FORCE START: {device_name} for {duration} minutes")

    async def cancel_scheduled_program(self, device_name: str):
        """Cancel scheduled program."""
        device_state = self.device_states[device_name]
        
        if device_name in self._scheduled_tasks:
            self._scheduled_tasks[device_name].cancel()
            del self._scheduled_tasks[device_name]
        
        if device_state.get('state') == 'scheduled':
            device_state['state'] = 'idle'
            device_state['scheduled_start'] = None
            device_state['scheduled_end'] = None
            device_state['schedule_locked'] = False
            device_state['program_detected'] = False
            
            _LOGGER.info(f"CANCELLED: Scheduled program for {device_name}")

    async def reset_optimal_windows(self, device_name: str):
        """Reset optimal windows calculation."""
        # Clear cache to force recalculation
        cache_key = f"{device_name}_{self.devices[device_name].get('duration', 120)}"
        if cache_key in self._optimal_windows_cache:
            del self._optimal_windows_cache[cache_key]
        
        self._forecast_cache_time = None
        _LOGGER.info(f"RESET: Optimal windows cache for {device_name}")

    def get_program_analytics(self, device_name: str) -> dict:
        """Get program analytics for a device."""
        device_state = self.device_states.get(device_name, {})
        history = device_state.get('program_history', [])
        
        if not history:
            return {'error': 'No program history available'}
        
        completed_programs = [r for r in history if r.get('actual_duration')]
        
        analytics = {
            'total_programs': len(history),
            'completed_programs': len(completed_programs),
            'programs_in_optimal_windows': len([r for r in completed_programs if r.get('window_used')]),
            'avg_duration_minutes': 0,
            'avg_cost_euros': 0,
            'optimal_window_usage_rate': 0,
            'recent_programs': history[-5:] if len(history) >= 5 else history
        }
        
        if completed_programs:
            durations = [r['actual_duration'] for r in completed_programs]
            analytics['avg_duration_minutes'] = sum(durations) / len(durations)
            
            costs = [r['actual_cost'] for r in completed_programs if r.get('actual_cost')]
            if costs:
                analytics['avg_cost_euros'] = sum(costs) / len(costs)
            
            analytics['optimal_window_usage_rate'] = analytics['programs_in_optimal_windows'] / len(completed_programs)
        
        return analytics

    async def update_schedules(self):
        """Update schedules - check for delayed devices and active scheduling."""
        price_data = await self._get_price_data()
        if not price_data:
            return
        
        # Check Smart Delay devices waiting for cheaper prices
        for device_name, device_state in self.device_states.items():
            if device_state.get('waiting_for_cheap_price'):
                await self._check_resume_conditions(device_name, price_data)
        
        # Check Active Scheduler devices
        await self._check_active_scheduler_devices()

    async def _check_resume_conditions(self, device_name: str, price_data: Dict):
        """Check if delayed device can resume."""
        device_config = self.devices[device_name]
        device_state = self.device_states[device_name]
        
        current_price = price_data['current_price']
        resume_threshold = device_config.get('price_resume_threshold', 0.25)
        
        if current_price <= resume_threshold:
            entities = device_config.get(CONF_ENTITIES, [])
            await self._turn_on_entities(entities)
            
            device_state['state'] = 'running'
            device_state['started_time'] = datetime.now()
            device_state['device_running'] = True
            device_state['waiting_for_cheap_price'] = False
            device_state['runs_today'] += 1
            
            _LOGGER.info(f"RESUMED: {device_name} at {current_price:.3f} EUR/kWh")

    async def _check_active_scheduler_devices(self):
        """Check active scheduler devices for execution."""
        current_time = datetime.now()
        
        for device_name, device_config in self.devices.items():
            if device_config.get('device_mode') != 'active_scheduler':
                continue
                
            device_state = self.device_states[device_name]
            
            if device_state.get('device_running') or device_state.get('manual_override_until'):
                continue
            
            # Check if time to execute scheduled start
            scheduled_start = device_state.get('scheduled_start')
            if (scheduled_start and 
                scheduled_start <= current_time <= scheduled_start + timedelta(minutes=5) and
                device_state.get('state') == 'scheduled'):
                
                await self._execute_scheduled_start(device_name, {
                    'start_time': scheduled_start,
                    'end_time': device_state.get('scheduled_end'),
                    'duration_minutes': device_config.get('duration', 120)
                })
                continue
            
            # Create new schedule if needed
            if not device_state.get('scheduled_start') or device_state.get('scheduled_start') <= current_time:
                optimal_window = await self._find_single_optimal_window(device_name)
                if optimal_window:
                    await self._schedule_for_window(device_name, optimal_window)

    async def remove_device(self, device_name):
        """Remove a device."""
        if device_name in self._scheduled_tasks:
            self._scheduled_tasks[device_name].cancel()
            del self._scheduled_tasks[device_name]
        
        if device_name in self.devices:
            del self.devices[device_name]
        if device_name in self.device_states:
            del self.device_states[device_name]
            
        # Clear cache entries
        cache_keys_to_remove = [k for k in self._optimal_windows_cache.keys() if k.startswith(f"{device_name}_")]
        for key in cache_keys_to_remove:
            del self._optimal_windows_cache[key]
            
        await self.async_save_devices()
        _LOGGER.info(f"Removed device: {device_name}")

    async def async_save_devices(self):
        """Save devices to storage."""
        try:
            await self._store.async_save({"devices": self.devices})
        except Exception as e:
            _LOGGER.error(f"Error saving devices: {e}")

    async def async_unload(self):
        """Unload coordinator."""
        for task in self._scheduled_tasks.values():
            task.cancel()
        self._scheduled_tasks.clear()
        
        if self._unsub_update:
            self._unsub_update()
        if self._unsub_state_change:
            self._unsub_state_change()
        for unsub in self._unsub_entity_changes:
            unsub()

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tibber Smart Scheduler."""
    coordinator = TibberSmartCoordinator(hass, entry)
    await coordinator.async_load_devices()
    
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    
    # Set up periodic checks every 5 minutes
    async def update_schedules(now):
        await coordinator.update_schedules()
    
    coordinator._unsub_update = async_track_time_interval(
        hass, update_schedules, timedelta(minutes=5)
    )
    
    # Track price changes
    async def price_changed(event):
        await coordinator.update_schedules()
    
    coordinator._unsub_state_change = async_track_state_change_event(
        hass, [coordinator.tibber_sensor], price_changed
    )
    
    # Register services
    async def handle_force_start(call: ServiceCall):
        entity_id = call.data.get("entity_id")
        duration = call.data.get("duration")
        device_name = entity_id.split(".")[-1].replace("tibber_scheduler_", "")
        if device_name in coordinator.devices:
            await coordinator.force_start_now(device_name, duration)
    
    async def handle_cancel_program(call: ServiceCall):
        entity_id = call.data.get("entity_id")
        device_name = entity_id.split(".")[-1].replace("tibber_scheduler_", "")
        if device_name in coordinator.devices:
            await coordinator.cancel_scheduled_program(device_name)
    
    async def handle_reset_windows(call: ServiceCall):
        entity_id = call.data.get("entity_id")
        device_name = entity_id.split(".")[-1].replace("tibber_scheduler_", "")
        if device_name in coordinator.devices:
            await coordinator.reset_optimal_windows(device_name)
    
    async def handle_get_analytics(call: ServiceCall):
        entity_id = call.data.get("entity_id")
        device_name = entity_id.split(".")[-1].replace("tibber_scheduler_", "")
        if device_name in coordinator.devices:
            analytics = coordinator.get_program_analytics(device_name)
            _LOGGER.info(f"Analytics for {device_name}: {analytics}")
            return analytics
    
    hass.services.async_register(DOMAIN, "force_start_now", handle_force_start)
    hass.services.async_register(DOMAIN, "cancel_scheduled_program", handle_cancel_program)
    hass.services.async_register(DOMAIN, "reset_optimal_windows", handle_reset_windows)
    hass.services.async_register(DOMAIN, "get_program_analytics", handle_get_analytics)
    
    # Setup platforms
    await hass.config_entries.async_forward_entry_setups(entry, ["switch", "sensor"])
    
    _LOGGER.info(f"Tibber Smart Scheduler with Window-Fitting loaded")
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload entry."""
    coordinator = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator:
        await coordinator.async_unload()
    
    hass.services.async_remove(DOMAIN, "force_start_now")
    hass.services.async_remove(DOMAIN, "cancel_scheduled_program")  
    hass.services.async_remove(DOMAIN, "reset_optimal_windows")
    hass.services.async_remove(DOMAIN, "get_program_analytics")
    
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["switch", "sensor"])

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    
    return unload_ok
