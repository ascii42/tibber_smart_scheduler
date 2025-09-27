"""Enhanced Tibber Smart Scheduler Switch Entity with Stable Timing and Charts."""

import logging
import json
import base64
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import STATE_ON, STATE_OFF, SERVICE_TURN_ON, SERVICE_TURN_OFF

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tibber switch entities."""
    try:
        coordinator = hass.data[DOMAIN][entry.entry_id]
        coordinator._async_add_entities = async_add_entities

        switches = []

        # Create main scheduler switch for each configured device
        for device_name in coordinator.devices:
            _LOGGER.info(f"Creating scheduler switch for device: {device_name}")
            switches.append(TibberSchedulerSwitch(coordinator, device_name))

            # Create device power control switch
            switches.append(TibberDevicePowerSwitch(coordinator, device_name))

            # Create automatic/manual mode switch
            switches.append(TibberAutomaticModeSwitch(coordinator, device_name))

        if switches:
            async_add_entities(switches)
            _LOGGER.info(f"Added {len(switches)} switch entities")

    except Exception as e:
        _LOGGER.error(f"Error setting up switch entities: {e}")


class TibberSchedulerSwitch(SwitchEntity, RestoreEntity):
    """Main scheduler switch with stable timing and chart visualization."""

    def __init__(self, coordinator, device_name: str):
        """Initialize the scheduler switch."""
        self._coordinator = coordinator
        self._device_name = device_name
        self._attr_name = f"Tibber Scheduler {device_name.replace('_', ' ').title()}"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{device_name}_scheduler"
        self._attr_icon = "mdi:calendar-clock"

        # Stable timing cache (1 hour cache for schedule stability)
        self._last_schedule_calculation = None
        self._cached_schedule = None
        self._schedule_cache_duration = 60 * 60  # 1 hour

        # Attributes cache (15 minute cache for other attributes)
        self._last_calculation = None
        self._cached_attributes = {}
        self._cache_duration = 15 * 60  # 15 minutes

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
    def is_on(self) -> bool:
        """Return true if the scheduler is enabled."""
        try:
            device_config = self._coordinator.devices.get(self._device_name, {})
            return bool(device_config.get("enabled", True))
        except Exception as e:
            _LOGGER.error(f"Error getting is_on for {self._device_name}: {e}")
            return True

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        try:
            tibber_state = self.hass.states.get(self._coordinator.tibber_sensor)
            device_exists = self._device_name in self._coordinator.devices
            return tibber_state is not None and device_exists
        except Exception as e:
            _LOGGER.error(f"Error checking availability for {self._device_name}: {e}")
            return False

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
        """Return comprehensive attributes with stable timing and chart data."""
        # Check cache validity for general attributes
        current_time = datetime.now()
        if (self._last_calculation and
            (current_time - self._last_calculation).total_seconds() < self._cache_duration):
            # Update only the countdown timers but keep stable schedule
            if self._cached_attributes and 'next_start_datetime' in self._cached_attributes:
                self._update_countdown_timers(self._cached_attributes)
            return self._cached_attributes

        try:
            device_config = self._coordinator.devices.get(self._device_name, {})
            device_state = self._coordinator.device_states.get(self._device_name, {})

            # Get current price safely
            current_price = "Unknown"
            current_cost_rate = "Unknown"
            try:
                tibber_state = self.hass.states.get(self._coordinator.tibber_sensor)
                if tibber_state and tibber_state.state not in ['unavailable', 'unknown']:
                    current_price = f"{float(tibber_state.state):.3f} €/kWh"
                    current_cost_rate = tibber_state.attributes.get('current_cost_rate', 'NORMAL')
            except (ValueError, TypeError):
                pass

            # Get device status
            status = self._get_device_status(device_state, device_config)

            # Calculate stable timing (cached for longer periods)
            timing_data = self._get_stable_timing(device_config, device_state)

            # Generate chart data
            chart_data = self._generate_chart_data(device_config)

            # Core attributes
            attributes = {
                # Main status
                'status': status,
                'current_price': current_price,
                'current_cost_rate': current_cost_rate,
                'tibber_sensor': self._coordinator.tibber_sensor,

                # Stable timing data
                **timing_data,

                # Device configuration
                'device_mode': device_config.get('device_mode', 'smart_delay'),
                'enabled': device_config.get('enabled', True),
                'controlled_entities': device_config.get('entities', []),
                'duration_minutes': device_config.get('duration', 120),
                'search_length_hours': device_config.get('search_length', 8),

                # Smart Delay states
                'state': device_state.get('state', 'idle'),
                'device_running': device_state.get('device_running', False),
                'program_detected': device_state.get('program_detected', False),
                'waiting_for_cheap_price': device_state.get('waiting_for_cheap_price', False),
                'scheduler_enabled': device_state.get('scheduler_enabled', True),

                # Price thresholds
                'price_threshold': device_config.get('price_threshold', 0.30),
                'price_resume_threshold': device_config.get('price_resume_threshold', 0.25),
                'use_cost_rate_attribute': device_config.get('use_cost_rate_attribute', False),

                # Power monitoring
                'power_sensor': device_config.get('power_sensor', 'none'),
                'min_power_detection': device_config.get('min_power_detection', 15),
                'last_power_reading': device_state.get('last_power_reading', 0),

                # Runtime statistics
                'runs_today': device_state.get('runs_today', 0),
                'total_runtime_today': device_state.get('total_runtime_today', 0),

                # Manual overrides
                'manual_override_until': device_state.get('manual_override_until'),

                # Timing
                'programmed_time': device_state.get('programmed_time'),
                'started_time': device_state.get('started_time'),
                'scheduled_start': device_state.get('scheduled_start'),
                'scheduled_end': device_state.get('scheduled_end'),

                # Chart visualization
                'price_chart_url': chart_data.get('chart_url'),
                'price_chart_data': chart_data.get('chart_data'),
                'schedule_windows': chart_data.get('schedule_windows'),
            }

            # Cache the results
            self._cached_attributes = attributes
            self._last_calculation = current_time

            return attributes

        except Exception as e:
            _LOGGER.error(f"Error getting attributes for {self._device_name}: {e}")
            return {}

    def _update_countdown_timers(self, attributes: dict):
        """Update only countdown timers without recalculating the schedule."""
        current_time = datetime.now()

        if 'next_start_datetime' in attributes:
            try:
                next_start = datetime.fromisoformat(attributes['next_start_datetime'])
                if next_start > current_time:
                    attributes['minutes_until_start'] = max(0, int((next_start - current_time).total_seconds() / 60))
                else:
                    attributes['minutes_until_start'] = 0
            except (ValueError, TypeError):
                attributes['minutes_until_start'] = 0

        if 'next_stop_datetime' in attributes:
            try:
                next_stop = datetime.fromisoformat(attributes['next_stop_datetime'])
                if next_stop > current_time:
                    attributes['minutes_until_stop'] = max(0, int((next_stop - current_time).total_seconds() / 60))
                else:
                    attributes['minutes_until_stop'] = 0
            except (ValueError, TypeError):
                attributes['minutes_until_stop'] = 0

    def _get_stable_timing(self, device_config: dict, device_state: dict) -> dict:
        """Get stable timing data with proper caching."""
        current_time = datetime.now()

        # Check if we should recalculate schedule (1 hour cache or if no cache)
        should_recalculate = (
            not self._last_schedule_calculation or
            not self._cached_schedule or
            (current_time - self._last_schedule_calculation).total_seconds() > self._schedule_cache_duration
        )

        # Always check current device state first
        device_running = device_state.get('device_running', False)

        # If device is currently running, show current run info
        if device_running:
            started_time = device_state.get('started_time')
            if started_time:
                duration_minutes = device_config.get('duration', 120)
                estimated_stop = started_time + timedelta(minutes=duration_minutes)

                if estimated_stop > current_time:
                    minutes_until_stop = int((estimated_stop - current_time).total_seconds() / 60)
                    return {
                        'next_start': 'Running now',
                        'next_stop': estimated_stop.strftime('%H:%M'),
                        'next_start_date': current_time.strftime('%Y-%m-%d'),
                        'next_stop_date': estimated_stop.strftime('%Y-%m-%d'),
                        'next_start_datetime': current_time.isoformat(),
                        'next_stop_datetime': estimated_stop.isoformat(),
                        'minutes_until_start': 0,
                        'minutes_until_stop': minutes_until_stop,
                        'window_status': f'Running until {estimated_stop.strftime("%H:%M")}',
                        'optimal_avg_price': None,
                        'schedule_locked': True,
                    }

        # Check if there's a coordinator-scheduled start
        scheduled_start = device_state.get('scheduled_start')
        if scheduled_start and scheduled_start > current_time:
            duration_minutes = device_config.get('duration', 120)
            scheduled_stop = scheduled_start + timedelta(minutes=duration_minutes)
            minutes_until_start = int((scheduled_start - current_time).total_seconds() / 60)
            minutes_until_stop = int((scheduled_stop - current_time).total_seconds() / 60)

            return {
                'next_start': scheduled_start.strftime('%H:%M'),
                'next_stop': scheduled_stop.strftime('%H:%M'),
                'next_start_date': scheduled_start.strftime('%Y-%m-%d'),
                'next_stop_date': scheduled_stop.strftime('%Y-%m-%d'),
                'next_start_datetime': scheduled_start.isoformat(),
                'next_stop_datetime': scheduled_stop.isoformat(),
                'minutes_until_start': minutes_until_start,
                'minutes_until_stop': minutes_until_stop,
                'window_status': f'Scheduled for {scheduled_start.strftime("%H:%M")}',
                'optimal_avg_price': None,
                'schedule_locked': True,
            }

        # Use cached schedule if available and still valid
        if not should_recalculate and self._cached_schedule:
            # Update countdown timers for cached schedule
            cached_result = self._cached_schedule.copy()
            if 'next_start_datetime' in cached_result:
                try:
                    next_start = datetime.fromisoformat(cached_result['next_start_datetime'])
                    next_stop = datetime.fromisoformat(cached_result['next_stop_datetime'])

                    # Only use cached schedule if it's still in the future
                    if next_start > current_time:
                        cached_result['minutes_until_start'] = max(0, int((next_start - current_time).total_seconds() / 60))
                        cached_result['minutes_until_stop'] = max(0, int((next_stop - current_time).total_seconds() / 60))
                        cached_result['schedule_locked'] = True
                        return cached_result
                except (ValueError, TypeError):
                    pass

        # Calculate new optimal window (only when cache expires or invalid)
        if should_recalculate:
            optimal_window = self._calculate_stable_optimal_window(device_config)
            if optimal_window:
                self._cached_schedule = optimal_window
                self._last_schedule_calculation = current_time
                return optimal_window

        # Return default if no schedule found
        return {
            'next_start': 'Not scheduled',
            'next_stop': 'Not scheduled',
            'next_start_date': 'Not scheduled',
            'next_stop_date': 'Not scheduled',
            'next_start_datetime': None,
            'next_stop_datetime': None,
            'minutes_until_start': 0,
            'minutes_until_stop': 0,
            'window_status': 'No optimal window found',
            'optimal_avg_price': None,
            'schedule_locked': False,
        }

    def _calculate_stable_optimal_window(self, device_config: dict) -> Optional[dict]:
        """Calculate optimal window that remains stable for longer periods."""
        try:
            # Get Tibber price data
            tibber_state = self.hass.states.get(self._coordinator.tibber_sensor)
            if not tibber_state:
                return None

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
                return None

            # Sort by time
            all_prices.sort(key=lambda x: x['time'])

            # Find optimal period using hour boundaries for stability
            optimal_period = self._find_stable_optimal_period(
                all_prices,
                device_config.get('duration', 120),
                device_config.get('search_length', 8)
            )

            if optimal_period:
                current_time = datetime.now()
                minutes_until_start = max(0, int((optimal_period['start_time'] - current_time).total_seconds() / 60))
                minutes_until_stop = max(0, int((optimal_period['end_time'] - current_time).total_seconds() / 60))

                # Determine if this is part of a split run sequence
                is_split = optimal_period.get('split_run', False)
                duration_minutes = device_config.get('duration', 120)
                optimal_duration = (optimal_period['end_time'] - optimal_period['start_time']).total_seconds() / 60

                if is_split or optimal_duration < duration_minutes:
                    window_status = f"Split run: {optimal_period['start_time'].strftime('%H:%M')}-{optimal_period['end_time'].strftime('%H:%M')} (Part 1)"
                else:
                    window_status = f"Optimal: {optimal_period['start_time'].strftime('%H:%M')}-{optimal_period['end_time'].strftime('%H:%M')}"

                return {
                    'next_start': optimal_period['start_time'].strftime('%H:%M'),
                    'next_stop': optimal_period['end_time'].strftime('%H:%M'),
                    'next_start_date': optimal_period['start_time'].strftime('%Y-%m-%d'),
                    'next_stop_date': optimal_period['end_time'].strftime('%Y-%m-%d'),
                    'next_start_datetime': optimal_period['start_time'].isoformat(),
                    'next_stop_datetime': optimal_period['end_time'].isoformat(),
                    'optimal_avg_price': round(optimal_period['avg_price'], 4),
                    'minutes_until_start': minutes_until_start,
                    'minutes_until_stop': minutes_until_stop,
                    'window_status': window_status,
                    'schedule_locked': True,
                    'split_run': is_split,
                }

            return None

        except Exception as e:
            _LOGGER.error(f"Error calculating stable optimal window: {e}")
            return None

    def _find_stable_optimal_period(self, prices: list, duration_minutes: int, search_hours: int) -> Optional[dict]:
        """Find optimal period with hour-boundary alignment for stability."""
        current_time = datetime.now()

        # For split runs and long durations, search the full forecast period
        # Don't limit by search_hours for more comprehensive scheduling
        next_hour = current_time.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        relevant_prices = [p for p in prices if p['time'] >= next_hour]

        duration_hours = max(1, duration_minutes // 60)

        # Find cheapest consecutive period first (preferred)
        best_period = None
        best_avg_price = float('inf')

        if len(relevant_prices) >= duration_hours:
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
                        'avg_price': avg_price,
                        'split_run': False
                    }

        # If no consecutive period found and we have prices, return earliest for split runs
        if not best_period and relevant_prices:
            # For split runs, return the earliest cheap period
            start_time = relevant_prices[0]['time']
            # Use shorter window for split runs
            split_duration = min(duration_minutes, 60)  # Max 1 hour chunks
            end_time = start_time + timedelta(minutes=split_duration)

            best_period = {
                'start_time': start_time,
                'end_time': end_time,
                'avg_price': relevant_prices[0]['price'],
                'split_run': True
            }

        return best_period

    def _generate_chart_data(self, device_config: dict) -> dict:
        """Generate chart visualization data showing prices and scheduled windows."""
        try:
            # Get Tibber price data
            tibber_state = self.hass.states.get(self._coordinator.tibber_sensor)
            if not tibber_state:
                return {}

            today_prices = tibber_state.attributes.get('today', [])
            tomorrow_prices = tibber_state.attributes.get('tomorrow', [])

            # Combine and parse price data
            all_prices = []
            chart_data = {
                'labels': [],
                'prices': [],
                'schedule_windows': [],
                'current_time': datetime.now().strftime('%H:%M')
            }

            # Process today's prices
            for price_data in today_prices:
                if 'starts_at' in price_data:
                    try:
                        price_time = datetime.fromisoformat(price_data['starts_at'].replace('Z', '+00:00'))
                        if price_time.tzinfo:
                            price_time = price_time.replace(tzinfo=None)

                        price_value = float(price_data.get('total', 0))
                        all_prices.append({
                            'time': price_time,
                            'price': price_value
                        })

                        chart_data['labels'].append(price_time.strftime('%H:%M'))
                        chart_data['prices'].append(round(price_value, 3))
                    except Exception:
                        continue

            # Process tomorrow's prices (limited to next 24 hours)
            for price_data in tomorrow_prices[:24]:  # Limit to next 24 hours
                if 'starts_at' in price_data:
                    try:
                        price_time = datetime.fromisoformat(price_data['starts_at'].replace('Z', '+00:00'))
                        if price_time.tzinfo:
                            price_time = price_time.replace(tzinfo=None)

                        price_value = float(price_data.get('total', 0))
                        all_prices.append({
                            'time': price_time,
                            'price': price_value
                        })

                        chart_data['labels'].append(price_time.strftime('%H:%M'))
                        chart_data['prices'].append(round(price_value, 3))
                    except Exception:
                        continue

            # Find optimal windows for visualization
            if all_prices:
                all_prices.sort(key=lambda x: x['time'])
                optimal_window = self._find_stable_optimal_period(
                    all_prices,
                    device_config.get('duration', 120),
                    device_config.get('search_length', 8)
                )

                if optimal_window:
                    chart_data['schedule_windows'].append({
                        'start': optimal_window['start_time'].strftime('%H:%M'),
                        'end': optimal_window['end_time'].strftime('%H:%M'),
                        'start_date': optimal_window['start_time'].strftime('%Y-%m-%d'),
                        'avg_price': round(optimal_window['avg_price'], 3),
                        'type': 'optimal'
                    })

            # Generate simple chart URL (using a simple chart service or base64 encoded SVG)
            chart_url = self._create_simple_chart_svg(chart_data)

            return {
                'chart_data': chart_data,
                'chart_url': chart_url,
                'schedule_windows': chart_data['schedule_windows']
            }

        except Exception as e:
            _LOGGER.error(f"Error generating chart data: {e}")
            return {}

    def _create_simple_chart_svg(self, chart_data: dict) -> str:
        """Create a simple SVG chart as base64 encoded data URL."""
        try:
            if not chart_data['prices']:
                return ""

            # SVG dimensions
            width, height = 400, 200
            margin = 40

            # Calculate scales
            max_price = max(chart_data['prices']) if chart_data['prices'] else 1
            min_price = min(chart_data['prices']) if chart_data['prices'] else 0
            price_range = max_price - min_price if max_price != min_price else 1

            # Start SVG
            svg_parts = [
                f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">',
                '<style>',
                '.price-line { fill: none; stroke: #2196F3; stroke-width: 2; }',
                '.schedule-bar { fill: rgba(255, 152, 0, 0.3); stroke: #FF9800; stroke-width: 1; }',
                '.axis { stroke: #666; stroke-width: 1; }',
                '.label { font-family: Arial; font-size: 10px; fill: #333; }',
                '</style>',

                # Draw axes
                f'<line x1="{margin}" y1="{height-margin}" x2="{width-margin}" y2="{height-margin}" class="axis"/>',
                f'<line x1="{margin}" y1="{margin}" x2="{margin}" y2="{height-margin}" class="axis"/>',
            ]

            # Draw price line
            if len(chart_data['prices']) > 1:
                chart_width = width - 2 * margin
                chart_height = height - 2 * margin

                points = []
                for i, price in enumerate(chart_data['prices']):
                    x = margin + (i * chart_width / (len(chart_data['prices']) - 1))
                    y = height - margin - ((price - min_price) / price_range * chart_height)
                    points.append(f"{x},{y}")

                svg_parts.append(f'<polyline points="{" ".join(points)}" class="price-line"/>')

                # Draw schedule windows
                for window in chart_data.get('schedule_windows', []):
                    try:
                        start_time = datetime.strptime(window['start'], '%H:%M').time()
                        end_time = datetime.strptime(window['end'], '%H:%M').time()

                        # Find approximate positions (simplified)
                        for i, label in enumerate(chart_data['labels']):
                            label_time = datetime.strptime(label, '%H:%M').time()
                            if label_time <= start_time <= label_time or i == 0:
                                start_x = margin + (i * chart_width / (len(chart_data['prices']) - 1))
                                break

                        for i, label in enumerate(chart_data['labels']):
                            label_time = datetime.strptime(label, '%H:%M').time()
                            if label_time >= end_time:
                                end_x = margin + (i * chart_width / (len(chart_data['prices']) - 1))
                                break
                        else:
                            end_x = width - margin

                        # Draw schedule window
                        svg_parts.append(
                            f'<rect x="{start_x}" y="{margin}" '
                            f'width="{end_x - start_x}" height="{chart_height}" '
                            f'class="schedule-bar"/>'
                        )

                        # Add label
                        svg_parts.append(
                            f'<text x="{(start_x + end_x) / 2}" y="{margin - 5}" '
                            f'text-anchor="middle" class="label">{window["start"]}-{window["end"]}</text>'
                        )
                    except Exception:
                        continue

            # Add price labels
            svg_parts.append(f'<text x="5" y="{margin}" class="label">{max_price:.2f}€</text>')
            svg_parts.append(f'<text x="5" y="{height-margin+15}" class="label">{min_price:.2f}€</text>')

            svg_parts.append('</svg>')

            # Convert to base64 data URL
            svg_content = ''.join(svg_parts)
            encoded_svg = base64.b64encode(svg_content.encode('utf-8')).decode('utf-8')
            return f"data:image/svg+xml;base64,{encoded_svg}"

        except Exception as e:
            _LOGGER.error(f"Error creating chart SVG: {e}")
            return ""

    def _get_device_status(self, device_state: dict, device_config: dict) -> str:
        """Get human-readable device status."""
        try:
            if not device_config.get('enabled', True):
                return "Scheduler disabled"

            state = device_state.get('state', 'idle')

            if device_state.get('manual_override_until'):
                override_until = device_state['manual_override_until']
                if datetime.now() < override_until:
                    return f"Manual override until {override_until.strftime('%H:%M')}"

            if device_state.get('device_running'):
                started_time = device_state.get('started_time')
                if started_time:
                    runtime = (datetime.now() - started_time).total_seconds() / 60
                    return f"Running ({runtime:.0f} min)"
                return "Running"

            if device_state.get('waiting_for_cheap_price'):
                return "Cut off - waiting for lower price"

            if device_state.get('program_detected'):
                return "Program detected - checking price"

            if state == 'cut_off':
                return "Cut off - price too high"

            # Check current conditions
            try:
                tibber_state = self.hass.states.get(self._coordinator.tibber_sensor)
                if tibber_state:
                    current_price = float(tibber_state.state)
                    threshold = device_config.get('price_threshold', 0.30)

                    if current_price <= threshold:
                        return f"Ready to start (price: {current_price:.3f}€)"
                    else:
                        return f"Waiting (price too high: {current_price:.3f}€)"
            except (ValueError, TypeError):
                pass

            return "Idle - waiting for conditions"

        except Exception as e:
            _LOGGER.error(f"Error getting device status: {e}")
            return "Unknown"

    async def async_turn_on(self, **kwargs):
        """Enable the scheduler."""
        try:
            _LOGGER.info(f"Enabling scheduler for {self._device_name}")
            device_config = self._coordinator.devices.get(self._device_name, {})
            device_config['enabled'] = True
            await self._coordinator.async_save_devices()

            # Initialize device state if missing
            if self._device_name not in self._coordinator.device_states:
                self._coordinator._init_device_state(self._device_name)

            device_state = self._coordinator.device_states[self._device_name]
            device_state['scheduler_enabled'] = True

            # Clear cache to force recalculation
            self._last_calculation = None
            self._last_schedule_calculation = None

            self.async_write_ha_state()

        except Exception as e:
            _LOGGER.error(f"Error turning on {self._device_name}: {e}")

    async def async_turn_off(self, **kwargs):
        """Disable the scheduler."""
        try:
            _LOGGER.info(f"Disabling scheduler for {self._device_name}")
            device_config = self._coordinator.devices.get(self._device_name, {})
            device_config['enabled'] = False
            await self._coordinator.async_save_devices()

            # Turn off controlled entities if they're running
            entities = device_config.get('entities', [])
            if entities:
                try:
                    await self._coordinator._turn_off_entities(entities)
                except Exception as e:
                    _LOGGER.error(f"Error turning off entities: {e}")

            # Clear device state
            if self._device_name in self._coordinator.device_states:
                device_state = self._coordinator.device_states[self._device_name]
                device_state['device_running'] = False
                device_state['waiting_for_cheap_price'] = False
                device_state['state'] = 'idle'
                device_state['program_detected'] = False
                device_state['scheduler_enabled'] = False

            self.async_write_ha_state()

        except Exception as e:
            _LOGGER.error(f"Error turning off {self._device_name}: {e}")


class TibberDevicePowerSwitch(SwitchEntity):
    """Switch to directly control device power on/off."""

    def __init__(self, coordinator, device_name: str):
        """Initialize the device power switch."""
        self._coordinator = coordinator
        self._device_name = device_name
        self._attr_name = f"{device_name.replace('_', ' ').title()} Power"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{device_name}_power"
        self._attr_icon = "mdi:power"
        self._attr_entity_category = "config"

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
    def is_on(self) -> bool:
        """Return true if the device is running."""
        device_state = self._coordinator.device_states.get(self._device_name, {})
        return device_state.get('device_running', False)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        try:
            device_exists = self._device_name in self._coordinator.devices
            # Initialize device state if missing
            if device_exists and self._device_name not in self._coordinator.device_states:
                self._coordinator._init_device_state(self._device_name)
            return device_exists
        except Exception as e:
            _LOGGER.error(f"Error checking availability for power switch {self._device_name}: {e}")
            return False

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return device power attributes."""
        device_config = self._coordinator.devices.get(self._device_name, {})
        device_state = self._coordinator.device_states.get(self._device_name, {})

        return {
            'controlled_entities': device_config.get('entities', []),
            'last_power_reading': device_state.get('last_power_reading', 0),
            'power_sensor': device_config.get('power_sensor', 'none'),
            'started_time': device_state.get('started_time'),
            'manual_control': True,
        }

    async def async_turn_on(self, **kwargs):
        """Turn on the device manually."""
        try:
            _LOGGER.info(f"Manually turning on device {self._device_name}")
            device_config = self._coordinator.devices.get(self._device_name, {})
            entities = device_config.get('entities', [])

            if entities:
                await self._coordinator._turn_on_entities(entities)

                # Update device state
                current_time = datetime.now()
                program_id = f"{self._device_name}_{current_time.strftime('%Y%m%d_%H%M%S')}_manual"

                device_state = self._coordinator.device_states.get(self._device_name, {})
                device_state['device_running'] = True
                device_state['started_time'] = current_time
                device_state['actual_start_time'] = current_time
                device_state['state'] = 'manual_run'
                device_state['manual_override_until'] = current_time + timedelta(hours=1)
                device_state['program_id'] = program_id
                device_state['programmed_time'] = current_time
                device_state['estimated_duration'] = device_config.get('duration', 120)
                device_state['runs_today'] = device_state.get('runs_today', 0) + 1

            self.async_write_ha_state()

        except Exception as e:
            _LOGGER.error(f"Error manually turning on {self._device_name}: {e}")

    async def async_turn_off(self, **kwargs):
        """Turn off the device manually."""
        try:
            _LOGGER.info(f"Manually turning off device {self._device_name}")
            device_config = self._coordinator.devices.get(self._device_name, {})
            entities = device_config.get('entities', [])

            if entities:
                await self._coordinator._turn_off_entities(entities)

                # Record completion if there was a program running
                device_state = self._coordinator.device_states.get(self._device_name, {})
                if device_state.get('program_id'):
                    await self._coordinator._record_program_completion(self._device_name)

                # Update device state
                device_state['device_running'] = False
                device_state['started_time'] = None
                device_state['state'] = 'idle'
                device_state['manual_override_until'] = None
                device_state['program_id'] = None

            self.async_write_ha_state()

        except Exception as e:
            _LOGGER.error(f"Error manually turning off {self._device_name}: {e}")


class TibberAutomaticModeSwitch(SwitchEntity):
    """Switch to toggle automatic/manual mode."""

    def __init__(self, coordinator, device_name: str):
        """Initialize the automatic mode switch."""
        self._coordinator = coordinator
        self._device_name = device_name
        self._attr_name = f"{device_name.replace('_', ' ').title()} Automatic Mode"
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{device_name}_auto_mode"
        self._attr_icon = "mdi:robot"
        self._attr_entity_category = "config"

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
    def is_on(self) -> bool:
        """Return true if automatic mode is enabled."""
        device_state = self._coordinator.device_states.get(self._device_name, {})
        return device_state.get('scheduler_enabled', True)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        try:
            device_exists = self._device_name in self._coordinator.devices
            # Initialize device state if missing
            if device_exists and self._device_name not in self._coordinator.device_states:
                self._coordinator._init_device_state(self._device_name)
            return device_exists
        except Exception as e:
            _LOGGER.error(f"Error checking availability for auto mode switch {self._device_name}: {e}")
            return False

    @property
    def icon(self) -> str:
        """Return dynamic icon."""
        if self.is_on:
            return "mdi:robot"
        else:
            return "mdi:robot-off"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return automatic mode attributes."""
        device_config = self._coordinator.devices.get(self._device_name, {})
        device_state = self._coordinator.device_states.get(self._device_name, {})

        return {
            'device_mode': device_config.get('device_mode', 'smart_delay'),
            'scheduler_enabled': device_state.get('scheduler_enabled', True),
            'waiting_for_cheap_price': device_state.get('waiting_for_cheap_price', False),
            'program_detected': device_state.get('program_detected', False),
            'manual_override_until': device_state.get('manual_override_until'),
        }

    async def async_turn_on(self, **kwargs):
        """Enable automatic mode."""
        try:
            _LOGGER.info(f"Enabling automatic mode for {self._device_name}")

            if self._device_name not in self._coordinator.device_states:
                self._coordinator._init_device_state(self._device_name)

            device_state = self._coordinator.device_states[self._device_name]
            device_state['scheduler_enabled'] = True
            device_state['manual_override_until'] = None

            self.async_write_ha_state()

        except Exception as e:
            _LOGGER.error(f"Error enabling automatic mode for {self._device_name}: {e}")

    async def async_turn_off(self, **kwargs):
        """Disable automatic mode (enable manual mode)."""
        try:
            _LOGGER.info(f"Disabling automatic mode for {self._device_name}")

            if self._device_name not in self._coordinator.device_states:
                self._coordinator._init_device_state(self._device_name)

            device_state = self._coordinator.device_states[self._device_name]
            device_state['scheduler_enabled'] = False
            device_state['waiting_for_cheap_price'] = False
            device_state['program_detected'] = False

            self.async_write_ha_state()

        except Exception as e:
            _LOGGER.error(f"Error disabling automatic mode for {self._device_name}: {e}")