import json
import os

CONFIG_PATH = os.path.expanduser("~/mullvad_finder_config.json")

DEFAULT_CONFIG = {
    "favorite_servers": [],
    "last_country": "",
    "last_protocol": "wireguard",
    "ping_count": 4,
    "max_workers": 10,
    "cache_path": "/Library/Caches/mullvad-vpn/relays.json",
    "custom_cache_path": "",
    "auto_connect_fastest": False,
    "timeout_seconds": 10,
    "theme_mode": "system",  # system, light, dark
    "color_latency": True,
    "color_speed": True,
    "speed_test_size": 10,  # MB
    "default_sort_column": "latency",
    "default_sort_order": "ascending",
    "test_type": "ping",  # ping, speed, both
    "alternating_row_colors": True
}

def load_config():
    """Load the user configuration from the config file."""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                config = json.load(f)
            # Merge with default config to ensure all keys exist
            for key, value in DEFAULT_CONFIG.items():
                if key not in config:
                    config[key] = value
            return config
        except Exception as e:
            print(f"Error loading config: {e}")
    
    # If the file doesn't exist or there was an error, return the default config
    return DEFAULT_CONFIG.copy()

def save_config(config):
    """Save the user configuration to the config file."""
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving config: {e}")
        return False

def add_favorite_server(config, server):
    """Add a server to the list of favorite servers."""
    server_info = {
        "hostname": server.get("hostname"),
        "country_code": server.get("country_code"),
        "city_code": server.get("city_code"),
        "country": server.get("country"),
        "city": server.get("city")
    }
    
    # Check if the server is already in favorites
    for favorite in config.get("favorite_servers", []):
        if favorite.get("hostname") == server_info["hostname"]:
            return False  # Already a favorite
    
    # Add to favorites
    config["favorite_servers"].append(server_info)
    save_config(config)
    return True

def remove_favorite_server(config, hostname):
    """Remove a server from the list of favorite servers."""
    favorites = config.get("favorite_servers", [])
    initial_count = len(favorites)
    
    # Remove the server with the matching hostname
    config["favorite_servers"] = [f for f in favorites if f.get("hostname") != hostname]
    
    # Save if there was a change
    if len(config["favorite_servers"]) != initial_count:
        save_config(config)
        return True
    
    return False

def get_cache_path(config):
    """Get the path to the Mullvad cache file."""
    # Use custom path if specified, otherwise use default
    if config.get("custom_cache_path"):
        return config["custom_cache_path"]
    return config["cache_path"]
