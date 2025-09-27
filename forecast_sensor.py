"""Forecast visualization sensor for dashboard charts."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from datetime import datetime, timedelta

from .const import DOMAIN

class TibberForecastSensor(SensorEntity):
    """Sensor providing forecast data for visualization."""
    
    def __init__(self, coordinator, sensor_type: str = "forecast"):
        """Initialize forecast sensor."""
        self._coordinator = coordinator
        self._sensor_type = sensor_type
        self._attr_name = f"Tibber {sensor_type.replace('_', ' ').title()}"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{sensor_type}"
        self._attr_icon = "mdi:chart-line"
        
    @property
    def state(self) -> str:
        """Return sensor state."""
        if self._sensor_type == "forecast":
            forecast = self._coordinator.get_forecast_data()
            return f"{len(forecast)} hours"
        elif self._sensor_type == "next_optimal":
            # Show next optimal period across all devices
            next_periods = []
            for device_name in self._coordinator.devices:
                periods = self._coordinator.get_next_optimal_periods(device_name, 1)
                if periods:
                    next_periods.append(periods[0])
            
            if next_periods:
                # Find soonest period
                next_periods.sort(key=lambda x: x['start_time'])
                next_period = next_periods[0]
                return next_period['start_time'].strftime('%H:%M')
            return "No periods"
        
        return "Unknown"
    
    @property
    def extra_state_attributes(self) -> dict:
        """Return detailed attributes for visualization."""
        if self._sensor_type == "forecast":
            return self._get_forecast_attributes()
        elif self._sensor_type == "next_optimal":
            return self._get_next_optimal_attributes()
        
        return {}
    
    def _get_forecast_attributes(self) -> dict:
        """Get forecast data for ApexCharts visualization."""
        forecast = self._coordinator.get_forecast_data()
        
        if not forecast:
            return {
                'forecast_hours': 0,
                'last_update': 'Never',
                'price_data': [],
                'chart_data': []
            }
        
        # Prepare data for ApexCharts
        chart_data = []
        price_data = []
        
        for price_point in forecast:
            timestamp = price_point['time'].timestamp() * 1000  # ApexCharts needs milliseconds
            price = price_point['price']
            
            chart_data.append([timestamp, price])
            price_data.append({
                'time': price_point['time'].strftime('%H:%M'),
                'date': price_point['time'].strftime('%Y-%m-%d'),
                'price': round(price, 4),
                'day': price_point.get('day', 'today')
            })
        
        # Calculate statistics
        prices = [p['price'] for p in forecast]
        min_price = min(prices) if prices else 0
        max_price = max(prices) if prices else 0
        avg_price = sum(prices) / len(prices) if prices else 0
        
        # Find tomorrow's data availability
        tomorrow_count = len([p for p in forecast if p.get('day') == 'tomorrow'])
        tomorrow_available = tomorrow_count > 0
        
        return {
            'forecast_hours': len(forecast),
            'last_update': self._coordinator._last_forecast_update.strftime('%H:%M') if self._coordinator._last_forecast_update else 'Never',
            'tomorrow_data_available': tomorrow_available,
            'tomorrow_hours': tomorrow_count,
            'min_price': round(min_price, 4),
            'max_price': round(max_price, 4),
            'avg_price': round(avg_price, 4),
            'price_range': round(max_price - min_price, 4),
            'chart_data': chart_data,  # For ApexCharts
            'price_data': price_data,  # For table display
            'current_hour': datetime.now().hour
        }
    
    def _get_next_optimal_attributes(self) -> dict:
        """Get next optimal periods for all devices."""
        all_periods = {}
        
        for device_name, device_config in self._coordinator.devices.items():
            if not device_config.get('enabled', True):
                continue
                
            periods = self._coordinator.get_next_optimal_periods(device_name, 3)
            device_mode = device_config.get('device_mode', 'unknown')
            
            all_periods[device_name] = {
                'device_mode': device_mode,
                'enabled': device_config.get('enabled', True),
                'periods': []
            }
            
            for i, period in enumerate(periods):
                all_periods[device_name]['periods'].append({
                    'rank': i + 1,
                    'start_time': period['start_time'].strftime('%H:%M'),
                    'end_time': period['end_time'].strftime('%H:%M'),
                    'start_date': period['start_time'].strftime('%Y-%m-%d'),
                    'avg_price': round(period['avg_price'], 4),
                    'duration_minutes': period['duration_minutes'],
                    'hours_until_start': round((period['start_time'] - datetime.now()).total_seconds() / 3600, 1)
                })
        
        # Find global next period
        all_device_periods = []
        for device_data in all_periods.values():
            all_device_periods.extend(device_data['periods'])
        
        if all_device_periods:
            # Sort by start time
            all_device_periods.sort(key=lambda x: datetime.strptime(f"{x['start_date']} {x['start_time']}", '%Y-%m-%d %H:%M'))
            next_global = all_device_periods[0]
        else:
            next_global = None
        
        return {
            'devices': all_periods,
            'next_global_period': next_global,
            'total_devices': len([d for d in all_periods.values() if d['enabled']]),
            'calculation_time': self._coordinator._last_schedule_calculation.strftime('%H:%M') if self._coordinator._last_schedule_calculation else 'Never'
        }

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up forecast sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    sensors = [
        TibberForecastSensor(coordinator, "forecast"),
        TibberForecastSensor(coordinator, "next_optimal")
    ]
    
    async_add_entities(sensors)
