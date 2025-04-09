
"""
Setup script to create a macOS .app bundle for Mullvad Server Finder using py2app.
"""

import os
import sys
from setuptools import setup

# --- Configuration ---
APP_NAME = "Mullvad Server Finder"
APP_VERSION = "1.1.0" # Keep consistent with setup.py
APP_SCRIPT = 'main.py'
ICON_FILE = 'mullvad_icon.icns' # Ensure this file exists

# Required packages to include in the bundle
# Add any other third-party packages your app uses
PACKAGES = ['tkinter', 'ttkthemes', 'requests', 'logging']

# Data files to include (icon, maybe default config if needed)
# Format: ('destination_folder_in_bundle', ['list_of_source_files'])
# Use '' for the main Resources folder inside the .app
DATA_FILES = []
if os.path.exists(ICON_FILE):
     DATA_FILES.append(('', [ICON_FILE]))
else:
     print(f"Warning: Icon file '{ICON_FILE}' not found.", file=sys.stderr)


# --- py2app Options ---
OPTIONS = {
    'argv_emulation': True, # Allows dropping files onto the app icon
    'packages': PACKAGES,
    'plist': {
        'CFBundleName': APP_NAME,
        'CFBundleDisplayName': APP_NAME,
        # Use reverse domain name notation for identifier
        'CFBundleIdentifier': 'com.yourdomain.mullvadserverfinder', # CHANGE THIS
        'CFBundleVersion': APP_VERSION,
        'CFBundleShortVersionString': APP_VERSION, # User-visible version
        'NSHumanReadableCopyright': f'© {__import__("datetime").date.today().year} Your Name', # CHANGE THIS
        'NSHighResolutionCapable': True, # Important for Retina displays
        # 'LSMinimumSystemVersion': '10.13', # Optional: Set minimum macOS version
    },
    # Include standard libs that py2app might miss
    'includes': ['tkinter.messagebox', 'tkinter.filedialog'],
}

# Add icon file to options if it exists
if os.path.exists(ICON_FILE):
     OPTIONS['iconfile'] = ICON_FILE


# --- Setup Call ---
setup(
    app=[APP_SCRIPT],
    name=APP_NAME,
    version=APP_VERSION,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)

# --- Build Instructions ---
# 1. Make sure py2app is installed: pip install py2app
# 2. Place mullvad_icon.icns in the same directory as this script.
# 3. Run from terminal in this directory: python setup_mac.py py2app
# 4. The .app bundle will be created in the 'dist' subdirectory.
# 5. Test the .app bundle thoroughly on macOS.