import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import time
import platform
import os
import csv
import json
import pickle
import itertools
import logging
from threading import Event
from typing import Optional, List, Dict, Any, Set, Tuple
import subprocess

# --- SV-TTK Import ---
try:
    import sv_ttk
except ImportError:
    sv_ttk = None # Flag that sv_ttk is not available
    # Logger might not be configured yet, print is safer here initially
    print("WARNING: sv-ttk library not found. Falling back to default ttk theme. "
          "Install using: pip install sv-ttk")
# --- END SV-TTK Import ---


# Setup logger for this module
logger = logging.getLogger(__name__)

# Import API and Server Manager functions
try:
    from mullvad_api import (load_cached_servers, set_mullvad_location,
                             set_mullvad_protocol, connect_mullvad,
                             disconnect_mullvad, get_mullvad_status, MullvadCLIError)
    from server_manager import (get_all_servers, get_servers_by_country,
                               test_servers, filter_servers_by_protocol,
                               export_to_csv, calculate_latency_color,
                               calculate_speed_color, run_socket_ping_pong_test)
    # --- MODIFIED IMPORT ---
    from config import (load_config, save_config, add_favorite_server,
                       remove_favorite_server, get_cache_path, get_log_path, # Added get_log_path
                       get_default_cache_path) # Added get_default_cache_path
    # --- END MODIFIED IMPORT ---
except ImportError as e:
    logger.exception("Failed to import necessary modules. Ensure all files are present.")
    # Show error immediately if GUI can't even start
    root = tk.Tk()
    root.withdraw() # Hide the root window
    messagebox.showerror("Import Error", f"Failed to import modules: {e}\nPlease ensure all script files are in the same directory.")
    exit() # Exit if core components are missing


# --- Constants ---
CHECKBOX_UNCHECKED = "☐"
CHECKBOX_CHECKED = "☑"

# --- Helper Functions ---
def get_flag_emoji(country_code: str) -> str:
    """Converts a two-letter country code (ISO 3166-1 alpha-2) to a flag emoji."""
    if not country_code or len(country_code) != 2:
        return "" # Return empty string for invalid codes
    # Regional Indicator Symbol Letters start at 0x1F1E6
    # A = 0x1F1E6, B = 0x1F1E7, ..., Z = 0x1F1FF
    try:
        offset = 0x1F1E6 - ord('A')
        point1 = chr(ord(country_code[0].upper()) + offset)
        point2 = chr(ord(country_code[1].upper()) + offset)
        return point1 + point2
    except Exception:
        logger.warning(f"Could not generate flag emoji for code: {country_code}")
        return "" # Fallback

# --- Helper Classes ---

class LoadingAnimation:
    """Class to handle loading animation in the status bar."""
    def __init__(self, label_var: tk.StringVar, original_text: str, animation_frames: Optional[List[str]] = None):
        self.label_var = label_var
        self.original_text = original_text
        # --- USE UNICODE BRAILLE CHARACTERS ---
        self.animation_frames = animation_frames or ['⣾', '⣽', '⣻', '⢿', '⡿', '⣟', '⣯', '⣷']
        # Fallback if Unicode causes issues: self.animation_frames = animation_frames or ['|', '/', '-', '\\']
        # --- END CHANGE ---
        self.is_running = False
        self.current_frame = 0
        self.after_id: Optional[str] = None
        self.root: Optional[tk.Tk] = None
    def start(self, root: tk.Tk):
        """Start the loading animation."""
        if self.is_running:
            return
        self.root = root
        self.is_running = True
        self.current_frame = 0 # Reset frame index
        self.animate()
        logger.debug("Loading animation started.")

    def stop(self):
        """Stop the loading animation."""
        if not self.is_running:
            return
        self.is_running = False
        if self.after_id and self.root:
            try:
                self.root.after_cancel(self.after_id)
                logger.debug(f"Cancelled after_id: {self.after_id}")
            except Exception as e:
                 logger.warning(f"Error cancelling animation after_id: {e}")
            self.after_id = None
        # Ensure the final text is set correctly even if root is gone
        try:
            self.label_var.set(self.original_text)
        except Exception as e:
             logger.warning(f"Error setting label_var on stop: {e}")
        logger.debug("Loading animation stopped.")


    def animate(self):
        """Update the animation frame."""
        if not self.is_running or not self.root:
            return
        # Update with the next animation frame
        try:
            frame = self.animation_frames[self.current_frame]
            self.label_var.set(f"{self.original_text} {frame}")

            # Move to the next frame
            self.current_frame = (self.current_frame + 1) % len(self.animation_frames)

            # Schedule the next update
            self.after_id = self.root.after(150, self.animate)
            # logger.debug(f"Scheduled next animation frame, after_id: {self.after_id}")
        except Exception as e:
             # Catch errors if the root window is destroyed during animation
             logger.error(f"Error during animation cycle: {e}")
             self.stop()

    def update_text(self, new_text: str):
        """Update the text portion of the animation."""
        self.original_text = new_text
        # Update immediately if not running, otherwise next cycle will show it
        if not self.is_running:
             try:
                 self.label_var.set(self.original_text)
             except Exception as e:
                 logger.warning(f"Error setting label_var on update_text: {e}")


# --- Main Application Class ---

class MullvadFinderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Mullvad Server Finder")
        self.root.geometry("950x650") # Slightly larger default size

        # --- Initialization ---
        logger.info("Initializing MullvadFinderApp...")
        self._setup_icon()
        self.config = load_config()
        # self.theme_colors needed later by apply_theme
        self.theme_colors: Dict[str, str] = {}
        self.main_frame: Optional[ttk.Frame] = None # Store reference to main frame

        # --- State Variables ---
        self.server_data: Optional[Dict[str, Any]] = None
        self.countries: List[Dict[str, str]] = []
        self.current_country_var = tk.StringVar()
        self.protocol_var = tk.StringVar(value=self.config.get("last_protocol", "wireguard"))
        self.status_var = tk.StringVar(value="Initializing...")
        self.test_type_var = tk.StringVar(value=self.config.get("test_type", "ping"))
        self.current_operation = tk.StringVar(value="Ready")
        self.ping_in_progress = False
        self.speed_in_progress = False
        self.sort_column = self.config.get("default_sort_column", "latency")
        self.sort_order = self.config.get("default_sort_order", "ascending")
        self.selected_server_items: Set[str] = set() # Stores item IDs of checked servers
        self.theme_var = tk.StringVar(value=self.config.get("theme_mode", "system")) # Initialize theme_var here

        # --- Thread Control ---
        self.stop_event = Event()
        self.pause_event = Event()

        # --- UI Elements (placeholders, created in create_ui) ---
        # Initialize all UI widget variables to None first
        self.server_tree: Optional[ttk.Treeview] = None
        self.test_button: Optional[ttk.Button] = None
        self.connect_button: Optional[ttk.Button] = None
        self.country_combo: Optional[ttk.Combobox] = None
        self.progress_bar: Optional[ttk.Progressbar] = None
        self.progress_var = tk.DoubleVar()
        self.operation_label: Optional[ttk.Label] = None
        self.control_frame: Optional[ttk.Frame] = None
        self.pause_button: Optional[ttk.Button] = None
        self.stop_button: Optional[ttk.Button] = None
        self.status_label: Optional[ttk.Label] = None # Reference to status label itself

        # --- Other ---
        self.loading_animation = LoadingAnimation(self.current_operation, "Ready")
        self.created_cell_tags: Set[str] = set() # Track dynamic tags for cell colors
        self.status_update_after_id: Optional[str] = None

        # --- Build UI First ---
        self.create_menu()
        self.create_ui() # <-- Create the widgets here

        # --- Apply Theme *After* UI is Built ---
        self.apply_theme() # <-- Moved the call here

        # --- Post-UI Setup ---
        self.load_server_data() # Initial data load
        self.update_status()    # Start status polling
        self._update_run_test_button_text() # Set initial button text

        logger.info("MullvadFinderApp initialization complete.")

    # --- UI Creation Helpers ---

    def _setup_icon(self):
        """Sets the application icon if available."""
        icon_name = 'mullvad_icon'
        icon_path = None
        try:
            # Basic check for icon file in the script's directory
            script_dir = os.path.dirname(os.path.abspath(__file__))
            potential_paths = [
                os.path.join(script_dir, f"{icon_name}.ico"),
                os.path.join(script_dir, f"{icon_name}.png"), # For other OS? Tk might handle png
                os.path.join(script_dir, f"{icon_name}.icns") # For completeness
            ]
            for p in potential_paths:
                if os.path.exists(p):
                    icon_path = p
                    break

            if not icon_path:
                 logger.warning("Application icon file not found.")
                 return

            if platform.system() == 'Windows' and icon_path.endswith(".ico"):
                self.root.iconbitmap(icon_path)
                logger.info(f"Set Windows icon: {icon_path}")
            # Add elif for Linux/macOS if specific Tk commands are needed for other formats
            # elif platform.system() == 'Darwin': ...
            else:
                 # Try setting PhotoImage for other systems (might work for PNG)
                 try:
                     img = tk.PhotoImage(file=icon_path)
                     self.root.iconphoto(True, img)
                     logger.info(f"Set icon using PhotoImage: {icon_path}")
                 except tk.TclError:
                     logger.warning(f"Could not set icon {icon_path} using PhotoImage (format might be unsupported).")

        except Exception as e:
            logger.error(f"Error setting application icon: {e}")

    def create_menu(self):
        """Create the application menu bar."""
        menubar = tk.Menu(self.root)

        # File Menu
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Reload Server Data", command=self.load_server_data, accelerator="Ctrl+R")
        file_menu.add_command(label="Export to CSV...", command=self.export_to_csv, accelerator="Ctrl+E")
        file_menu.add_separator()
        file_menu.add_command(label="Save Test Results...", command=self.save_test_results, accelerator="Ctrl+S")
        file_menu.add_command(label="Load Test Results...", command=self.load_test_results, accelerator="Ctrl+L")
        file_menu.add_command(label="Clear All Results", command=self.clear_all_results)
        file_menu.add_separator()
        file_menu.add_command(label="Settings", command=self.open_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)
        # Bind accelerators
        self.root.bind_all("<Control-r>", lambda e: self.load_server_data())
        self.root.bind_all("<Control-e>", lambda e: self.export_to_csv())
        self.root.bind_all("<Control-s>", lambda e: self.save_test_results())
        self.root.bind_all("<Control-l>", lambda e: self.load_test_results())


        # Connection Menu
        connection_menu = tk.Menu(menubar, tearoff=0)
        connection_menu.add_command(label="Connect to Selected", command=self.connect_selected, accelerator="Ctrl+C")
        connection_menu.add_command(label="Connect to Fastest", command=self.connect_to_fastest)
        connection_menu.add_separator()
        connection_menu.add_command(label="Disconnect", command=self.disconnect, accelerator="Ctrl+D")
        menubar.add_cascade(label="Connection", menu=connection_menu)
        self.root.bind_all("<Control-c>", lambda e: self.connect_selected())
        self.root.bind_all("<Control-d>", lambda e: self.disconnect())

        # Test Menu
        test_menu = tk.Menu(menubar, tearoff=0)
        test_menu.add_command(label="Run Test (using selection)", command=self.start_tests, accelerator="Ctrl+T")
        test_menu.add_separator()
        test_menu.add_command(label="Run Ping Test", command=lambda: self.start_tests(test_type="ping"))
        test_menu.add_command(label="Run Speed Test", command=lambda: self.start_tests(test_type="speed"))
        test_menu.add_command(label="Run Ping & Speed Test", command=lambda: self.start_tests(test_type="both"))
        test_menu.add_separator()
        test_menu.add_command(label="Stop Current Test", command=self.stop_tests, accelerator="Ctrl+X")
        menubar.add_cascade(label="Test", menu=test_menu)
        self.root.bind_all("<Control-t>", lambda e: self.start_tests())
        self.root.bind_all("<Control-x>", lambda e: self.stop_tests())


        # Favorites Menu
        favorites_menu = tk.Menu(menubar, tearoff=0)
        favorites_menu.add_command(label="Add Selected to Favorites", command=self.add_selected_to_favorites, accelerator="Ctrl+F")
        favorites_menu.add_command(label="Manage Favorites", command=self.manage_favorites)
        menubar.add_cascade(label="Favorites", menu=favorites_menu)
        self.root.bind_all("<Control-f>", lambda e: self.add_selected_to_favorites())

        # View Menu
        view_menu = tk.Menu(menubar, tearoff=0)
        # Theme Submenu
        theme_menu = tk.Menu(view_menu, tearoff=0)
        # self.theme_var is initialized in __init__ now
        theme_menu.add_radiobutton(label="System", variable=self.theme_var, value="system", command=self.change_theme)
        theme_menu.add_radiobutton(label="Light", variable=self.theme_var, value="light", command=self.change_theme)
        theme_menu.add_radiobutton(label="Dark", variable=self.theme_var, value="dark", command=self.change_theme)
        view_menu.add_cascade(label="Theme", menu=theme_menu)
        # Sort Submenu (removed commands, handled by clicking headers)
        view_menu.add_command(label="Sort by...", command=lambda: messagebox.showinfo("Sort", "Click column headers to sort."))
        menubar.add_cascade(label="View", menu=view_menu)

        # Help Menu
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)

    def _create_top_frame(self, parent: ttk.Frame):
        """Creates the top frame with filters and controls."""
        top_frame = ttk.Frame(parent)
        top_frame.pack(fill=tk.X, pady=(0, 10), padx=5)

        # Country selection
        ttk.Label(top_frame, text="Country:").pack(side=tk.LEFT, padx=(0, 5))
        self.country_combo = ttk.Combobox(top_frame, textvariable=self.current_country_var, width=20, state="readonly")
        self.country_combo.pack(side=tk.LEFT, padx=(0, 10))
        self.country_combo.bind("<<ComboboxSelected>>", self.on_country_selected)

        # Protocol selection
        ttk.Label(top_frame, text="Protocol:").pack(side=tk.LEFT, padx=(0, 5))
        protocol_combo = ttk.Combobox(top_frame, textvariable=self.protocol_var, values=["wireguard", "openvpn", "both"], width=10, state="readonly")
        protocol_combo.pack(side=tk.LEFT, padx=(0, 10))
        protocol_combo.bind("<<ComboboxSelected>>", self.on_protocol_selected)

        # Test type selection
        ttk.Label(top_frame, text="Test Type:").pack(side=tk.LEFT, padx=(0, 5))
        test_type_combo = ttk.Combobox(top_frame, textvariable=self.test_type_var,
                                       values=["ping", "speed", "both"], width=8, state="readonly")
        test_type_combo.pack(side=tk.LEFT, padx=(0, 15))
        test_type_combo.bind("<<ComboboxSelected>>", self.on_test_type_selected)

        # Action buttons
        self.test_button = ttk.Button(top_frame, text="Run Test", command=self.start_tests)
        self.test_button.pack(side=tk.LEFT, padx=(0, 5))

        self.connect_button = ttk.Button(top_frame, text="Connect", command=self.connect_selected)
        self.connect_button.pack(side=tk.LEFT, padx=(0, 15))


        # Status display (aligned right)
        status_frame = ttk.Frame(top_frame)
        status_frame.pack(side=tk.RIGHT, padx=(10, 0))
        ttk.Label(status_frame, text="Status:").pack(side=tk.LEFT)
        # Use a dedicated label widget to potentially change its style (e.g., color)
        # Removed fixed width to prevent truncation
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var, anchor=tk.W)
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _create_middle_frame(self, parent: ttk.Frame):
        """Creates the middle frame with the server list Treeview."""
        middle_frame = ttk.Frame(parent)
        middle_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        # Define columns including the new checkbox column
        columns = ("selected", "hostname", "city", "country", "protocol", "latency", "download", "upload")
        self.server_tree = ttk.Treeview(middle_frame, columns=columns, show="headings")

        # Define headings with sort commands
        self.server_tree.heading("selected", text=CHECKBOX_UNCHECKED, anchor=tk.CENTER,
                                 command=lambda: self._toggle_all_checkboxes()) # Add toggle all functionality
        # Center align headings
        self.server_tree.heading("hostname", text="Hostname", anchor=tk.CENTER, command=lambda: self.sort_treeview("hostname"))
        self.server_tree.heading("city", text="City", anchor=tk.CENTER, command=lambda: self.sort_treeview("city"))
        self.server_tree.heading("country", text="Country", anchor=tk.CENTER, command=lambda: self.sort_treeview("country"))
        self.server_tree.heading("protocol", text="Protocol", anchor=tk.CENTER, command=lambda: self.sort_treeview("protocol"))
        self.server_tree.heading("latency", text="Latency (ms)", anchor=tk.CENTER, command=lambda: self.sort_treeview("latency"))
        self.server_tree.heading("download", text="DL (Mbps, Sock)", anchor=tk.CENTER, command=lambda: self.sort_treeview("download"))
        self.server_tree.heading("upload", text="UL (Mbps, Sock)", anchor=tk.CENTER, command=lambda: self.sort_treeview("upload"))

        # Define column properties (widths, alignment, stretch)
        # Center align column content
        self.server_tree.column("selected", width=80, minwidth=35, stretch=tk.NO, anchor=tk.CENTER)
        self.server_tree.column("hostname", width=200, stretch=tk.YES, anchor=tk.CENTER)
        self.server_tree.column("city", width=120, stretch=tk.YES, anchor=tk.CENTER)
        self.server_tree.column("country", width=120, stretch=tk.YES, anchor=tk.CENTER)
        self.server_tree.column("protocol", width=80, stretch=tk.NO, anchor=tk.CENTER)
        self.server_tree.column("latency", width=90, stretch=tk.NO, anchor=tk.CENTER)
        self.server_tree.column("download", width=110, stretch=tk.NO, anchor=tk.CENTER)
        self.server_tree.column("upload", width=110, stretch=tk.NO, anchor=tk.CENTER)

        # Scrollbars
        tree_scroll_y = ttk.Scrollbar(middle_frame, orient=tk.VERTICAL, command=self.server_tree.yview)
        tree_scroll_x = ttk.Scrollbar(middle_frame, orient=tk.HORIZONTAL, command=self.server_tree.xview)
        self.server_tree.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)

        # Layout with grid for better scrollbar placement
        middle_frame.grid_rowconfigure(0, weight=1)
        middle_frame.grid_columnconfigure(0, weight=1)
        self.server_tree.grid(row=0, column=0, sticky='nsew')
        tree_scroll_y.grid(row=0, column=1, sticky='ns')
        tree_scroll_x.grid(row=1, column=0, sticky='ew')

        # Configure tags for row colors (will be applied/overridden by theme)
        self.server_tree.tag_configure('odd_row', background=self.theme_colors.get("row_odd", "#F8F8F8"))
        self.server_tree.tag_configure('even_row', background=self.theme_colors.get("row_even", "#FFFFFF"))

        # Bind click event for checkbox toggling
        self.server_tree.bind("<Button-1>", self._on_tree_click)
        # Bind double-click to connect
        self.server_tree.bind("<Double-1>", lambda e: self.connect_selected())


    def _create_bottom_frame(self, parent: ttk.Frame):
        """Creates the bottom frame with progress bar and status."""
        bottom_frame = ttk.Frame(parent)
        bottom_frame.pack(fill=tk.X, pady=(10, 0), padx=5)

        # Operation label (with animation)
        self.operation_label = ttk.Label(bottom_frame, textvariable=self.current_operation, anchor=tk.W)
        self.operation_label.pack(side=tk.LEFT, padx=(0, 10))

        # Control buttons (Pause/Stop) - initially hidden
        self.control_frame = ttk.Frame(bottom_frame)
        # Don't pack yet, pack when needed

        self.pause_button = ttk.Button(self.control_frame, text="Pause", command=self.pause_resume_test)
        self.pause_button.pack(side=tk.LEFT, padx=(0, 5))

        self.stop_button = ttk.Button(self.control_frame, text="Stop", command=self.stop_tests)
        self.stop_button.pack(side=tk.LEFT)

        # Progress bar (aligned right)
        self.progress_bar = ttk.Progressbar(bottom_frame, variable=self.progress_var, mode="determinate")
        self.progress_bar.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(10, 0))


    def create_ui(self):
        """Create the main user interface by calling helper methods."""
        self.main_frame = ttk.Frame(self.root, padding=10) # Store reference
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        self._create_top_frame(self.main_frame)
        self._create_middle_frame(self.main_frame)
        self._create_bottom_frame(self.main_frame)


    # --- Event Handlers & UI Logic ---

    def _on_tree_click(self, event):
        """Handle clicks on the Treeview, specifically for checkbox toggling."""
        if not self.server_tree: return
        region = self.server_tree.identify_region(event.x, event.y)
        if region == "cell":
            column_id = self.server_tree.identify_column(event.x)
            item_id = self.server_tree.identify_row(event.y)

            # Check if the click was on the first column ("selected")
            if column_id == "#1" and item_id: # "#1" is the first column's ID
                 self._toggle_checkbox(item_id)

    def _toggle_checkbox(self, item_id: str):
         """Toggles the checkbox state for a given item ID."""
         if not self.server_tree: return
         current_value = self.server_tree.set(item_id, "#1")
         new_value = CHECKBOX_CHECKED if current_value == CHECKBOX_UNCHECKED else CHECKBOX_UNCHECKED
         self.server_tree.set(item_id, "#1", new_value)

         # Update the selection set
         if new_value == CHECKBOX_CHECKED:
             self.selected_server_items.add(item_id)
         else:
             self.selected_server_items.discard(item_id)

         # Update the run button text
         self._update_run_test_button_text()

    def _toggle_all_checkboxes(self):
        """Toggles all visible checkboxes based on the current state of the first item."""
        if not self.server_tree: return
        all_items = self.server_tree.get_children('')
        if not all_items:
            return

        # Determine target state based on the first item (or assume unchecked if mixed)
        first_item_state = self.server_tree.set(all_items[0], "#1")
        target_state = CHECKBOX_CHECKED if first_item_state == CHECKBOX_UNCHECKED else CHECKBOX_UNCHECKED
        self.server_tree.heading("selected", text=target_state) # Update header checkbox

        self.selected_server_items.clear() # Clear existing selection first

        for item_id in all_items:
            self.server_tree.set(item_id, "#1", target_state)
            if target_state == CHECKBOX_CHECKED:
                self.selected_server_items.add(item_id)

        self._update_run_test_button_text()


    def _update_run_test_button_text(self):
        """Updates the 'Run Test' button text based on checkbox selections."""
        if not self.test_button: return # UI not fully created yet

        num_selected = len(self.selected_server_items)
        base_text = "Run"

        # Add specific test type to button text
        test_type = self.test_type_var.get()
        if test_type == "ping":
            base_text = "Run Ping Test"
        elif test_type == "speed":
            base_text = "Run Speed Test"
        else: # both
            base_text = "Run Full Test"


        if num_selected > 0:
            self.test_button.configure(text=f"{base_text} on Selected ({num_selected})")
        else:
            self.test_button.configure(text=f"{base_text} on All Visible")

    def on_country_selected(self, event=None): # Add event=None for direct calls
        """Handle country selection change."""
        logger.info(f"Country selected: {self.current_country_var.get()}")
        self.load_servers_by_country()

    def on_protocol_selected(self, event=None):
        """Handle protocol selection change."""
        protocol = self.protocol_var.get()
        logger.info(f"Protocol selected: {protocol}")
        self.config["last_protocol"] = protocol
        save_config(self.config)
        self.load_servers_by_country() # Reload servers with the new protocol filter

    def on_test_type_selected(self, event=None):
        """Handle test type selection change."""
        test_type = self.test_type_var.get()
        logger.info(f"Test type selected: {test_type}")
        self.config["test_type"] = test_type
        save_config(self.config)
        self._update_run_test_button_text() # Update button text immediately


    # --- Data Loading and Display ---

    def load_server_data(self):
        """Load Mullvad server data from cache and populate countries."""
        self.loading_animation.update_text("Loading server data...")
        self.loading_animation.start(self.root)
        self.root.update_idletasks() # Ensure UI updates

        try:
            cache_path = get_cache_path(self.config)
            logger.info(f"Using cache path: {cache_path}")
            self.server_data = load_cached_servers(cache_path)

            if not self.server_data:
                messagebox.showerror("Error", f"Failed to load server data from {cache_path}.\nCheck path in Settings or logs for details.", parent=self.root)
                self.loading_animation.update_text("Error loading data")
                self.loading_animation.stop() # Stop animation on error
                return

            # Extract and sort countries
            self.countries = [
                {"code": country.get("code", ""), "name": country.get("name", "Unknown")}
                for country in self.server_data.get("countries", [])
            ]
            self.countries.sort(key=lambda x: x["name"])
            # --- ADD FLAGS TO COUNTRY NAMES ---
            country_names = ["All Countries"] + [
                f"{get_flag_emoji(c['code'])} {c['name']}" for c in self.countries
            ]
            # --- END CHANGE ---
            if not self.countries: # Add a check here
                 logger.warning("No countries found in the loaded server data structure.")
                 messagebox.showwarning("Warning", "No countries were found in the server data file.", parent=self.root)
            else:
                 logger.info(f"Populated {len(self.countries)} countries from data file.")

            if self.country_combo:
                self.country_combo["values"] = country_names

            # Restore last selected country or default to "All Countries"
            last_country_code = self.config.get("last_country", "")
            selected_country_display_name = "All Countries" # Default
            if last_country_code:
                for country in self.countries:
                    if country["code"] == last_country_code:
                        # Find the display name with the flag
                        selected_country_display_name = f"{get_flag_emoji(country['code'])} {country['name']}"
                        break
            self.current_country_var.set(selected_country_display_name)
            logger.info(f"Populated {len(self.countries)} active countries. Selected: {selected_country_display_name}")

            # Load servers for the initially selected country
            self.load_servers_by_country()
            self.loading_animation.update_text("Server data loaded")

        except Exception as e:
            logger.exception("An error occurred during server data loading.")
            messagebox.showerror("Error", f"An unexpected error occurred loading server data: {e}", parent=self.root)
            self.loading_animation.update_text("Error loading data")
        finally:
             # Ensure animation stops after a short delay to show final message
             self.root.after(500, self.loading_animation.stop)


    def load_servers_by_country(self):
        """Load servers for the selected country/protocol into the Treeview."""
        if not self.server_data or not self.server_tree:
            logger.warning("load_servers_by_country called before data or UI ready.")
            return

        logger.info(f"Loading servers for country: '{self.current_country_var.get()}', protocol: '{self.protocol_var.get()}'")
        self.loading_animation.update_text("Filtering servers...")
        self.loading_animation.start(self.root)
        self.root.update_idletasks()

        # Clear current treeview items and selection
        self.server_tree.delete(*self.server_tree.get_children())
        self.selected_server_items.clear()
        self.server_tree.heading("selected", text=CHECKBOX_UNCHECKED) # Reset header checkbox

        # Handle "All Countries" case before stripping flag
        country_display_name = self.current_country_var.get()
        if country_display_name == "All Countries":
            country_name = "All Countries"
        else:
            # Strip flag emoji for lookup logic
            country_name = country_display_name.split(" ", 1)[-1] if len(country_display_name.split(" ", 1)) > 1 else country_display_name

        protocol_filter = self.protocol_var.get()
        if protocol_filter == "both":
            protocol_filter = None # Pass None to server manager

        servers: List[Dict[str, Any]] = []
        if country_name == "All Countries":
            servers = get_all_servers(self.server_data, protocol_filter)
            self.config["last_country"] = "" # Clear last country if 'All' is selected
        else:
            # Find country code based on name without flag
            country_code = next((c["code"] for c in self.countries if c["name"] == country_name), None)
            if country_code:
                self.config["last_country"] = country_code
                servers = get_servers_by_country(self.server_data, country_code, protocol_filter)
            else:
                logger.error(f"Could not find country code for selected name: {country_name}")

        save_config(self.config) # Save potential last_country change

        # Populate treeview
        use_alt_colors = self.config.get("alternating_row_colors", True)
        for i, server in enumerate(servers):
            hostname = server.get("hostname", "N/A")
            city = server.get("city", "N/A")
            country_name_only = server.get("country", "N/A")
            # Get country code directly from server data if available (might need adjustment in server_manager)
            country_code = server.get("country_code", "")
            # If not directly available, look it up (less efficient)
            if not country_code:
                 country_code = next((c["code"] for c in self.countries if c["name"] == country_name_only), "")

            country_display = f"{get_flag_emoji(country_code)} {country_name_only}" if country_code else country_name_only

            # --- CORRECTED PROTOCOL DISPLAY LOGIC ---
            endpoint_data = server.get("endpoint_data")
            if isinstance(endpoint_data, dict) and "wireguard" in endpoint_data:
                protocol_str = "WireGuard"
            elif isinstance(endpoint_data, str) and endpoint_data == "openvpn":
                protocol_str = "OpenVPN"
            elif isinstance(endpoint_data, str) and endpoint_data == "bridge":
                 protocol_str = "Bridge" # Display Bridge type too
            else:
                 # Fallback based on hostname if endpoint_data is weird/missing
                 hn_lower = hostname.lower()
                 protocol_str = "WireGuard" if (hn_lower.endswith("-wg") or ".wg." in hn_lower) else "OpenVPN"
                 logger.warning(f"Using hostname fallback for protocol display for {hostname}. endpoint_data: {endpoint_data}")
            # --- END CORRECTION ---

            # Assign alternating row tag if enabled
            tags = []
            if use_alt_colors:
                 tags.append('odd_row' if i % 2 else 'even_row')

            # Insert item with checkbox unchecked initially
            # Make sure the indices match the column order:
            # ("selected", "hostname", "city", "country", "protocol", "latency", "download", "upload")
            # Index 0: Checkbox
            # Index 1: Hostname
            # Index 2: City
            # Index 3: Country (with flag)
            # Index 4: Protocol
            # Index 5: Latency
            # Index 6: Download
            # Index 7: Upload
            self.server_tree.insert("", tk.END, values=(
                CHECKBOX_UNCHECKED, hostname, city, country_display, protocol_str, "", "", ""
            ), tags=tags)

        logger.info(f"Displayed {len(servers)} servers in the list.")

        # Apply initial sort and update button text
        self.sort_treeview(self.sort_column, force_order=self.sort_order)
        self._update_run_test_button_text()

        self.loading_animation.update_text(f"{len(servers)} servers loaded")
        self.root.after(500, self.loading_animation.stop)

    def sort_treeview(self, column: str, force_order: Optional[str] = None):
        """Sort the treeview by the specified column."""
        if not self.server_tree: return
        logger.debug(f"Sorting Treeview by column '{column}', force_order='{force_order}'")

        # Determine new sort order
        if column == self.sort_column and not force_order:
            self.sort_order = "descending" if self.sort_order == "ascending" else "ascending"
        else:
            self.sort_column = column
            self.sort_order = force_order if force_order else "ascending"

        # Update config for persistence
        self.config["default_sort_column"] = self.sort_column
        self.config["default_sort_order"] = self.sort_order
        # No need to save config on every sort, maybe save on exit? For now, keep it simple.
        # save_config(self.config)

        items = [(self.server_tree.set(item_id, column), item_id) for item_id in self.server_tree.get_children('')]

        # Define conversion logic for different columns
        def get_sort_key(value_str: str) -> Any:
            if column in ['latency', 'download', 'upload']:
                if not value_str or value_str == "Timeout":
                    return float('inf') # Place timeouts/empty values last
                try:
                    return float(value_str)
                except ValueError:
                    return float('inf') # Treat non-numeric as infinite
            elif column == 'selected':
                 return 0 if value_str == CHECKBOX_CHECKED else 1 # Checked items first
            else: # String columns (strip flag for country sort)
                if column == 'country' and len(value_str.split(" ", 1)) > 1:
                     value_str = value_str.split(" ", 1)[-1]
                return str(value_str).lower() # Case-insensitive string sort

        # Sort items using the key function
        try:
             items.sort(key=lambda x: get_sort_key(x[0]), reverse=(self.sort_order == "descending"))
        except Exception as e:
             logger.exception(f"Error during sorting prep for column {column}: {e}")
             return # Abort sort if conversion fails

        # Rearrange items in the treeview
        use_alt_colors = self.config.get("alternating_row_colors", True)
        for index, (_, item_id) in enumerate(items):
            self.server_tree.move(item_id, '', index)

            # Update row tags for alternating colors if enabled
            if use_alt_colors:
                try:
                    current_tags = list(self.server_tree.item(item_id, "tags"))
                    # Keep only non-row-color tags (and potentially cell tags)
                    filtered_tags = [tag for tag in current_tags if not tag.startswith(('odd_row', 'even_row'))]
                    # Add back the correct row color tag
                    row_tag = 'odd_row' if index % 2 else 'even_row'
                    filtered_tags.append(row_tag)
                    self.server_tree.item(item_id, tags=tuple(filtered_tags)) # Use tuple for tags
                except tk.TclError:
                    logger.warning(f"TCL error updating tags for item {item_id} during sort (item might be gone).")
                    continue # Skip to next item

        logger.debug(f"Treeview sorted by {self.sort_column} {self.sort_order}.")


    # --- Testing Logic ---

    def start_tests(self, test_type: Optional[str] = None):
        """Start tests based on the selected type and checkbox selection."""
        if self.ping_in_progress or self.speed_in_progress:
            messagebox.showwarning("Test in Progress", "A test is already running.", parent=self.root)
            return

        # Determine test type
        effective_test_type = test_type or self.test_type_var.get()
        logger.info(f"Starting test: type='{effective_test_type}', selection based.")

        # Determine which servers to test
        if not self.server_tree: return
        target_item_ids = list(self.selected_server_items)
        if not target_item_ids: # If nothing selected, test all visible
             target_item_ids = list(self.server_tree.get_children(''))
             logger.info("No servers selected via checkbox, testing all visible servers.")
        else:
             logger.info(f"Testing {len(target_item_ids)} servers selected via checkbox.")


        if not target_item_ids:
            messagebox.showinfo("No Servers", "No servers found to test.", parent=self.root)
            return

        # Get full server details for the target items
        servers_to_test: List[Dict[str, Any]] = []
        for item_id in target_item_ids:
            server_details = self._get_server_details_from_item_id(item_id)
            if server_details:
                 server_details["treeview_item"] = item_id # Store item ID for UI updates
                 servers_to_test.append(server_details)
            else:
                 try:
                     hostname = self.server_tree.set(item_id, "hostname")
                     logger.warning(f"Could not find server data for hostname '{hostname}' (item {item_id}). Skipping.")
                 except tk.TclError:
                     logger.warning(f"Could not get hostname for item {item_id} (item might be gone). Skipping.")


        if not servers_to_test:
            messagebox.showerror("Error", "Could not retrieve details for any servers to test.", parent=self.root)
            return

        # --- Start Test Process ---
        self.stop_event.clear()
        self.pause_event.clear()
        if self.test_button: self.test_button.configure(state=tk.DISABLED)
        if self.connect_button: self.connect_button.configure(state=tk.DISABLED) # Disable connect during test
        self.progress_var.set(0)

        # Show control buttons (Pause/Stop)
        if self.control_frame and self.pause_button and self.stop_button:
            self.control_frame.pack(side=tk.LEFT, padx=(10, 0))
            self.pause_button.configure(text="Pause", state=tk.NORMAL)
            self.stop_button.configure(state=tk.NORMAL)

        operation_text = f"Starting {effective_test_type} test on {len(servers_to_test)} servers..."
        self.loading_animation.update_text(operation_text)
        self.loading_animation.start(self.root)

        # Launch the appropriate test thread
        if effective_test_type in ["ping", "both"]:
            self.ping_in_progress = True
            threading.Thread(target=self.run_ping_test, args=(servers_to_test, effective_test_type), daemon=True).start()
        elif effective_test_type == "speed":
            self.speed_in_progress = True
            threading.Thread(target=self.run_speed_test, args=(servers_to_test,), daemon=True).start()
        else:
             logger.error(f"Invalid test type requested: {effective_test_type}")
             self._test_cleanup() # Cleanup UI state


    def pause_resume_test(self):
        """Pause or resume the current test."""
        if self.pause_event.is_set():
            self.pause_event.clear()
            if self.pause_button: self.pause_button.configure(text="Pause")
            self.loading_animation.update_text("Resuming test...")
            logger.info("Test resumed.")
        else:
            self.pause_event.set()
            if self.pause_button: self.pause_button.configure(text="Resume")
            self.loading_animation.update_text("Test paused")
            logger.info("Test paused.")


    def stop_tests(self):
        """Stop all running tests."""
        if not (self.ping_in_progress or self.speed_in_progress):
            logger.info("Stop requested but no test running.")
            return

        logger.info("Stop requested. Signaling threads...")
        self.stop_event.set()
        # Ensure pause is cleared if we stop while paused
        if self.pause_event.is_set():
            self.pause_event.clear()

        # Update UI immediately
        self.loading_animation.update_text("Stopping tests...")
        if self.pause_button: self.pause_button.configure(state=tk.DISABLED)
        if self.stop_button: self.stop_button.configure(state=tk.DISABLED)
        # Test completion logic in finally blocks will handle full cleanup


    def _test_cleanup(self):
        """Internal helper to reset UI state after tests finish or are stopped."""
        logger.debug("Running test cleanup...")
        self.ping_in_progress = False
        self.speed_in_progress = False
        self.loading_animation.stop()
        if self.test_button: self.test_button.configure(state=tk.NORMAL)
        if self.connect_button: self.connect_button.configure(state=tk.NORMAL)
        if self.control_frame: self.control_frame.pack_forget() # Hide pause/stop buttons
        self.progress_var.set(0) # Reset progress bar
        # Ensure pause/stop buttons are re-enabled for next time
        if self.pause_button: self.pause_button.configure(state=tk.NORMAL)
        if self.stop_button: self.stop_button.configure(state=tk.NORMAL)


    def apply_cell_color(self, item_id: str, column_key: str, value: Any):
        """Apply Excel-style background color to a specific cell."""
        if not self.server_tree: return
        if value is None or value == "" or value == "Timeout" or value == float('inf'):
            # Optionally remove existing color tag for this cell?
            return

        color = "#FFFFFF" # Default white
        try:
            numeric_value = float(value)
            if column_key == "latency":
                 if self.config.get("color_latency", True):
                     color = calculate_latency_color(numeric_value)
                 else: return # Coloring disabled
            elif column_key in ["download", "upload"]:
                 if self.config.get("color_speed", True):
                     # Adjust max speed for color calculation if needed, e.g., based on results
                     color = calculate_speed_color(numeric_value, max_expected_speed=200.0)
                 else: return # Coloring disabled
            else:
                return # Not a colorable column

            # Skip if color is default or gray (no need for tag)
            if color.upper() in ["#FFFFFF", "#AAAAAA"]:
                 # TODO: Remove existing tag if needed
                 return

            # Create or reuse tag
            cell_tag = f"cell_{column_key}_{color.replace('#', '')}"
            if cell_tag not in self.created_cell_tags:
                # Use foreground color that contrasts with background
                # Simple check: dark background -> white text, light background -> black text
                r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
                text_color = "#FFFFFF" if (r*0.299 + g*0.587 + b*0.114) < 140 else "#000000"
                self.server_tree.tag_configure(cell_tag, background=color, foreground=text_color)
                self.created_cell_tags.add(cell_tag)

            # Apply tag (thread-safe via root.after)
            def _apply_tag():
                try:
                    if not self.server_tree or not self.server_tree.exists(item_id): return # Check if item still exists
                    current_tags = list(self.server_tree.item(item_id, "tags"))
                    # Remove previous color tag for this specific column
                    prefix = f"cell_{column_key}_"
                    filtered_tags = [tag for tag in current_tags if not tag.startswith(prefix)]
                    filtered_tags.append(cell_tag)
                    self.server_tree.item(item_id, tags=tuple(filtered_tags))
                except tk.TclError:
                     logger.warning(f"TCL error applying tag {cell_tag} to item {item_id} (item might be gone).")
                except Exception as e:
                    logger.exception(f"Error applying cell tag {cell_tag} to {item_id}: {e}")

            self.root.after(0, _apply_tag)

        except (ValueError, TypeError) as e:
            logger.debug(f"Cannot apply color: Value '{value}' for column '{column_key}' is not numeric. Error: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error applying cell color for item {item_id}, column {column_key}: {e}")


    def run_ping_test(self, servers: List[Dict[str, Any]], test_type: str):
        """Run ping test in background thread with UI updates."""
        logger.info(f"Ping test thread started for {len(servers)} servers.")
        start_time = time.time()
        try:
            def update_progress(percentage: float):
                 # Schedule UI update on the main thread
                 self.root.after(0, lambda p=percentage: self.progress_var.set(p))
                 # self.root.after(0, lambda p=percentage: self.loading_animation.update_text(
                 #    f"Pinging servers... {int(p)}%")) # Can be too verbose

            def update_result(result: Dict[str, Any]):
                server = result.get("server")
                latency = result.get("latency")
                if not server: return
                item_id = server.get("treeview_item")
                if not item_id: return

                latency_str = f"{latency:.1f}" if latency is not None else "Timeout"

                # Schedule UI update on the main thread
                def _update_ui():
                    try:
                        if not self.server_tree or not self.server_tree.exists(item_id): return # Check if item still exists
                        # Get current values, careful if item deleted
                        values = list(self.server_tree.item(item_id, "values"))
                        values[5] = latency_str # Latency is index 5 now
                        self.server_tree.item(item_id, values=tuple(values))
                        self.apply_cell_color(item_id, "latency", latency)
                    except tk.TclError:
                         logger.warning(f"TCL error updating item {item_id} (item might be gone).")
                    except Exception as e:
                        logger.exception(f"Error updating UI for ping result of item {item_id}: {e}")

                self.root.after(0, _update_ui)

            # Run the tests
            results = test_servers(
                servers,
                progress_callback=update_progress,
                result_callback=update_result,
                max_workers=self.config.get("max_workers", 10),
                ping_count=self.config.get("ping_count", 3),
                timeout_sec=self.config.get("timeout_seconds", 10),
                stop_event=self.stop_event,
                pause_event=self.pause_event
            )
            elapsed = time.time() - start_time
            logger.info(f"Ping test thread finished in {elapsed:.2f}s. Stop signaled: {self.stop_event.is_set()}")


            # If test was not stopped and it's "both", start speed test
            if not self.stop_event.is_set() and test_type == "both":
                 self.root.after(0, lambda: self.loading_animation.update_text("Ping complete. Starting speed test..."))
                 # Directly call speed test (it will run in this same thread sequentially)
                 # This might block UI updates if speed tests are long. Consider a new thread.
                 # For now, keep it simple:
                 self.ping_in_progress = False # Mark ping as done before starting speed
                 self.speed_in_progress = True
                 self.run_speed_test(servers) # Reuse the server list
                 return # Speed test finally block will handle cleanup

            # --- Ping test only or stopped ---
            if not self.stop_event.is_set():
                self.root.after(0, lambda: self.sort_treeview("latency"))
                self.root.after(0, self._highlight_fastest_server) # Select best result
                final_text = f"Ping test completed in {elapsed:.1f}s"
                if self.config.get("auto_connect_fastest", False):
                    self.root.after(100, self.connect_to_fastest) # Connect after slight delay
            else:
                 final_text = "Ping test stopped"

            self.root.after(0, lambda t=final_text: self.loading_animation.update_text(t))
            self.root.after(1000, self._test_cleanup) # Delay cleanup slightly


        except Exception as e:
            logger.exception("Error occurred within ping test thread.")
            self.root.after(0, lambda: messagebox.showerror("Ping Test Error", f"An error occurred: {e}", parent=self.root))
            self.root.after(0, lambda: self.loading_animation.update_text("Ping test failed"))
            self.root.after(500, self._test_cleanup) # Ensure cleanup happens on error
        finally:
            # Final check: if only ping was running, ensure cleanup happens
             if not self.speed_in_progress: # Only cleanup if speed test isn't taking over
                 self.root.after(0, self._test_cleanup)


    def _highlight_fastest_server(self):
        """Finds and selects the server with the lowest latency in the Treeview."""
        if not self.server_tree: return
        fastest_item_id: Optional[str] = None
        lowest_latency = float('inf')

        for item_id in self.server_tree.get_children(''):
            try:
                if not self.server_tree.exists(item_id): continue # Check if item still exists
                latency_str = self.server_tree.set(item_id, "latency")
                if latency_str and latency_str != "Timeout":
                    latency = float(latency_str)
                    if latency < lowest_latency:
                        lowest_latency = latency
                        fastest_item_id = item_id
            except (ValueError, tk.TclError):
                continue # Ignore conversion errors or missing items

        if fastest_item_id:
            try:
                if self.server_tree.exists(fastest_item_id): # Check again before using
                    logger.info(f"Highlighting fastest server: {self.server_tree.set(fastest_item_id, 'hostname')} ({lowest_latency:.1f} ms)")
                    self.server_tree.selection_set(fastest_item_id)
                    self.server_tree.focus(fastest_item_id)
                    self.server_tree.see(fastest_item_id)
            except tk.TclError:
                 logger.warning(f"TCL error highlighting fastest server {fastest_item_id} (item might be gone).")
        else:
             logger.info("Could not find a fastest server with valid latency to highlight.")


    def run_speed_test(self, servers: List[Dict[str, Any]]):
        """Run Socket Ping-Pong speed tests in background thread."""
        logger.info(f"Socket Ping-Pong test thread started for {len(servers)} servers.")
        start_time = time.time()
        total = len(servers)
        completed = 0

        # --- Fetch Config Option for Duration ---
        # Fetch from config or use default (e.g., 5 seconds)
        # Make sure this key exists in your DEFAULT_CONFIG in config.py if you add the setting
        test_duration = self.config.get("speed_test_duration", 5)
        # ---

        try:
            self.root.after(0, lambda: self.progress_var.set(0))
            self.root.after(0, lambda: self.loading_animation.update_text(f"Starting socket speed test ({test_duration}s) for {total} servers..."))

            for i, server in enumerate(servers):
                # Pause Check
                while self.pause_event.is_set():
                    if self.stop_event.is_set(): break # Allow stop while paused
                    time.sleep(0.5)
                # Stop Check
                if self.stop_event.is_set(): break

                hostname = server.get("hostname", "N/A")
                item_id = server.get("treeview_item")

                # Skip if item_id is missing or item no longer exists in tree
                if not item_id or not self.server_tree or not self.server_tree.exists(item_id):
                    logger.warning(f"Skipping speed test for {hostname} - item not found in tree.")
                    completed += 1 # Count as completed for progress bar
                    self.root.after(0, lambda c=completed, t=total: self.progress_var.set(c / t * 100))
                    continue

                # Update status before starting test for this server
                status_text = f"Sock Speed Test: {hostname} ({i+1}/{total})..."
                self.root.after(0, lambda txt=status_text: self.loading_animation.update_text(txt))

                # --- CORRECTED CALL TO THE PING-PONG TEST FUNCTION ---
                # Pass the fetched test_duration to the 'duration' argument
                # of the function in server_manager.py
                download_mbps, upload_mbps = run_socket_ping_pong_test(
                    server=server,
                    duration=test_duration, # Pass the value here
                    # chunk_size=..., # Pass if configured
                    # ports=..., # Pass if configured
                    stop_event=self.stop_event
                )
                # --- END CORRECTION ---

                # Check stop event again immediately after blocking call
                if self.stop_event.is_set(): break

                # Schedule UI update for this result
                def _update_ui(it=item_id, dl=download_mbps, ul=upload_mbps):
                    try:
                        if not self.server_tree or not self.server_tree.exists(it): return # Check if item still exists
                        values = list(self.server_tree.item(it, "values"))
                        values[6] = f"{dl:.1f}" if dl is not None else "" # Download is index 6
                        values[7] = f"{ul:.1f}" if ul is not None else "" # Upload is index 7
                        self.server_tree.item(it, values=tuple(values))

                        # Apply coloring
                        self.apply_cell_color(it, "download", dl)
                        self.apply_cell_color(it, "upload", ul)
                    except tk.TclError:
                        logger.warning(f"TCL error updating speed for item {it} (item might be gone).")
                    except Exception as e:
                         logger.exception(f"Error updating UI for speed result of item {it}: {e}")

                self.root.after(0, _update_ui)

                # Update overall progress
                completed += 1
                self.root.after(0, lambda c=completed, t=total: self.progress_var.set(c / t * 100))

            # --- Speed Test Loop Finished ---
            elapsed = time.time() - start_time
            logger.info(f"Speed test thread finished in {elapsed:.2f}s. Stop signaled: {self.stop_event.is_set()}")

            if not self.stop_event.is_set():
                 self.root.after(0, lambda: self.sort_treeview("download")) # Sort by download speed
                 self.root.after(0, lambda: self.loading_animation.update_text(f"Speed test completed in {elapsed:.1f}s"))
            else:
                 self.root.after(0, lambda: self.loading_animation.update_text("Speed test stopped"))

            self.root.after(1000, self._test_cleanup) # Delay cleanup

        except Exception as e:
            logger.exception("Error occurred within speed test thread.")
            self.root.after(0, lambda: messagebox.showerror("Speed Test Error", f"An error occurred: {e}", parent=self.root))
            self.root.after(0, lambda: self.loading_animation.update_text("Speed test failed"))
            self.root.after(500, self._test_cleanup)
        finally:
             # Final cleanup check
             self.root.after(0, self._test_cleanup)


    # --- Connection Logic ---

    def _get_server_details_from_item_id(self, item_id: str) -> Optional[Dict[str, Any]]:
         """Finds the full server data dictionary based on a Treeview item ID."""
         if not self.server_tree or not self.server_data:
             return None
         try:
             if not self.server_tree.exists(item_id): return None # Check if item exists
             values = self.server_tree.item(item_id, "values")
             hostname = values[1] # Hostname is index 1 now
             city_name = values[2]
             country_display = values[3]
             # Strip flag for lookup
             country_name_only = country_display.split(" ", 1)[-1] if len(country_display.split(" ", 1)) > 1 else country_display

             # Search through server_data (can be slow for 'All Countries')
             for country_obj in self.server_data.get("countries", []):
                  if country_obj.get("name") == country_name_only: # Use name without flag
                      for city_obj in country_obj.get("cities", []):
                          if city_obj.get("name") == city_name:
                              for server in city_obj.get("relays", []):
                                  if server.get("hostname") == hostname:
                                      # Return a copy enriched with codes if needed
                                      server_copy = server.copy()
                                      server_copy["country"] = country_name_only # Store name without flag
                                      server_copy["city"] = city_name
                                      server_copy["country_code"] = country_obj.get("code")
                                      server_copy["city_code"] = city_obj.get("code")
                                      server_copy["treeview_item"] = item_id # Ensure item ID is present
                                      return server_copy
             logger.warning(f"Could not find server data for hostname: {hostname}")
             return None
         except (IndexError, tk.TclError):
              logger.warning(f"Could not get details for item_id {item_id} (may be invalid).")
              return None


    def connect_selected(self):
        """Connect to the server selected in the Treeview."""
        if not self.server_tree: return
        selected_items = self.server_tree.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select a server in the list to connect.", parent=self.root)
            return
        item_id = selected_items[0] # Use the first selected item

        server_details = self._get_server_details_from_item_id(item_id)

        if not server_details:
             messagebox.showerror("Error", "Could not retrieve details for the selected server.", parent=self.root)
             return

        hostname = server_details.get("hostname", "N/A")
        country_code = server_details.get("country_code")
        city_code = server_details.get("city_code")
        try:
            protocol_str = self.server_tree.set(item_id, "protocol") # Get protocol from tree
        except tk.TclError:
             messagebox.showerror("Error", "Could not retrieve protocol for the selected server (item might be gone).", parent=self.root)
             return


        if not country_code or not city_code:
             messagebox.showerror("Error", f"Missing country/city code for server {hostname}.", parent=self.root)
             return

        # Determine protocol for the CLI command
        protocol = "wireguard" if protocol_str == "WireGuard" else "openvpn"

        logger.info(f"Attempting connection to: {hostname} ({country_code}/{city_code}) using {protocol}")
        # Run connection in a separate thread
        threading.Thread(
            target=self._connect_to_server,
            args=(protocol, country_code, city_code, hostname),
            daemon=True
        ).start()


    def connect_to_fastest(self):
        """Connect to the server with the lowest latency result."""
        if not self.server_tree: return
        logger.info("Attempting to connect to the fastest server based on latency.")
        self._highlight_fastest_server() # Select the best one first

        # Check if a server was actually highlighted/selected
        selected_items = self.server_tree.selection()
        if not selected_items:
             messagebox.showinfo("No Results", "No server with valid latency results found to connect to.", parent=self.root)
             return

        # Now call connect_selected which will use the newly selected item
        self.connect_selected()


    def _connect_to_server(self, protocol: str, country_code: str, city_code: str, hostname: str):
        """Internal method to handle connection process in a thread."""
        self.root.after(0, lambda: self.loading_animation.update_text(f"Setting up connection to {hostname}..."))
        self.root.after(0, lambda: self.loading_animation.start(self.root))
        self.root.after(0, lambda: self.connect_button.configure(state=tk.DISABLED) if self.connect_button else None) # Disable while connecting

        try:
            logger.info(f"Setting protocol to {protocol}...")
            set_mullvad_protocol(protocol)
            time.sleep(0.5) # Small delay after setting protocol

            logger.info(f"Setting location to {country_code} {city_code} {hostname}...")
            set_mullvad_location(country_code, city_code, hostname)
            time.sleep(0.5) # Small delay after setting location

            logger.info("Initiating Mullvad connect command...")
            connect_mullvad()

            # Update UI upon success
            self.root.after(0, lambda h=hostname: self.loading_animation.update_text(f"Successfully connected to {h}"))
            logger.info(f"Connection to {hostname} successful.")
            self.root.after(1500, self.loading_animation.stop) # Stop animation after showing success


        except MullvadCLIError as e:
            logger.error(f"Mullvad CLI error during connection: {e}")
            self.root.after(0, lambda err=e: messagebox.showerror("Connection Failed", f"Mullvad command failed:\n{err}", parent=self.root))
            self.root.after(0, lambda: self.loading_animation.update_text("Connection failed"))
            self.root.after(1500, self.loading_animation.stop)
        except ValueError as e: # e.g., invalid protocol
             logger.error(f"Value error during connection setup: {e}")
             self.root.after(0, lambda err=e: messagebox.showerror("Connection Error", f"Configuration error:\n{err}", parent=self.root))
             self.root.after(0, lambda: self.loading_animation.update_text("Connection setup failed"))
             self.root.after(1500, self.loading_animation.stop)
        except Exception as e:
            logger.exception("Unexpected error during connection process.")
            self.root.after(0, lambda err=e: messagebox.showerror("Connection Error", f"An unexpected error occurred:\n{err}", parent=self.root))
            self.root.after(0, lambda: self.loading_animation.update_text("Connection error"))
            self.root.after(1500, self.loading_animation.stop)
        finally:
             # Re-enable connect button regardless of outcome
             self.root.after(0, lambda: self.connect_button.configure(state=tk.NORMAL) if self.connect_button else None)


    def disconnect(self):
        """Disconnect from Mullvad VPN."""
        logger.info("Disconnect requested.")
        threading.Thread(target=self._disconnect, daemon=True).start()

    def _disconnect(self):
        """Internal method to handle disconnection in a thread."""
        self.root.after(0, lambda: self.loading_animation.update_text("Disconnecting..."))
        self.root.after(0, lambda: self.loading_animation.start(self.root))
        self.root.after(0, lambda: self.connect_button.configure(state=tk.DISABLED) if self.connect_button else None) # Disable connect during disconnect

        try:
            disconnect_mullvad()
            self.root.after(0, lambda: self.loading_animation.update_text("Disconnected successfully"))
            logger.info("Disconnection successful.")
            self.root.after(1500, self.loading_animation.stop)

        except MullvadCLIError as e:
            logger.error(f"Mullvad CLI error during disconnection: {e}")
            # Check if already disconnected
            status = get_mullvad_status()
            if "Disconnected" in status:
                 self.root.after(0, lambda: self.loading_animation.update_text("Already disconnected"))
                 self.root.after(1500, self.loading_animation.stop)
            else:
                 self.root.after(0, lambda err=e: messagebox.showerror("Disconnect Failed", f"Mullvad command failed:\n{err}", parent=self.root))
                 self.root.after(0, lambda: self.loading_animation.update_text("Disconnect failed"))
                 self.root.after(1500, self.loading_animation.stop)
        except Exception as e:
            logger.exception("Unexpected error during disconnection process.")
            self.root.after(0, lambda err=e: messagebox.showerror("Disconnect Error", f"An unexpected error occurred:\n{err}", parent=self.root))
            self.root.after(0, lambda: self.loading_animation.update_text("Disconnect error"))
            self.root.after(1500, self.loading_animation.stop)
        finally:
             # Re-enable connect button
             self.root.after(0, lambda: self.connect_button.configure(state=tk.NORMAL) if self.connect_button else None)


    # --- Status Update ---

    def update_status(self):
        """Update the connection status periodically."""
        # Stop scheduling new updates if root window is closed
        try:
            if not self.root.winfo_exists():
                logger.info("Root window closed, stopping status updates.")
                if self.status_update_after_id:
                    self.root.after_cancel(self.status_update_after_id)
                return
        except tk.TclError:
             logger.info("Root window seems closed (TclError), stopping status updates.")
             return # Window destroyed

        try:
            # Run get_mullvad_status in a separate thread to avoid brief UI hangs
            def _fetch_status():
                try:
                    status = get_mullvad_status()
                    # Schedule the UI update back on the main thread
                    self.root.after(0, lambda s=status: self.status_var.set(s))
                except Exception as fetch_e:
                     logger.error(f"Error fetching Mullvad status in thread: {fetch_e}")
                     self.root.after(0, lambda: self.status_var.set("Status Error"))

            threading.Thread(target=_fetch_status, daemon=True).start()

        except Exception as e:
            # Catch errors scheduling the thread itself
            logger.exception(f"Error scheduling status update thread: {e}")
            self.status_var.set("Status Error") # Update UI immediately with error

        # Schedule the next update
        self.status_update_after_id = self.root.after(5000, self.update_status) # Check every 5 seconds


    # --- File Operations ---

    def export_to_csv(self):
        """Export the current server list with results to a CSV file."""
        if not self.server_tree: return
        items = self.server_tree.get_children()
        if not items:
            messagebox.showinfo("Export", "No server data to export.", parent=self.root)
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
            title="Export Server List to CSV",
            parent=self.root
        )
        if not file_path: return # User cancelled

        self.loading_animation.update_text("Exporting to CSV...")
        self.loading_animation.start(self.root)
        self.root.update_idletasks()

        try:
            servers_data: List[Dict[str, Any]] = []
            for item_id in items:
                 # Get full data if possible, otherwise just tree values
                 server_details = self._get_server_details_from_item_id(item_id)
                 if server_details:
                      # Add latency/speed results from treeview to the dict
                      try:
                          if self.server_tree.exists(item_id):
                              values = self.server_tree.item(item_id, "values")
                              server_details['latency'] = values[5] if values[5] else None
                              server_details['download_speed'] = values[6] if values[6] else None
                              server_details['upload_speed'] = values[7] if values[7] else None
                              server_details['protocol'] = values[4] # Get protocol from tree display
                          else: continue # Skip if item disappeared
                      except (tk.TclError, IndexError):
                           logger.warning(f"Could not get values for item {item_id} during export.")
                           continue # Skip this item
                      servers_data.append(server_details)
                 else: # Fallback if server data lookup failed
                      try:
                          if self.server_tree.exists(item_id):
                              values = self.server_tree.item(item_id, "values")
                              servers_data.append({
                                   "hostname": values[1], "city": values[2], "country": values[3],
                                   "protocol": values[4], "latency": values[5],
                                   "download_speed": values[6], "upload_speed": values[7]
                              })
                          else: continue # Skip if item disappeared
                      except (tk.TclError, IndexError):
                           logger.warning(f"Could not get fallback values for item {item_id} during export.")
                           continue # Skip this item


            success = export_to_csv(servers_data, file_path)
            if success:
                 messagebox.showinfo("Export Successful", f"Server list exported to:\n{file_path}", parent=self.root)
                 self.loading_animation.update_text("Export successful")
            else:
                 messagebox.showerror("Export Failed", "Failed to export server list to CSV. Check logs.", parent=self.root)
                 self.loading_animation.update_text("Export failed")

        except Exception as e:
            logger.exception("Error during CSV export.")
            messagebox.showerror("Export Error", f"An unexpected error occurred:\n{e}", parent=self.root)
            self.loading_animation.update_text("Export error")
        finally:
             self.root.after(1000, self.loading_animation.stop)


    def save_test_results(self):
        """Save the current Treeview state (including results and selection) to a file."""
        if not self.server_tree: return
        items = self.server_tree.get_children()
        if not items:
            messagebox.showinfo("Save", "No data in the list to save.", parent=self.root)
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".msf", # Mullvad Server Finder results
            filetypes=[("MSF Results", "*.msf"), ("All Files", "*.*")],
            title="Save Test Results",
            parent=self.root
        )
        if not file_path: return

        self.loading_animation.update_text("Saving results...")
        self.loading_animation.start(self.root)
        self.root.update_idletasks()

        try:
            results_data: List[Dict[str, Any]] = []
            selected_hostnames: List[str] = []
            for item_id in items:
                 try:
                     if not self.server_tree.exists(item_id): continue # Skip if item disappeared
                     values = self.server_tree.item(item_id, "values")
                     tags = self.server_tree.item(item_id, "tags")
                     hostname = values[1]

                     result = {
                         "hostname": hostname,
                         "city": values[2],
                         "country": values[3], # Save display value with flag
                         "protocol": values[4],
                         "latency": values[5] or None,
                         "download_speed": values[6] or None,
                         "upload_speed": values[7] or None,
                         "tags": list(tags) # Save tags for potential color restoration
                     }
                     results_data.append(result)

                     # Check if selected
                     if self.server_tree.set(item_id, "#1") == CHECKBOX_CHECKED:
                          selected_hostnames.append(hostname)
                 except (tk.TclError, IndexError):
                      logger.warning(f"Could not get data for item {item_id} during save.")
                      continue # Skip this item


            # Data structure to save
            save_data = {
                "version": "1.1", # Add version for future compatibility
                "timestamp": time.time(),
                "config_summary": { # Save key config settings used for this test
                     "country": self.current_country_var.get(), # Save display value with flag
                     "protocol_filter": self.protocol_var.get(),
                     "ping_count": self.config.get("ping_count"),
                     "test_type_run": self.test_type_var.get(), # What test was run?
                },
                "results": results_data,
                "selected_hostnames": selected_hostnames,
                "view_state": { # Save view settings
                     "sort_column": self.sort_column,
                     "sort_order": self.sort_order,
                },
                "cell_color_tags": list(self.created_cell_tags) # Save created color tags
            }

            with open(file_path, 'wb') as f:
                pickle.dump(save_data, f)

            messagebox.showinfo("Save Successful", f"Test results saved to:\n{file_path}", parent=self.root)
            self.loading_animation.update_text("Results saved")

        except Exception as e:
            logger.exception("Error saving test results.")
            messagebox.showerror("Save Error", f"An unexpected error occurred:\n{e}", parent=self.root)
            self.loading_animation.update_text("Save error")
        finally:
             self.root.after(1000, self.loading_animation.stop)


    def load_test_results(self):
        """Load test results from a .msf file into the Treeview."""
        if not self.server_tree: return

        file_path = filedialog.askopenfilename(
            filetypes=[("MSF Results", "*.msf"), ("All Files", "*.*")],
            title="Load Test Results",
            parent=self.root
        )
        if not file_path: return

        self.loading_animation.update_text("Loading results...")
        self.loading_animation.start(self.root)
        self.root.update_idletasks()

        try:
            with open(file_path, 'rb') as f:
                loaded_data = pickle.load(f)

            # Basic validation
            if not isinstance(loaded_data, dict) or "results" not in loaded_data:
                raise ValueError("Invalid or unrecognized file format.")

            # --- Restore UI State ---
            # Clear current view
            self.server_tree.delete(*self.server_tree.get_children())
            self.selected_server_items.clear()
            self.created_cell_tags.clear() # Clear old dynamic tags
            self.server_tree.heading("selected", text=CHECKBOX_UNCHECKED)

            # Restore config summary (optional, could just display it)
            config_summary = loaded_data.get("config_summary", {})
            country_display_name = config_summary.get("country", "All Countries")
            protocol_filter = config_summary.get("protocol_filter", "wireguard")
            # self.current_country_var.set(country_display_name) # Avoid triggering reload
            # self.protocol_var.set(protocol_filter) # Avoid triggering reload
            logger.info(f"Loaded results for Country: {country_display_name}, Protocol: {protocol_filter}")


            # Restore cell color tags
            saved_tags = loaded_data.get("cell_color_tags", [])
            for tag_name in saved_tags:
                 if tag_name.startswith("cell_"):
                     try:
                         parts = tag_name.split('_') # cell_latency_63BE7B
                         if len(parts) == 3:
                             color_code = f"#{parts[2]}"
                             # Reconfigure tag with appropriate foreground
                             r, g, b = int(color_code[1:3], 16), int(color_code[3:5], 16), int(color_code[5:7], 16)
                             text_color = "#FFFFFF" if (r*0.299 + g*0.587 + b*0.114) < 140 else "#000000"
                             self.server_tree.tag_configure(tag_name, background=color_code, foreground=text_color)
                             self.created_cell_tags.add(tag_name)
                     except Exception as e:
                         logger.warning(f"Could not restore cell tag '{tag_name}': {e}")


            # Populate Treeview
            results_list = loaded_data.get("results", [])
            item_id_map: Dict[str, str] = {} # Map hostname to item_id for selection restore
            use_alt_colors = self.config.get("alternating_row_colors", True)

            for i, result in enumerate(results_list):
                hostname = result.get("hostname", "N/A")
                tags_to_apply = []
                # Restore row color tag
                if use_alt_colors:
                    tags_to_apply.append('odd_row' if i % 2 else 'even_row')
                # Restore valid cell color tags found in the result's saved tags
                for saved_tag in result.get("tags", []):
                     if saved_tag in self.created_cell_tags: # Only apply tags we successfully restored
                         tags_to_apply.append(saved_tag)

                item_id = self.server_tree.insert("", tk.END, values=(
                    CHECKBOX_UNCHECKED, # Start unchecked
                    hostname,
                    result.get("city", ""),
                    result.get("country", ""), # Use saved display value (with flag)
                    result.get("protocol", ""),
                    result.get("latency", ""),
                    result.get("download_speed", ""),
                    result.get("upload_speed", "")
                ), tags=tuple(tags_to_apply))
                item_id_map[hostname] = item_id

            # Restore selection state
            selected_hostnames = loaded_data.get("selected_hostnames", [])
            for hostname in selected_hostnames:
                 item_id = item_id_map.get(hostname)
                 if item_id:
                     self._toggle_checkbox(item_id) # Toggle to checked state and update set
            self._update_run_test_button_text()


            # Restore sort order
            view_state = loaded_data.get("view_state", {})
            self.sort_column = view_state.get("sort_column", self.config["default_sort_column"])
            self.sort_order = view_state.get("sort_order", self.config["default_sort_order"])
            self.sort_treeview(self.sort_column, force_order=self.sort_order)

            # Display info
            timestamp = loaded_data.get("timestamp")
            time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp)) if timestamp else "N/A"
            messagebox.showinfo("Load Successful", f"Loaded {len(results_list)} results from:\n{file_path}\nSaved: {time_str}", parent=self.root)
            self.loading_animation.update_text("Results loaded")

        except (FileNotFoundError, pickle.UnpicklingError, ValueError, TypeError) as e:
            logger.exception(f"Error loading results file: {file_path}")
            messagebox.showerror("Load Error", f"Failed to load results:\n{e}", parent=self.root)
            self.loading_animation.update_text("Load failed")
        except Exception as e:
            logger.exception(f"Unexpected error loading results file: {file_path}")
            messagebox.showerror("Load Error", f"An unexpected error occurred:\n{e}", parent=self.root)
            self.loading_animation.update_text("Load error")
        finally:
             self.root.after(1000, self.loading_animation.stop)


    def clear_all_results(self):
        """Clear latency/speed results from the Treeview, keeping servers."""
        if not self.server_tree: return
        if not messagebox.askyesno("Confirm Clear", "Are you sure you want to clear all test results (latency, speed) from the current list?", parent=self.root):
            return

        logger.info("Clearing all test results from Treeview.")
        self.loading_animation.update_text("Clearing results...")
        self.loading_animation.start(self.root)
        self.root.update_idletasks()

        items = self.server_tree.get_children()
        for item_id in items:
             try:
                 if not self.server_tree.exists(item_id): continue # Skip if item disappeared
                 values = list(self.server_tree.item(item_id, "values"))
                 # Clear results columns (indices 5, 6, 7)
                 values[5] = ""
                 values[6] = ""
                 values[7] = ""

                 # Remove cell color tags, keep row color tags
                 current_tags = list(self.server_tree.item(item_id, "tags"))
                 filtered_tags = [tag for tag in current_tags if tag.startswith(('odd_row', 'even_row'))]

                 self.server_tree.item(item_id, values=tuple(values), tags=tuple(filtered_tags))
             except (tk.TclError, IndexError):
                  logger.warning(f"Could not clear results for item {item_id} (may be invalid).")
                  continue

        self.created_cell_tags.clear() # All color tags are now invalid
        self.loading_animation.update_text("Results cleared")
        self.root.after(500, self.loading_animation.stop)

    # --- Favorites ---

    def add_selected_to_favorites(self):
        """Add the selected server to the favorites list."""
        if not self.server_tree: return
        selected_items = self.server_tree.selection()
        if not selected_items:
            messagebox.showinfo("Info", "No server selected to add to favorites.", parent=self.root)
            return

        item_id = selected_items[0]
        server = self._get_server_details_from_item_id(item_id)

        if not server:
            messagebox.showerror("Error", "Could not retrieve details for the selected server.", parent=self.root)
            return

        if add_favorite_server(self.config, server):
            hostname = server.get("hostname", "N/A")
            messagebox.showinfo("Favorite Added", f"Server '{hostname}' added to favorites.", parent=self.root)
        else:
            # Check if it failed because it already exists or due to save error
             hostname = server.get("hostname", "N/A")
             is_already_fav = any(fav.get("hostname") == hostname for fav in self.config.get("favorite_servers", []))
             if is_already_fav:
                  messagebox.showinfo("Already Favorite", f"Server '{hostname}' is already in your favorites.", parent=self.root)
             else:
                  messagebox.showerror("Error", f"Failed to add '{hostname}' to favorites. Check logs.", parent=self.root)


    def manage_favorites(self):
        """Open a window to manage favorite servers."""
        favorites_window = tk.Toplevel(self.root)
        favorites_window.title("Manage Favorites")
        favorites_window.geometry("550x400")
        favorites_window.transient(self.root) # Keep on top of main window
        favorites_window.grab_set() # Modal behavior

        # Frame
        frame = ttk.Frame(favorites_window, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        # Treeview for favorites
        columns = ("hostname", "city", "country")
        fav_tree = ttk.Treeview(frame, columns=columns, show="headings")
        fav_tree.heading("hostname", text="Hostname", anchor=tk.W)
        fav_tree.heading("city", text="City", anchor=tk.W)
        fav_tree.heading("country", text="Country", anchor=tk.W)
        fav_tree.column("hostname", width=200, stretch=tk.YES)
        fav_tree.column("city", width=150, stretch=tk.YES)
        fav_tree.column("country", width=150, stretch=tk.YES)

        # Scrollbar
        scroll_y = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=fav_tree.yview)
        fav_tree.configure(yscrollcommand=scroll_y.set)

        # Layout
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        fav_tree.grid(row=0, column=0, sticky='nsew', pady=(0, 10))
        scroll_y.grid(row=0, column=1, sticky='ns', pady=(0, 10))


        # Populate Treeview
        favorites = self.config.get("favorite_servers", [])
        for fav in favorites:
             country_code = fav.get("country_code", "")
             country_name = fav.get("country", "")
             display_country = f"{get_flag_emoji(country_code)} {country_name}" if country_code else country_name
             fav_tree.insert("", tk.END, values=(
                 fav.get("hostname", ""), fav.get("city", ""), display_country
             ))

        # --- Buttons ---
        button_frame = ttk.Frame(frame)
        button_frame.grid(row=1, column=0, columnspan=2, sticky='ew')

        def on_connect_fav():
            selection = fav_tree.selection()
            if not selection: return
            item_id = selection[0]
            hostname = fav_tree.item(item_id, "values")[0]

            # Find full favorite details from config
            fav_details = next((f for f in self.config["favorite_servers"] if f.get("hostname") == hostname), None)
            if not fav_details:
                 messagebox.showerror("Error", "Could not find details for selected favorite.", parent=favorites_window)
                 return

            country_code = fav_details.get("country_code")
            city_code = fav_details.get("city_code")
            if not country_code or not city_code:
                  messagebox.showerror("Error", f"Missing location codes for favorite {hostname}.", parent=favorites_window)
                  return

            # Determine protocol based on hostname convention
            protocol = "wireguard" if "-wg" in hostname.lower() or ".wg." in hostname.lower() else "openvpn"

            logger.info(f"Connecting to favorite: {hostname}")
            threading.Thread(target=self._connect_to_server, args=(protocol, country_code, city_code, hostname), daemon=True).start()
            favorites_window.destroy()

        def on_remove_fav():
             selection = fav_tree.selection()
             if not selection: return
             item_id = selection[0]
             hostname = fav_tree.item(item_id, "values")[0]

             if messagebox.askyesno("Confirm Remove", f"Are you sure you want to remove '{hostname}' from favorites?", parent=favorites_window):
                  if remove_favorite_server(self.config, hostname):
                      fav_tree.delete(item_id)
                      logger.info(f"Removed favorite: {hostname}")
                  else:
                       messagebox.showerror("Error", f"Failed to remove favorite '{hostname}'. Check logs.", parent=favorites_window)


        ttk.Button(button_frame, text="Connect", command=on_connect_fav).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Remove", command=on_remove_fav).pack(side=tk.LEFT, padx=(0, 15))
        ttk.Button(button_frame, text="Close", command=favorites_window.destroy).pack(side=tk.RIGHT)

        favorites_window.wait_window() # Wait until closed


    # --- Settings ---

    def _create_general_settings_tab(self, notebook: ttk.Notebook) -> ttk.Frame:
        tab = ttk.Frame(notebook, padding=15)
        tab.grid_columnconfigure(1, weight=1) # Make entry expand

        # Cache Path
        ttk.Label(tab, text="Cache Path:").grid(row=0, column=0, sticky=tk.W, pady=5)
        cache_path_var = tk.StringVar(value=get_cache_path(self.config)) # Show effective path
        cache_entry = ttk.Entry(tab, textvariable=cache_path_var, width=50)
        cache_entry.grid(row=0, column=1, sticky=tk.EW, padx=5)
        def browse_cache():
            # Suggest directory of current path, default to home
            initial_dir = os.path.dirname(cache_path_var.get()) or os.path.expanduser("~")
            path = filedialog.askopenfilename(title="Select relays.json", filetypes=[("JSON", "*.json")], initialdir=initial_dir, parent=tab)
            if path: cache_path_var.set(path)
        ttk.Button(tab, text="Browse...", command=browse_cache).grid(row=0, column=2, padx=5)
        # Store variable for saving later
        tab.cache_path_var = cache_path_var # Attach to tab frame

        # Auto Connect
        auto_connect_var = tk.BooleanVar(value=self.config.get("auto_connect_fastest", False))
        ttk.Checkbutton(tab, text="Auto-connect to fastest server after ping test", variable=auto_connect_var).grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=5)
        tab.auto_connect_var = auto_connect_var

        # Theme (Uses self.theme_var initialized in __init__)
        ttk.Label(tab, text="Theme:").grid(row=2, column=0, sticky=tk.W, pady=5)
        theme_combo = ttk.Combobox(tab, textvariable=self.theme_var, values=["system", "light", "dark"], width=10, state="readonly")
        theme_combo.grid(row=2, column=1, sticky=tk.W, padx=5)
        # No need for restart label if sv-ttk handles it dynamically
        # ttk.Label(tab, text="(Restart required)").grid(row=2, column=2, sticky=tk.W, padx=5)
        # self.theme_var is already attached to self

        # Alternating Row Colors
        alt_rows_var = tk.BooleanVar(value=self.config.get("alternating_row_colors", True))
        ttk.Checkbutton(tab, text="Use alternating row colors in list", variable=alt_rows_var).grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=5)
        tab.alt_rows_var = alt_rows_var

        return tab

    def _create_testing_settings_tab(self, notebook: ttk.Notebook) -> ttk.Frame:
         tab = ttk.Frame(notebook, padding=15)
         tab.grid_columnconfigure(1, weight=1)

         # --- Ping Settings ---
         # Remove explicit font to use theme default
         ttk.Label(tab, text="Ping Settings").grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=(0,10)) # Apply bold via style if needed later

         ttk.Label(tab, text="Ping Count:").grid(row=1, column=0, sticky=tk.W, pady=2)
         ping_count_var = tk.IntVar(value=self.config.get("ping_count", 3))
         ttk.Spinbox(tab, from_=1, to=10, textvariable=ping_count_var, width=5).grid(row=1, column=1, sticky=tk.W, padx=5)
         tab.ping_count_var = ping_count_var

         ttk.Label(tab, text="Max Workers:").grid(row=2, column=0, sticky=tk.W, pady=2)
         max_workers_var = tk.IntVar(value=self.config.get("max_workers", 15))
         ttk.Spinbox(tab, from_=1, to=50, textvariable=max_workers_var, width=5).grid(row=2, column=1, sticky=tk.W, padx=5)
         tab.max_workers_var = max_workers_var

         ttk.Label(tab, text="Test Timeout (s):").grid(row=3, column=0, sticky=tk.W, pady=2)
         timeout_var = tk.IntVar(value=self.config.get("timeout_seconds", 15))
         ttk.Spinbox(tab, from_=5, to=60, textvariable=timeout_var, width=5).grid(row=3, column=1, sticky=tk.W, padx=5)
         tab.timeout_var = timeout_var

         color_latency_var = tk.BooleanVar(value=self.config.get("color_latency", True))
         ttk.Checkbutton(tab, text="Color-code latency cells", variable=color_latency_var).grid(row=4, column=0, columnspan=3, sticky=tk.W, pady=5)
         tab.color_latency_var = color_latency_var

         # --- Speed Test Settings ---
         # Remove explicit font to use theme default
         ttk.Label(tab, text="Speed Test Settings").grid(row=5, column=0, columnspan=3, sticky=tk.W, pady=(15,10)) # Apply bold via style if needed later

         # Renamed from "Test Size (MB)" to "Test Duration (s)" for clarity with socket test
         ttk.Label(tab, text="Test Duration (s):").grid(row=6, column=0, sticky=tk.W, pady=2)
         speed_duration_var = tk.IntVar(value=self.config.get("speed_test_duration", 5)) # Use new config key
         ttk.Spinbox(tab, from_=2, to=30, increment=1, textvariable=speed_duration_var, width=5).grid(row=6, column=1, sticky=tk.W, padx=5)
         tab.speed_duration_var = speed_duration_var # Store with new name

         color_speed_var = tk.BooleanVar(value=self.config.get("color_speed", True))
         ttk.Checkbutton(tab, text="Color-code speed cells", variable=color_speed_var).grid(row=7, column=0, columnspan=3, sticky=tk.W, pady=5)
         tab.color_speed_var = color_speed_var

         ttk.Label(tab, text="Default Test Type:").grid(row=8, column=0, sticky=tk.W, pady=5)
         test_type_var = tk.StringVar(value=self.config.get("test_type", "ping"))
         ttk.Combobox(tab, textvariable=test_type_var, values=["ping", "speed", "both"], width=10, state="readonly").grid(row=8, column=1, sticky=tk.W, padx=5)
         tab.test_type_var = test_type_var


         return tab

    def _create_display_settings_tab(self, notebook: ttk.Notebook) -> ttk.Frame:
        tab = ttk.Frame(notebook, padding=15)
        tab.grid_columnconfigure(1, weight=1)

        ttk.Label(tab, text="Default Sort Column:").grid(row=0, column=0, sticky=tk.W, pady=5)
        sort_col_var = tk.StringVar(value=self.config.get("default_sort_column", "latency"))
        # Use actual column keys used internally for sorting
        sort_cols = ["selected", "hostname", "city", "country", "protocol", "latency", "download", "upload"]
        ttk.Combobox(tab, textvariable=sort_col_var, values=sort_cols, width=15, state="readonly").grid(row=0, column=1, sticky=tk.W, padx=5)
        tab.sort_col_var = sort_col_var

        ttk.Label(tab, text="Default Sort Order:").grid(row=1, column=0, sticky=tk.W, pady=5)
        sort_ord_var = tk.StringVar(value=self.config.get("default_sort_order", "ascending"))
        ttk.Combobox(tab, textvariable=sort_ord_var, values=["ascending", "descending"], width=15, state="readonly").grid(row=1, column=1, sticky=tk.W, padx=5)
        tab.sort_ord_var = sort_ord_var

        return tab


    def open_settings(self):
        """Open the settings window with tabbed interface."""
        settings_window = tk.Toplevel(self.root)
        settings_window.title("Settings")
        settings_window.geometry("600x480") # Adjusted size
        settings_window.transient(self.root)
        settings_window.grab_set()
        settings_window.resizable(False, False)

        # Main frame and Notebook
        main_frame = ttk.Frame(settings_window, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # Create tabs by calling helper methods
        tab_general = self._create_general_settings_tab(notebook)
        tab_testing = self._create_testing_settings_tab(notebook)
        tab_display = self._create_display_settings_tab(notebook)

        notebook.add(tab_general, text=" General ") # Added padding in text
        notebook.add(tab_testing, text=" Testing ")
        notebook.add(tab_display, text=" Display ")

        # --- Save/Cancel Buttons ---
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))

        def save_and_close():
            logger.info("Saving settings...")
            # Retrieve values from variables attached to tabs
            new_config = self.config.copy() # Start with current config

            # General
            custom_cache = tab_general.cache_path_var.get()
            # Only save custom path if it's different from the *default* for the platform
            if custom_cache != get_default_cache_path():
                 new_config["custom_cache_path"] = custom_cache
            else:
                 new_config["custom_cache_path"] = "" # Clear custom if it matches default
            new_config["auto_connect_fastest"] = tab_general.auto_connect_var.get()
            new_config["theme_mode"] = self.theme_var.get() # Get from self.theme_var
            new_config["alternating_row_colors"] = tab_general.alt_rows_var.get()

            # Testing
            new_config["ping_count"] = tab_testing.ping_count_var.get()
            new_config["max_workers"] = tab_testing.max_workers_var.get()
            new_config["timeout_seconds"] = tab_testing.timeout_var.get()
            new_config["color_latency"] = tab_testing.color_latency_var.get()
            new_config["speed_test_duration"] = tab_testing.speed_duration_var.get() # Use new key
            new_config["color_speed"] = tab_testing.color_speed_var.get()
            new_config["test_type"] = tab_testing.test_type_var.get()

            # Display
            new_config["default_sort_column"] = tab_display.sort_col_var.get()
            new_config["default_sort_order"] = tab_display.sort_ord_var.get()

            if save_config(new_config):
                 self.config = new_config # Update in-memory config
                 # Apply relevant immediate changes
                 self.test_type_var.set(self.config["test_type"])
                 self.on_test_type_selected() # Update UI based on new default test type
                 self.apply_theme() # Re-apply theme in case alt colors changed
                 # Reload server data if cache path changed effectively
                 if get_cache_path(self.config) != get_cache_path(load_config()): # Compare effective paths
                     self.load_server_data()

                 messagebox.showinfo("Settings Saved", "Settings saved successfully.", parent=settings_window)
                 settings_window.destroy()
            else:
                 messagebox.showerror("Save Error", "Failed to save settings. Check logs.", parent=settings_window)


        ttk.Button(button_frame, text="Save", command=save_and_close).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Cancel", command=settings_window.destroy).pack(side=tk.RIGHT)

        settings_window.wait_window()


    # --- Miscellaneous ---

    def show_about(self):
        """Show the about dialog."""
        about_text = (
            "Mullvad Server Finder\n\n"
            "Version: 1.2.0 (Python/Tkinter + sv-ttk)\n\n" # Incremented version
            "Find the best Mullvad VPN server based on latency and estimated socket performance.\n\n" # Updated description
            "Features:\n"
            "- Load servers from Mullvad cache\n"
            "- Ping latency testing (ICMP)\n"
            "- Estimated Socket Speed testing (TCP Ping-Pong)\n" # Updated description
            "- Connect/disconnect via Mullvad CLI\n"
            "- Favorites and settings persistence\n"
            "- Light/Dark/System theme support (via sv-ttk)\n\n" # Added theme feature
            "Speed Test Note:\n"
            "The 'DL (Mbps, Sock)' and 'UL (Mbps, Sock)' columns estimate performance "
            "by sending/receiving small data chunks over a direct TCP socket "
            "connection to common ports (e.g., 443, 80) for a short duration.\n"
            "This method measures the relative responsiveness and throughput *for this specific type of interaction*.\n"
            "Results are primarily useful for *comparing servers against each other* under these conditions.\n"
            "They do *not* represent real-world browsing/download/upload speeds for standard protocols (HTTP, FTP, etc.) "
            "and may differ significantly. Tests may fail or show 0 Mbps if servers block or quickly close these raw TCP connections.\n\n"
            f"Log File: {get_log_path()}"
        )
        messagebox.showinfo("About Mullvad Server Finder", about_text, parent=self.root)


    # --- THEMEING ---

    def apply_theme(self):
        """Applies the selected theme (sv-ttk if available, or custom ttk)."""
        global sv_ttk # Allow modification if sv_ttk fails
        theme_mode = self.theme_var.get() # "system", "light", "dark"
        logger.info(f"Applying theme: {theme_mode}")

        # --- sv-ttk Integration ---
        if sv_ttk:
            try:
                # Determine actual mode (light/dark) based on system if needed
                actual_mode = theme_mode
                if theme_mode == "system":
                    # sv_ttk doesn't have explicit system detection, we do it manually
                    try:
                        system = platform.system()
                        is_dark = False
                        if system == "Windows":
                            import winreg
                            key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
                            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path)
                            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                            is_dark = (value == 0)
                            winreg.CloseKey(key)
                        elif system == "Darwin": # macOS
                            # Use the tk call which might be more reliable within Tk context
                            is_dark = self.root.tk.call("tk", "windowingsystem") == "aqua" and \
                                      self.root.tk.call("::tk::unsupported::MacWindowStyle", "isdark", self.root)
                        # Add Linux detection if needed (complex)

                        actual_mode = "dark" if is_dark else "light"
                        logger.info(f"System theme detected as: {actual_mode}")
                    except (tk.TclError, ImportError, FileNotFoundError, Exception) as e:
                        logger.warning(f"Could not reliably detect system theme: {e}. Defaulting to light.")
                        actual_mode = "light" # Default fallback

                sv_ttk.set_theme(actual_mode) # Apply "light" or "dark"
                self.theme_colors = { # Update colors based on sv-ttk's current theme
                    "background": sv_ttk.style.colors.bg,
                    "foreground": sv_ttk.style.colors.fg,
                    "row_odd": sv_ttk.style.colors.bg, # Often same as bg in modern themes
                    "row_even": sv_ttk.style.colors.alt_bg if hasattr(sv_ttk.style.colors, 'alt_bg') else sv_ttk.style.colors.bg,
                    "select_bg": sv_ttk.style.colors.select_bg,
                    "select_fg": sv_ttk.style.colors.select_fg,
                    # Add more colors as needed from sv_ttk.style.colors
                }
                logger.info(f"sv-ttk theme set to '{actual_mode}'.")

                # Apply background to root and main frame for consistency
                self.root.configure(bg=self.theme_colors["background"])
                if self.main_frame:
                    # Ensure it uses ttk style which sv-ttk overrides
                    self.main_frame.configure(style='TFrame')

                # Re-apply Treeview row colors using sv-ttk colors
                if self.server_tree:
                    self.server_tree.tag_configure('odd_row', background=self.theme_colors["row_odd"], foreground=self.theme_colors["foreground"])
                    self.server_tree.tag_configure('even_row', background=self.theme_colors["row_even"], foreground=self.theme_colors["foreground"])
                    # Update selection colors via style map
                    style = ttk.Style()
                    style.map('Treeview',
                              background=[('selected', self.theme_colors["select_bg"])],
                              foreground=[('selected', self.theme_colors["select_fg"])])

                # Update status label color if needed (sv-ttk might handle this)
                if self.status_label:
                     # sv-ttk should style labels automatically, but force if needed
                     self.status_label.configure(foreground=self.theme_colors["foreground"])

                # Force redraw/update of elements
                self.root.update_idletasks()
                if self.server_tree:
                    # Reloading data is heavy, try just updating tags on existing items
                    self.sort_treeview(self.sort_column, force_order=self.sort_order) # Re-sort applies row tags

                return # Successfully applied sv-ttk

            except Exception as e:
                logger.error(f"Error applying sv-ttk theme: {e}. Disabling sv-ttk and falling back.")
                sv_ttk = None # Disable sv_ttk if it causes errors
                # Fall through to manual styling if sv_ttk fails

        # --- Fallback/Manual TTK Styling (if sv_ttk not available or failed) ---
        logger.info("Applying manual fallback theme.")
        style = ttk.Style()
        is_dark_mode = False
        if theme_mode == "dark":
            is_dark_mode = True
        elif theme_mode == "system":
             # Basic system theme detection (same as above, could be improved)
             try:
                 system = platform.system()
                 if system == "Windows":
                     import winreg
                     key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
                     key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path)
                     value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                     is_dark_mode = (value == 0)
                     winreg.CloseKey(key)
                 elif system == "Darwin": # macOS
                     is_dark_mode = self.root.tk.call("tk", "windowingsystem") == "aqua" and \
                                   self.root.tk.call("::tk::unsupported::MacWindowStyle", "isdark", self.root)
                 logger.info(f"System theme detected as: {'dark' if is_dark_mode else 'light'}")
             except (tk.TclError, ImportError, FileNotFoundError, Exception) as e:
                 logger.warning(f"Could not reliably detect system theme for fallback: {e}. Defaulting to light.")
                 is_dark_mode = False # Default fallback

        # Define light/dark color palettes manually
        if is_dark_mode:
            self.theme_colors = {
                "background": "#2E2E2E", "foreground": "#EAEAEA",
                "row_odd": "#3C3C3C", "row_even": "#333333",
                "select_bg": "#005A9E", "select_fg": "#FFFFFF", # Darker blue selection
                "button_bg": "#4F4F4F", "button_fg": "#EAEAEA",
                "entry_bg": "#3C3C3C", "entry_fg": "#EAEAEA",
                "disabled_fg": "#888888", "header_bg": "#424242", "header_fg": "#EAEAEA",
                "progress_fg": "#0078D7", "highlight_bg": "#5F5F5F"
            }
            try: style.theme_use('clam')
            except tk.TclError: style.theme_use('default')
        else: # Light mode
            self.theme_colors = {
                "background": "#F0F0F0", "foreground": "#000000",
                "row_odd": "#FFFFFF", "row_even": "#F5F5F5", # Slightly off-white even row
                "select_bg": "#0078D7", "select_fg": "#FFFFFF", # Standard blue selection
                "button_bg": "#E1E1E1", "button_fg": "#000000",
                "entry_bg": "#FFFFFF", "entry_fg": "#000000",
                "disabled_fg": "#A0A0A0", "header_bg": "#E1E1E1", "header_fg": "#000000",
                "progress_fg": "#0078D7", "highlight_bg": "#CCE4F7"
            }
            # Use a default theme that might be available
            try:
                if platform.system() == "Windows": style.theme_use('vista')
                elif platform.system() == "Darwin": style.theme_use('aqua')
                else: style.theme_use('clam') # Clam is often better than default on Linux
            except tk.TclError:
                 style.theme_use('default') # Fallback


        # Apply manual styles
        style.configure('.', background=self.theme_colors["background"], foreground=self.theme_colors["foreground"],
                        fieldbackground=self.theme_colors["entry_bg"], # Default field background
                        selectbackground=self.theme_colors["select_bg"], selectforeground=self.theme_colors["select_fg"])
        style.configure('TFrame', background=self.theme_colors["background"])
        style.configure('TLabel', background=self.theme_colors["background"], foreground=self.theme_colors["foreground"])
        style.configure('TButton', background=self.theme_colors["button_bg"], foreground=self.theme_colors["button_fg"])
        style.map('TButton',
                  background=[('active', self.theme_colors["highlight_bg"]), ('disabled', self.theme_colors["background"])],
                  foreground=[('disabled', self.theme_colors["disabled_fg"])])
        style.configure('TCombobox', fieldbackground=self.theme_colors["entry_bg"], foreground=self.theme_colors["entry_fg"])
        style.map('TCombobox', fieldbackground=[('readonly', self.theme_colors["background"])]) # Style readonly state
        style.configure('Treeview', background=self.theme_colors["entry_bg"], fieldbackground=self.theme_colors["entry_bg"], foreground=self.theme_colors["foreground"])
        style.map('Treeview',
                  background=[('selected', self.theme_colors["select_bg"])],
                  foreground=[('selected', self.theme_colors["select_fg"])])
        # Remove explicit font to use theme default
        style.configure('Treeview.Heading', background=self.theme_colors["header_bg"], foreground=self.theme_colors["header_fg"])
        style.map('Treeview.Heading', background=[('active', self.theme_colors["highlight_bg"])])
        style.configure('TScrollbar', background=self.theme_colors["background"], troughcolor=self.theme_colors["button_bg"])
        style.configure('Horizontal.TProgressbar', background=self.theme_colors["progress_fg"], troughcolor=self.theme_colors["button_bg"])

        self.root.configure(bg=self.theme_colors["background"])
        # Apply to main frame
        if self.main_frame:
            self.main_frame.configure(style='TFrame')

        # Re-apply Treeview row colors
        if self.server_tree:
            self.server_tree.tag_configure('odd_row', background=self.theme_colors["row_odd"], foreground=self.theme_colors["foreground"])
            self.server_tree.tag_configure('even_row', background=self.theme_colors["row_even"], foreground=self.theme_colors["foreground"])
            # Reload/resort to apply
            self.sort_treeview(self.sort_column, force_order=self.sort_order)

        # Update status label color
        if self.status_label:
             self.status_label.configure(foreground=self.theme_colors["foreground"])

        self.root.update_idletasks()


    def change_theme(self):
        """Called when the theme radiobutton selection changes."""
        new_theme = self.theme_var.get()
        logger.info(f"Theme selection changed to: {new_theme}")
        # Only save if it actually changed from the loaded config value
        if new_theme != self.config.get("theme_mode", "system"):
            self.config["theme_mode"] = new_theme
            save_config(self.config) # Save the new theme preference
        self.apply_theme() # Apply the newly selected theme immediately
