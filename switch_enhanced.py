"""Enhanced switch with forecast integration."""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up enhanced switches."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    entities = []
    for device_name in coordinator.devices:
        entities.append(TibberSchedulerSwitchEnhanced(coordinator, device_name))
    
    async_add_entities(entities)

class TibberSchedulerSwitchEnhanced(SwitchEntity):
    """Enhanced switch with forecast and stable scheduling."""
    
    def __init__(self, coordinator, device_name: str):
        """Initialize switch."""
        self._coordinator = coordinator
        self._device_name = device_name
        self._attr_name = f"Tibber Scheduler {device_name.replace('_', ' ').title()}"
        self._attr_unique_id = f"tibber_scheduler_{device_name}"
        
        # Cache for stable attributes (15 minute cache like nordpool_planner)
        self._last_calculation = None
        self._cached_attributes = {}
        self._cache_duration = 15 * 60  # 15 minutes
        
    @property
    def is_on(self) -> bool:
        """Return if scheduler is enabled."""
        device_config = self._coordinator.devices.get(self._device_name, {})
        return device_config.get('enabled', True)
    
    @property
    def icon(self) -> str:
        """Return dynamic icon."""
        device_state = self._coordinator.device_states.get(self._device_name, {})
        
        if not self.is_on:
            return "mdi:calendar-remove"
        elif device_state.get('device_running', False):
            return "mdi:play-circle"
        elif device_state.get('waiting_for_cheap_price', False):
            return "mdi:clock-time-four"
        else:
            return "mdi:calendar-clock"
    
    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return comprehensive attributes with stable caching."""
        # Check cache validity
        current_time = datetime.now()
        if (self._last_calculation and 
            (current_time - self._last_calculation).total_seconds() < self._cache_duration):
            # Return cached attributes for stability
            return self._cached_attributes
        
        # Calculate new attributes
        device_config = self._coordinator.devices.get(self._device_name, {})
        device_state = self._coordinator.device_states.get(self._device_name, {})
        
        attrs = {
            # Basic info
            'device_mode': device_config.get('device_mode', 'smart_delay'),
            'enabled': self.is_on,
            'device_running': device_state.get('device_running', False),
            'duration_minutes': device_config.get('duration', 120),
            'search_length_hours': device_config.get('search_length', 8),
        }
        
        # Get forecast data if coordinator supports it
        if hasattr(self._coordinator, 'get_forecast_data'):
            try:
                # This is async, so we can't call it directly in a property
                # Instead, we'll use cached forecast if available
                forecast_count = getattr(self._coordinator, '_forecast_count', 0)
                attrs['forecast_hours'] = forecast_count
                attrs['tomorrow_data'] = getattr(self._coordinator, '_has_tomorrow_data', False)
            except Exception as e:
                _LOGGER.debug(f"Error getting forecast info: {e}")
        
        # Enhanced optimal period calculation (stable)
        optimal_info = self._calculate_stable_optimal_periods(device_config)
        attrs.update(optimal_info)
        
        # Current price info
        try:
            tibber_state = self._coordinator.hass.states.get(self._coordinator.tibber_sensor)
            if tibber_state and tibber_state.state not in ['unavailable', 'unknown']:
                attrs['current_price'] = round(float(tibber_state.state), 4)
        except (ValueError, TypeError):
            pass
        
        # Cache the results
        self._cached_attributes = attrs
        self._last_calculation = current_time
        
        return attrs
    
    def _calculate_stable_optimal_periods(self, device_config: dict) -> dict:
        """Calculate stable optimal periods (cached for 15 minutes)."""
        try:
            # Get Tibber price data
            tibber_state = self._coordinator.hass.states.get(self._coordinator.tibber_sensor)
            if not tibber_state:
                return {'next_start': 'No data', 'next_stop': 'No data'}
            
            # Try to get forecast from today/tomorrow attributes
            today_prices = tibber_state.attributes.get('today', [])
            tomorrow_prices = tibber_state.attributes.get('tomorrow', [])
            
            all_prices = []
            
            # Parse today's prices
            for price_data in today_prices:
                if 'starts_at' in price_data:
                    try:
                        price_time = datetime.fromisoformat(price_data['starts_at'].replace('Z', '+00:00'))
                        if price_time.tzinfo:
                            price_time = price_time.replace(tzinfo=None)
                        
                        all_prices.append({
                            'time': price_time,
                            'price': float(price_data.get('total', 0))
                        })
                    except Exception:
                        continue
            
            # Parse tomorrow's prices
            for price_data in tomorrow_prices:
                if 'starts_at' in price_data:
                    try:
                        price_time = datetime.fromisoformat(price_data['starts_at'].replace('Z', '+00:00'))
                        if price_time.tzinfo:
                            price_time = price_time.replace(tzinfo=None)
                        
                        all_prices.append({
                            'time': price_time,
                            'price': float(price_data.get('total', 0))
                        })
                    except Exception:
                        continue
            
            if not all_prices:
                return {'next_start': 'No prices', 'next_stop': 'No prices'}
            
            # Sort by time
            all_prices.sort(key=lambda x: x['time'])
            
            # Find optimal period
            optimal_period = self._find_cheapest_consecutive_period(
                all_prices, 
                device_config.get('duration', 120),
                device_config.get('search_length', 8)
            )
            
            if optimal_period:
                return {
                    'next_start': optimal_period['start_time'].strftime('%H:%M'),
                    'next_stop': optimal_period['end_time'].strftime('%H:%M'),
                    'next_start_date': optimal_period['start_time'].strftime('%Y-%m-%d'),
                    'optimal_avg_price': round(optimal_period['avg_price'], 4),
                    'minutes_until_start': max(0, int((optimal_period['start_time'] - datetime.now()).total_seconds() / 60)),
                    'window_status': f"Optimal period: {optimal_period['start_time'].strftime('%H:%M')}-{optimal_period['end_time'].strftime('%H:%M')}",
                    'calculation_cached': True
                }
            else:
                return {
                    'next_start': 'Not found',
                    'next_stop': 'Not found',
                    'window_status': 'No optimal period found'
                }
                
        except Exception as e:
            _LOGGER.error(f"Error calculating optimal periods: {e}")
            return {
                'next_start': 'Error',
                'next_stop': 'Error',
                'window_status': f'Calculation error: {str(e)}'
            }
    
    def _find_cheapest_consecutive_period(self, prices: list, duration_minutes: int, search_hours: int) -> dict:
        """Find cheapest consecutive period (nordpool_planner algorithm)."""
        current_time = datetime.now()
        search_end = current_time + timedelta(hours=search_hours)
        
        # Filter to search window
        relevant_prices = [p for p in prices if current_time <= p['time'] <= search_end]
        
        duration_hours = max(1, duration_minutes // 60)
        if len(relevant_prices) < duration_hours:
            return None
        
        # Find cheapest consecutive period
        best_period = None
        best_avg_price = float('inf')
        
        for i in range(len(relevant_prices) - duration_hours + 1):
            period_prices = relevant_prices[i:i + duration_hours]
            avg_price = sum(p['price'] for p in period_prices) / len(period_prices)
            
            if avg_price < best_avg_price:
                best_avg_price = avg_price
                start_time = period_prices[0]['time']
                end_time = start_time + timedelta(minutes=duration_minutes)
                
                best_period = {
                    'start_time': start_time,
                    'end_time': end_time,
                    'avg_price': avg_price
                }
        
        return best_period
    
    async def async_turn_on(self, **kwargs) -> None:
        """Enable scheduler."""
        device_config = self._coordinator.devices.get(self._device_name, {})
        device_config['enabled'] = True
        await self._coordinator.async_save_devices()
        
        # Clear cache to force recalculation
        self._last_calculation = None
        
        self.async_write_ha_state()
    
    async def async_turn_off(self, **kwargs) -> None:
        """Disable scheduler."""
        device_config = self._coordinator.devices.get(self._device_name, {})
        device_config['enabled'] = False
        await self._coordinator.async_save_devices()
        
        self.async_write_ha_state()
