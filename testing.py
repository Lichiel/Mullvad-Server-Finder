
#!/usr/bin/env python3
"""
This script provides a simple way to test components of Mullvad Server Finder
without running the full GUI application. Uses logging.
"""

import json
import time
import argparse
import os
import sys
import logging

# --- Setup Basic Logging for Testing Script ---
log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
logging.basicConfig(level=logging.INFO, format=log_format, stream=sys.stdout)
logger = logging.getLogger("testing_script")

# --- Add project root to path ---
try:
    project_root = os.path.dirname(os.path.abspath(__file__))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    logger.debug(f"Testing script added project root to sys.path: {project_root}")

    # --- Import Modules to Test ---
    from mullvad_api import load_cached_servers, get_mullvad_status, set_mullvad_location, connect_mullvad, MullvadCLIError
    from server_manager import ping_test, get_all_servers, get_servers_by_country, test_servers, test_server_speed
    from config import get_default_cache_path, load_config # Use config defaults
except ImportError as e:
    logger.critical(f"Failed to import modules needed for testing: {e}")
    sys.exit(1)
except Exception as e:
    logger.critical(f"Unexpected error during test script imports: {e}")
    sys.exit(1)


# --- Test Functions ---

def test_load_servers(cache_path=None):
    """Test loading the Mullvad server cache."""
    if not cache_path:
        # Use the default path logic from config module
        temp_config = load_config() # Load default config to get path logic
        cache_path = temp_config.get("cache_path", get_default_cache_path())
        logger.info(f"No cache path provided, using default: {cache_path}")
    else:
        logger.info(f"Using provided cache path: {cache_path}")

    print(f"\n===== Testing Server Loading ({cache_path}) =====")
    server_data = load_cached_servers(cache_path) # Function logs internally

    if not server_data:
        print("❌ Failed to load server data.")
        logger.error("Server data loading test FAILED.")
        return None

    countries = server_data.get("countries", [])
    print(f"✅ Successfully loaded server data.")
    logger.info("Server data loading test PASSED.")

    # Print some basic stats
    total_cities = sum(len(country.get("cities", [])) for country in countries)
    total_servers = sum(
        sum(len(city.get("relays", [])) for city in country.get("cities", []))
        for country in countries
    )

    print(f"Total active countries found: {len(countries)}") # Assuming load_cached_servers doesn't filter active status
    print(f"Total cities found: {total_cities}")
    print(f"Total servers (relays) found: {total_servers}")
    logger.info(f"Stats - Countries: {len(countries)}, Cities: {total_cities}, Servers: {total_servers}")

    # Print the first country's details as an example
    if countries:
        first_country = countries[0]
        print("\nExample country data (first entry):")
        print(f"  Name: {first_country.get('name')}")
        print(f"  Code: {first_country.get('code')}")

        if first_country.get("cities"):
            first_city = first_country["cities"][0]
            print(f"  First city: {first_city.get('name')} ({first_city.get('code')})")

            if first_city.get("relays"):
                first_relay = first_city["relays"][0]
                print(f"    First server: {first_relay.get('hostname')}")
                print(f"    IPv4 address: {first_relay.get('ipv4_addr_in')}")
                print(f"    Active: {first_relay.get('active')}")

    return server_data

def test_ping(ip_address=None, count=3):
    """Test the ping functionality."""
    print(f"\n===== Testing Ping Function =====")
    if not ip_address:
        print("No IP address provided, using 1.1.1.1 (Cloudflare DNS)...")
        ip_address = "1.1.1.1"

    print(f"Pinging {ip_address} (count={count})...")
    start_time = time.time()
    latency = ping_test(ip_address, count=count) # ping_test logs internally now
    elapsed = time.time() - start_time

    if latency is None:
        print(f"❌ Ping test FAILED for {ip_address}.")
        logger.error(f"Ping test function FAILED for {ip_address}")
    else:
        print(f"✅ Successfully pinged {ip_address}: {latency:.2f} ms")
        logger.info(f"Ping test function PASSED for {ip_address}: {latency:.2f} ms")

    print(f"(Test took {elapsed:.2f} seconds)")
    return latency

def test_server_discovery(server_data=None, country_code=None, protocol=None):
    """Test the server discovery (get_all_servers, get_servers_by_country)."""
    print(f"\n===== Testing Server Discovery =====")
    if not server_data:
        print("No server data provided, attempting to load defaults...")
        server_data = test_load_servers() # Reuse loading test
        if not server_data:
            print("❌ Cannot proceed with discovery test without server data.")
            logger.error("Server discovery test FAILED due to missing data.")
            return None

    print("Discovering servers...")
    if country_code:
        print(f"Filtering by country: {country_code}")
        servers = get_servers_by_country(server_data, country_code, protocol)
    else:
        print("Getting all servers")
        servers = get_all_servers(server_data, protocol)

    if protocol:
        print(f"Filtering by protocol: {protocol}")

    if not servers:
         print(f"❌ No servers found matching criteria (Country: {country_code or 'All'}, Protocol: {protocol or 'Any'}).")
         logger.warning(f"Server discovery found no servers for Country={country_code}, Protocol={protocol}")
         # This isn't necessarily a failure of the function, but worth noting
    else:
        print(f"✅ Found {len(servers)} servers.")
        logger.info(f"Server discovery test PASSED, found {len(servers)} servers.")

        # Print a few example servers
        print("\nExample servers found:")
        for i, server in enumerate(servers[:3]):
            hn = server.get('hostname', 'N/A')
            city = server.get('city', 'N/A')
            country = server.get('country', 'N/A')
            ip = server.get('ipv4_addr_in', 'N/A')
            print(f"  {i+1}. {hn} ({ip}) - {city}, {country}")

    return servers


def test_parallel_pings(servers, max_servers=10, ping_count=3):
    """Test pinging multiple servers in parallel using test_servers."""
    print(f"\n===== Testing Parallel Pings (test_servers) =====")
    if not servers:
        print("No servers provided to test.")
        logger.warning("Parallel ping test skipped: No servers.")
        return None

    # Limit the number of servers for quick testing
    servers_to_test = servers[:max_servers]
    print(f"Testing parallel ping for {len(servers_to_test)} servers (ping_count={ping_count})...")

    results_list: list = [] # To store results from callback

    # Define simple callbacks for testing
    def progress_cb(percentage: float):
        print(f"Progress: {percentage:.1f}%", end='\r') # Use carriage return for inline progress

    def result_cb(result: dict):
        server = result.get("server", {})
        latency = result.get("latency")
        hostname = server.get("hostname", "Unknown")
        ip = server.get("ipv4_addr_in", "N/A")
        status = f"{latency:.1f} ms" if latency is not None else "Timeout"
        print(f"  Result: {hostname} ({ip}) -> {status}   ") # Extra spaces to clear progress line
        results_list.append(result)

    # Start the parallel ping test
    start_time = time.time()
    # Using default stop/pause events for this test
    test_servers(
        servers_to_test,
        progress_callback=progress_cb,
        result_callback=result_cb,
        max_workers=5, # Use fewer workers for testing clarity
        ping_count=ping_count,
        timeout_sec=10
    )
    elapsed = time.time() - start_time
    print("\n") # Newline after progress indicator

    # Display summary
    print(f"✅ Parallel ping test completed in {elapsed:.2f} seconds.")
    logger.info(f"Parallel ping test PASSED in {elapsed:.2f}s for {len(servers_to_test)} servers.")

    if results_list:
        # Sort results by latency (None values at the end)
        results_list.sort(key=lambda x: x.get("latency", float('inf')) if x.get("latency") is not None else float('inf'))

        print("\nFastest servers from test:")
        for i, result in enumerate(results_list[:5]):
            server = result["server"]
            latency = result["latency"]
            if latency is not None:
                print(f"  {i+1}. {server.get('hostname')}: {latency:.1f} ms")
            else:
                 print(f"  {i+1}. {server.get('hostname')}: Timeout")
    else:
         print("No results were collected from the parallel ping test.")
         logger.warning("Parallel ping test collected no results.")

    return results_list


def test_speed(servers, max_servers=3):
    """Test the speed test functionality for a few servers."""
    print(f"\n===== Testing Speed Test Function (test_server_speed) =====")
    if not servers:
        print("No servers provided for speed test.")
        logger.warning("Speed test skipped: No servers.")
        return None

    servers_to_test = servers[:max_servers]
    print(f"Testing speed for {len(servers_to_test)} servers (this might take a while)...")

    results = []
    for i, server in enumerate(servers_to_test):
        hostname = server.get("hostname", f"Server {i+1}")
        ip = server.get("ipv4_addr_in", "N/A")
        print(f"\nTesting server {i+1}/{len(servers_to_test)}: {hostname} ({ip})...")

        start_time = time.time()
        try:
            # test_server_speed logs internally now
            download_mbps, upload_mbps = test_server_speed(server, size_mb=5, timeout_sec=20) # Use smaller size for test
            elapsed = time.time() - start_time

            down_str = f"{download_mbps:.1f} Mbps" if download_mbps is not None else "Failed/Timeout"
            # Upload is expected to be None from current implementation
            up_str = f"{upload_mbps:.1f} Mbps" if upload_mbps is not None else "N/A"

            print(f"✅ Result for {hostname}: Est. Download={down_str}, Est. Upload={up_str} (took {elapsed:.1f}s)")
            logger.info(f"Speed test for {hostname} completed: DL={down_str}, UL={up_str}")
            results.append({"server": server, "download": download_mbps, "upload": upload_mbps})

        except Exception as e:
            elapsed = time.time() - start_time
            print(f"❌ Error testing speed for {hostname}: {e} (after {elapsed:.1f}s)")
            logger.exception(f"Speed test failed for {hostname}: {e}")
            results.append({"server": server, "download": None, "upload": None})


    print("\nSpeed test function finished.")
    if not results:
         logger.error("Speed test function execution FAILED to produce results.")
    else:
         logger.info("Speed test function execution PASSED.")
    return results


def test_mullvad_status():
    """Test getting the Mullvad status."""
    print(f"\n===== Testing Mullvad Status (mullvad status) =====")
    print("Getting Mullvad connection status...")
    try:
        status = get_mullvad_status() # API function logs internally
        print(f"✅ Mullvad status reported: '{status}'")
        logger.info(f"Mullvad status test PASSED, status: {status}")
        return status
    except MullvadCLIError as e:
         print(f"❌ Failed to get Mullvad status (CLI Error): {e}")
         logger.error(f"Mullvad status test FAILED (CLI Error): {e}")
         return None
    except Exception as e:
        print(f"❌ An unexpected error occurred getting Mullvad status: {e}")
        logger.exception("Mullvad status test FAILED (Unexpected Error).")
        return None

def test_mullvad_connection(server_details):
     """Test setting location and connecting."""
     print(f"\n===== Testing Mullvad Connection (set location, connect) =====")
     if not server_details:
         print("❌ Cannot test connection without server details.")
         logger.error("Mullvad connection test skipped: no server details.")
         return

     hostname = server_details.get('hostname')
     country_code = server_details.get('country_code')
     city_code = server_details.get('city_code')

     if not all([hostname, country_code, city_code]):
          print(f"❌ Incomplete server details: {server_details}. Cannot test connection.")
          logger.error(f"Mullvad connection test skipped: incomplete details for {hostname}")
          return

     # Determine protocol from hostname
     protocol = "wireguard" if "-wg" in hostname.lower() or ".wg." in hostname.lower() else "openvpn"
     print(f"Attempting to connect to {hostname} ({country_code}/{city_code}) using {protocol}...")

     try:
         # print(f"Setting protocol to {protocol}...")
         # set_mullvad_protocol(protocol) # Requires Mullvad 2023.4+
         # time.sleep(0.5)

         print(f"Setting location to {country_code} {city_code} {hostname}...")
         set_mullvad_location(country_code, city_code, hostname)
         time.sleep(1) # Allow daemon to process location change

         print("Connecting...")
         connect_mullvad()
         time.sleep(2) # Allow connection to establish

         print("Checking status after connect...")
         status = get_mullvad_status()
         print(f"Status: {status}")

         if "Connected" in status and hostname in status:
              print(f"✅ Connection test PASSED for {hostname}.")
              logger.info(f"Mullvad connection test PASSED for {hostname}")
         else:
              print(f"❌ Connection test FAILED for {hostname}. Status does not confirm connection.")
              logger.error(f"Mullvad connection test FAILED for {hostname}. Final status: {status}")

         # print("Disconnecting...")
         # disconnect_mullvad() # Add disconnect test separately if needed

     except MullvadCLIError as e:
         print(f"❌ Connection test FAILED (CLI Error): {e}")
         logger.error(f"Mullvad connection test FAILED (CLI Error): {e}")
     except Exception as e:
        print(f"❌ Connection test FAILED (Unexpected Error): {e}")
        logger.exception("Mullvad connection test FAILED (Unexpected Error).")


# --- Main Execution Logic ---

def main():
    """Main function for the testing script."""
    parser = argparse.ArgumentParser(description="Test Mullvad Server Finder components.")
    parser.add_argument("--cache-path", help="Path to Mullvad relays.json cache file")
    parser.add_argument("--ping-ip", help="Specific IP address to test ping function")
    parser.add_argument("--country", help="Country code (e.g., us, se, de) to filter servers for discovery/tests")
    parser.add_argument("--protocol", choices=["wireguard", "openvpn"], help="Protocol (wireguard or openvpn) to filter servers")
    parser.add_argument("--test-all", action="store_true", help="Run all standard tests")
    parser.add_argument("--test-parallel", action="store_true", help="Run only the parallel ping test")
    parser.add_argument("--test-speed", action="store_true", help="Run only the speed test")
    parser.add_argument("--test-connect", help="Hostname of a server to test connection with (requires --country and loaded data)")
    parser.add_argument("--status", action="store_true", help="Run only the Mullvad status test")
    parser.add_argument("--debug", action="store_true", help="Enable DEBUG level logging")

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
        for handler in logging.getLogger().handlers:
            handler.setLevel(logging.DEBUG)
        logger.info("DEBUG logging enabled.")


    # --- Run Tests ---
    server_data = None
    servers = None

    # Load server data first if needed for other tests or --test-all
    if args.test_all or args.country or args.test_parallel or args.test_speed or args.test_connect:
        server_data = test_load_servers(args.cache_path)
        if not server_data and (args.test_parallel or args.test_speed or args.test_connect or (args.test_all and not args.ping_ip)):
             print("\n❌ Cannot run further tests without server data. Exiting.")
             sys.exit(1)
        if server_data:
            # Discover servers based on filters if provided, or all for --test-all
            servers = test_server_discovery(server_data, args.country, args.protocol)
            if not servers and (args.test_parallel or args.test_speed or args.test_connect):
                  print(f"\n❌ No servers found matching Country='{args.country}', Protocol='{args.protocol}'. Cannot run further tests.")
                  sys.exit(1)


    # --- Execute Specific Tests or All ---

    if args.test_all:
        print("\n===== Running All Standard Tests =====")
        # Assumes server_data and servers loaded above if needed
        test_ping(args.ping_ip or "1.1.1.1") # Test basic ping
        if servers:
            test_parallel_pings(servers, max_servers=20, ping_count=3)
            test_speed(servers, max_servers=3)
        test_mullvad_status()
        # Add connect test if a server was found? Risky for automated tests.
        if servers and args.country: # Only run connect test if a country was specified for safety
             test_mullvad_connection(servers[0]) # Test connection with the first found server
        print("\n===== All Tests Completed =====")

    else:
        # Run specific tests based on arguments
        if args.ping_ip:
            test_ping(args.ping_ip)

        if args.test_parallel:
            if servers: test_parallel_pings(servers, max_servers=50, ping_count=3)
            else: print("Skipping parallel ping test: Server discovery failed or found no servers.")

        if args.test_speed:
            if servers: test_speed(servers, max_servers=5)
            else: print("Skipping speed test: Server discovery failed or found no servers.")

        if args.status:
            test_mullvad_status()

        if args.test_connect:
             if servers:
                 # Find the specific server by hostname
                 target_server = next((s for s in servers if s.get('hostname') == args.test_connect), None)
                 if target_server:
                      # Add location codes if missing (might happen if discovery wasn't run with country)
                      if 'country_code' not in target_server and server_data:
                           print(f"Looking up location codes for {args.test_connect}...")
                           all_servers_with_codes = get_all_servers(server_data) # Get all to ensure codes are present
                           target_server = next((s for s in all_servers_with_codes if s.get('hostname') == args.test_connect), None)

                      if target_server and 'country_code' in target_server:
                           test_mullvad_connection(target_server)
                      else:
                           print(f"❌ Could not find complete details (incl. location codes) for hostname '{args.test_connect}' to test connection.")
                 else:
                      print(f"❌ Could not find server with hostname '{args.test_connect}' in the discovered list.")
             else:
                  print("❌ Cannot test connection: Server discovery failed or found no servers for the specified filters.")


if __name__ == "__main__":
    main()
