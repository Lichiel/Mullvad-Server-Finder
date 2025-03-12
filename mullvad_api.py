import subprocess
import json
import os

def load_cached_servers(cache_path="/Library/Caches/mullvad-vpn/relays.json"):
    """Load the cached Mullvad servers JSON from macOS."""
    try:
        with open(cache_path, "r") as f:
            data = json.load(f)
        return data
    except Exception as e:
        print(f"Error loading cached servers from {cache_path}: {e}")
        return None

def set_mullvad_location(country_code, city_code=None, hostname=None):
    """Set Mullvad location to the given country, city, and server."""
    cmd = ['mullvad', 'relay', 'set', 'location']
    
    # Add parameters as needed
    if country_code:
        cmd.append(country_code)
        if city_code:
            cmd.append(city_code)
            if hostname:
                cmd.append(hostname)
    
    print(f"Setting Mullvad location: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise Exception(f"Error setting location: {result.stderr}")
    
    return result.stdout

def set_mullvad_protocol(protocol):
    """Set Mullvad tunneling protocol (openvpn or wireguard)."""
    if protocol.lower() not in ["openvpn", "wireguard"]:
        raise ValueError("Protocol must be either 'openvpn' or 'wireguard'")
    
    cmd = ['mullvad', 'relay', 'set', 'tunnel-protocol', protocol.lower()]
    print(f"Setting Mullvad protocol: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise Exception(f"Error setting protocol: {result.stderr}")
    
    return result.stdout

def get_mullvad_status():
    """Get the current Mullvad connection status."""
    cmd = ['mullvad', 'status']
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise Exception(f"Error getting status: {result.stderr}")
    
    return result.stdout.strip()

def connect_mullvad():
    """Connect to Mullvad VPN."""
    cmd = ['mullvad', 'connect']
    print(f"Connecting to Mullvad: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise Exception(f"Error connecting to Mullvad: {result.stderr}")
    
    return result.stdout

def disconnect_mullvad():
    """Disconnect from Mullvad VPN."""
    cmd = ['mullvad', 'disconnect']
    print(f"Disconnecting from Mullvad: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        raise Exception(f"Error disconnecting from Mullvad: {result.stderr}")
    
    return result.stdout
