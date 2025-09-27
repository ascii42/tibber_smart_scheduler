# Tibber Smart Scheduler with nordpool_planner Features

This integration combines the best of both worlds:
- Advanced Tibber price-based scheduling
- nordpool_planner style monitoring and binary sensors
- Rich visualization and calendar integration
- Multiple device modes and advanced algorithms

## Entities Created

For each device, you get:

### Switch Entities
- `switch.tibber_scheduler_{device}` - Main scheduler control

### Binary Sensors (nordpool_planner style)
- `binary_sensor.tibber_{device}_low_cost` - Low cost period active
- `binary_sensor.tibber_{device}_high_cost` - High cost period active  
- `binary_sensor.tibber_{device}_optimal_start` - Optimal start time

### Sensors (Visualization)
- `sensor.tibber_{device}_next_optimal` - Next optimal time info
- `sensor.tibber_{device}_cost_comparison` - Cost rate comparison
- `sensor.tibber_{device}_schedule_overview` - Schedule status

### Calendar
- `calendar.tibber_schedule_{device}` - Scheduled time slots visualization

## Key Features

✅ **nordpool_planner Compatibility**: Binary sensors with `now_cost_rate`, `best_average`, `hours_to_optimal`
✅ **Advanced Time Slots**: Predefined slots, coherent vs split ranges  
✅ **Visualization**: Calendar integration, dashboard cards, cost charts
✅ **Multiple Modes**: Active scheduler, Smart delay, Price protection, Hybrid
✅ **Power Filtering**: Load management and consumption limits
✅ **Rich Monitoring**: Like nordpool_planner but enhanced

## Usage Examples

See the dashboard configuration for complete examples.
