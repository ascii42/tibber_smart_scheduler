#!/usr/bin/env python3
"""Restart script for Tibber Smart Scheduler integration."""

import os
import sys
from datetime import datetime

def restart_integration():
    """Instructions to restart the Tibber Smart Scheduler integration."""

    print("🔄 Tibber Smart Scheduler Integration Restart Instructions")
    print("=" * 60)
    print()

    print("📋 STEP-BY-STEP RESTART PROCESS:")
    print()

    print("1. 🔌 Reload Integration in Home Assistant:")
    print("   - Go to Settings > Devices & Services")
    print("   - Find 'Tibber Smart Scheduler'")
    print("   - Click the 3-dots menu (⋮) > Reload")
    print()

    print("2. 🔍 Check Tibber Sensor Configuration:")
    print("   - The integration needs a proper Tibber price sensor")
    print("   - The sensor should have 'today' and 'tomorrow' price attributes")
    print("   - Common Tibber sensor names:")
    print("     • sensor.electricity_price_[location]")
    print("     • sensor.tibber_price_[home_name]")
    print("     • sensor.tibber_current_price")
    print()

    print("3. 🚨 If sensors still show 'unknown' or 'No optimal window found':")
    print("   - Check if your Tibber sensor exists: Developer Tools > States")
    print("   - Look for sensors starting with 'sensor.tibber' or 'sensor.electricity'")
    print("   - The sensor should have attributes like 'today' and 'tomorrow'")
    print("   - If no such sensor exists, you may need to configure the Tibber integration first")
    print()

    print("4. 🎯 Alternative: Reconfigure Integration:")
    print("   - Go to Settings > Devices & Services")
    print("   - Find 'Tibber Smart Scheduler'")
    print("   - Click 'CONFIGURE' to select the correct Tibber sensor")
    print()

    print("5. 🔄 If problems persist, restart Home Assistant:")
    print("   - Settings > System > Restart")
    print()

    print("📊 DIAGNOSTIC INFORMATION:")
    print(f"   - Integration version: 1.2.1")
    print(f"   - Restart time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("   - Check the 'smart_delay_decision' sensor attributes for diagnostic info")
    print("   - Look for 'price_data_diagnostic' and 'tibber_sensor_entity' in sensor attributes")
    print()

    print("✅ The integration has been updated with better error handling and diagnostics.")
    print("   After restart, check your sensors for more detailed error messages.")

if __name__ == "__main__":
    restart_integration()