# Mullvad Server Finder

A Python GUI application to identify and connect to the fastest Mullvad VPN servers. Retrieve server listings, perform latency and speed tests, and connect to optimal servers with a single click.

![Mullvad Server Finder Screenshot](Screenshot.png)

## Key Features

- **Server Discovery**: Automatically fetches the complete Mullvad server list
- **Performance Testing**: Runs ping tests to measure server latency and speed tests to measure throughput
- **Smart Filtering**: Filter servers by country, city, and protocol (WireGuard/OpenVPN)
- **Visual Feedback**: Color-coded latency and speed indicators help identify the best-performing servers
- **One-Click Connection**: Connect to any server directly from the application
- **Favorites System**: Save preferred servers for quick access
- **Customizable Settings**: Configure testing parameters, appearance, and behavior

## System Requirements

- Python 3.6 or newer
- Tkinter (included with most Python installations)
- Mullvad VPN desktop client installed and properly configured
- `mullvad` command-line tool in your system PATH

## Installation

1. Clone this repository:
   ```
   git clone https://github.com/yourusername/mullvad-server-finder.git
   cd mullvad-server-finder
   ```

2. (Optional) Create a virtual environment:
   ```
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```
   pip install ttkthemes  # For enhanced visual themes (optional)
   ```

## Usage Guide

### Starting the Application

Launch the application by running:
```
python main.py
```

### Selecting Servers

1. Use the country dropdown to filter servers by location
2. Select your preferred protocol (WireGuard or OpenVPN)
3. Choose a test type (ping, speed, or both)

### Testing Server Performance

1. Click "Run Test" to start testing server performance
2. Servers will be tested and sorted automatically with the best performers at the top
3. Results are color-coded for easy identification of optimal servers

### Connecting to Servers

- Select any server and click "Connect to Selected" to connect via the Mullvad client
- Use "Connect to Fastest" from the Connection menu to connect to the best-performing server
- Set up Auto-Connect in settings to automatically connect after tests

### Managing Favorites

- Add frequently used servers to your favorites list for quick access
- Manage favorites through the Favorites menu

## Configuration

Access the Settings dialog through the File menu to customize:

- **Cache Location**: Specify where the application finds Mullvad's relay list
- **Testing Parameters**: Configure ping count, timeout, concurrent tests, and more
- **Visual Settings**: Choose between light, dark, or system theme
- **Default Behaviors**: Set auto-connect options and default sorting preferences

## Troubleshooting

### Common Issues

- **Can't find Mullvad cache file**: In Settings, update the cache path to match your system's location
- **Connection failures**: Ensure Mullvad client is properly installed and has necessary permissions
- **Slow testing**: Reduce "Max Concurrent Pings" setting if your system has limited resources

### Platform-Specific Notes

- **macOS**: Cache file is typically located at `/Library/Caches/mullvad-vpn/relays.json`
- **Windows**: Cache file is usually in `%LOCALAPPDATA%\Mullvad VPN\relays.json`
- **Linux**: Cache file is commonly found in `~/.cache/mullvad-vpn/relays.json`

## Project Structure

- `main.py`: Application entry point
- `gui.py`: User interface implementation
- `server_manager.py`: Server testing and management functions
- `mullvad_api.py`: Integration with Mullvad VPN CLI
- `config.py`: User configuration management

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- [Mullvad VPN](https://mullvad.net/) for their privacy-focused VPN service
- The Tkinter and ttkthemes projects for GUI components