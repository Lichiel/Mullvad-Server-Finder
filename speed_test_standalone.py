# --- START OF FILE speed_test_standalone.py ---

import socket
import time
import argparse
import os
import random
import logging
import sys
from typing import Tuple, Optional, Dict

# --- Basic Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stdout)
logger = logging.getLogger("SpeedTestStandalone")

DEFAULT_PORTS = [443, 80, 8080, 51820, 1194] # Common ports to try
DEFAULT_DURATION = 5 # Seconds per phase/test
DEFAULT_CHUNK_SIZE = 65536 # 64 KB

# --- Helper ---
def calculate_mbps(bytes_transferred: int, duration_sec: float) -> Optional[float]:
    """Calculate speed in Megabits per second."""
    if duration_sec <= 0 or bytes_transferred <= 0:
        return 0.0 # Avoid division by zero or return None? Let's return 0 for simplicity here.
    return (bytes_transferred * 8) / (duration_sec * 1_000_000)

# --- Strategy 1: Bulk Send then Receive ---
def test_strategy_bulk_send_recv(
    ip: str,
    port: int,
    duration: int = DEFAULT_DURATION,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    conn_timeout: int = 5
) -> Tuple[Optional[float], Optional[float]]:
    """
    Connects, sends bulk data for 'duration' sec, then receives bulk data for 'duration' sec.
    Returns (download_mbps, upload_mbps).
    """
    logger.info(f"[Bulk] Testing {ip}:{port} (Duration: {duration}s, Chunk: {chunk_size}b)")
    download_mbps: Optional[float] = None
    upload_mbps: Optional[float] = None
    sock = None

    try:
        # 1. Connect
        logger.info(f"[Bulk] Connecting...")
        conn_start_time = time.monotonic()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(conn_timeout)
        sock.connect((ip, port))
        conn_elapsed = time.monotonic() - conn_start_time
        logger.info(f"[Bulk] Connected in {conn_elapsed:.3f}s. Setting timeout to {duration + 2}s for tests.")
        sock.settimeout(duration + 2) # Longer timeout for data transfer phases

        # 2. Upload Phase
        logger.info(f"[Bulk] Starting Upload Phase...")
        upload_data_chunk = os.urandom(chunk_size)
        total_bytes_sent = 0
        upload_start_time = time.monotonic()
        upload_end_time = upload_start_time + duration
        upload_error = None
        while time.monotonic() < upload_end_time:
            try:
                sent = sock.send(upload_data_chunk)
                if sent == 0:
                    upload_error = "Socket connection broken (send returned 0)"
                    break
                total_bytes_sent += sent
            except socket.timeout:
                upload_error = "Socket send timed out"
                break
            except socket.error as e:
                upload_error = f"Socket error during send: {e}"
                break
            except Exception as e:
                upload_error = f"Unexpected error during send: {e}"
                break
        upload_elapsed = time.monotonic() - upload_start_time
        if upload_error:
            logger.warning(f"[Bulk] Upload phase stopped early: {upload_error}")
        logger.info(f"[Bulk] Upload Phase finished: Sent {total_bytes_sent} bytes in {upload_elapsed:.2f}s.")
        upload_mbps = calculate_mbps(total_bytes_sent, upload_elapsed)

        # 3. Download Phase
        logger.info(f"[Bulk] Starting Download Phase...")
        total_bytes_received = 0
        download_start_time = time.monotonic()
        download_end_time = download_start_time + duration
        download_error = None
        while time.monotonic() < download_end_time:
            try:
                chunk = sock.recv(chunk_size)
                if not chunk:
                    download_error = "Socket connection closed by peer"
                    break
                total_bytes_received += len(chunk)
            except socket.timeout:
                download_error = "Socket recv timed out (expected at end of duration or if idle)"
                break
            except socket.error as e:
                download_error = f"Socket error during recv: {e}"
                break
            except Exception as e:
                download_error = f"Unexpected error during recv: {e}"
                break
        download_elapsed = time.monotonic() - download_start_time
        if download_error and total_bytes_received == 0: # Only warn if timeout wasn't just end of test
             logger.warning(f"[Bulk] Download phase stopped/yielded no data: {download_error}")
        logger.info(f"[Bulk] Download Phase finished: Received {total_bytes_received} bytes in {download_elapsed:.2f}s.")
        download_mbps = calculate_mbps(total_bytes_received, download_elapsed)

    except socket.timeout:
        logger.error(f"[Bulk] Connection timed out ({conn_timeout}s).")
    except socket.error as e:
        logger.error(f"[Bulk] Connection error: {e}")
    except Exception as e:
        logger.exception(f"[Bulk] Unexpected error: {e}")
    finally:
        if sock:
            logger.info("[Bulk] Closing socket.")
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except: pass
            try:
                sock.close()
            except: pass

    logger.info(f"[Bulk] Result: Download={download_mbps:.2f} Mbps, Upload={upload_mbps:.2f} Mbps" if download_mbps is not None and upload_mbps is not None else "[Bulk] Result: Failed")
    return download_mbps, upload_mbps


# --- Strategy 2: Ping-Pong ---
def test_strategy_ping_pong(
    ip: str,
    port: int,
    duration: int = DEFAULT_DURATION,
    chunk_size: int = 8192, # Smaller chunk size for ping-pong
    conn_timeout: int = 5
) -> Tuple[Optional[float], Optional[float]]:
    """
    Connects, then repeatedly sends a chunk and tries to receive a chunk back for 'duration' sec.
    Returns aggregate (download_mbps, upload_mbps).
    """
    logger.info(f"[PingPong] Testing {ip}:{port} (Duration: {duration}s, Chunk: {chunk_size}b)")
    download_mbps: Optional[float] = None
    upload_mbps: Optional[float] = None
    sock = None
    rtt_samples = []
    ping_data = os.urandom(chunk_size)
    expected_recv_size = len(ping_data)

    try:
        # 1. Connect
        logger.info(f"[PingPong] Connecting...")
        conn_start_time = time.monotonic()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(conn_timeout)
        sock.connect((ip, port))
        conn_elapsed = time.monotonic() - conn_start_time
        # Shorter timeout per round-trip attempt
        sock.settimeout(2.0)
        logger.info(f"[PingPong] Connected in {conn_elapsed:.3f}s. Setting timeout to {sock.gettimeout()}s for rounds.")

        # 2. Ping-Pong Loop
        logger.info(f"[PingPong] Starting Send/Recv Loop...")
        total_bytes_sent = 0
        total_bytes_received = 0
        successful_exchanges = 0
        loop_start_time = time.monotonic()
        loop_end_time = loop_start_time + duration
        loop_error = None

        while time.monotonic() < loop_end_time:
            round_start_time = time.monotonic()
            # Send
            try:
                sent = sock.send(ping_data)
                if sent == 0:
                    loop_error = "Socket connection broken during send"
                    break
                total_bytes_sent += sent
            except (socket.timeout, socket.error, Exception) as e:
                loop_error = f"Error during send: {e}"
                break

            # Receive
            bytes_received_this_round = 0
            received_data = b''
            recv_start_time = time.monotonic()
            try:
                # Try to receive up to expected size
                while bytes_received_this_round < expected_recv_size and (time.monotonic() - recv_start_time) < sock.gettimeout():
                    chunk = sock.recv(expected_recv_size - bytes_received_this_round)
                    if not chunk:
                         # Peer closed connection during our receive attempt
                         raise socket.error("Connection closed by peer during recv")
                    received_data += chunk
                    bytes_received_this_round += len(chunk)

                total_bytes_received += bytes_received_this_round
                round_end_time = time.monotonic()
                rtt = round_end_time - round_start_time
                rtt_samples.append(rtt)
                if bytes_received_this_round >= expected_recv_size:
                    successful_exchanges += 1
                    # logger.debug(f"[PingPong] Round success: RTT={rtt*1000:.1f}ms")
                # else: logger.debug(f"[PingPong] Round partial recv: {bytes_received_this_round}/{expected_recv_size} bytes, RTT={rtt*1000:.1f}ms")


            except socket.timeout:
                # Didn't get response in time for this specific round
                logger.debug(f"[PingPong] Timeout waiting for response this round.")
                # Continue to next round? Or break? Let's continue for now.
                pass
            except (socket.error, Exception) as e:
                loop_error = f"Error during recv: {e}"
                break # Break outer loop on receive error

        # Loop finished or broken by error
        loop_elapsed = time.monotonic() - loop_start_time
        if loop_error:
            logger.warning(f"[PingPong] Loop stopped early: {loop_error}")
        logger.info(f"[PingPong] Loop finished: Sent={total_bytes_sent}, Recv={total_bytes_received} bytes in {loop_elapsed:.2f}s. Successful Exchanges={successful_exchanges}")

        # Calculate aggregate speeds
        upload_mbps = calculate_mbps(total_bytes_sent, loop_elapsed)
        download_mbps = calculate_mbps(total_bytes_received, loop_elapsed)

    except socket.timeout:
        logger.error(f"[PingPong] Connection timed out ({conn_timeout}s).")
    except socket.error as e:
        logger.error(f"[PingPong] Connection error: {e}")
    except Exception as e:
        logger.exception(f"[PingPong] Unexpected error: {e}")
    finally:
        if sock:
            logger.info("[PingPong] Closing socket.")
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except: pass
            try:
                sock.close()
            except: pass

    avg_rtt_ms = (sum(rtt_samples) / len(rtt_samples) * 1000) if rtt_samples else None
    logger.info(f"[PingPong] Result: Download={download_mbps:.2f} Mbps, Upload={upload_mbps:.2f} Mbps, Avg RTT={avg_rtt_ms:.1f} ms" if download_mbps is not None and upload_mbps is not None and avg_rtt_ms is not None else "[PingPong] Result: Failed or Incomplete")
    return download_mbps, upload_mbps

# --- Main Execution ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Standalone Socket Speed Test Utility")
    parser.add_argument("ip", help="Target IP address")
    parser.add_argument("-p", "--port", type=int, help=f"Target port (optional, will try defaults: {DEFAULT_PORTS})")
    parser.add_argument("-d", "--duration", type=int, default=DEFAULT_DURATION, help="Duration (seconds) for each test phase/loop")
    parser.add_argument("-c", "--chunksize", type=int, default=DEFAULT_CHUNK_SIZE, help="Chunk size (bytes) for sending/receiving")
    parser.add_argument("-s", "--strategy", type=int, choices=[1, 2], default=1, help="Test strategy: 1=Bulk Send->Recv, 2=Ping-Pong")
    parser.add_argument("-t", "--timeout", type=int, default=5, help="Connection timeout (seconds)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable DEBUG logging")

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)
        logger.info("Debug logging enabled.")

    ports_to_try = [args.port] if args.port else DEFAULT_PORTS

    results: Dict[int, Tuple[Optional[float], Optional[float]]] = {}

    for port in ports_to_try:
        if args.strategy == 1:
            dl, ul = test_strategy_bulk_send_recv(args.ip, port, args.duration, args.chunksize, args.timeout)
        elif args.strategy == 2:
            dl, ul = test_strategy_ping_pong(args.ip, port, args.duration, args.chunksize, args.timeout)
        else:
            logger.error(f"Invalid strategy: {args.strategy}")
            sys.exit(1)

        results[port] = (dl, ul)
        # Optionally break after first successful port test?
        # if dl is not None or ul is not None:
        #    logger.info(f"Test succeeded on port {port}, stopping.")
        #    break

    print("\n--- Summary ---")
    found_result = False
    for port, (dl, ul) in results.items():
        dl_str = f"{dl:.2f}" if dl is not None else "N/A"
        ul_str = f"{ul:.2f}" if ul is not None else "N/A"
        print(f"Port {port}: Download = {dl_str} Mbps, Upload = {ul_str} Mbps")
        if dl is not None or ul is not None:
            found_result = True

    if not found_result:
        print("No successful speed measurements obtained.")

# --- END OF FILE speed_test_standalone.py ---