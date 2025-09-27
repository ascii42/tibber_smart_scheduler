"""
Nordpool_planner style calculation for stable "low cost starts at" times.
This mimics nordpool_planner behavior exactly.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging

_LOGGER = logging.getLogger(__name__)

class NordpoolPlannerCalculator:
    """Calculator that mimics nordpool_planner behavior."""
    
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self._last_calculation_time = None
        self._cached_optimal_periods = {}
        self._calculation_interval = 900  # 15 minutes like nordpool_planner
        
    def get_low_cost_start_time(self, device_name: str) -> Optional[str]:
        """
        Get stable "low cost starts at" time like nordpool_planner.
        This is the equivalent of nordpool_planner's next optimal start.
        """
        optimal_periods = self._get_cached_optimal_periods(device_name)
        
        if not optimal_periods:
            return None
            
        # Find next period that hasn't started yet
        current_time = datetime.now()
        for period in optimal_periods:
            if period['start_time'] > current_time:
                return period['start_time'].strftime('%H:%M')
        
        return None
    
    def get_low_cost_end_time(self, device_name: str) -> Optional[str]:
        """Get when the low cost period ends."""
        low_cost_start = self.get_low_cost_start_time(device_name)
        if not low_cost_start:
            return None
            
        device_config = self.coordinator.devices.get(device_name, {})
        duration_minutes = device_config.get('duration', 120)
        
        # Parse start time and add duration
        try:
            start_hour, start_min = map(int, low_cost_start.split(':'))
            start_dt = datetime.now().replace(hour=start_hour, minute=start_min, second=0, microsecond=0)
            
            # If start time is in the past, assume tomorrow
            if start_dt <= datetime.now():
                start_dt += timedelta(days=1)
                
            end_dt = start_dt + timedelta(minutes=duration_minutes)
            return end_dt.strftime('%H:%M')
        except:
            return None
    
    def is_in_low_cost_period(self, device_name: str) -> bool:
        """Check if currently in a low cost period (like nordpool_planner binary sensor)."""
        optimal_periods = self._get_cached_optimal_periods(device_name)
        current_time = datetime.now()
        
        for period in optimal_periods:
            if period['start_time'] <= current_time <= period['end_time']:
                return True
        return False
    
    def get_nordpool_attributes(self, device_name: str) -> Dict:
        """Get nordpool_planner style attributes."""
        device_config = self.coordinator.devices.get(device_name, {})
        optimal_periods = self._get_cached_optimal_periods(device_name)
        
        # Get current price
        try:
            tibber_state = self.coordinator.hass.states.get(self.coordinator.tibber_sensor)
            current_price = float(tibber_state.state) if tibber_state else 0
        except:
            current_price = 0
        
        # Calculate nordpool_planner metrics
        best_average = min(p['avg_price'] for p in optimal_periods) if optimal_periods else current_price
        now_cost_rate = (current_price / best_average) if best_average > 0 else 1.0
        hours_to_optimal = self._hours_to_next_optimal(optimal_periods)
        
        return {
            'now_cost_rate': round(now_cost_rate, 2),
            'best_average': round(best_average, 4),
            'current_price': round(current_price, 4),
            'hours_to_optimal': hours_to_optimal,
            'search_length': device_config.get('search_length', 8),
            'duration': device_config.get('duration', 120) // 60,
            'low_cost_starts_at': self.get_low_cost_start_time(device_name),
            'low_cost_ends_at': self.get_low_cost_end_time(device_name),
            'in_low_cost_period': self.is_in_low_cost_period(device_name),
            'optimal_periods_found': len(optimal_periods),
            'calculation_cached': self._is_calculation_cached()
        }
    
    def _get_cached_optimal_periods(self, device_name: str) -> List[Dict]:
        """Get cached optimal periods (recalculates every 15 minutes)."""
        current_time = datetime.now()
        
        # Check if we need to recalculate
        if (self._last_calculation_time is None or 
            (current_time - self._last_calculation_time).total_seconds() > self._calculation_interval):
            
            _LOGGER.info("Recalculating optimal periods (nordpool_planner style)")
            self._calculate_all_optimal_periods()
            self._last_calculation_time = current_time
        
        return self._cached_optimal_periods.get(device_name, [])
    
    def _calculate_all_optimal_periods(self):
        """Calculate optimal periods for all devices (like nordpool_planner does)."""
        self._cached_optimal_periods = {}
        
        for device_name, device_config in self.coordinator.devices.items():
            if device_config.get('enabled', True):
                self._cached_optimal_periods[device_name] = self._calculate_optimal_periods(device_name)
    
    def _calculate_optimal_periods(self, device_name: str) -> List[Dict]:
        """Calculate optimal periods for a device (nordpool_planner algorithm)."""
        device_config = self.coordinator.devices.get(device_name, {})
        duration_minutes = device_config.get('duration', 120)
        search_length = device_config.get('search_length', 8)
        
        # Get price forecast
        forecast = self._get_price_forecast()
        if not forecast:
            return []
        
        current_time = datetime.now()
        search_end = current_time + timedelta(hours=search_length)
        
        # Filter to search window
        relevant_hours = [h for h in forecast if current_time <= h['time'] <= search_end]
        
        duration_hours = max(1, duration_minutes // 60)
        if len(relevant_hours) < duration_hours:
            return []
        
        # Find all possible consecutive periods
        possible_periods = []
        for i in range(len(relevant_hours) - duration_hours + 1):
            period_hours = relevant_hours[i:i + duration_hours]
            avg_price = sum(h['price'] for h in period_hours) / len(period_hours)
            
            # Calculate actual end time based on duration in minutes
            start_time = period_hours[0]['time']
            end_time = start_time + timedelta(minutes=duration_minutes)
            
            possible_periods.append({
                'start_time': start_time,
                'end_time': end_time,
                'avg_price': avg_price,
                'duration_minutes': duration_minutes
            })
        
        # Sort by price (cheapest first) - this is the key nordpool_planner behavior
        possible_periods.sort(key=lambda x: x['avg_price'])
        
        # Return top periods (nordpool_planner usually shows top 3-5)
        return possible_periods[:5]
    
    def _get_price_forecast(self) -> List[Dict]:
        """Get price forecast from coordinator."""
        try:
            if hasattr(self.coordinator, '_get_price_forecast'):
                return self.coordinator._get_price_forecast(False) or []
            
            # Fallback: try to get from Tibber sensor
            tibber_state = self.coordinator.hass.states.get(self.coordinator.tibber_sensor)
            if tibber_state and tibber_state.attributes:
                for attr_name in ['today', 'tomorrow', 'prices']:
                    prices = tibber_state.attributes.get(attr_name, [])
                    if prices and isinstance(prices, list):
                        forecast_data = []
                        for price_point in prices:
                            if isinstance(price_point, dict) and 'starts_at' in price_point:
                                try:
                                    price_time = datetime.fromisoformat(price_point['starts_at'].replace('Z', '+00:00'))
                                    if price_time.tzinfo:
                                        price_time = price_time.replace(tzinfo=None)
                                    
                                    forecast_data.append({
                                        'time': price_time,
                                        'price': float(price_point.get('total', price_point.get('value', 0)))
                                    })
                                except Exception as e:
                                    _LOGGER.debug(f"Error parsing price point: {e}")
                                    continue
                        
                        if forecast_data:
                            return forecast_data
            
            return []
        except Exception as e:
            _LOGGER.error(f"Error getting price forecast: {e}")
            return []
    
    def _hours_to_next_optimal(self, optimal_periods: List[Dict]) -> float:
        """Calculate hours to next optimal period."""
        if not optimal_periods:
            return 0.0
        
        current_time = datetime.now()
        for period in optimal_periods:
            if period['start_time'] > current_time:
                hours_diff = (period['start_time'] - current_time).total_seconds() / 3600
                return round(hours_diff, 1)
        
        return 0.0
    
    def _is_calculation_cached(self) -> bool:
        """Check if using cached calculation."""
        if self._last_calculation_time is None:
            return False
        
        time_since_calc = (datetime.now() - self._last_calculation_time).total_seconds()
        return time_since_calc < self._calculation_interval
