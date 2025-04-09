
import subprocess
import threading
from queue import Queue, Empty
import time
import platform
import re
import csv
import os
import socket
import random # Keep this import
import logging
from threading import Event
from typing import Optional, List, Dict, Any, Tuple, Callable

# Setup logger for this module
logger = logging.getLogger(__name__)

# --- Ping Functions ---

def parse_unix_ping(output: str) -> Optional[float]:
    """Parse ping output on Unix-like systems to extract average latency."""
    # Improved regex to handle different ping output formats
    match = re.search(r'rtt min/avg/max/mdev = [\d.]+/([\d.]+)/[\d.]+/[\d.]+ ms', output)
    if match:
        return float(match.group(1))
    # Fallback for simpler output formats
    for line in output.splitlines():
        if "avg" in line and "=" in line:
            try:
                parts = line.split('=')[1].strip().split('/')
                if len(parts) >= 2:
                    return float(parts[1])
            except (IndexError, ValueError):
                continue # Ignore lines that don't parse correctly
    logger.debug(f"Could not parse Unix ping avg latency from output:\n{output}")
    return None

def parse_windows_ping(output: str) -> Optional[float]:
    """Parse ping output on Windows to extract average latency."""
    match = re.search(r"Average = (\d+)ms", output)
    if match:
        return float(match.group(1))
    logger.debug(f"Could not parse Windows ping avg latency from output:\n{output}")
    return None

def ping_test(target_ip: str, count: int = 3, timeout_sec: int = 5) -> Optional[float]:
    """
    Run a ping test to the target IP address and return the average latency in ms.

    Args:
        target_ip: The IP address or hostname to ping.
        count: Number of ping packets to send.
        timeout_sec: Timeout for the entire ping command.

    Returns:
        Average latency in milliseconds, or None if ping fails or times out.
    """
    if not target_ip:
        logger.warning("ping_test called with empty target_ip.")
        return None

    system = platform.system().lower()
    try:
        if system == "windows":
            # -w timeout is in milliseconds for Windows
            cmd = ['ping', '-n', str(count), '-w', str(timeout_sec * 1000), target_ip]
            parse_func = parse_windows_ping
        else:  # For Unix-like systems (macOS, Linux)
            # -W timeout is in seconds for Linux/macOS ping
            # -i interval (e.g., 0.2 for faster pings) - use with caution
            cmd = ['ping', '-c', str(count), '-W', str(timeout_sec), target_ip]
            parse_func = parse_unix_ping

        logger.debug(f"Executing ping command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec + 2) # Command timeout slightly longer

        if result.returncode != 0:
            # Log specific failure reasons if possible
            stderr_lower = result.stderr.lower()
            stdout_lower = result.stdout.lower()
            if "unknown host" in stderr_lower or "could not find host" in stdout_lower:
                 logger.warning(f"Ping failed for {target_ip}: Unknown host.")
            elif "request timed out" in stdout_lower or "100% packet loss" in stdout_lower:
                 logger.warning(f"Ping failed for {target_ip}: Request timed out / packet loss.")
            else:
                 logger.warning(f"Ping failed for {target_ip} (code {result.returncode}). Stderr: {result.stderr.strip()}")
            return None

        avg_latency = parse_func(result.stdout)
        if avg_latency is None:
             logger.warning(f"Ping successful for {target_ip}, but failed to parse average latency.")
        return avg_latency

    except subprocess.TimeoutExpired:
        logger.warning(f"Ping command timed out for {target_ip} after {timeout_sec} seconds.")
        return None
    except FileNotFoundError:
        logger.exception("Ping command not found. Is ICMP allowed or ping installed?")
        # Re-raise or return None; returning None might be more user-friendly
        return None
    except Exception as e:
        logger.exception(f"Unexpected error pinging {target_ip}: {e}")
        return None

# --- Server Testing Framework ---

def get_server_latency(server: Dict[str, Any], ping_count: int, timeout_sec: int) -> Dict[str, Any]:
    """Get the latency for a specific server."""
    ip_address = server.get("ipv4_addr_in")
    result = {
        "server": server,
        "latency": None
    }
    if not ip_address:
        logger.warning(f"Server {server.get('hostname', 'N/A')} has no ipv4_addr_in.")
        return result # Return result with None latency

    latency = ping_test(ip_address, count=ping_count, timeout_sec=timeout_sec // 2) # Use half the main timeout per ping
    result["latency"] = latency
    return result

def test_servers(
    servers: List[Dict[str, Any]],
    progress_callback: Optional[Callable[[float], None]] = None,
    result_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    max_workers: int = 10,
    ping_count: int = 3,
    timeout_sec: int = 10,
    stop_event: Optional[Event] = None,
    pause_event: Optional[Event] = None
) -> List[Dict[str, Any]]:
    """
    Test the latency of a list of servers using multiple threads.

    Args:
        servers: List of server dictionaries. Each dict needs 'ipv4_addr_in'.
        progress_callback: Callback function for progress updates (receives percentage).
        result_callback: Callback function for individual results (receives result dict).
        max_workers: Maximum number of concurrent ping tests.
        ping_count: Number of pings per server.
        timeout_sec: Timeout for each ping test.
        stop_event: Threading event to signal stopping the test.
        pause_event: Threading event to signal pausing the test.

    Returns:
        List of result dictionaries, each containing the server and its latency.
    """
    results: List[Dict[str, Any]] = []
    total = len(servers)
    if total == 0:
        return results
    completed = 0

    server_queue: Queue[Dict[str, Any]] = Queue()
    for server in servers:
        server_queue.put(server)

    result_queue: Queue[Dict[str, Any]] = Queue()
    lock = threading.Lock()

    # Use provided events or create new ones
    _stop_event = stop_event or Event()
    _pause_event = pause_event or Event()

    def worker():
        nonlocal completed
        while not _stop_event.is_set():
            # Handle pause
            if _pause_event.is_set():
                time.sleep(0.2) # Reduce CPU usage while paused
                continue

            try:
                # Get server non-blockingly to check stop_event frequently
                server = server_queue.get(block=True, timeout=0.1)
            except Empty:
                # Queue is empty, worker can exit if others are still running or queue is truly done
                if threading.active_count() <= max_workers + 1 : # +1 for main thread
                    break # Assume finished if queue is empty and workers are winding down
                else:
                    continue # Keep checking queue

            if _stop_event.is_set(): # Check again after potentially blocking get
                server_queue.task_done()
                break

            try:
                result = get_server_latency(server, ping_count, timeout_sec)
                if result:
                    result_queue.put(result)
                    if result_callback:
                        try:
                            result_callback(result)
                        except Exception as cb_err:
                             logger.error(f"Error in result_callback: {cb_err}")

                with lock:
                    completed += 1
                    if progress_callback:
                         try:
                             progress_callback(completed / total * 100)
                         except Exception as cb_err:
                             logger.error(f"Error in progress_callback: {cb_err}")

            except Exception as e:
                logger.exception(f"Error testing server {server.get('hostname', 'N/A')} in worker thread: {e}")
            finally:
                server_queue.task_done() # Ensure task_done is called even on error


    threads: List[threading.Thread] = []
    actual_workers = min(max_workers, total)
    logger.info(f"Starting latency test with {actual_workers} workers for {total} servers.")
    for i in range(actual_workers):
        thread = threading.Thread(target=worker, daemon=True, name=f"PingWorker-{i}")
        thread.start()
        threads.append(thread)

    # Wait for queue processing or stop signal more robustly
    while not _stop_event.is_set():
        if server_queue.unfinished_tasks == 0:
             logger.info("Server queue processed.")
             break
        # Check pause state without busy-waiting
        if _pause_event.is_set():
            logger.debug("Ping test paused...")
            while _pause_event.is_set() and not _stop_event.is_set():
                 time.sleep(0.5) # Sleep longer while paused
            logger.debug("Ping test resumed or stopped.")
        else:
            time.sleep(0.2) # Short sleep while active

    if _stop_event.is_set():
        logger.info("Stop event set. Cleaning up ping test.")
        # Help clear the queue faster if stopped
        while not server_queue.empty():
            try:
                server_queue.get(block=False)
                server_queue.task_done()
            except Queue.Empty:
                break

    # Wait briefly for threads to finish processing their last item or notice stop event
    # for thread in threads:
    #    thread.join(timeout=1.0) # Don't block forever

    # Collect results
    while not result_queue.empty():
        try:
            results.append(result_queue.get(block=False))
        except Queue.Empty:
            break

    logger.info(f"Latency test finished. Collected {len(results)} results.")
    # Sort results by latency (None values at the end)
    results.sort(key=lambda x: x.get("latency", float('inf')) if x.get("latency") is not None else float('inf'))
    return results

DEFAULT_PORTS = [443, 80, 8080, 51820] # Prioritize TCP-likely ports
DEFAULT_DURATION = 5 # Seconds per test
DEFAULT_CHUNK_SIZE = 8192 # 8 KB for ping-pong
DEFAULT_CONN_TIMEOUT = 5 # Seconds

def calculate_mbps(bytes_transferred: int, duration_sec: float) -> float:
    """Calculate speed in Megabits per second. Returns 0.0 if inputs are invalid."""
    if duration_sec <= 0.01 or bytes_transferred <= 0: # Need minimal duration and some bytes
        return 0.0
    return (bytes_transferred * 8) / (duration_sec * 1_000_000)

def _execute_socket_ping_pong(
    ip: str,
    port: int,
    duration: int = DEFAULT_DURATION,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    conn_timeout: int = DEFAULT_CONN_TIMEOUT,
    stop_event: Optional[Event] = None,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Core logic for the Ping-Pong socket test on a specific IP and port.
    Returns (download_mbps, upload_mbps).
    """
    logger.debug(f"[PingPong] Testing {ip}:{port} (Duration: {duration}s, Chunk: {chunk_size}b)")
    download_mbps: Optional[float] = None
    upload_mbps: Optional[float] = None
    sock = None
    rtt_samples = []
    ping_data = os.urandom(chunk_size) # Generate random data chunk
    expected_recv_size = len(ping_data)

    try:
        # 1. Connect
        logger.debug(f"[PingPong] Connecting to {ip}:{port}...")
        conn_start_time = time.monotonic()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(conn_timeout)
        sock.connect((ip, port))
        conn_elapsed = time.monotonic() - conn_start_time
        # Set timeout for individual send/recv operations within the loop
        # A slightly longer timeout might allow slower servers to respond occasionally
        round_timeout = 2.0 # Seconds to wait for response after sending
        sock.settimeout(round_timeout)
        logger.info(f"[PingPong] Connected to {ip}:{port} in {conn_elapsed:.3f}s. Round timeout: {round_timeout}s.")

        # 2. Ping-Pong Loop
        logger.debug(f"[PingPong] Starting Send/Recv Loop...")
        total_bytes_sent = 0
        total_bytes_received = 0
        successful_exchanges = 0
        loop_start_time = time.monotonic()
        loop_end_time = loop_start_time + duration
        loop_error = None

        while time.monotonic() < loop_end_time:
            if stop_event and stop_event.is_set():
                loop_error = "Test stopped by event"
                break

            round_start_time = time.monotonic()
            # --- Send ---
            try:
                sent = sock.send(ping_data)
                if sent == 0:
                    loop_error = "Socket connection broken during send (sent 0 bytes)"
                    break
                total_bytes_sent += sent
            except (socket.timeout, socket.error, Exception) as e:
                loop_error = f"Error during send: {e}"
                break

            # --- Receive ---
            bytes_received_this_round = 0
            received_data = b''
            recv_deadline = time.monotonic() + round_timeout # Max time for this recv phase

            try:
                while bytes_received_this_round < expected_recv_size and time.monotonic() < recv_deadline:
                    if stop_event and stop_event.is_set(): # Check stop event during potential blocking recv
                         loop_error = "Test stopped by event during recv"
                         raise StopIteration() # Use exception to break out immediately

                    # Calculate remaining timeout for this specific recv call
                    remaining_time = recv_deadline - time.monotonic()
                    if remaining_time <= 0: break # Timeout for this round's recv

                    sock.settimeout(remaining_time) # Adjust socket timeout dynamically
                    chunk = sock.recv(expected_recv_size - bytes_received_this_round)
                    if not chunk:
                         # Peer closed connection during our receive attempt
                         raise socket.error("Connection closed by peer during recv")
                    received_data += chunk
                    bytes_received_this_round += len(chunk)

                # Round finished (or timed out/error)
                total_bytes_received += bytes_received_this_round
                round_end_time = time.monotonic()
                rtt = round_end_time - round_start_time
                rtt_samples.append(rtt)
                if bytes_received_this_round > 0: # Count exchange if we got anything back
                    successful_exchanges += 1
                    # logger.debug(f"[PingPong] Round RTT: {rtt*1000:.1f}ms, Recv: {bytes_received_this_round} bytes")

            except StopIteration: # Catch stop event from inner loop
                 break
            except socket.timeout:
                logger.debug(f"[PingPong] Timeout waiting for full response this round.")
                # Continue to next round even if this one timed out recv
                pass
            except (socket.error, Exception) as e:
                loop_error = f"Error during recv: {e}"
                break # Break outer loop on receive error

        # --- Loop End ---
        loop_elapsed = time.monotonic() - loop_start_time
        if loop_error:
            logger.warning(f"[PingPong] Loop stopped early: {loop_error}")
        logger.info(f"[PingPong] Loop finished: Sent={total_bytes_sent}, Recv={total_bytes_received} bytes in {loop_elapsed:.2f}s. Successful Exchanges={successful_exchanges}/{len(rtt_samples)}")

        # Calculate aggregate speeds
        upload_mbps = calculate_mbps(total_bytes_sent, loop_elapsed)
        download_mbps = calculate_mbps(total_bytes_received, loop_elapsed)

    except socket.timeout:
        logger.error(f"[PingPong] Initial connection to {ip}:{port} timed out ({conn_timeout}s).")
    except socket.error as e:
        logger.error(f"[PingPong] Connection error to {ip}:{port}: {e}")
    except Exception as e:
        logger.exception(f"[PingPong] Unexpected error testing {ip}:{port}: {e}")
    finally:
        if sock:
            logger.debug(f"[PingPong] Closing socket for {ip}:{port}.")
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except: pass
            try:
                sock.close()
            except: pass

    # Calculate Avg RTT safely
    avg_rtt_ms = (sum(rtt_samples) / len(rtt_samples) * 1000) if rtt_samples else None

    # Format parts conditionally before creating the final log string
    dl_str = f"{download_mbps:.2f}" if download_mbps is not None else "N/A"
    ul_str = f"{upload_mbps:.2f}" if upload_mbps is not None else "N/A"
    rtt_str = f"{avg_rtt_ms:.1f}" if avg_rtt_ms is not None else "N/A"

    logger.info(f"[PingPong] Result for {ip}:{port}: DL={dl_str} Mbps, UL={ul_str} Mbps, Avg RTT={rtt_str} ms")

    return download_mbps, upload_mbps


def run_socket_ping_pong_test(
    server: Dict[str, Any],
    duration: int = DEFAULT_DURATION,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    ports: List[int] = DEFAULT_PORTS,
    stop_event: Optional[Event] = None
) -> Tuple[Optional[float], Optional[float]]:
    """
    Wrapper function to perform socket ping-pong test on a server.
    Tries multiple ports and returns the result from the first successful one.
    """
    ip_address = server.get("ipv4_addr_in")
    hostname = server.get("hostname", "N/A")
    if not ip_address:
        logger.warning(f"PingPong Wrapper: No IP for server {hostname}")
        return None, None

    logger.info(f"Initiating PingPong speed test for {hostname} ({ip_address}) on ports {ports}...")

    # Try ports sequentially, return first success
    for port in ports:
        if stop_event and stop_event.is_set():
             logger.info(f"PingPong Wrapper: Test stopped by event before trying port {port}.")
             return None, None

        dl_mbps, ul_mbps = _execute_socket_ping_pong(
            ip=ip_address,
            port=port,
            duration=duration,
            chunk_size=chunk_size,
            conn_timeout=DEFAULT_CONN_TIMEOUT,
            stop_event=stop_event
        )

        # Consider a test successful if *either* upload or download has a value > 0
        # (as download might often be 0 even if upload burst worked)
        if dl_mbps is not None or ul_mbps is not None:
            logger.info(f"PingPong Wrapper: Test for {hostname} completed on port {port}.")
            return dl_mbps, ul_mbps # Return result from first working port

    logger.warning(f"PingPong Wrapper: Test failed for {hostname} on all tried ports {ports}.")
    return None, None # Failed on all ports

# --- Server Data Processing ---

def extract_countries(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract a list of countries from the Mullvad server data."""
    return data.get("countries", [])

def extract_cities(country: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract a list of cities from a country dictionary."""
    return country.get("cities", [])

def extract_relays(city: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract a list of relays (servers) from a city dictionary."""
    return city.get("relays", [])

def filter_servers_by_protocol(servers: List[Dict[str, Any]], protocol: Optional[str]) -> List[Dict[str, Any]]:
    """
    Filter servers by the specified protocol (wireguard, openvpn, or None for both),
    based on the structure of the 'endpoint_data' field in relays.json.
    """
    if not protocol or protocol.lower() == "both":
        logger.debug("No protocol filtering applied.")
        return servers # No filtering needed

    protocol_filter = protocol.lower()
    filtered_servers: List[Dict[str, Any]] = []
    logger.debug(f"Filtering {len(servers)} servers by protocol: {protocol_filter}")

    for server in servers:
        endpoint_data = server.get("endpoint_data")
        hostname = server.get("hostname", "N/A") # Keep for logging

        # Determine server type based on endpoint_data structure
        is_wireguard = isinstance(endpoint_data, dict) and "wireguard" in endpoint_data
        is_openvpn = isinstance(endpoint_data, str) and endpoint_data == "openvpn"
        # Optional: Check for bridges if needed later
        # is_bridge = isinstance(endpoint_data, str) and endpoint_data == "bridge"

        # Apply the filter
        if protocol_filter == "wireguard":
            if is_wireguard:
                # logger.debug(f"Match WG: {hostname}")
                filtered_servers.append(server)
            # else: logger.debug(f"No Match WG: {hostname}, endpoint_data={endpoint_data}")
        elif protocol_filter == "openvpn":
            if is_openvpn:
                # logger.debug(f"Match OVPN: {hostname}")
                filtered_servers.append(server)
            # else: logger.debug(f"No Match OVPN: {hostname}, endpoint_data={endpoint_data}")

    logger.info(f"Filtering complete. {len(filtered_servers)} servers match protocol '{protocol_filter}'.")
    return filtered_servers


def _add_location_info(servers: List[Dict[str, Any]], country_name: str, country_code: str, city_name: str, city_code: str) -> List[Dict[str, Any]]:
    """Adds location details to a list of server dictionaries in-place."""
    for server in servers:
        server["country"] = country_name
        server["country_code"] = country_code
        server["city"] = city_name
        server["city_code"] = city_code
    return servers # Return modified list

def get_all_servers(data: Optional[Dict[str, Any]], protocol: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get a flat list of all servers, optionally filtered by protocol."""
    if not data:
        logger.error("get_all_servers called with no server data.")
        return []

    all_servers: List[Dict[str, Any]] = []
    countries = extract_countries(data)
    if not countries:
         logger.warning("No countries found in server data.")
         return []

    for country in countries:
        country_name = country.get("name", "Unknown Country")
        country_code = country.get("code", "??")
        for city in extract_cities(country):
            city_name = city.get("name", "Unknown City")
            city_code = city.get("code", "???")
            city_servers = extract_relays(city)
            # Add location info to each server from this city
            _add_location_info(city_servers, country_name, country_code, city_name, city_code)
            all_servers.extend(city_servers)

    logger.info(f"Extracted {len(all_servers)} total servers.")
    return filter_servers_by_protocol(all_servers, protocol)


def get_servers_by_country(data: Optional[Dict[str, Any]], country_code_filter: str, protocol: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get all servers for a specific country, optionally filtered by protocol."""
    if not data:
        logger.error("get_servers_by_country called with no server data.")
        return []
    if not country_code_filter:
         logger.error("get_servers_by_country called with empty country_code_filter.")
         return []

    servers: List[Dict[str, Any]] = []
    country_code_filter_lower = country_code_filter.lower()
    found_country = False

    for country in extract_countries(data):
        current_code = country.get("code", "").lower()
        if current_code == country_code_filter_lower:
            found_country = True
            country_name = country.get("name", f"Country {country_code_filter}")
            country_code = country.get("code", country_code_filter.upper())
            for city in extract_cities(country):
                city_name = city.get("name", "Unknown City")
                city_code = city.get("code", "???")
                city_servers = extract_relays(city)
                # Add location info
                _add_location_info(city_servers, country_name, country_code, city_name, city_code)
                servers.extend(city_servers)
            break # Found the country, no need to check others

    if not found_country:
         logger.warning(f"No country found with code: {country_code_filter}")

    logger.info(f"Found {len(servers)} servers for country {country_code_filter}.")
    return filter_servers_by_protocol(servers, protocol)

# --- Formatting and Export ---

def export_to_csv(servers: List[Dict[str, Any]], filename: str) -> bool:
    """Export server list with results to a CSV file."""
    if not servers:
        logger.warning("Export to CSV called with no servers.")
        return False

    # Define consistent headers, prioritize common results
    headers = [
        'hostname', 'country', 'city', 'protocol', 'latency',
        'download_speed', 'upload_speed', 'country_code', 'city_code',
        'ipv4_addr_in', 'ipv6_addr_in', 'active', 'owned', 'provider'
        # Add other potential fields if needed, checking the first server is less reliable
    ]
    # Ensure all actual keys from the first server are included if not already present
    # first_server_keys = servers[0].keys()
    # for key in first_server_keys:
    #     if key not in headers and not key.startswith('_'): # Avoid internal keys like 'treeview_item'
    #          headers.append(key)

    try:
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=headers, extrasaction='ignore')
            writer.writeheader()

            for server in servers:
                # Create a row dict based on headers, getting values safely
                row_data = {header: server.get(header, '') for header in headers}

                # Determine protocol string if not explicitly set
                if 'protocol' not in server or not isinstance(server.get('protocol'), str):
                    hostname = server.get("hostname", "").lower()
                    is_wireguard = hostname.endswith("-wg") or ".wg." in hostname
                    row_data['protocol'] = "WireGuard" if is_wireguard else "OpenVPN"

                writer.writerow(row_data)
        logger.info(f"Successfully exported {len(servers)} servers to CSV: {filename}")
        return True
    except IOError as e:
        logger.exception(f"IOError exporting server list to CSV {filename}: {e}")
        return False
    except Exception as e:
        logger.exception(f"Unexpected error exporting server list to CSV {filename}: {e}")
        return False


def calculate_latency_color(latency: Optional[float]) -> str:
    """Calculate a color for the given latency value (Excel-style gradient)."""
    if latency is None or latency == float('inf'):
        return "#AAAAAA"  # Gray for unknown/timeout

    # Green (good < 50ms) -> Yellow (medium 100-150ms) -> Red (bad > 250ms)
    if latency < 50:
        return "#63BE7B"  # Green
    elif latency < 125: # Transition Green -> Yellow
        ratio = (latency - 50) / (125 - 50)
        # Interpolate green (99, 190, 123) to yellow (255, 235, 132)
        r = int(99 + (255 - 99) * ratio)
        g = int(190 + (235 - 190) * ratio)
        b = int(123 + (132 - 123) * ratio)
        return f"#{r:02x}{g:02x}{b:02x}"
    elif latency < 250: # Transition Yellow -> Orange/Red
        ratio = (latency - 125) / (250 - 125)
         # Interpolate yellow (255, 235, 132) to orange/red (248, 105, 107)
        r = int(255 + (248 - 255) * ratio)
        g = int(235 + (105 - 235) * ratio)
        b = int(132 + (107 - 132) * ratio)
        return f"#{r:02x}{g:02x}{b:02x}"
    else: # > 250ms
        return "#F8696B"  # Red

def calculate_speed_color(speed: Optional[float], max_expected_speed: float = 100.0) -> str:
    """Calculate a color for the given speed value (Excel-style gradient)."""
    if speed is None or speed == float('inf'):
        return "#AAAAAA"  # Gray for unknown

    # Red (bad < 10Mbps) -> Yellow (medium 50Mbps) -> Green (good > 100Mbps)
    # Normalize speed relative to max_expected_speed for better gradient spread
    # Cap speed at max_expected_speed for color calculation
    speed = min(speed, max_expected_speed)

    if speed < max_expected_speed * 0.1: # < 10% of max (e.g., < 10Mbps if max=100)
        return "#F8696B"  # Red
    elif speed < max_expected_speed * 0.6: # Transition Red -> Yellow (10% to 60%)
        ratio = (speed - max_expected_speed * 0.1) / (max_expected_speed * (0.6 - 0.1))
        # Interpolate red (248, 105, 107) to yellow (255, 235, 132)
        r = int(248 + (255 - 248) * ratio)
        g = int(105 + (235 - 105) * ratio)
        b = int(107 + (132 - 107) * ratio)
        return f"#{r:02x}{g:02x}{b:02x}"
    else: # Transition Yellow -> Green (60% to 100%)
        ratio = (speed - max_expected_speed * 0.6) / (max_expected_speed * (1.0 - 0.6))
        # Interpolate yellow (255, 235, 132) to green (99, 190, 123)
        r = int(255 + (99 - 255) * ratio)
        g = int(235 + (190 - 235) * ratio)
        b = int(132 + (123 - 132) * ratio)
        return f"#{r:02x}{g:02x}{b:02x}"