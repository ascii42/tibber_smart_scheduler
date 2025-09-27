"""Calendar entities for visualizing scheduled time slots."""

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

class TibberCalendarEntity(CalendarEntity):
    """Calendar entity for visualizing scheduled time slots."""
    
    def __init__(self, coordinator, device_name: str):
        """Initialize the calendar entity."""
        self._coordinator = coordinator
        self._device_name = device_name
        self._attr_name = f"Tibber Schedule {device_name.title()}"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_calendar_{device_name}"
    
    @property
    def event(self):
        """Return the current event."""
        events = self._get_calendar_events()
        now = datetime.now()
        
        for event in events:
            if hasattr(event, 'start') and hasattr(event, 'end'):
                if event.start <= now < event.end:
                    return event
        
        return None
    
    async def async_get_events(self, hass, start_date: datetime, end_date: datetime):
        """Get events for calendar visualization."""
        return self._get_calendar_events(start_date, end_date)
    
    def _get_calendar_events(self, start_date=None, end_date=None):
        """Generate calendar events from scheduled slots."""
        events = []
        
        if start_date is None:
            start_date = datetime.now()
        if end_date is None:
            end_date = start_date + timedelta(days=2)
        
        device_config = self._coordinator.devices.get(self._device_name, {})
        schedule = self._coordinator.current_schedules.get(self._device_name, [])
        device_state = self._coordinator.device_states.get(self._device_name, {})
        
        # Add scheduled slots as events
        for i, slot in enumerate(schedule):
            if slot.get('start_time') and start_date <= slot['start_time'] < end_date:
                event_summary = f"{self._device_name.title()} Run #{i+1}"
                description = f"Duration: {slot.get('duration_minutes', 0)}min\nCost: {slot.get('estimated_cost', 'Unknown')}\nReason: {slot.get('reason', 'Scheduled')}"
                
                events.append(CalendarEvent(
                    start=slot['start_time'],
                    end=slot.get('end_time', slot['start_time'] + timedelta(minutes=slot.get('duration_minutes', 120))),
                    summary=event_summary,
                    description=description,
                    uid=f"tibber_{self._device_name}_{i}_{slot['start_time'].strftime('%Y%m%d_%H%M')}"
                ))
        
        # Add current running event
        if device_state.get('device_running') and device_state.get('started_time'):
            start_time = device_state['started_time']
            if start_date <= start_time < end_date:
                duration = device_config.get('duration', 120)
                end_time = start_time + timedelta(minutes=duration)
                
                events.append(CalendarEvent(
                    start=start_time,
                    end=end_time,
                    summary=f"{self._device_name.title()} Running",
                    description=f"Currently running\nStarted: {start_time.strftime('%H:%M')}",
                    uid=f"tibber_{self._device_name}_running_{start_time.strftime('%Y%m%d_%H%M')}"
                ))
        
        return sorted(events, key=lambda x: x.start if hasattr(x, 'start') else datetime.min)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tibber calendar entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    calendars = []
    
    # Create calendar for each device
    for device_name in coordinator.devices:
        calendars.append(TibberCalendarEntity(coordinator, device_name))

