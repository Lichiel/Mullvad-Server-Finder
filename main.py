import tkinter as tk
from tkinter import ttk
import sys
import os
import platform
import threading

# Add the current directory to the path so we can import our modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import our application modules
from gui import MullvadFinderApp

def set_appearance_mode():
    """Set the appearance mode based on the OS."""
    try:
        # Try to use the themed tk if available
        from ttkthemes import ThemedTk
        root = ThemedTk(theme="arc")  # A modern looking theme
    except ImportError:
        # Fall back to regular Tk if ttkthemes is not available
        root = tk.Tk()
        
        # Apply system theme on supported platforms
        if platform.system() == 'Windows':
            try:
                from tkinter import _windowingsystem
                if _windowingsystem == 'win32':
                    import ctypes
                    ctypes.windll.shcore.SetProcessDpiAwareness(1)
                    root.tk.call('source', 'azure.tcl')
            except:
                pass
        elif platform.system() == 'Darwin':  # macOS
            try:
                root.tk.call('source', 'aqua.tcl')
            except:
                pass
    
    # Set up DPI awareness
    if platform.system() == 'Windows':
        try:
            # Make the application DPI aware
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            # Adjust font sizes based on DPI
            font_scale = root.winfo_fpixels('1i') / 72
            default_font = ('Segoe UI', int(9 * font_scale))
            root.option_add('*Font', default_font)
        except:
            pass
        
    
    return root

def check_dependencies():
    """Check if the Mullvad CLI is installed and accessible."""
    import subprocess
    try:
        result = subprocess.run(['mullvad', '--version'], capture_output=True, text=True)
        if result.returncode == 0:
            return True
        return False
    except FileNotFoundError:
        return False

def main():
    """Main entry point for the application."""
    # Check dependencies
    if not check_dependencies():
        import tkinter.messagebox as messagebox
        messagebox.showerror(
            "Dependency Error",
            "Mullvad CLI not found. Please install the Mullvad VPN client and ensure the CLI tool is in your PATH."
        )
        return

    # Set up the root window
    root = set_appearance_mode()
    root.title("Mullvad Server Finder")
    
    # Set a minimum size
    root.minsize(800, 500)
    
    # Initialize the application
    app = MullvadFinderApp(root)
    
    # Start the Tkinter main loop
    root.mainloop()

if __name__ == "__main__":
    main()
