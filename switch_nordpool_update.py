# ADD TO YOUR SWITCH CLASS:

@property
def extra_state_attributes(self) -> Dict[str, Any]:
    """Nordpool_planner style stable attributes."""
    device_config = self._coordinator.devices.get(self._device_name, {})
    device_state = self._coordinator.device_states.get(self._device_name, {})
    
    # Initialize nordpool calculator if not exists
    if not hasattr(self._coordinator, '_nordpool_calculator'):
        from .nordpool_calculation import NordpoolPlannerCalculator
        self._coordinator._nordpool_calculator = NordpoolPlannerCalculator(self._coordinator)
    
    calc = self._coordinator._nordpool_calculator
    
    # Basic attributes
    attrs = {
        'device_mode': device_config.get('device_mode', 'smart_delay'),
        'enabled': self.is_on,
        'duration_minutes': device_config.get('duration', 120),
        'search_length_hours': device_config.get('search_length', 8),
        'device_running': device_state.get('device_running', False),
        'waiting_for_cheap_price': device_state.get('waiting_for_cheap_price', False),
    }
    
    # Nordpool_planner style attributes (STABLE - only update every 15min)
    nordpool_attrs = calc.get_nordpool_attributes(self._device_name)
    attrs.update(nordpool_attrs)
    
    # Map to expected attribute names
    attrs['next_start'] = nordpool_attrs.get('low_cost_starts_at', 'Not scheduled')
    attrs['next_stop'] = nordpool_attrs.get('low_cost_ends_at', 'Not scheduled')
    
    # Additional status
    if nordpool_attrs.get('in_low_cost_period'):
        attrs['window_status'] = 'In low cost period'
    elif nordpool_attrs.get('low_cost_starts_at'):
        hours_to = nordpool_attrs.get('hours_to_optimal', 0)
        if hours_to > 0:
            attrs['window_status'] = f'Low cost starts in {hours_to}h'
        else:
            attrs['window_status'] = 'Low cost period starting soon'
    else:
        attrs['window_status'] = 'No optimal periods found'
    
    return attrs
