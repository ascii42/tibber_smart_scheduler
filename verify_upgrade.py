#!/usr/bin/env python3
"""Verify Tibber Smart Scheduler upgrade was successful."""

import os
import sys
from pathlib import Path

def check_file_exists(file_path, description):
    """Check if a file exists and report status."""
    if os.path.exists(file_path):
        print(f"✅ {description}: {file_path}")
        return True
    else:
        print(f"❌ {description}: {file_path} (MISSING)")
        return False

def check_file_content(file_path, search_terms, description):
    """Check if file contains expected content."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        missing = []
        for term in search_terms:
            if term not in content:
                missing.append(term)

        if not missing:
            print(f"✅ {description}: All expected content found")
            return True
        else:
            print(f"❌ {description}: Missing content: {missing}")
            return False
    except Exception as e:
        print(f"❌ {description}: Error reading file: {e}")
        return False

def main():
    """Main verification function."""
    print("🔍 Verifying Tibber Smart Scheduler Upgrade...")
    print("=" * 50)

    base_path = Path(__file__).parent

    # Check core files exist
    core_files = [
        ("switch.py", "Enhanced switch file"),
        ("__init__.py", "Main coordinator"),
        ("sensor.py", "Sensor entities"),
        ("manifest.json", "Integration manifest"),
        ("const.py", "Constants"),
    ]

    files_ok = True
    for file_name, description in core_files:
        if not check_file_exists(base_path / file_name, description):
            files_ok = False

    # Check archive directory exists
    archive_path = base_path / "archive"
    if not check_file_exists(archive_path, "Archive directory"):
        files_ok = False

    print("\n📁 File Organization:")
    print("-" * 30)

    # Check switch.py content
    switch_content_checks = [
        "TibberSchedulerSwitch",
        "TibberDevicePowerSwitch",
        "TibberAutomaticModeSwitch",
        "next_start",
        "next_stop",
        "_get_stable_timing",
        "_generate_chart_data",
        "price_chart_url",
        "schedule_cache_duration",
    ]

    content_ok = check_file_content(
        base_path / "switch.py",
        switch_content_checks,
        "Switch.py enhanced functionality"
    )

    # Check archive has expected files
    if archive_path.exists():
        archive_files = list(archive_path.glob("*"))
        if len(archive_files) > 10:
            print(f"✅ Archive directory: {len(archive_files)} files moved")
        else:
            print(f"⚠️  Archive directory: Only {len(archive_files)} files (expected 30+)")

    # Check upgrade summary exists
    summary_ok = check_file_exists(base_path / "UPGRADE_SUMMARY.md", "Upgrade summary")

    print("\n📊 Verification Summary:")
    print("-" * 30)

    if files_ok and content_ok and summary_ok:
        print("🎉 UPGRADE SUCCESSFUL!")
        print("\nNext steps:")
        print("1. Restart Home Assistant")
        print("2. Check for new switch entities")
        print("3. Test stable next_start/next_stop timing")
        print("4. View price charts in switch attributes")
        print("5. Test chart visualization: open demo_chart.html")
        return 0
    else:
        print("❌ UPGRADE INCOMPLETE")
        print("\nIssues found - please review the errors above")
        return 1

if __name__ == "__main__":
    sys.exit(main())