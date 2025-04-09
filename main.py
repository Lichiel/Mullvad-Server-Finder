
import tkinter as tk
from tkinter import ttk, messagebox
import sys
import os
import platform
import threading
import logging
import logging.handlers
import subprocess

# --- Setup Logging ---
try:
    # Ensure config directory exists for log file path resolution
    config_dir = os.path.expanduser("~/.config/mullvad-finder")
    os.makedirs(config_dir, exist_ok=True)
    log_file_path = os.path.expanduser("~/mullvad_finder.log") # Log in home dir

    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    # Use rotating file handler to limit log file size
    log_handler = logging.handlers.RotatingFileHandler(
        log_file_path, maxBytes=2*1024*1024, backupCount=1, encoding='utf-8'
    )
    log_handler.setFormatter(logging.Formatter(log_format))

    logging.basicConfig(
        level=logging.INFO, # Default level, can be changed
        # level=logging.DEBUG, # Uncomment for more detailed logs
        format=log_format,
        handlers=[
            log_handler,
            logging.StreamHandler(sys.stdout) # Also log to console
        ]
    )
    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized. Log file: {log_file_path}")

except Exception as e:
     print(f"FATAL: Failed to initialize logging: {e}", file=sys.stderr)
     # Basic fallback logging if setup fails
     logging.basicConfig(level=logging.ERROR)
     logger = logging.getLogger(__name__)
     logger.error(f"Logging setup failed: {e}")


# --- Add project root to path ---
# This ensures modules can be imported correctly, especially when run directly
try:
    project_root = os.path.dirname(os.path.abspath(__file__))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    logger.debug(f"Project root added to sys.path: {project_root}")

    # --- Import GUI Application ---
    from gui import MullvadFinderApp
except ImportError as e:
     logger.exception("Failed to import MullvadFinderApp. Critical dependency missing?")
     messagebox.showerror("Startup Error", f"Failed to load application components:\n{e}\n\nPlease ensure all files are present.")
     sys.exit(1)
except Exception as e:
     logger.exception("An unexpected error occurred during initial imports.")
     messagebox.showerror("Startup Error", f"An unexpected error occurred on startup:\n{e}")
     sys.exit(1)


# --- Platform Specific Setup ---

def set_dpi_awareness():
    """Set DPI awareness, primarily for Windows."""
    if platform.system() == 'Windows':
        try:
            import ctypes
            # Query DPI Awareness before setting
            awareness = ctypes.c_int()
            errorCode = ctypes.windll.shcore.GetProcessDpiAwareness(0, ctypes.byref(awareness))
            logger.info(f"Initial DPI Awareness: {awareness.value} (0=Unaware, 1=System, 2=Per-Monitor)")

            # Set Per-Monitor DPI Awareness (Recommended)
            if awareness.value < 2: # If not already Per-Monitor aware
                errorCode = ctypes.windll.shcore.SetProcessDpiAwareness(2) # 2 = Per Monitor DPI Aware
                if errorCode == 0: # S_OK
                    logger.info("Successfully set Per-Monitor DPI Awareness.")
                else:
                    logger.error(f"Failed to set Per-Monitor DPI Awareness, Error Code: {errorCode}")
                    # Fallback to System Aware if Per-Monitor fails?
                    # errorCode = ctypes.windll.shcore.SetProcessDpiAwareness(1)
                    # logger.info(f"Attempted to set System DPI Awareness, Result: {errorCode == 0}")

        except ImportError:
             logger.warning("Could not import ctypes, cannot set DPI awareness.")
        except AttributeError:
             logger.warning("shcore.SetProcessDpiAwareness not found (requires Windows 8.1+).")
        except Exception as e:
             logger.exception(f"Error setting DPI awareness: {e}")


# --- Dependency Check ---

def check_dependencies() -> bool:
    """Check if the Mullvad CLI is installed and accessible."""
    logger.info("Checking for Mullvad CLI dependency...")
    try:
        # Use 'mullvad version' as a simple check command
        # Set encoding explicitly for subprocess output
        result = subprocess.run(
            ['mullvad', 'version'],
            capture_output=True, text=True, check=False, timeout=5, encoding='utf-8'
        )
        # --- MODIFIED CONDITION ---
        # If return code is 0, consider the CLI present and functional enough.
        if result.returncode == 0:
            # Log the actual version output for debugging if needed
            version_output = result.stdout.strip()
            logger.info(f"Mullvad CLI check successful. Output: '{version_output}'")
            return True
        # --- END MODIFIED CONDITION ---
        else:
            # Log error if return code is non-zero
            stderr_output = result.stderr.strip()
            logger.error(f"Mullvad CLI check command failed. Return code: {result.returncode}, Stderr: '{stderr_output}'")
            return False
    except FileNotFoundError:
        logger.error("Mullvad CLI command ('mullvad') not found in PATH.")
        return False
    except subprocess.TimeoutExpired:
        logger.error("Mullvad CLI check command timed out.")
        return False
    except Exception as e:
        logger.exception(f"Unexpected error during Mullvad CLI check: {e}")
        return False


# --- Main Execution ---

def main():
    """Main entry point for the Mullvad Server Finder application."""
    logger.info("--- Mullvad Server Finder Application Starting ---")
    set_dpi_awareness()

    # Check critical dependencies
    if not check_dependencies():
        logger.critical("Mullvad CLI dependency check failed. Application cannot continue.")
        messagebox.showerror(
            "Dependency Error",
            "Mullvad CLI ('mullvad') not found or not working.\n\n"
            "Please ensure the Mullvad VPN client is installed correctly "
            "and the 'mullvad' command is accessible in your system's PATH."
        )
        sys.exit(1)


    # --- Initialize Tkinter Root ---
    root = tk.Tk()
    root.withdraw() # Hide the window initially

    # Set window title (already done in GUI class, but can set initial here)
    root.title("Mullvad Server Finder")
    # Set minimum size
    root.minsize(800, 500)

    # --- Initialize and Run Application ---
    try:
        app = MullvadFinderApp(root)
        root.deiconify() # Show the window after initialization
        logger.info("Starting Tkinter main loop...")
        root.mainloop()
        logger.info("Tkinter main loop finished.")

    except Exception as e:
         logger.exception("An unhandled exception occurred during application execution.")
         messagebox.showerror("Fatal Error", f"An unexpected error occurred:\n{e}\n\nPlease check the log file:\n{log_file_path}")
         try:
             root.destroy() # Attempt to close the window gracefully
         except:
             pass # Ignore errors during destroy
         sys.exit(1)

    logger.info("--- Mullvad Server Finder Application Exiting ---")


if __name__ == "__main__":
    # Add guard for multiprocessing on Windows if ever needed
    # if platform.system() == "Windows":
    #     import multiprocessing
    #     multiprocessing.freeze_support()
    main()