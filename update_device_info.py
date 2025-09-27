import re

# Read switch.py
with open('switch.py', 'r') as f:
    content = f.read()

# New device_info that should work with brands system
new_device_info = '''    @property
    def device_info(self):
        """Device info that uses Tibber brand from Home Assistant brands."""
        return {
            "identifiers": {(DOMAIN, f"tibber_scheduler_{self._device_name}")},
            "name": f"Tibber {self._device_name.replace('_', ' ').title()}",
            "manufacturer": "Tibber",
            "model": "Smart Energy Scheduler",
            "sw_version": "5.4.0",
            "configuration_url": "https://app.tibber.com/",
        }'''

# Replace all device_info methods in both switch classes
content = re.sub(
    r'    @property\s+def device_info\(self\):.*?return \{[^}]*\}',
    new_device_info,
    content,
    flags=re.DOTALL
)

# Write back
with open('switch.py', 'w') as f:
    f.write(content)

print("Updated device_info methods to use Tibber brand")
