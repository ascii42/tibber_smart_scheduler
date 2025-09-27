# UPDATE YOUR extra_state_attributes METHOD:

@property
def extra_state_attributes(self) -> Dict[str, Any]:
    """FIXED: Stable attributes that don't change rapidly."""
    device_config = self._coordinator.devices.get(self._device_name, {})
    device_state = self._coordinator.device_states.get(self._device_name, {})
    
    attrs = {
        'device_mode': device_config.get('device_mode', 'smart_delay'),
        'enabled': self.is_on,
        'duration_minutes': device_config.get('duration', 120),
        'search_length_hours': device_config.get('search_length', 8),
        'device_running': device_state.get('device_running', False),
        'waiting_for_cheap_price': device_state.get('waiting_for_cheap_price', False),
    }
    
    # FIXED: Use stable schedule calculation
    attrs['next_start'] = self._get_next_start_time()
    attrs['next_stop'] = self._get_next_stop_time()
    
    # Add schedule info from stable cache
    stable_schedules = getattr(self._coordinator, 'stable_schedules', {})
    schedule = stable_schedules.get(self._device_name, [])
    
    if schedule:
        next_slot = schedule[0]
        attrs.update({
            'next_start_date': next_slot['start_time'].strftime('%Y-%m-%d') if hasattr(next_slot['start_time'], 'strftime') else 'today',
            'next_stop_date': next_slot['end_time'].strftime('%Y-%m-%d') if hasattr(next_slot['end_time'], 'strftime') else 'today',
            'window_duration_minutes': next_slot.get('duration_minutes', device_config.get('duration', 120)),
            'optimal_avg_price': round(next_slot.get('avg_price', 0), 4),
            'window_status': 'Stable schedule calculated',
            'schedule_cached': True,
            'minutes_until_start': max(0, int((next_slot['start_time'] - datetime.now()).total_seconds() / 60)) if hasattr(next_slot['start_time'], 'timestamp') else 0
        })
    else:
        attrs.update({
            'next_start_date': 'Not scheduled',
            'next_stop_date': 'Not scheduled', 
            'window_status': 'No optimal window found',
            'schedule_cached': False
        })
    
    # Current price (if available)
    try:
        tibber_state = self.hass.states.get(self._coordinator.tibber_sensor)
        if tibber_state and tibber_state.state not in ['unavailable', 'unknown']:
            attrs['current_price'] = round(float(tibber_state.state), 4)
    except (ValueError, TypeError):
        pass
    
    return attrs
