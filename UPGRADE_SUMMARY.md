# Tibber Smart Scheduler - Upgrade Summary

## Fixes Applied (September 26, 2025)

### 🔧 Issues Fixed

1. **Next Stop Functionality** ✅
   - Fixed missing `next_stop` attribute in switch entity
   - Added proper `next_stop_date` and timing calculations
   - Shows actual stop time when device is running
   - Shows scheduled stop time for upcoming starts

2. **Stable Next Start Timing** ✅ **NEW**
   - Fixed next_start moving every minute issue
   - Implemented 1-hour caching for stable scheduling
   - Schedule locks in and only updates countdown timers
   - Hour-boundary alignment for consistent windows

3. **Automatic Device Turn-On** ✅
   - Enhanced automatic scheduling logic in coordinator
   - Improved optimal window detection and execution
   - Better handling of cheap window periods
   - Fixed device state tracking during automatic starts

4. **Enhanced Switch Controls** ✅
   - **Main Scheduler Switch**: Controls the scheduling functionality
   - **Device Power Switch**: Direct manual on/off control of devices
   - **Automatic Mode Switch**: Toggle between automatic and manual modes

5. **Price Chart Visualization** ✅ **NEW**
   - Interactive SVG charts showing price vs schedule windows
   - Base64-encoded charts available as entity attributes
   - Visual representation of optimal scheduling periods
   - Customizable chart with current time indicators

### 🆕 New Features

#### Three Switch Types Per Device
For each configured device (e.g., "dishwasher"), you now get:

1. **`switch.tibber_scheduler_dishwasher`** - Main scheduler control
   - Shows comprehensive scheduling status
   - Displays next_start and next_stop times
   - Controls whether scheduling is active

2. **`switch.dishwasher_power`** - Direct device control
   - Manual on/off control of the actual device
   - Bypasses scheduling logic
   - Shows device running status

3. **`switch.dishwasher_automatic_mode`** - Automation toggle
   - Enable/disable automatic scheduling
   - When off, device runs in manual mode only
   - Preserves manual overrides

#### Enhanced Attributes
The main scheduler switch now provides:
- `next_start`: Time when device will next start (e.g., "14:30") - **STABLE**
- `next_stop`: Time when device will next stop (e.g., "16:30") - **STABLE**
- `next_start_date` / `next_stop_date`: Dates for start/stop
- `minutes_until_start` / `minutes_until_stop`: Live countdown timers
- `window_status`: Human-readable scheduling status
- `optimal_avg_price`: Average price during optimal window
- `scheduler_enabled`: Whether automatic mode is active
- `schedule_locked`: Whether schedule is cached and stable

#### Chart Visualization Attributes **NEW**
- `price_chart_url`: Base64-encoded SVG chart as data URL
- `price_chart_data`: Raw chart data (prices, labels, timestamps)
- `schedule_windows`: List of optimal scheduling windows with times and prices

### 🗂️ File Organization

#### Moved to Archive
The following maintenance and debug files were moved to `archive/` directory:
- All `apply_*.py` and `fix*.sh` scripts
- Test files (`test_*.py`, `test_*.sh`)
- Debug utilities (`debug.sh`, `diagnose.py`)
- Backup files (`*.bck`, `*.backup`, `*.save`)
- Patch files (`*_patch.py`, `*_fix.py`)

#### Core Files Remain
- `__init__.py` - Main coordinator logic
- `switch.py` - Enhanced switch entities (completely rewritten)
- `sensor.py` - Sensor entities
- `config_flow.py` - Configuration flow
- `const.py` - Constants
- `manifest.json` - Integration manifest

### 🔄 Usage Examples

#### Dashboard Cards
```yaml
# Main scheduler status
type: entity
entity: switch.tibber_scheduler_dishwasher
name: "Dishwasher Scheduler"
attribute: next_start

# Next stop time
type: entity
entity: switch.tibber_scheduler_dishwasher
name: "Next Stop"
attribute: next_stop

# Manual device control
type: entity
entity: switch.dishwasher_power
name: "Dishwasher Power"

# Automation toggle
type: entity
entity: switch.dishwasher_automatic_mode
name: "Auto Mode"

# Price chart visualization **NEW**
type: picture
image: "{{ state_attr('switch.tibber_scheduler_dishwasher', 'price_chart_url') }}"
title: "Price Chart & Schedule"
tap_action:
  action: more-info
  entity: switch.tibber_scheduler_dishwasher
```

#### Automations
```yaml
# Alert when device starts automatically
- alias: "Dishwasher Auto Start Alert"
  trigger:
    platform: state
    entity_id: switch.dishwasher_power
    from: "off"
    to: "on"
  condition:
    condition: state
    entity_id: switch.dishwasher_automatic_mode
    state: "on"
  action:
    service: notify.mobile_app
    data:
      message: "Dishwasher started automatically at {{ states('sensor.tibber_current_price') }}€/kWh"

# Manual override when price is very low
- alias: "Force Start on Very Low Price"
  trigger:
    platform: numeric_state
    entity_id: sensor.tibber_current_price
    below: 0.10
  action:
    service: switch.turn_on
    entity_id: switch.dishwasher_power
```

### 🧪 Testing

To test the new functionality:

1. **Check Entity Creation**:
   ```bash
   # View all new entities
   ha entity list | grep tibber_scheduler
   ha entity list | grep "_power"
   ha entity list | grep "_automatic_mode"
   ```

2. **Test Switch Functionality**:
   - Toggle main scheduler on/off
   - Use power switch for manual control
   - Toggle automatic mode

3. **Verify Stable Timing**:
   ```bash
   # Check stable next_start/next_stop attributes
   ha state get switch.tibber_scheduler_dishwasher
   # Note: next_start should NOT change every minute
   ```

4. **Test Chart Visualization**:
   ```bash
   # Check chart attributes exist
   ha state get switch.tibber_scheduler_dishwasher | grep price_chart
   # Open demo chart
   firefox demo_chart.html
   ```

### 🔍 Troubleshooting

#### Common Issues
1. **"Entity not found"** - Restart Home Assistant after changes
2. **"No next_stop shown"** - Check Tibber sensor has price data
3. **"Automatic start not working"** - Verify automatic mode switch is ON
4. **"Next start keeps changing"** - Fixed! Should now be stable for 1 hour
5. **"Chart not showing"** - Check price_chart_url attribute exists and has data
6. **"Schedule not locked"** - Check schedule_locked attribute is true

#### Debug Information
- All switches log their actions with INFO level
- Check Home Assistant logs for "Tibber Scheduler" entries
- Use `diagnose.py` in archive/ for detailed debugging

### 📈 Performance Improvements

- **Stable Schedule Caching**: 1-hour cache for schedule stability (fixes minute-by-minute changes)
- **Attribute Caching**: General attributes cached for 15 minutes
- **Smart Timer Updates**: Only countdown timers update, schedule stays stable
- **Reduced API Calls**: Efficient price data parsing
- **Better Error Handling**: Graceful degradation when sensors unavailable
- **Chart Generation**: SVG charts cached and generated efficiently

### 🔄 Migration Notes

**No configuration changes required** - existing device configurations are preserved.

New switches will automatically appear for all configured devices after restart.