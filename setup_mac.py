"""
Setup script to create a macOS .app bundle for Mullvad Server Finder
"""

import os
import sys
from setuptools import setup

APP = ['main.py']
DATA_FILES = [
    ('', ['mullvad_icon.icns']),  # Include your icon file
    # Add any other data files your app needs
]
OPTIONS = {
    'argv_emulation': True,
    'iconfile': 'mullvad_icon.icns',
    'plist': {
        'CFBundleName': 'Mullvad Server Finder',
        'CFBundleDisplayName': 'Mullvad Server Finder',
        'CFBundleIdentifier': 'com.yourusername.mullvadserverfinder',
        'CFBundleVersion': '1.1.0',
        'CFBundleShortVersionString': '1.0.0',
        'NSHumanReadableCopyright': '© 2025 Your Name',
        'NSHighResolutionCapable': True,
    },
    'packages': ['tkinter', 'ttkthemes'],  # Include required packages
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)