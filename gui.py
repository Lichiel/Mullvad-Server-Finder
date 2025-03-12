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
from threading import Event
from mullvad_api import (load_cached_servers, set_mullvad_location, 
                         set_mullvad_protocol, connect_mullvad, 
                         disconnect_mullvad, get_mullvad_status)
from server_manager import (get_all_servers, get_servers_by_country, 
                           test_servers, filter_servers_by_protocol,
                           export_to_csv, calculate_latency_color,
                           calculate_speed_color, test_server_speed)
from config import (load_config, save_config, add_favorite_server, 
                   remove_favorite_server, get_cache_path)

class LoadingAnimation:
    """Class to handle loading animation in the status bar."""
    def __init__(self, label_var, original_text, animation_frames=None):
        self.label_var = label_var
        self.original_text = original_text
        self.animation_frames = animation_frames or ['⣾', '⣽', '⣻', '⢿', '⡿', '⣟', '⣯', '⣷']
        self.is_running = False
        self.current_frame = 0
        self.after_id = None
        self.root = None
    
    def start(self, root):
        """Start the loading animation."""
        self.root = root
        self.is_running = True
        self.animate()
    
    def stop(self):
        """Stop the loading animation."""
        self.is_running = False
        if self.after_id and self.root:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        self.label_var.set(self.original_text)
    
    def animate(self):
        """Update the animation frame."""
        if not self.is_running:
            return
        
        # Update with the next animation frame
        frame = self.animation_frames[self.current_frame]
        self.label_var.set(f"{self.original_text} {frame}")
        
        # Move to the next frame
        self.current_frame = (self.current_frame + 1) % len(self.animation_frames)
        
        # Schedule the next update
        self.after_id = self.root.after(150, self.animate)
    
    def update_text(self, new_text):
        """Update the text portion of the animation."""
        self.original_text = new_text
        # The next animation cycle will show the new text

class MullvadFinderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Mullvad Server Finder")
        self.root.geometry("900x600")
        
        # Set icon for the app if available
        try:
            if platform.system() == 'Windows':
                self.root.iconbitmap('mullvad_icon.ico')
            # For macOS and Linux we would need different approaches
        except:
            pass  # If icon is not available, just ignore
        
        # Load user configuration
        self.config = load_config()
        
        # Apply theme
        self.apply_theme()
        
        # Initialize UI variables
        self.server_data = None
        self.countries = []
        self.current_country_var = tk.StringVar()
        self.protocol_var = tk.StringVar(value=self.config.get("last_protocol", "wireguard"))
        self.status_var = tk.StringVar(value="Not connected")
        self.test_type_var = tk.StringVar(value=self.config.get("test_type", "ping"))
        self.ping_in_progress = False
        self.speed_in_progress = False
        self.current_operation = tk.StringVar(value="Ready")
        
        # Loading animation
        self.loading_animation = LoadingAnimation(self.current_operation, "Ready")
        
        # Sorting variables
        self.sort_column = self.config.get("default_sort_column", "latency")
        self.sort_order = self.config.get("default_sort_order", "ascending")
        
        # Thread control events
        self.stop_event = Event()
        self.pause_event = Event()
        
        # Track created cell color tags
        self.created_cell_tags = set()
        
        # Create the UI
        self.create_menu()
        self.create_ui()
        
        # Load server data
        self.load_server_data()
        
        # Start status update timer
        self.update_status()
    
    def apply_theme(self):
        """Apply the theme based on configuration."""
        theme_mode = self.config.get("theme_mode", "system")
        
        # Determine if we should use dark mode
        use_dark_mode = False
        
        if theme_mode == "dark":
            use_dark_mode = True
        elif theme_mode == "system":
            # Try to detect system theme
            if platform.system() == "Windows":
                try:
                    import winreg
                    registry = winreg.ConnectRegistry(None, winreg.HKEY_CURRENT_USER)
                    key = winreg.OpenKey(registry, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
                    value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                    use_dark_mode = value == 0
                except:
                    pass
            elif platform.system() == "Darwin":  # macOS
                try:
                    # Check macOS dark mode (this is a simplified approach)
                    import subprocess
                    result = subprocess.run(
                        ['defaults', 'read', '-g', 'AppleInterfaceStyle'],
                        capture_output=True, text=True
                    )
                    use_dark_mode = result.stdout.strip() == "Dark"
                except:
                    pass
        
        # Apply theme colors
        if use_dark_mode:
            # Dark theme colors
            self.theme_colors = {
                "bg": "#2D2D2D",
                "fg": "#E0E0E0",
                "row_odd": "#383838",
                "row_even": "#2D2D2D",
                "select_bg": "#505050",
                "header_bg": "#202020",
                "button_bg": "#404040",
                "highlight_bg": "#606060",
                "progress_fg": "#00A5E0",
                "input_bg": "#404040",
                "input_fg": "#E0E0E0"
            }
            
            # Configure ttk styles for dark mode
            style = ttk.Style()
            style.theme_use('clam')  # Use clam as it's more customizable
            
            style.configure(".", 
                background=self.theme_colors["bg"],
                foreground=self.theme_colors["fg"],
                fieldbackground=self.theme_colors["input_bg"])
            
            style.configure("TButton", 
                background=self.theme_colors["button_bg"],
                foreground=self.theme_colors["fg"])
            
            style.map("TButton",
                background=[("active", self.theme_colors["highlight_bg"])])
            
            style.configure("TFrame", background=self.theme_colors["bg"])
            style.configure("TLabel", background=self.theme_colors["bg"], foreground=self.theme_colors["fg"])
            style.configure("TNotebook", background=self.theme_colors["bg"], tabmargins=[2, 5, 2, 0])
            style.configure("TNotebook.Tab", background=self.theme_colors["button_bg"], foreground=self.theme_colors["fg"])
            style.map("TNotebook.Tab", background=[("selected", self.theme_colors["highlight_bg"])])
            
            style.configure("Treeview", 
                background=self.theme_colors["row_even"],
                foreground=self.theme_colors["fg"],
                fieldbackground=self.theme_colors["row_even"])
            
            style.map("Treeview",
                background=[("selected", self.theme_colors["select_bg"])],
                foreground=[("selected", "white")])
            
            style.configure("Treeview.Heading", 
                background=self.theme_colors["header_bg"],
                foreground=self.theme_colors["fg"])
            
            style.configure("Horizontal.TProgressbar", 
                background=self.theme_colors["progress_fg"],
                troughcolor=self.theme_colors["bg"])
            
            # Configure Tk widgets
            self.root.configure(bg=self.theme_colors["bg"])
            
        else:
            # Light theme colors
            self.theme_colors = {
                "bg": "#F0F0F0",
                "fg": "#000000",
                "row_odd": "#F8F8F8",
                "row_even": "#FFFFFF",
                "select_bg": "#0078D7",
                "header_bg": "#E0E0E0",
                "button_bg": "#E0E0E0",
                "highlight_bg": "#CCE8FF",
                "progress_fg": "#0078D7",
                "input_bg": "#FFFFFF",
                "input_fg": "#000000"
            }
            
            # Use default theme (depends on OS)
            style = ttk.Style()
            if platform.system() == "Darwin":  # macOS
                style.theme_use("aqua")
            elif platform.system() == "Windows":
                style.theme_use("vista")
            else:
                style.theme_use("clam")
            
            # Set Treeview colors for alternating rows
            style.configure("Treeview", 
                background=self.theme_colors["row_even"],
                foreground=self.theme_colors["fg"],
                fieldbackground=self.theme_colors["row_even"])
            
            # Configure the root window
            self.root.configure(bg=self.theme_colors["bg"])
    
    def create_menu(self):
        """Create the application menu bar."""
        menubar = tk.Menu(self.root)
        
        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Reload Server Data", command=self.load_server_data)
        file_menu.add_command(label="Export to CSV...", command=self.export_to_csv)
        file_menu.add_command(label="Save Test Results...", command=self.save_test_results)
        file_menu.add_command(label="Load Test Results...", command=self.load_test_results)
        file_menu.add_command(label="Clear All Results", command=self.clear_all_results)
        file_menu.add_command(label="Settings", command=self.open_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)
        
        # Connection menu
        connection_menu = tk.Menu(menubar, tearoff=0)
        connection_menu.add_command(label="Connect", command=self.connect_selected)
        connection_menu.add_command(label="Connect to Fastest", command=self.connect_to_fastest)
        connection_menu.add_command(label="Disconnect", command=self.disconnect)
        menubar.add_cascade(label="Connection", menu=connection_menu)
        
        # Test menu
        test_menu = tk.Menu(menubar, tearoff=0)
        test_menu.add_command(label="Ping Test", command=lambda: self.start_tests(test_type="ping"))
        test_menu.add_command(label="Speed Test", command=lambda: self.start_tests(test_type="speed"))
        test_menu.add_command(label="Ping & Speed Test", command=lambda: self.start_tests(test_type="both"))
        test_menu.add_separator()
        test_menu.add_command(label="Stop Current Test", command=self.stop_tests)
        menubar.add_cascade(label="Test", menu=test_menu)
        
        # Favorites menu
        favorites_menu = tk.Menu(menubar, tearoff=0)
        favorites_menu.add_command(label="Add Selected to Favorites", command=self.add_selected_to_favorites)
        favorites_menu.add_command(label="Manage Favorites", command=self.manage_favorites)
        menubar.add_cascade(label="Favorites", menu=favorites_menu)
        
        # View menu
        view_menu = tk.Menu(menubar, tearoff=0)
        
        # Theme submenu
        theme_menu = tk.Menu(view_menu, tearoff=0)
        self.theme_var = tk.StringVar(value=self.config.get("theme_mode", "system"))
        theme_menu.add_radiobutton(label="System", variable=self.theme_var, value="system", command=self.change_theme)
        theme_menu.add_radiobutton(label="Light", variable=self.theme_var, value="light", command=self.change_theme)
        theme_menu.add_radiobutton(label="Dark", variable=self.theme_var, value="dark", command=self.change_theme)
        view_menu.add_cascade(label="Theme", menu=theme_menu)
        
        # Sort submenu
        sort_menu = tk.Menu(view_menu, tearoff=0)
        sort_menu.add_command(label="Sort by Hostname", command=lambda: self.sort_treeview("hostname"))
        sort_menu.add_command(label="Sort by Country", command=lambda: self.sort_treeview("country"))
        sort_menu.add_command(label="Sort by City", command=lambda: self.sort_treeview("city"))
        sort_menu.add_command(label="Sort by Protocol", command=lambda: self.sort_treeview("protocol"))
        sort_menu.add_command(label="Sort by Latency", command=lambda: self.sort_treeview("latency"))
        sort_menu.add_command(label="Sort by Download Speed", command=lambda: self.sort_treeview("download"))
        sort_menu.add_command(label="Sort by Upload Speed", command=lambda: self.sort_treeview("upload"))
        view_menu.add_cascade(label="Sort", menu=sort_menu)
        
        menubar.add_cascade(label="View", menu=view_menu)
        
        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)
        
        self.root.config(menu=menubar)
    
    def change_theme(self):
        """Change the theme based on the selected option."""
        theme = self.theme_var.get()
        self.config["theme_mode"] = theme
        save_config(self.config)
        
        # Show a message about restarting
        messagebox.showinfo(
            "Theme Changed",
            "The theme has been changed. Please restart the application for the changes to take effect."
        )
    
    def create_ui(self):
        """Create the main user interface."""
        # Main frame
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Top section - Filters and controls
        top_frame = ttk.Frame(main_frame)
        top_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Country selection
        ttk.Label(top_frame, text="Country:").pack(side=tk.LEFT, padx=(0, 5))
        self.country_combo = ttk.Combobox(top_frame, textvariable=self.current_country_var, width=20)
        self.country_combo.pack(side=tk.LEFT, padx=(0, 10))
        self.country_combo.bind("<<ComboboxSelected>>", self.on_country_selected)
        
        # Protocol selection
        ttk.Label(top_frame, text="Protocol:").pack(side=tk.LEFT, padx=(0, 5))
        protocol_combo = ttk.Combobox(top_frame, textvariable=self.protocol_var, values=["wireguard", "openvpn", "both"], width=10)
        protocol_combo.pack(side=tk.LEFT, padx=(0, 10))
        protocol_combo.bind("<<ComboboxSelected>>", self.on_protocol_selected)
        
        # Test type selection
        ttk.Label(top_frame, text="Test:").pack(side=tk.LEFT, padx=(0, 5))
        test_type_combo = ttk.Combobox(top_frame, textvariable=self.test_type_var, 
                                       values=["ping", "speed", "both"], width=10)
        test_type_combo.pack(side=tk.LEFT, padx=(0, 10))
        test_type_combo.bind("<<ComboboxSelected>>", self.on_test_type_selected)
        
        # Test button
        self.test_button = ttk.Button(top_frame, text="Run Test", command=self.start_tests)
        self.test_button.pack(side=tk.LEFT, padx=(0, 10))
        
        # Connect button
        self.connect_button = ttk.Button(top_frame, text="Connect to Selected", command=self.connect_selected)
        self.connect_button.pack(side=tk.LEFT)
        
        # Status display
        status_frame = ttk.Frame(top_frame)
        status_frame.pack(side=tk.RIGHT)
        ttk.Label(status_frame, text="Status:").pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(status_frame, textvariable=self.status_var).pack(side=tk.LEFT)
        
        # Middle section - Server list
        middle_frame = ttk.Frame(main_frame)
        middle_frame.pack(fill=tk.BOTH, expand=True)
        
        # Server treeview
        columns = ("hostname", "city", "country", "protocol", "latency", "download", "upload")
        self.server_tree = ttk.Treeview(middle_frame, columns=columns, show="headings")
        
        # Define headings with sort on click
        self.server_tree.heading("hostname", text="Hostname", 
                                command=lambda: self.sort_treeview("hostname"))
        self.server_tree.heading("city", text="City", 
                                command=lambda: self.sort_treeview("city"))
        self.server_tree.heading("country", text="Country", 
                                command=lambda: self.sort_treeview("country"))
        self.server_tree.heading("protocol", text="Protocol", 
                                command=lambda: self.sort_treeview("protocol"))
        self.server_tree.heading("latency", text="Latency (ms)", 
                                command=lambda: self.sort_treeview("latency"))
        self.server_tree.heading("download", text="Download (Mbps)", 
                                command=lambda: self.sort_treeview("download"))
        self.server_tree.heading("upload", text="Upload (Mbps)", 
                                command=lambda: self.sort_treeview("upload"))
        
        # Define columns
        self.server_tree.column("hostname", width=150)
        self.server_tree.column("city", width=100)
        self.server_tree.column("country", width=100)
        self.server_tree.column("protocol", width=80)
        self.server_tree.column("latency", width=100)
        self.server_tree.column("download", width=120)
        self.server_tree.column("upload", width=120)
        
        # Add scrollbars
        tree_scroll_y = ttk.Scrollbar(middle_frame, orient=tk.VERTICAL, command=self.server_tree.yview)
        self.server_tree.configure(yscrollcommand=tree_scroll_y.set)
        
        # Pack the treeview and scrollbar
        self.server_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Configure tags for alternating row colors
        self.server_tree.tag_configure('odd_row', background=self.theme_colors["row_odd"])
        self.server_tree.tag_configure('even_row', background=self.theme_colors["row_even"])
        
        # Bottom section - Progress and status
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill=tk.X, pady=(10, 0))
        
        # Current operation label
        self.operation_label = ttk.Label(bottom_frame, textvariable=self.current_operation)
        self.operation_label.pack(side=tk.LEFT, padx=(0, 10))
        
        # Control buttons (initially hidden)
        self.control_frame = ttk.Frame(bottom_frame)
        self.control_frame.pack(side=tk.LEFT, padx=(10, 0))
        
        self.pause_button = ttk.Button(self.control_frame, text="Pause", command=self.pause_resume_test)
        self.pause_button.pack(side=tk.LEFT, padx=(0, 5))
        
        self.stop_button = ttk.Button(self.control_frame, text="Stop", command=self.stop_tests)
        self.stop_button.pack(side=tk.LEFT)
        
        # Hide control buttons initially
        self.control_frame.pack_forget()
        
        # Progress bar
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(bottom_frame, variable=self.progress_var, mode="determinate")
        self.progress_bar.pack(side=tk.RIGHT, fill=tk.X, expand=True)
    
    def on_test_type_selected(self, event):
        """Handle test type selection change."""
        test_type = self.test_type_var.get()
        self.config["test_type"] = test_type
        save_config(self.config)
        
        # Update button text based on test type
        if test_type == "ping":
            self.test_button.configure(text="Run Ping Test")
        elif test_type == "speed":
            self.test_button.configure(text="Run Speed Test")
        else:  # both
            self.test_button.configure(text="Run Full Test")
    
    def load_server_data(self):
        """Load the Mullvad server data from the cache file."""
        try:
            self.current_operation.set("Loading server data...")
            self.root.update()
            
            cache_path = get_cache_path(self.config)
            self.server_data = load_cached_servers(cache_path)
            
            if not self.server_data:
                messagebox.showerror("Error", f"Could not load server data from {cache_path}")
                self.current_operation.set("Failed to load server data")
                return
            
            # Extract countries
            self.countries = [
                {"code": country.get("code", ""), "name": country.get("name", "")}
                for country in self.server_data.get("countries", [])
            ]
            
            # Sort countries by name
            self.countries.sort(key=lambda x: x["name"])
            
            # Update country combobox
            country_names = ["All Countries"] + [c["name"] for c in self.countries]
            self.country_combo["values"] = country_names
            
            # Set the default selection
            last_country = self.config.get("last_country", "")
            if last_country:
                # Find the country name from the code
                for country in self.countries:
                    if country["code"] == last_country:
                        self.current_country_var.set(country["name"])
                        break
            
            if not self.current_country_var.get():
                self.current_country_var.set("All Countries")
            
            # Load the servers based on the selected country
            self.load_servers_by_country()
            self.current_operation.set("Ready")
            
        except Exception as e:
            messagebox.showerror("Error", f"Error loading server data: {e}")
            self.current_operation.set("Error loading server data")
    
    def load_servers_by_country(self):
        """Load the servers for the selected country and protocol."""
        if not self.server_data:
            return
        
        # Clear the current server list
        for item in self.server_tree.get_children():
            self.server_tree.delete(item)
        
        country_name = self.current_country_var.get()
        protocol = self.protocol_var.get()
        
        # Adjust protocol value
        if protocol == "both":
            protocol = None
        
        if country_name == "All Countries":
            servers = get_all_servers(self.server_data, protocol)
        else:
            # Find the country code from the name
            country_code = next((c["code"] for c in self.countries if c["name"] == country_name), None)
            if country_code:
                self.config["last_country"] = country_code
                save_config(self.config)
                servers = get_servers_by_country(self.server_data, country_code, protocol)
            else:
                servers = []
        
        # Add servers to the treeview with alternating row colors
        for i, server in enumerate(servers):
            hostname = server.get("hostname", "")
            city = server.get("city", "")
            country = server.get("country", "")
            
            # Determine protocol
            is_wireguard = "wg" in hostname.lower()
            protocol_str = "WireGuard" if is_wireguard else "OpenVPN"
            
            # Add to treeview with alternating row tag
            row_tag = 'odd_row' if i % 2 else 'even_row'
            self.server_tree.insert("", tk.END, values=(hostname, city, country, protocol_str, "", "", ""), 
                                    tags=(row_tag, hostname))
        
        # Apply the initial sort if configured
        self.sort_treeview(self.sort_column, force_order=self.sort_order)
    
    def sort_treeview(self, column, force_order=None):
        """Sort the treeview by the specified column."""
        # Get current sort column and order
        if column == self.sort_column and not force_order:
            # Toggle sort order if clicking the same column
            self.sort_order = "descending" if self.sort_order == "ascending" else "ascending"
        else:
            # New column - sort ascending by default
            self.sort_column = column
            self.sort_order = force_order if force_order else "ascending"
        
        # Update configuration
        self.config["default_sort_column"] = self.sort_column
        self.config["default_sort_order"] = self.sort_order
        save_config(self.config)
        
        # Get all items
        items = [(self.server_tree.set(item, column), item) for item in self.server_tree.get_children('')]
        
        # Convert values to the appropriate type for sorting
        if column in ['latency', 'download', 'upload']:
            # For numeric columns, convert to float for proper sorting
            # Handle empty values and "Timeout" text
            items = [
                (float(value) if value and value != "Timeout" else float('inf'), item) 
                for value, item in items
            ]
        
        # Sort items
        items.sort(reverse=(self.sort_order == "descending"))
        
        # Rearrange items in the sorted order
        for index, (_, item) in enumerate(items):
            # Move the item to the correct position
            self.server_tree.move(item, '', index)
            
            # Update row tags to maintain alternating colors
            current_tags = list(self.server_tree.item(item, "tags"))
            
            # Keep only non-row-color tags
            filtered_tags = [tag for tag in current_tags 
                           if not tag in ('odd_row', 'even_row')]
            
            # Add back the appropriate row color tag
            row_tag = 'odd_row' if index % 2 else 'even_row'
            filtered_tags.append(row_tag)
            
            self.server_tree.item(item, tags=filtered_tags)
    
    def export_to_csv(self):
        """Export the current server list to a CSV file."""
        # Get all items from the treeview
        items = self.server_tree.get_children()
        if not items:
            messagebox.showinfo("Export", "No data to export")
            return
        
        # Ask for save location
        file_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
            title="Export Server List"
        )
        
        if not file_path:
            return  # User cancelled
        
        try:
            # Create a list of dictionaries for each server
            servers = []
            for item in items:
                values = self.server_tree.item(item, "values")
                server = {
                    "hostname": values[0],
                    "city": values[1],
                    "country": values[2],
                    "protocol": values[3],
                    "latency": values[4] if values[4] else None,
                    "download_speed": values[5] if values[5] else None,
                    "upload_speed": values[6] if values[6] else None
                }
                servers.append(server)
            
            # Export to CSV
            if export_to_csv(servers, file_path):
                messagebox.showinfo("Export Successful", f"Server list exported to {file_path}")
            else:
                messagebox.showerror("Export Failed", "Failed to export server list")
        
        except Exception as e:
            messagebox.showerror("Export Error", f"Error exporting data: {e}")
    
    def save_test_results(self):
        """Save the current test results to a file."""
        # Get all items from the treeview
        items = self.server_tree.get_children()
        if not items:
            messagebox.showinfo("Save", "No data to save")
            return
        
        # Ask for save location
        file_path = filedialog.asksaveasfilename(
            defaultextension=".msf",
            filetypes=[("Mullvad Server Finder Files", "*.msf"), ("All Files", "*.*")],
            title="Save Test Results"
        )
        
        if not file_path:
            return  # User cancelled
        
        try:
            # Create a list of dictionaries for each server
            results = []
            for item in items:
                values = self.server_tree.item(item, "values")
                tags = self.server_tree.item(item, "tags")
                
                result = {
                    "hostname": values[0],
                    "city": values[1],
                    "country": values[2],
                    "protocol": values[3],
                    "latency": values[4] if values[4] else None,
                    "download_speed": values[5] if values[5] else None,
                    "upload_speed": values[6] if values[6] else None,
                    "tags": list(tags)
                }
                results.append(result)
            
            # Save to file
            with open(file_path, 'wb') as f:
                pickle.dump({
                    "timestamp": time.time(),
                    "country": self.current_country_var.get(),
                    "protocol": self.protocol_var.get(),
                    "results": results,
                    "sort_column": self.sort_column,
                    "sort_order": self.sort_order,
                    "cell_tags": list(self.created_cell_tags)
                }, f)
            
            messagebox.showinfo("Save Successful", f"Test results saved to {file_path}")
            
        except Exception as e:
            messagebox.showerror("Save Error", f"Error saving test results: {e}")
    
    def load_test_results(self):
        """Load test results from a file."""
        # Ask for file location
        file_path = filedialog.askopenfilename(
            filetypes=[("Mullvad Server Finder Files", "*.msf"), ("All Files", "*.*")],
            title="Load Test Results"
        )
        
        if not file_path:
            return  # User cancelled
        
        try:
            # Load the data
            with open(file_path, 'rb') as f:
                data = pickle.load(f)
            
            # Set the country and protocol if available
            if "country" in data:
                self.current_country_var.set(data["country"])
            
            if "protocol" in data:
                self.protocol_var.set(data["protocol"])
            
            # Clear existing items
            for item in self.server_tree.get_children():
                self.server_tree.delete(item)
            
            # Configure saved cell tags if available
            if "cell_tags" in data:
                for tag in data["cell_tags"]:
                    if "cell_" in tag:
                        # Extract color from tag
                        # Format: cell_latency_FF0000, cell_download_00FF00, etc.
                        parts = tag.split('_')
                        if len(parts) >= 3:
                            color_code = f"#{parts[2]}"
                            self.server_tree.tag_configure(tag, background=color_code)
                            self.created_cell_tags.add(tag)
            
            # Add the results to the treeview
            for i, result in enumerate(data.get("results", [])):
                # Determine row tag
                row_tag = 'odd_row' if i % 2 else 'even_row'
                
                # Get saved tags and ensure they exist
                saved_tags = result.get("tags", [])
                valid_tags = [row_tag]  # Start with row tag
                
                for tag in saved_tags:
                    # Accept cell_ tags that we've configured
                    if tag.startswith("cell_") and tag in self.created_cell_tags:
                        valid_tags.append(tag)
                
                # Insert into treeview
                item = self.server_tree.insert("", tk.END, values=(
                    result.get("hostname", ""),
                    result.get("city", ""),
                    result.get("country", ""),
                    result.get("protocol", ""),
                    result.get("latency", ""),
                    result.get("download_speed", ""),
                    result.get("upload_speed", "")
                ), tags=valid_tags)
            
            # Set the sort column and order if available
            if "sort_column" in data and "sort_order" in data:
                self.sort_column = data["sort_column"]
                self.sort_order = data["sort_order"]
                self.sort_treeview(self.sort_column, force_order=self.sort_order)
            
            # Show a message with the timestamp
            if "timestamp" in data:
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(data["timestamp"]))
                messagebox.showinfo("Load Successful", f"Test results loaded from {file_path}\nSaved on: {timestamp}")
            else:
                messagebox.showinfo("Load Successful", f"Test results loaded from {file_path}")
            
        except Exception as e:
            messagebox.showerror("Load Error", f"Error loading test results: {e}")
    
    def clear_all_results(self):
        """Clear all test results from the treeview."""
        # Ask for confirmation
        if messagebox.askyesno("Clear All", "Are you sure you want to clear all test results?"):
            # Get the current servers without test results
            items = self.server_tree.get_children()
            if not items:
                return
            
            # Clear the treeview
            for item in items:
                values = list(self.server_tree.item(item, "values"))
                
                # Clear latency, download, and upload values
                values[4] = ""  # Latency
                values[5] = ""  # Download
                values[6] = ""  # Upload
                
                # Get current tags and keep only row tags (odd/even)
                tags = list(self.server_tree.item(item, "tags"))
                tags = [tag for tag in tags if tag in ('odd_row', 'even_row') or tag == values[0]]
                
                # Update the item
                self.server_tree.item(item, values=values, tags=tags)
            
            self.current_operation.set("All test results cleared")
    
    def on_country_selected(self, event):
        """Handle country selection change."""
        self.load_servers_by_country()
    
    def on_protocol_selected(self, event):
        """Handle protocol selection change."""
        protocol = self.protocol_var.get()
        self.config["last_protocol"] = protocol
        save_config(self.config)
        self.load_servers_by_country()
    
    def start_tests(self, test_type=None):
        """Start tests based on the selected test type."""
        if self.ping_in_progress or self.speed_in_progress:
            messagebox.showinfo("Info", "Test already in progress")
            return
        
        # Use parameter or fallback to the dropdown selection
        test_type = test_type or self.test_type_var.get()
        
        # Get all visible servers from the treeview
        server_items = self.server_tree.get_children()
        if not server_items:
            messagebox.showinfo("Info", "No servers to test")
            return
        
        # Collect server information
        servers_to_test = []
        for item in server_items:
            values = self.server_tree.item(item, "values")
            hostname = values[0]
            city = values[1]
            country = values[2]
            protocol_str = values[3]
            
            # Find the corresponding server object
            for country_obj in self.server_data.get("countries", []):
                if country_obj.get("name") == country:
                    for city_obj in country_obj.get("cities", []):
                        if city_obj.get("name") == city:
                            for server in city_obj.get("relays", []):
                                if server.get("hostname") == hostname:
                                    servers_to_test.append(server)
                                    # Store the treeview item ID for updating later
                                    server["treeview_item"] = item
                                    break
        
        if not servers_to_test:
            messagebox.showinfo("Info", "Could not find server details for tests")
            return
        
        # Reset control events
        self.stop_event.clear()
        self.pause_event.clear()
        
        # Disable the test button and reset progress
        self.test_button.configure(state=tk.DISABLED)
        self.progress_var.set(0)
        
        # Show control buttons
        self.control_frame.pack(side=tk.LEFT, padx=(10, 0))
        self.pause_button.configure(text="Pause")
        
        # Start the loading animation
        operation_text = f"Testing {len(servers_to_test)} servers"
        self.loading_animation.update_text(operation_text)
        self.loading_animation.start(self.root)
        
        # Start the appropriate test(s)
        if test_type in ["ping", "both"]:
            self.ping_in_progress = True
            threading.Thread(target=self.run_ping_test, args=(servers_to_test, test_type), daemon=True).start()
        elif test_type == "speed":
            self.speed_in_progress = True
            threading.Thread(target=self.run_speed_test, args=(servers_to_test,), daemon=True).start()
    
    def pause_resume_test(self):
        """Pause or resume the current test."""
        if self.pause_event.is_set():
            # Resume test
            self.pause_event.clear()
            self.pause_button.configure(text="Pause")
            self.loading_animation.update_text("Resuming test")
        else:
            # Pause test
            self.pause_event.set()
            self.pause_button.configure(text="Resume")
            self.loading_animation.update_text("Test paused")
    
    def stop_tests(self):
        """Stop all running tests."""
        if not (self.ping_in_progress or self.speed_in_progress):
            return
        
        # Signal threads to stop
        self.stop_event.set()
        
        # Update UI in a thread-safe way
        self.root.after(0, lambda: self.loading_animation.update_text("Stopping tests"))
        
        # Disable control buttons until test is fully stopped
        self.root.after(0, lambda: self.pause_button.configure(state=tk.DISABLED))
        self.root.after(0, lambda: self.stop_button.configure(state=tk.DISABLED))
    
    def apply_cell_color(self, item, column_idx, cell_value, color_type):
        """Apply Excel-style cell background color to a specific cell."""
        if cell_value is None or cell_value == "" or cell_value == "Timeout":
            return
        
        try:
            value = float(cell_value)
            
            # Determine which color function to use
            if color_type == "latency":
                color = calculate_latency_color(value)
            elif color_type in ["download", "upload"]:
                color = calculate_speed_color(value)
            else:
                return
            
            # Create a unique tag for this cell's color
            cell_tag = f"cell_{color_type}_{color.replace('#', '')}"
            
            # Configure tag if it doesn't exist
            if cell_tag not in self.created_cell_tags:
                self.server_tree.tag_configure(cell_tag, background=color)
                self.created_cell_tags.add(cell_tag)
            
            # Get current item tags
            current_tags = list(self.server_tree.item(item, "tags"))
            
            # Remove any existing cell color tags for this column
            filtered_tags = [tag for tag in current_tags 
                           if not tag.startswith(f"cell_{color_type}_")]
            
            # Add the new cell color tag
            filtered_tags.append(cell_tag)
            
            # Update item tags
            self.server_tree.item(item, tags=filtered_tags)
            
        except (ValueError, TypeError):
            # Not a numeric value, ignore
            pass
    
    def run_ping_test(self, servers, test_type="ping"):
        """Run the ping test in a background thread."""
        try:
            def update_progress(percentage):
                # Schedule UI update on the main thread
                self.root.after(0, lambda: self.progress_var.set(percentage))
                self.root.after(0, lambda: self.loading_animation.update_text(
                    f"Pinging servers... {int(percentage)}% complete"))
            
            def update_result(result):
                server = result["server"]
                latency = result["latency"]
                item = server.get("treeview_item")
                
                if item:
                    # Get current values
                    values = list(self.server_tree.item(item, "values"))
                    
                    # Update latency
                    latency_str = f"{latency:.1f}" if latency is not None else "Timeout"
                    values[4] = latency_str
                    
                    # Schedule UI update on the main thread
                    self.root.after(0, lambda: self.server_tree.item(item, values=values))
                    
                    # Apply cell coloring if enabled
                    if self.config.get("color_latency", True) and latency is not None:
                        self.root.after(0, lambda: self.apply_cell_color(item, 4, latency, "latency"))
            
            # Run the ping tests with callbacks for progress and results
            results = test_servers(
                servers, 
                progress_callback=update_progress, 
                result_callback=update_result,
                max_workers=self.config.get("max_workers", 10),
                ping_count=self.config.get("ping_count", 4),
                stop_event=self.stop_event,
                pause_event=self.pause_event
            )
            
            # If test was not stopped and it's "both", start speed test
            if not self.stop_event.is_set() and test_type == "both":
                self.root.after(0, lambda: self.loading_animation.update_text("Ping test completed. Starting speed test..."))
                self.run_speed_test(servers)
                return
            
            # Otherwise sort and finish
            self.root.after(0, lambda: self.sort_treeview("latency"))
            
            # Highlight the fastest server
            if not self.stop_event.is_set():
                # Find the fastest server
                fastest_item = None
                fastest_latency = float('inf')
                
                for item in self.server_tree.get_children():
                    latency_str = self.server_tree.item(item, "values")[4]
                    if latency_str and latency_str != "Timeout":
                        try:
                            latency = float(latency_str)
                            if latency < fastest_latency:
                                fastest_latency = latency
                                fastest_item = item
                        except ValueError:
                            continue
                
                # Schedule UI update on the main thread
                if fastest_item:
                    self.root.after(0, lambda: self.server_tree.selection_set(fastest_item))
                    self.root.after(0, lambda: self.server_tree.focus(fastest_item))
                    self.root.after(0, lambda: self.server_tree.see(fastest_item))
                
                # Auto-connect to fastest if configured
                if self.config.get("auto_connect_fastest", False) and fastest_item:
                    self.root.after(0, self.connect_to_fastest)
            
            # Update final status
            final_text = "Ping test completed" if not self.stop_event.is_set() else "Ping test stopped"
            self.root.after(0, lambda: self.loading_animation.update_text(final_text))
            
            # Make sure we don't immediately stop the animation when only doing ping test
            # This keeps the animation visible until the finally block executes
            if test_type == "ping":
                time.sleep(0.5)  # Brief delay to ensure the animation text is visible
                
        except Exception as e:
            # Handle exceptions and schedule UI update on the main thread
            self.root.after(0, lambda: messagebox.showerror("Error", f"Error during ping test: {e}"))
            self.root.after(0, lambda: self.loading_animation.update_text("Ping test failed"))
        finally:
            # Stop loading animation and restore UI state on the main thread
            self.root.after(0, self.loading_animation.stop)
            
            # Re-enable the test button and hide controls if no other test is running
            self.ping_in_progress = False
            
            # Schedule UI update on the main thread
            if not self.speed_in_progress:
                self.root.after(0, lambda: self.test_button.configure(state=tk.NORMAL))
                self.root.after(0, lambda: self.control_frame.pack_forget())
                self.root.after(0, lambda: self.pause_button.configure(state=tk.NORMAL))
                self.root.after(0, lambda: self.stop_button.configure(state=tk.NORMAL))
    
    def run_speed_test(self, servers):
        """Run speed tests for the servers in a background thread."""
        try:
            # Set the flag
            self.speed_in_progress = True
            
            total = len(servers)
            completed = 0
            
            # Schedule UI update on the main thread
            self.root.after(0, lambda: self.progress_var.set(0))
            self.root.after(0, lambda: self.loading_animation.update_text(f"Testing speed for {total} servers..."))
            
            for i, server in enumerate(servers):
                # Check if test was stopped
                if self.stop_event.is_set():
                    break
                
                # Check if test is paused
                while self.pause_event.is_set() and not self.stop_event.is_set():
                    time.sleep(0.5)  # Sleep to reduce CPU usage while paused
                
                # Skip if test was stopped during pause
                if self.stop_event.is_set():
                    break
                
                # Get server details
                hostname = server.get("hostname", "")
                item = server.get("treeview_item")
                
                if not item:
                    continue
                
                # Update status on the main thread
                self.root.after(0, lambda host=hostname, idx=i: self.loading_animation.update_text(
                    f"Testing speed for {host}... ({idx+1}/{total})"))
                
                # Run the speed test
                download_speed, upload_speed = test_server_speed(
                    server, 
                    size_mb=self.config.get("speed_test_size", 10),
                    timeout=self.config.get("timeout_seconds", 30),
                    stop_event=self.stop_event
                )
                
                # Prepare the updated values
                values = list(self.server_tree.item(item, "values"))
                
                # Update download speed
                if download_speed is not None:
                    values[5] = f"{download_speed:.1f}"
                
                # Update upload speed
                if upload_speed is not None:
                    values[6] = f"{upload_speed:.1f}"
                
                # Schedule UI updates on the main thread
                self.root.after(0, lambda it=item, vals=values: self.server_tree.item(it, values=vals))
                
                # Apply cell coloring if enabled
                if self.config.get("color_speed", True):
                    if download_speed is not None:
                        self.root.after(0, lambda it=item, ds=download_speed: 
                                       self.apply_cell_color(it, 5, ds, "download"))
                    if upload_speed is not None:
                        self.root.after(0, lambda it=item, us=upload_speed: 
                                       self.apply_cell_color(it, 6, us, "upload"))
                
                # Update progress
                completed += 1
                self.root.after(0, lambda c=completed, t=total: self.progress_var.set(c / t * 100))
            
            # Sort by download speed if completed
            if not self.stop_event.is_set():
                self.root.after(0, lambda: self.sort_treeview("download"))
                self.root.after(0, lambda: self.loading_animation.update_text("Speed test completed"))
            else:
                self.root.after(0, lambda: self.loading_animation.update_text("Speed test stopped"))
            
        except Exception as e:
            # Handle exceptions and schedule UI update on the main thread
            self.root.after(0, lambda: messagebox.showerror("Error", f"Error during speed test: {e}"))
            self.root.after(0, lambda: self.loading_animation.update_text("Speed test failed"))
        finally:
            # Stop loading animation and restore UI state on the main thread
            self.root.after(0, self.loading_animation.stop)
            
            # Re-enable the test button and hide controls if no other test is running
            self.speed_in_progress = False
            
            # Schedule UI update on the main thread
            if not self.ping_in_progress:
                self.root.after(0, lambda: self.test_button.configure(state=tk.NORMAL))
                self.root.after(0, lambda: self.control_frame.pack_forget())
                self.root.after(0, lambda: self.pause_button.configure(state=tk.NORMAL))
                self.root.after(0, lambda: self.stop_button.configure(state=tk.NORMAL))

    def connect_selected(self):
        """Connect to the selected server."""
        selected_items = self.server_tree.selection()
        if not selected_items:
            messagebox.showinfo("Info", "No server selected")
            return
        
        # Get the selected server details
        values = self.server_tree.item(selected_items[0], "values")
        hostname = values[0]
        city = values[1]
        country = values[2]
        protocol_str = values[3]
        
        # Find the corresponding server object to get the codes
        country_code = None
        city_code = None
        
        for country_obj in self.server_data.get("countries", []):
            if country_obj.get("name") == country:
                country_code = country_obj.get("code")
                for city_obj in country_obj.get("cities", []):
                    if city_obj.get("name") == city:
                        city_code = city_obj.get("code")
                        break
                break
        
        if not country_code or not city_code:
            messagebox.showerror("Error", "Could not determine location codes")
            return
        
        # Set the protocol
        protocol = "wireguard" if protocol_str == "WireGuard" else "openvpn"
        
        # Connect in a separate thread to avoid freezing the UI
        threading.Thread(
            target=self._connect_to_server,
            args=(protocol, country_code, city_code, hostname),
            daemon=True
        ).start()
    
    def connect_to_fastest(self):
        """Connect to the fastest server based on ping results."""
        # Find the server with the lowest latency
        best_item = None
        best_latency = float('inf')
        
        for item in self.server_tree.get_children():
            values = self.server_tree.item(item, "values")
            latency_str = values[4]
            
            if latency_str and latency_str != "Timeout":
                try:
                    latency = float(latency_str)
                    if latency < best_latency:
                        best_latency = latency
                        best_item = item
                except ValueError:
                    continue
        
        if not best_item:
            messagebox.showinfo("Info", "No servers with valid latency found")
            return
        
        # Select the fastest server
        self.server_tree.selection_set(best_item)
        self.server_tree.focus(best_item)
        self.server_tree.see(best_item)
        
        # Connect to it
        self.connect_selected()
    
    def _connect_to_server(self, protocol, country_code, city_code, hostname):
        """Helper method to connect to a server in a background thread."""
        try:
            # Update UI on the main thread
            self.root.after(0, lambda: self.loading_animation.update_text(f"Connecting to {hostname}..."))
            
            # Set the protocol
            set_mullvad_protocol(protocol)
            
            # Set the location
            set_mullvad_location(country_code, city_code, hostname)
            
            # Connect to Mullvad
            connect_mullvad()
            
            # Update UI on the main thread
            self.root.after(0, lambda: self.loading_animation.update_text(f"Connected to {hostname}"))
            
        except Exception as e:
            # Handle exceptions and update UI on the main thread
            self.root.after(0, lambda: messagebox.showerror("Error", f"Error connecting to server: {e}"))
            self.root.after(0, lambda: self.loading_animation.update_text("Connection failed"))
    
    def disconnect(self):
        """Disconnect from Mullvad VPN."""
        # Disconnect in a separate thread
        threading.Thread(target=self._disconnect, daemon=True).start()
    
    def _disconnect(self):
        """Helper method to disconnect in a background thread."""
        try:
            # Update UI on the main thread
            self.root.after(0, lambda: self.loading_animation.update_text("Disconnecting..."))
            
            # Disconnect
            disconnect_mullvad()
            
            # Update UI on the main thread
            self.root.after(0, lambda: self.loading_animation.update_text("Disconnected"))
            
        except Exception as e:
            # Handle exceptions and update UI on the main thread
            self.root.after(0, lambda: messagebox.showerror("Error", f"Error disconnecting: {e}"))
            self.root.after(0, lambda: self.loading_animation.update_text("Disconnection failed"))
    
    def update_status(self):
        """Update the connection status periodically."""
        try:
            status = get_mullvad_status()
            self.status_var.set(status)
        except Exception as e:
            self.status_var.set(f"Error: {e}")
        
        # Schedule the next update
        self.root.after(5000, self.update_status)
    
    def add_selected_to_favorites(self):
        """Add the selected server to favorites."""
        selected_items = self.server_tree.selection()
        if not selected_items:
            messagebox.showinfo("Info", "No server selected")
            return
        
        # Get the selected server details
        values = self.server_tree.item(selected_items[0], "values")
        hostname = values[0]
        city = values[1]
        country = values[2]
        
        # Find the corresponding server object
        server = None
        for country_obj in self.server_data.get("countries", []):
            if country_obj.get("name") == country:
                for city_obj in country_obj.get("cities", []):
                    if city_obj.get("name") == city:
                        for relay in city_obj.get("relays", []):
                            if relay.get("hostname") == hostname:
                                server = relay
                                server["country_code"] = country_obj.get("code")
                                server["city_code"] = city_obj.get("code")
                                server["country"] = country
                                server["city"] = city
                                break
                        if server:
                            break
                if server:
                    break
        
        if not server:
            messagebox.showerror("Error", "Could not find server details")
            return
        
        # Add to favorites
        if add_favorite_server(self.config, server):
            messagebox.showinfo("Success", f"Added {hostname} to favorites")
        else:
            messagebox.showinfo("Info", f"{hostname} is already in favorites")
    
    def manage_favorites(self):
        """Open a window to manage favorite servers."""
        favorites_window = tk.Toplevel(self.root)
        favorites_window.title("Manage Favorites")
        favorites_window.geometry("500x400")
        favorites_window.transient(self.root)
        favorites_window.grab_set()
        
        # Create a listbox to display favorite servers
        frame = ttk.Frame(favorites_window, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(frame, text="Favorite Servers").pack(anchor=tk.W, pady=(0, 5))
        
        # Create a treeview for favorites
        columns = ("hostname", "city", "country")
        favorites_tree = ttk.Treeview(frame, columns=columns, show="headings")
        
        # Define headings
        favorites_tree.heading("hostname", text="Hostname")
        favorites_tree.heading("city", text="City")
        favorites_tree.heading("country", text="Country")
        
        # Define columns
        favorites_tree.column("hostname", width=200)
        favorites_tree.column("city", width=150)
        favorites_tree.column("country", width=150)
        
        # Add scrollbar
        tree_scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=favorites_tree.yview)
        favorites_tree.configure(yscrollcommand=tree_scroll.set)
        
        favorites_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Populate the treeview with favorite servers
        for favorite in self.config.get("favorite_servers", []):
            hostname = favorite.get("hostname", "")
            city = favorite.get("city", "")
            country = favorite.get("country", "")
            
            favorites_tree.insert("", tk.END, values=(hostname, city, country))
        
        # Button frame
        button_frame = ttk.Frame(favorites_window, padding=10)
        button_frame.pack(fill=tk.X)
        
        def connect_to_favorite():
            selection = favorites_tree.selection()
            if not selection:
                messagebox.showinfo("Info", "No server selected")
                return
            
            # Get the selected favorite details
            values = favorites_tree.item(selection[0], "values")
            hostname = values[0]
            
            # Find the corresponding favorite in config
            favorite = None
            for f in self.config["favorite_servers"]:
                if f.get("hostname") == hostname:
                    favorite = f
                    break
            
            if not favorite:
                messagebox.showerror("Error", "Could not find favorite details")
                return
            
            # Determine the protocol based on hostname
            is_wireguard = "wg" in hostname.lower()
            protocol = "wireguard" if is_wireguard else "openvpn"
            
            # Connect in a separate thread
            threading.Thread(
                target=self._connect_to_server,
                args=(protocol, favorite.get("country_code"), favorite.get("city_code"), hostname),
                daemon=True
            ).start()
            
            # Close the window
            favorites_window.destroy()
        
        def remove_favorite():
            selection = favorites_tree.selection()
            if not selection:
                messagebox.showinfo("Info", "No server selected")
                return
            
            # Get the selected favorite details
            values = favorites_tree.item(selection[0], "values")
            hostname = values[0]
            
            if remove_favorite_server(self.config, hostname):
                favorites_tree.delete(selection[0])
                messagebox.showinfo("Success", f"Removed {hostname} from favorites")
            else:
                messagebox.showerror("Error", f"Could not remove {hostname} from favorites")
        
        ttk.Button(button_frame, text="Connect", command=connect_to_favorite).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Remove", command=remove_favorite).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="Close", command=favorites_window.destroy).pack(side=tk.RIGHT)
    
    def open_settings(self):
        """Open the settings window."""
        settings_window = tk.Toplevel(self.root)
        settings_window.title("Settings")
        settings_window.geometry("520x450")
        settings_window.transient(self.root)
        settings_window.grab_set()
        
        # Create a frame for the settings
        frame = ttk.Frame(settings_window, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        
        # Create a notebook for tabbed settings
        notebook = ttk.Notebook(frame)
        notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # General settings tab
        general_tab = ttk.Frame(notebook, padding=10)
        notebook.add(general_tab, text="General")
        
        # Cache path setting
        ttk.Label(general_tab, text="Cache Path:").grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        
        cache_path_var = tk.StringVar(value=get_cache_path(self.config))
        cache_path_entry = ttk.Entry(general_tab, textvariable=cache_path_var, width=40)
        cache_path_entry.grid(row=0, column=1, sticky=tk.W+tk.E, padx=(5, 5))
        
        def browse_cache_path():
            path = filedialog.askopenfilename(
                title="Select Mullvad Cache File",
                filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")]
            )
            if path:
                cache_path_var.set(path)
        
        ttk.Button(general_tab, text="Browse...", command=browse_cache_path).grid(row=0, column=2, padx=(0, 5))
        
        # Auto-connect to fastest server
        auto_connect_var = tk.BooleanVar(value=self.config.get("auto_connect_fastest", False))
        ttk.Checkbutton(
            general_tab, 
            text="Automatically connect to fastest server after ping test", 
            variable=auto_connect_var
        ).grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(10, 5))
        
        # Theme mode
        ttk.Label(general_tab, text="Theme Mode:").grid(row=2, column=0, sticky=tk.W, pady=(10, 5))
        
        theme_var = tk.StringVar(value=self.config.get("theme_mode", "system"))
        theme_combo = ttk.Combobox(general_tab, textvariable=theme_var, values=["system", "light", "dark"], width=10)
        theme_combo.grid(row=2, column=1, sticky=tk.W, padx=(5, 5))
        ttk.Label(general_tab, text="Restart required for changes to take effect").grid(
            row=2, column=2, sticky=tk.W, padx=(5, 0))
        
        # Alternating row colors
        alt_rows_var = tk.BooleanVar(value=self.config.get("alternating_row_colors", True))
        ttk.Checkbutton(
            general_tab, 
            text="Use alternating row colors in server list", 
            variable=alt_rows_var
        ).grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=(10, 5))
        
        # Ping settings tab
        ping_tab = ttk.Frame(notebook, padding=10)
        notebook.add(ping_tab, text="Ping Settings")
        
        # Ping count setting
        ttk.Label(ping_tab, text="Ping Count:").grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        
        ping_count_var = tk.IntVar(value=self.config.get("ping_count", 4))
        ping_count_spinbox = ttk.Spinbox(ping_tab, from_=1, to=10, textvariable=ping_count_var, width=5)
        ping_count_spinbox.grid(row=0, column=1, sticky=tk.W, padx=(5, 5))
        ttk.Label(ping_tab, text="Higher values give more accurate results but take longer").grid(
            row=0, column=2, sticky=tk.W, padx=(5, 0))
        
        # Max workers setting
        ttk.Label(ping_tab, text="Max Concurrent Pings:").grid(row=1, column=0, sticky=tk.W, pady=(10, 5))
        
        max_workers_var = tk.IntVar(value=self.config.get("max_workers", 10))
        max_workers_spinbox = ttk.Spinbox(ping_tab, from_=1, to=50, textvariable=max_workers_var, width=5)
        max_workers_spinbox.grid(row=1, column=1, sticky=tk.W, padx=(5, 5))
        ttk.Label(ping_tab, text="Higher values test more servers in parallel").grid(
            row=1, column=2, sticky=tk.W, padx=(5, 0))
        
        # Ping timeout setting
        ttk.Label(ping_tab, text="Ping Timeout (seconds):").grid(row=2, column=0, sticky=tk.W, pady=(10, 5))
        
        timeout_var = tk.IntVar(value=self.config.get("timeout_seconds", 10))
        timeout_spinbox = ttk.Spinbox(ping_tab, from_=1, to=30, textvariable=timeout_var, width=5)
        timeout_spinbox.grid(row=2, column=1, sticky=tk.W, padx=(5, 5))
        
        # Color latency setting
        color_latency_var = tk.BooleanVar(value=self.config.get("color_latency", True))
        ttk.Checkbutton(
            ping_tab, 
            text="Color code latency values (Excel-style cell coloring)", 
            variable=color_latency_var
        ).grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=(10, 5))
        
        # Speed test settings tab
        speed_tab = ttk.Frame(notebook, padding=10)
        notebook.add(speed_tab, text="Speed Test")
        
        # Speed test size setting
        ttk.Label(speed_tab, text="Test File Size (MB):").grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        
        speed_size_var = tk.IntVar(value=self.config.get("speed_test_size", 10))
        speed_size_spinbox = ttk.Spinbox(speed_tab, from_=1, to=100, textvariable=speed_size_var, width=5)
        speed_size_spinbox.grid(row=0, column=1, sticky=tk.W, padx=(5, 5))
        ttk.Label(speed_tab, text="Larger files give more accurate results but take longer").grid(
            row=0, column=2, sticky=tk.W, padx=(5, 0))
        
        # Color speed setting
        color_speed_var = tk.BooleanVar(value=self.config.get("color_speed", True))
        ttk.Checkbutton(
            speed_tab, 
            text="Color code speed values (Excel-style cell coloring)", 
            variable=color_speed_var
        ).grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(10, 5))
        
        # Default test type
        ttk.Label(speed_tab, text="Default Test Type:").grid(row=2, column=0, sticky=tk.W, pady=(10, 5))
        
        test_type_var = tk.StringVar(value=self.config.get("test_type", "ping"))
        test_type_combo = ttk.Combobox(speed_tab, textvariable=test_type_var, 
                                      values=["ping", "speed", "both"], width=10)
        test_type_combo.grid(row=2, column=1, sticky=tk.W, padx=(5, 5))
        
        # Display settings tab
        display_tab = ttk.Frame(notebook, padding=10)
        notebook.add(display_tab, text="Display")
        
        # Default sort column
        ttk.Label(display_tab, text="Default Sort Column:").grid(row=0, column=0, sticky=tk.W, pady=(0, 5))
        
        sort_column_var = tk.StringVar(value=self.config.get("default_sort_column", "latency"))
        sort_column_combo = ttk.Combobox(display_tab, textvariable=sort_column_var, 
                                        values=["hostname", "city", "country", "protocol", 
                                                "latency", "download", "upload"], width=10)
        sort_column_combo.grid(row=0, column=1, sticky=tk.W, padx=(5, 5))
        
        # Default sort order
        ttk.Label(display_tab, text="Default Sort Order:").grid(row=1, column=0, sticky=tk.W, pady=(10, 5))
        
        sort_order_var = tk.StringVar(value=self.config.get("default_sort_order", "ascending"))
        sort_order_combo = ttk.Combobox(display_tab, textvariable=sort_order_var, 
                                       values=["ascending", "descending"], width=10)
        sort_order_combo.grid(row=1, column=1, sticky=tk.W, padx=(5, 5))
        
        # Button frame
        button_frame = ttk.Frame(frame)
        button_frame.pack(fill=tk.X)
        
        def save_settings():
            self.config["custom_cache_path"] = cache_path_var.get() if cache_path_var.get() != self.config["cache_path"] else ""
            self.config["ping_count"] = ping_count_var.get()
            self.config["max_workers"] = max_workers_var.get()
            self.config["auto_connect_fastest"] = auto_connect_var.get()
            self.config["timeout_seconds"] = timeout_var.get()
            self.config["theme_mode"] = theme_var.get()
            self.config["alternating_row_colors"] = alt_rows_var.get()
            self.config["color_latency"] = color_latency_var.get()
            self.config["color_speed"] = color_speed_var.get()
            self.config["speed_test_size"] = speed_size_var.get()
            self.config["test_type"] = test_type_var.get()
            self.config["default_sort_column"] = sort_column_var.get()
            self.config["default_sort_order"] = sort_order_var.get()
            
            # Update the test type in the UI
            self.test_type_var.set(test_type_var.get())
            self.on_test_type_selected(None)  # Update button text
            
            if save_config(self.config):
                messagebox.showinfo("Success", "Settings saved successfully")
                settings_window.destroy()
            else:
                messagebox.showerror("Error", "Could not save settings")
        
        ttk.Button(button_frame, text="Save", command=save_settings).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(button_frame, text="Cancel", command=settings_window.destroy).pack(side=tk.LEFT)
    
    def show_about(self):
        """Show the about dialog."""
        messagebox.showinfo(
            "About Mullvad Server Finder",
            "Mullvad Server Finder\n\n"
            "A tool to find the fastest Mullvad VPN server.\n\n"
            "This application interacts with the Mullvad VPN CLI to test server latency "
            "and connect to the fastest available server.\n\n"
            "Version: 1.0.0"
        )