
import json
import os
import platform
import logging
from typing import Dict, Any, Optional, List

# Setup logger for this module
logger = logging.getLogger(__name__)

# --- Platform-Specific Default Cache Paths ---
def get_default_cache_path() -> str:
    """Determines the default Mullvad cache path based on the OS."""
    system = platform.system()
    if system == "Darwin":  # macOS
        return "/Library/Caches/mullvad-vpn/relays.json"
    elif system == "Windows":
        # Common paths, might vary slightly based on installation type
        program_data = os.environ.get("PROGRAMDATA", "C:\\ProgramData")
        path1 = os.path.join(program_data, "Mullvad VPN", "cache", "relays.json")
        # Older path?
        path2 = os.path.join(os.path.expanduser("~"), "AppData", "Local", "Mullvad VPN", "cache", "relays.json")
        if os.path.exists(path1):
            return path1
        else:
             # Fallback or default assumption if ProgramData path doesn't exist
            return path2
    elif system == "Linux":
        # Common paths for Linux
        path1 = "/var/cache/mullvad-vpn/relays.json"
        path2 = os.path.expanduser("~/.cache/mullvad-vpn/relays.json")
        if os.path.exists(path1): # Prefer system-wide cache if it exists
            return path1
        else:
            return path2 # User-specific cache
    else:
        logger.warning(f"Unsupported operating system: {system}. Returning generic path.")
        return "mullvad_relays.json" # Fallback path

CONFIG_DIR = os.path.expanduser("~/.config/mullvad-finder") # Store config in .config subdir
CONFIG_PATH = os.path.join(CONFIG_DIR, "mullvad_finder_config.json")
LOG_PATH = os.path.expanduser("~/mullvad_finder.log") # Log file in home directory

DEFAULT_CONFIG: Dict[str, Any] = {
    "favorite_servers": [],
    "last_country": "",
    "last_protocol": "wireguard",
    "ping_count": 3, # Reduced default for faster initial tests
    "max_workers": 15, # Increased default
    "cache_path": get_default_cache_path(), # Platform-specific default
    "custom_cache_path": "",
    "auto_connect_fastest": False,
    "timeout_seconds": 15, # Increased default timeout
    "theme_mode": "system",  # system, light, dark
    "color_latency": True,
    "color_speed": True,
    "speed_test_size": 5,  # MB
    "default_sort_column": "latency",
    "default_sort_order": "ascending",
    "test_type": "ping",  # ping, speed, both
    "alternating_row_colors": True
}

def load_config() -> Dict[str, Any]:
    """Load the user configuration from the config file."""
    # Ensure config directory exists
    os.makedirs(CONFIG_DIR, exist_ok=True)

    if os.path.exists(CONFIG_PATH):
        logger.info(f"Loading configuration from: {CONFIG_PATH}")
        try:
            with open(CONFIG_PATH, "r", encoding='utf-8') as f:
                config = json.load(f)
            # Merge with default config to ensure all keys exist and add new defaults
            loaded_config = DEFAULT_CONFIG.copy()
            loaded_config.update(config) # Overwrite defaults with loaded values
            # Ensure cache_path is updated if default logic changed but custom isn't set
            if not loaded_config.get("custom_cache_path"):
                loaded_config["cache_path"] = get_default_cache_path()
            return loaded_config
        except json.JSONDecodeError:
            logger.exception(f"Error decoding JSON from config file: {CONFIG_PATH}. Using defaults.")
        except Exception as e:
            logger.exception(f"Error loading config file {CONFIG_PATH}: {e}. Using defaults.")
    else:
        logger.info(f"Config file not found at {CONFIG_PATH}. Creating with defaults.")
        save_config(DEFAULT_CONFIG.copy()) # Save defaults if file doesn't exist

    return DEFAULT_CONFIG.copy()

def save_config(config: Dict[str, Any]) -> bool:
    """Save the user configuration to the config file."""
    # Ensure config directory exists
    os.makedirs(CONFIG_DIR, exist_ok=True)
    try:
        logger.info(f"Saving configuration to: {CONFIG_PATH}")
        with open(CONFIG_PATH, "w", encoding='utf-8') as f:
            json.dump(config, f, indent=2)
        return True
    except Exception as e:
        logger.exception(f"Error saving config file {CONFIG_PATH}: {e}")
        return False

def add_favorite_server(config: Dict[str, Any], server: Dict[str, Any]) -> bool:
    """Add a server to the list of favorite servers."""
    server_info = {
        "hostname": server.get("hostname"),
        "country_code": server.get("country_code"),
        "city_code": server.get("city_code"),
        "country": server.get("country"),
        "city": server.get("city")
    }

    if not server_info["hostname"]:
        logger.warning("Attempted to add favorite server with no hostname.")
        return False

    # Check if the server is already in favorites
    favorites = config.setdefault("favorite_servers", [])
    for favorite in favorites:
        if favorite.get("hostname") == server_info["hostname"]:
            logger.info(f"Server {server_info['hostname']} is already a favorite.")
            return False  # Already a favorite

    # Add to favorites
    logger.info(f"Adding server {server_info['hostname']} to favorites.")
    favorites.append(server_info)
    return save_config(config) # Save after modification

def remove_favorite_server(config: Dict[str, Any], hostname: str) -> bool:
    """Remove a server from the list of favorite servers."""
    favorites: List[Dict[str, Any]] = config.get("favorite_servers", [])
    initial_count = len(favorites)

    # Remove the server with the matching hostname
    config["favorite_servers"] = [f for f in favorites if f.get("hostname") != hostname]

    # Save if there was a change
    if len(config["favorite_servers"]) != initial_count:
        logger.info(f"Removing server {hostname} from favorites.")
        return save_config(config)
    else:
        logger.warning(f"Attempted to remove non-favorite server: {hostname}")
        return False

def get_cache_path(config: Dict[str, Any]) -> str:
    """Get the path to the Mullvad cache file, prioritizing custom path."""
    custom_path = config.get("custom_cache_path")
    if custom_path and os.path.exists(custom_path):
        return custom_path
    elif custom_path:
        logger.warning(f"Custom cache path specified but not found: {custom_path}. Using default.")
    # Return default (which is already platform-aware)
    return config.get("cache_path", get_default_cache_path())

def get_log_path() -> str:
    """Get the path to the log file."""
    return LOG_PATH

