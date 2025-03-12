#!/usr/bin/env python3
"""
This script provides a simple way to test components of Mullvad Server Finder
without running the full GUI application.
"""

import json
import time
import argparse
import os
from mullvad_api import load_cached_servers, get_mullvad_status, set_mullvad_location, connect_mullvad
from server_manager import ping_test, get_all_servers, get_servers_by_country, test_servers

def test_load_servers(cache_path=None):
    """Test loading the Mullvad server cache."""
    print(f"Loading servers from {cache_path or 'default path'}...")
    server_data = load_cached_servers(cache_path)
    
    if not server_data:
        print("❌ Failed to load server data.")
        return
    
    countries = server_data.get("countries", [])
    print(f"✅ Successfully loaded server data. Found {len(countries)} countries.")
    
    # Print some basic stats
    total_cities = sum(len(country.get("cities", [])) for country in countries)
    total_servers = sum(
        sum(len(city.get("relays", [])) for city in country.get("cities", []))
        for country in countries
    )
    
    print(f"Total countries: {len(countries)}")
    print(f"Total cities: {total_cities}")
    print(f"Total servers: {total_servers}")
    
    # Print the first country's details as an example
    if countries:
        first_country = countries[0]
        print("\nExample country data:")
        print(f"  Name: {first_country.get('name')}")
        print(f"  Code: {first_country.get('code')}")
        
        if first_country.get("cities"):
            first_city = first_country["cities"][0]
            print(f"  First city: {first_city.get('name')} ({first_city.get('code')})")
            
            if first_city.get("relays"):
                first_relay = first_city["relays"][0]
                print(f"  First server: {first_relay.get('hostname')}")
                print(f"  IPv4 address: {first_relay.get('ipv4_addr_in')}")
    
    return server_data

def test_ping(ip_address=None):
    """Test the ping functionality."""
    if not ip_address:
        print("No IP address provided, using 1.1.1.1 (Cloudflare DNS)...")
        ip_address = "1.1.1.1"
    
    print(f"Pinging {ip_address}...")
    start_time = time.time()
    latency = ping_test(ip_address)
    elapsed = time.time() - start_time
    
    if latency is None:
        print(f"❌ Failed to ping {ip_address}.")
    else:
        print(f"✅ Successfully pinged {ip_address}: {latency:.2f} ms (test took {elapsed:.2f} seconds)")
    
    return latency

def test_server_discovery(server_data=None, country_code=None, protocol=None):
    """Test the server discovery functionality."""
    if not server_data:
        server_data = load_cached_servers()
        if not server_data:
            print("❌ Failed to load server data.")
            return
    
    print("Testing server discovery...")
    
    if country_code:
        print(f"Filtering servers by country: {country_code}")
        servers = get_servers_by_country(server_data, country_code, protocol)
    else:
        print("Getting all servers")
        servers = get_all_servers(server_data, protocol)
    
    if protocol:
        print(f"Filtering by protocol: {protocol}")
    
    print(f"✅ Found {len(servers)} servers")
    
    # Print a few example servers
    if servers:
        print("\nExample servers:")
        for i, server in enumerate(servers[:3]):
            print(f"  Server {i+1}: {server.get('hostname')} - {server.get('country')} / {server.get('city')}")
    
    return servers

def test_multiple_pings(servers, max_servers=5):
    """Test pinging multiple servers."""
    if not servers:
        print("No servers to ping.")
        return
    
    # Limit the number of servers to test
    servers_to_test = servers[:max_servers]
    print(f"Testing ping for {len(servers_to_test)} servers...")
    
    results = []
    for i, server in enumerate(servers_to_test):
        hostname = server.get("hostname", f"Server {i+1}")
        ip_address = server.get("ipv4_addr_in")
        
        if not ip_address:
            print(f"❌ No IP address for {hostname}, skipping...")
            continue
        
        print(f"Pinging {hostname} ({ip_address})...")
        latency = ping_test(ip_address)
        
        if latency is None:
            print(f"❌ Failed to ping {hostname}")
        else:
            print(f"✅ {hostname}: {latency:.2f} ms")
            results.append((hostname, latency))
    
    # Sort and show the fastest servers
    if results:
        print("\nServers ordered by latency:")
        results.sort(key=lambda x: x[1])
        for hostname, latency in results:
            print(f"  {hostname}: {latency:.2f} ms")
    
    return results

def test_parallel_pings(servers, max_servers=10):
    """Test pinging multiple servers in parallel."""
    if not servers:
        print("No servers to ping.")
        return
    
    # Limit the number of servers to test
    servers_to_test = servers[:max_servers]
    print(f"Testing parallel ping for {len(servers_to_test)} servers...")
    
    # Define callback functions
    def progress_callback(percentage):
        print(f"Progress: {percentage:.1f}%")
    
    def result_callback(result):
        server = result["server"]
        latency = result["latency"]
        hostname = server.get("hostname", "Unknown")
        
        if latency is None:
            print(f"❌ Failed to ping {hostname}")
        else:
            print(f"✅ {hostname}: {latency:.2f} ms")
    
    # Start the ping test
    start_time = time.time()
    results = test_servers(
        servers_to_test,
        progress_callback=progress_callback,
        result_callback=result_callback,
        max_workers=5,
        ping_count=3
    )
    elapsed = time.time() - start_time
    
    # Display summary
    print(f"\nCompleted parallel ping tests in {elapsed:.2f} seconds")
    
    if results:
        # Sort by latency
        sorted_results = sorted(
            results,
            key=lambda x: x["latency"] if x["latency"] is not None else float('inf')
        )
        
        print("\nFastest servers:")
        for i, result in enumerate(sorted_results[:5]):
            server = result["server"]
            latency = result["latency"]
            
            if latency is not None:
                print(f"  {i+1}. {server.get('hostname')}: {latency:.2f} ms")
    
    return results

def test_mullvad_status():
    """Test getting the Mullvad status."""
    print("Getting Mullvad connection status...")
    try:
        status = get_mullvad_status()
        print(f"✅ Mullvad status: {status}")
        return status
    except Exception as e:
        print(f"❌ Error getting Mullvad status: {e}")
        return None

def main():
    """Main function for the testing script."""
    parser = argparse.ArgumentParser(description="Test Mullvad Server Finder components.")
    parser.add_argument("--cache-path", help="Path to Mullvad cache file")
    parser.add_argument("--ping", help="IP address to ping")
    parser.add_argument("--country", help="Country code to filter servers")
    parser.add_argument("--protocol", choices=["wireguard", "openvpn"], help="Protocol to filter servers")
    parser.add_argument("--test-all", action="store_true", help="Run all tests")
    parser.add_argument("--parallel", action="store_true", help="Test parallel ping")
    parser.add_argument("--status", action="store_true", help="Test Mullvad status")
    
    args = parser.parse_args()
    
    # If no args or test-all, run basic tests
    if args.test_all or not any([args.ping, args.country, args.protocol, args.parallel, args.status]):
        print("===== Running all basic tests =====\n")
        
        server_data = test_load_servers(args.cache_path)
        print("\n")
        
        test_ping()
        print("\n")
        
        if server_data:
            servers = test_server_discovery(server_data)
            print("\n")
            
            if servers:
                test_multiple_pings(servers)
                print("\n")
        
        test_mullvad_status()
        
    else:
        # Run specific tests based on args
        if args.ping:
            test_ping(args.ping)
            print("\n")
        
        server_data = None
        if args.country or args.protocol or args.parallel:
            server_data = test_load_servers(args.cache_path)
            print("\n")
        
        if args.country or args.protocol:
            servers = test_server_discovery(server_data, args.country, args.protocol)
            print("\n")
            
            if servers and args.parallel:
                test_parallel_pings(servers)
                print("\n")
        
        if args.status:
            test_mullvad_status()

if __name__ == "__main__":
    main()
