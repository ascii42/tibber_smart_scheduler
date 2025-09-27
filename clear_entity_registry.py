#!/usr/bin/env python3
"""
Entity Registry Cleanup Script
Run this to remove old cached entities and force re-registration.
"""

import json
import os

def clean_entity_registry():
    """Clean entity registry of old tibber_smart_scheduler entities."""

    registry_path = "/config/.storage/core.entity_registry"
    backup_path = "/config/.storage/core.entity_registry.backup"

    print("🧹 Cleaning entity registry...")

    if not os.path.exists(registry_path):
        print("❌ Entity registry not found. This might be running outside HA.")
        return False

    try:
        # Backup the registry
        with open(registry_path, 'r') as f:
            registry = json.load(f)

        with open(backup_path, 'w') as f:
            json.dump(registry, f, indent=2)

        print(f"✅ Backed up registry to {backup_path}")

        # Remove tibber_smart_scheduler entities
        entities_before = len(registry.get('entities', []))

        if 'entities' in registry:
            registry['entities'] = [
                entity for entity in registry['entities']
                if not entity.get('platform') == 'tibber_smart_scheduler'
            ]

        entities_after = len(registry.get('entities', []))
        removed_count = entities_before - entities_after

        # Write back the cleaned registry
        with open(registry_path, 'w') as f:
            json.dump(registry, f, indent=2)

        print(f"✅ Removed {removed_count} tibber_smart_scheduler entities")
        print("⚠️  RESTART Home Assistant to apply changes!")

        return True

    except Exception as e:
        print(f"❌ Error cleaning registry: {e}")
        return False

if __name__ == "__main__":
    clean_entity_registry()