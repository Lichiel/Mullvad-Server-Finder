
from setuptools import setup, find_packages
import os

# Function to read the README file.
def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname), encoding='utf-8').read()

setup(
    name="mullvad-server-finder",
    version="1.1.0", # Updated version
    description="A GUI application to find the best Mullvad VPN server",
    long_description=read('README.md') if os.path.exists('README.md') else "",
    long_description_content_type="text/markdown",
    author="Your Name", # Replace with your name/handle
    author_email="your.email@example.com", # Replace with your email
    url="https://github.com/yourusername/mullvad-server-finder", # Optional: Link to your repository
    packages=find_packages(exclude=("tests",)), # Find packages automatically
    py_modules=["main", "gui", "mullvad_api", "server_manager", "config", "testing"], # Explicitly list modules if not in a package
    install_requires=[
        "ttkthemes>=3.2.2", # Optional but recommended for better themes
    ],
    entry_points={
        "gui_scripts": [ # Use gui_scripts for GUI apps
            "mullvad-finder = main:main",
        ],
        "console_scripts": [ # Keep console script for testing
             "mullvad-finder-test = testing:main",
        ]
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Win32 (MS Windows)",
        "Environment :: X11 Applications :: Tk", # Tkinter environment
        "Environment :: MacOS X :: Aqua",      # Tkinter on macOS uses Aqua
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License", # Choose your license
        "Operating System :: OS Independent", # Should run on Win, macOS, Linux
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7", # Specify minimum tested version
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Internet :: Proxy Servers",
        "Topic :: System :: Networking",
        "Topic :: Utilities",
        "Typing :: Typed", # Indicates type hints are used
    ],
    python_requires=">=3.7", # Set minimum Python version
    keywords="mullvad vpn tkinter gui network speedtest ping",
    project_urls={ # Optional: Add relevant links
        "Bug Tracker": "https://github.com/yourusername/mullvad-server-finder/issues",
        "Source Code": "https://github.com/yourusername/mullvad-server-finder",
    },
    # Add package_data if you have non-code files like icons within your package
    package_data={
         '': ['*.ico', '*.icns', '*.png'], # Example: include icons if they are part of the package
    },
    # include_package_data=True, # Use if MANIFEST.in is used
)

# --- Build Notes ---
# For Windows/Linux Executable (using PyInstaller):
# 1. Install PyInstaller: pip install pyinstaller
# 2. Navigate to the project directory in your terminal.
# 3. Run: pyinstaller --onefile --windowed --name MullvadFinder --icon=mullvad_icon.ico main.py
#    (Use --icon=mullvad_icon.png or .icns for other OS if needed)
#    (--windowed hides the console window)
#    (You might need to add --add-data "path/to/icon:." for icons)
# 4. The executable will be in the 'dist' folder.

# For macOS .app Bundle (using py2app):
# 1. Ensure setup_mac.py is configured correctly.
# 2. Install py2app: pip install py2app
# 3. Run: python setup_mac.py py2app -A (or just py2app)
# 4. The .app bundle will be in the 'dist' folder.
