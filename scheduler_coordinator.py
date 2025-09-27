"""
Complete Tibber Scheduler Coordinator with Automatic Scheduling.
This coordinator automatically schedules and runs devices during optimal periods.
"""

import logging
import asyncio
from datetime import datetime, timedelta, time
from typing import Dict, List, Optional, Tuple
import json

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.event import async_track_time_interval, async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.const import SERVICE_TURN_ON, SERVICE_TURN_OFF, STATE_ON, STATE_OFF

_LOGGER = logging.getLogger(__name__)

class TibberSchedulingCoordinator:
    """Complete coordinator with automatic scheduling and forecast handling."""
    
    def __init__(self, hass: HomeAssistant, entry):
        self.hass = hass
        self.entry = entry
        self.tibber_sensor = entry.data["tibber_sensor"]
        self.devices = {}
        self.device_states = {}
        self.scheduled_runs = {}  # Track scheduled automations
        self.current_forecast = []
        self.next_day_forecast = []
        self._store = Store(hass, 1, f"tibber_scheduler_{entry.entry_id}")
        
        # Tracking variables
        self._last_forecast_update = None
        self._last_schedule_calculation = None
        self._forecast_update_callbacks = []
        self._active_automations = {}
        
    async def async_setup(self):
        """Set up the coordinator."""
        await self.async_load_devices()
        
        # Schedule periodic updates
        self._unsub_forecast_update = async_track_time_interval(
            self.hass, self._update_forecast, timedelta(minutes=5)
        )
        
        # Schedule calculation updates (every 15 minutes like nordpool_planner)
        self._unsub_schedule_update = async_track_time_interval(
            self.hass, self._recalculate_schedules, timedelta(minutes=15)
        )
        
        # Track Tibber sensor changes for immediate updates
        self._unsub_price_change = async_track_state_change_event(
            self.hass, [self.tibber_sensor], self._on_price_change
        )
        
        # Initial forecast and schedule calculation
        await self._update_forecast()
        await self._recalculate_schedules()
        
        _LOGGER.info("Tibber Scheduling Coordinator setup complete")
    
    async def _update_forecast(self, now=None):
        """Update price forecast from Tibber sensor."""
        try:
            tibber_state = self.hass.states.get(self.tibber_sensor)
            if not tibber_state or tibber_state.state in ['unavailable', 'unknown']:
                _LOGGER.warning(f"Tibber sensor {self.tibber_sensor} unavailable")
                return
            
            # Get today's and tomorrow's prices
            today_prices = tibber_state.attributes.get('today', [])
            tomorrow_prices = tibber_state.attributes.get('tomorrow', [])
            
            # Parse forecast data
            forecast = []
            
            # Add today's prices
            for price_data in today_prices:
                if 'starts_at' in price_data:
                    try:
                        price_time = datetime.fromisoformat(price_data['starts_at'].replace('Z', '+00:00'))
                        if price_time.tzinfo:
                            price_time = price_time.replace(tzinfo=None)
                        
                        forecast.append({
                            'time': price_time,
                            'price': float(price_data.get('total', price_data.get('value', 0))),
                            'day': 'today'
                        })
                    except Exception as e:
                        _LOGGER.debug(f"Error parsing today price: {e}")
            
            # Add tomorrow's prices (available 13:00-15:00)
            for price_data in tomorrow_prices:
                if 'starts_at' in price_data:
                    try:
                        price_time = datetime.fromisoformat(price_data['starts_at'].replace('Z', '+00:00'))
                        if price_time.tzinfo:
                            price_time = price_time.replace(tzinfo=None)
                        
                        forecast.append({
                            'time': price_time,
                            'price': float(price_data.get('total', price_data.get('value', 0))),
                            'day': 'tomorrow'
                        })
                    except Exception as e:
                        _LOGGER.debug(f"Error parsing tomorrow price: {e}")
            
            # Sort by time
            forecast.sort(key=lambda x: x['time'])
            
            # Update stored forecast
            old_forecast_len = len(self.current_forecast)
            self.current_forecast = forecast
            self._last_forecast_update = datetime.now()
            
            _LOGGER.info(f"Updated forecast: {len(forecast)} hours (was {old_forecast_len})")
            
            # Check if tomorrow's data became available
            tomorrow_count = len([p for p in forecast if p['day'] == 'tomorrow'])
            if tomorrow_count > 0:
                current_hour = datetime.now().hour
                if 13 <= current_hour <= 15:
                    _LOGGER.info(f"Tomorrow's data available: {tomorrow_count} hours (received at {current_hour}:xx)")
                    # Trigger immediate schedule recalculation when tomorrow's data arrives
                    await self._recalculate_schedules()
            
            # Notify callbacks
            for callback in self._forecast_update_callbacks:
                try:
                    await callback(forecast)
                except Exception as e:
                    _LOGGER.error(f"Error in forecast callback: {e}")
                    
        except Exception as e:
            _LOGGER.error(f"Error updating forecast: {e}")
    
    async def _recalculate_schedules(self, now=None):
        """Recalculate optimal schedules for all devices."""
        if not self.current_forecast:
            _LOGGER.warning("No forecast data for schedule calculation")
            return
        
        _LOGGER.info("Recalculating optimal schedules for all devices")
        
        for device_name, device_config in self.devices.items():
            if not device_config.get('enabled', True):
                continue
                
            device_mode = device_config.get('device_mode', 'smart_delay')
            
            if device_mode == 'active_scheduler':
                # Calculate and schedule optimal periods
                await self._calculate_and_schedule_device(device_name)
            elif device_mode == 'smart_delay':
                # Update optimal periods for reference (but don't auto-schedule)
                await self._calculate_optimal_periods_for_device(device_name)
        
        self._last_schedule_calculation = datetime.now()
        _LOGGER.info("Schedule calculation completed")
    
    async def _calculate_and_schedule_device(self, device_name: str):
        """Calculate optimal periods and schedule device to run automatically."""
        device_config = self.devices[device_name]
        duration_minutes = device_config.get('duration', 120)
        search_length_hours = device_config.get('search_length', 24)  # Use 24h by default
        
        # Find optimal periods
        optimal_periods = self._find_optimal_periods(
            device_name, duration_minutes, search_length_hours
        )
        
        if not optimal_periods:
            _LOGGER.warning(f"No optimal periods found for {device_name}")
            return
        
        # Schedule the best period
        best_period = optimal_periods[0]
        
        # Cancel existing scheduled runs
        await self._cancel_scheduled_runs(device_name)
        
        # Schedule new run
        await self._schedule_device_run(device_name, best_period)
        
        # Store schedule for UI display
        self.scheduled_runs[device_name] = {
            'scheduled_periods': optimal_periods[:3],  # Store top 3 for display
            'active_period': best_period,
            'calculation_time': datetime.now(),
            'next_calculation': datetime.now() + timedelta(minutes=15)
        }
        
        _LOGGER.info(
            f"Scheduled {device_name}: {best_period['start_time'].strftime('%H:%M')}-"
            f"{best_period['end_time'].strftime('%H:%M')} (avg: {best_period['avg_price']:.3f} €/kWh)"
        )
    
    async def _calculate_optimal_periods_for_device(self, device_name: str):
        """Calculate optimal periods for smart_delay mode (no auto-scheduling)."""
        device_config = self.devices[device_name]
        duration_minutes = device_config.get('duration', 120)
        search_length_hours = device_config.get('search_length', 8)
        
        optimal_periods = self._find_optimal_periods(
            device_name, duration_minutes, search_length_hours
        )
        
        # Store for UI display (smart_delay shows optimal times but doesn't auto-run)
        self.scheduled_runs[device_name] = {
            'optimal_periods': optimal_periods[:5],  # Store top 5 for smart delay
            'mode': 'smart_delay',
            'calculation_time': datetime.now(),
        }
    
    def _find_optimal_periods(self, device_name: str, duration_minutes: int, search_hours: int) -> List[Dict]:
        """Find optimal periods using nordpool_planner algorithm."""
        if not self.current_forecast:
            return []
        
        current_time = datetime.now()
        search_end = current_time + timedelta(hours=search_hours)
        
        # Filter forecast to search window
        relevant_prices = [
            p for p in self.current_forecast 
            if current_time <= p['time'] <= search_end
        ]
        
        duration_hours = max(1, duration_minutes // 60)
        if len(relevant_prices) < duration_hours:
            return []
        
        # Find all possible consecutive periods
        possible_periods = []
        for i in range(len(relevant_prices) - duration_hours + 1):
            period_hours = relevant_prices[i:i + duration_hours]
            avg_price = sum(h['price'] for h in period_hours) / len(period_hours)
            
            start_time = period_hours[0]['time']
            end_time = start_time + timedelta(minutes=duration_minutes)
            
            possible_periods.append({
                'start_time': start_time,
                'end_time': end_time,
                'avg_price': avg_price,
                'duration_minutes': duration_minutes,
                'price_data': period_hours
            })
        
        # Sort by price (cheapest first)
        possible_periods.sort(key=lambda x: x['avg_price'])
        
        return possible_periods
    
    async def _schedule_device_run(self, device_name: str, period: Dict):
        """Schedule device to run at optimal time."""
        start_time = period['start_time']
        end_time = period['end_time']
        
        # Cancel any existing automation
        await self._cancel_scheduled_runs(device_name)
        
        # Calculate delays
        now = datetime.now()
        start_delay = (start_time - now).total_seconds()
        end_delay = (end_time - now).total_seconds()
        
        if start_delay <= 0:
            # Period already started or starting now
            if end_delay > 0:
                # We're in the period, turn on now and schedule stop
                await self._turn_on_device(device_name, f"Optimal period active (started {start_time.strftime('%H:%M')})")
                
                # Schedule stop
                stop_handle = self.hass.loop.call_later(
                    end_delay, 
                    lambda: asyncio.create_task(self._turn_off_device(device_name, "Optimal period ended"))
                )
                self._active_automations[f"{device_name}_stop"] = stop_handle
        else:
            # Schedule start
            start_handle = self.hass.loop.call_later(
                start_delay,
                lambda: asyncio.create_task(self._start_scheduled_run(device_name, period))
            )
            self._active_automations[f"{device_name}_start"] = start_handle
    
    async def _start_scheduled_run(self, device_name: str, period: Dict):
        """Start a scheduled device run."""
        end_time = period['end_time']
        duration_seconds = (end_time - datetime.now()).total_seconds()
        
        if duration_seconds <= 0:
            _LOGGER.warning(f"Scheduled period for {device_name} already ended")
            return
        
        # Turn on device
        await self._turn_on_device(device_name, f"Scheduled optimal run (until {end_time.strftime('%H:%M')})")
        
        # Schedule stop
        stop_handle = self.hass.loop.call_later(
            duration_seconds,
            lambda: asyncio.create_task(self._turn_off_device(device_name, "Scheduled period ended"))
        )
        self._active_automations[f"{device_name}_stop"] = stop_handle
    
    async def _turn_on_device(self, device_name: str, reason: str):
        """Turn on device entities."""
        device_config = self.devices[device_name]
        entities = device_config.get('entities', [])
        
        for entity_id in entities:
            try:
                domain = entity_id.split('.')[0]
                await self.hass.services.async_call(
                    domain, SERVICE_TURN_ON, {'entity_id': entity_id}
                )
                _LOGGER.info(f"Turned ON {entity_id}: {reason}")
            except Exception as e:
                _LOGGER.error(f"Error turning on {entity_id}: {e}")
        
        # Update device state
        device_state = self.device_states.setdefault(device_name, {})
        device_state.update({
            'device_running': True,
            'started_time': datetime.now(),
            'start_reason': reason,
            'optimal_start': True
        })
    
    async def _turn_off_device(self, device_name: str, reason: str):
        """Turn off device entities."""
        device_config = self.devices[device_name]
        entities = device_config.get('entities', [])
        
        for entity_id in entities:
            try:
                domain = entity_id.split('.')[0]
                await self.hass.services.async_call(
                    domain, SERVICE_TURN_OFF, {'entity_id': entity_id}
                )
                _LOGGER.info(f"Turned OFF {entity_id}: {reason}")
            except Exception as e:
                _LOGGER.error(f"Error turning off {entity_id}: {e}")
        
        # Update device state
        device_state = self.device_states.setdefault(device_name, {})
        device_state.update({
            'device_running': False,
            'stopped_time': datetime.now(),
            'stop_reason': reason,
            'optimal_start': False
        })
    
    async def _cancel_scheduled_runs(self, device_name: str):
        """Cancel any scheduled runs for device."""
        keys_to_remove = []
        for key, handle in self._active_automations.items():
            if key.startswith(device_name):
                handle.cancel()
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del self._active_automations[key]
    
    async def _on_price_change(self, event):
        """Handle Tibber price sensor changes."""
        # Update forecast when price sensor changes
        await self._update_forecast()
    
    # Device management methods
    async def add_device(self, device_config):
        """Add a device."""
        device_name = device_config['name']
        self.devices[device_name] = device_config
        self.device_states[device_name] = {
            'device_running': False,
            'enabled': device_config.get('enabled', True)
        }
        
        await self.async_save_devices()
        
        # If active scheduler, calculate schedule immediately
        if device_config.get('device_mode') == 'active_scheduler':
            await self._calculate_and_schedule_device(device_name)
        
        _LOGGER.info(f"Added device: {device_name} ({device_config.get('device_mode', 'unknown')} mode)")
    
    async def async_load_devices(self):
        """Load devices from storage."""
        try:
            stored_data = await self._store.async_load()
            if stored_data:
                self.devices = stored_data.get("devices", {})
                for device_name in self.devices:
                    self.device_states[device_name] = {
                        'device_running': False,
                        'enabled': self.devices[device_name].get('enabled', True)
                    }
            _LOGGER.info(f"Loaded {len(self.devices)} devices from storage")
        except Exception as e:
            _LOGGER.error(f"Error loading devices: {e}")
            self.devices = {}
    
    async def async_save_devices(self):
        """Save devices to storage."""
        try:
            await self._store.async_save({"devices": self.devices})
        except Exception as e:
            _LOGGER.error(f"Error saving devices: {e}")
    
    # Data access methods for UI
    def get_forecast_data(self) -> List[Dict]:
        """Get forecast data for visualization."""
        return self.current_forecast
    
    def get_device_schedule(self, device_name: str) -> Dict:
        """Get schedule information for device."""
        return self.scheduled_runs.get(device_name, {})
    
    def get_next_optimal_periods(self, device_name: str, count: int = 5) -> List[Dict]:
        """Get next optimal periods for device."""
        schedule = self.scheduled_runs.get(device_name, {})
        if schedule.get('mode') == 'smart_delay':
            return schedule.get('optimal_periods', [])[:count]
        else:
            return schedule.get('scheduled_periods', [])[:count]
    
    async def async_unload(self):
        """Unload coordinator."""
        # Cancel all scheduled runs
        for device_name in self.devices:
            await self._cancel_scheduled_runs(device_name)
        
        # Cancel update callbacks
        if hasattr(self, '_unsub_forecast_update'):
            self._unsub_forecast_update()
        if hasattr(self, '_unsub_schedule_update'):
            self._unsub_schedule_update()
        if hasattr(self, '_unsub_price_change'):
            self._unsub_price_change()
        
        _LOGGER.info("Tibber Scheduling Coordinator unloaded")
