#!/usr/bin/env python3
"""
Home Assistant Cache Clearing Script for Tibber Smart Scheduler
Run this script to force Home Assistant to reload the integration completely.
"""

import os
import shutil
import sys

def clear_ha_cache():
    """Clear Home Assistant cache files and force integration reload."""

    # Common Home Assistant cache paths
    cache_paths = [
        "/config/.storage",  # Entity registry and other storage
        "/config/custom_components/__pycache__",
        "/config/deps/__pycache__",
        "/tmp/__pycache__",
        # Add more paths if needed
    ]

    integration_name = "tibber_smart_scheduler"

    print("🧹 Clearing Home Assistant cache for Tibber Smart Scheduler...")

    # Remove Python cache files
    current_dir = os.path.dirname(os.path.abspath(__file__))
    pycache_dir = os.path.join(current_dir, "__pycache__")

    if os.path.exists(pycache_dir):
        try:
            shutil.rmtree(pycache_dir)
            print(f"✅ Removed {pycache_dir}")
        except Exception as e:
            print(f"⚠️ Could not remove {pycache_dir}: {e}")

    # Remove .pyc files
    for root, dirs, files in os.walk(current_dir):
        for file in files:
            if file.endswith('.pyc'):
                try:
                    os.remove(os.path.join(root, file))
                    print(f"✅ Removed {file}")
                except Exception as e:
                    print(f"⚠️ Could not remove {file}: {e}")

    print("\n📋 Next steps:")
    print("1. Restart Home Assistant completely")
    print("2. Go to Settings > Devices & Services")
    print("3. Find 'Tibber Smart Scheduler' integration")
    print("4. Click the three dots (...) > Reload")
    print("5. If reload doesn't work, remove and re-add the integration")

    print(f"\n🆕 Integration version updated to 1.1.0")
    print("This should force Home Assistant to recognize the changes.")

if __name__ == "__main__":
    clear_ha_cache()