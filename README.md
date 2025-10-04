# Tablet Home Assistant Application

A full-screen Windows tablet application that displays Home Assistant or a cookbook web app with intelligent presence detection and screen management.

## Features

- **Full-Screen Web Browser**: Displays Home Assistant or cookbook web applications
- **Presence Detection**: Uses webcam and face detection to monitor if someone is looking at the tablet
- **Automatic Screen Management**: 
  - Turns screen off when no one is present (configurable timeout)
  - Turns screen on when someone looks at the tablet
  - Optional brightness dimming instead of screen off
- **MQTT Integration**: Control tablet remotely via Home Assistant
- **App Switching**: Toggle between Home Assistant and Cookbook apps
- **Brightness Control**: Adjust screen brightness via MQTT or API

## Installation

### Prerequisites

- Windows 10/11
- Python 3.9 or higher
- Webcam
- Home Assistant instance (optional but recommended)

### Setup

1. **Clone or download this repository**

2. **Install Python dependencies**:
```powershell
pip install -r requirements.txt
```

3. **Configure the application**:
Edit `config.json` with your settings:

```json
{
  "home_assistant": {
    "url": "http://homeassistant.local:8123",
    "token": ""
  },
  "cookbook": {
    "url": "https://your-cookbook-app.com"
  },
  "mqtt": {
    "enabled": true,
    "broker": "homeassistant.local",
    "port": 1883,
    "username": "mqtt_user",
    "password": "mqtt_password",
    "topic_prefix": "tablet"
  },
  "presence_detection": {
    "enabled": true,
    "check_interval_ms": 1000,
    "presence_timeout_seconds": 30,
    "detection_confidence": 0.5
  },
  "screen": {
    "turn_off_when_no_presence": true,
    "dim_brightness_when_no_presence": false,
    "dim_level": 20,
    "normal_brightness": 100
  }
}
```

## Usage

### Running the Application

```powershell
python main.py
```

The application will:
1. Start in fullscreen mode
2. Load Home Assistant URL
3. Begin monitoring for presence via webcam
4. Connect to MQTT broker (if enabled)

### Keyboard Shortcuts

- **F1**: Switch between Home Assistant and Cookbook
- **F11**: Toggle fullscreen mode
- **Ctrl+Q**: Quit application

### MQTT Control

The application publishes to and subscribes from MQTT topics:

#### Published Topics (State)

- `tablet/state/presence`: Person detection status (`detected` or `not_detected`)
- `tablet/state/brightness`: Current screen brightness (0-100)
- `tablet/state/current_app`: Currently displayed app (`home_assistant` or `cookbook`)
- `tablet/state/availability`: Application online status (`online` or `offline`)

#### Subscribed Topics (Commands)

- `tablet/command/brightness`: Set brightness (0-100)
- `tablet/command/screen`: Turn screen on/off (`on` or `off`)
- `tablet/command/switch_app`: Switch apps (`home_assistant`, `cookbook`, or `toggle`)
- `tablet/command/presence_detection`: Enable/disable detection (`on` or `off`)

### Home Assistant Integration

The application supports MQTT Discovery. After connecting, it will automatically create entities in Home Assistant:

- **Binary Sensor**: `binary_sensor.tablet_presence` - Shows if person is detected
- **Sensor**: `sensor.tablet_brightness` - Shows current brightness

#### Example Home Assistant Automation

```yaml
automation:
  - alias: "Dim tablet at night"
    trigger:
      - platform: time
        at: "22:00:00"
    action:
      - service: mqtt.publish
        data:
          topic: "tablet/command/brightness"
          payload: "20"

  - alias: "Switch to cookbook when cooking"
    trigger:
      - platform: state
        entity_id: input_boolean.cooking_mode
        to: "on"
    action:
      - service: mqtt.publish
        data:
          topic: "tablet/command/switch_app"
          payload: "cookbook"
```

## Configuration Options

### Presence Detection

- `enabled`: Enable/disable presence detection
- `check_interval_ms`: How often to check for presence (milliseconds)
- `presence_timeout_seconds`: Seconds of no presence before turning screen off
- `detection_confidence`: Face detection confidence threshold (0.0-1.0)

### Screen Management

- `turn_off_when_no_presence`: Turn screen off when no one present
- `dim_brightness_when_no_presence`: Dim instead of turning off (alternative)
- `dim_level`: Brightness level when dimmed (0-100)
- `normal_brightness`: Normal brightness level (0-100)

## Auto-Start on Windows Boot

### Method 1: Task Scheduler

1. Open Task Scheduler
2. Create Basic Task
3. Set trigger to "When the computer starts"
4. Set action to "Start a program"
5. Program: `pythonw.exe` (or full path to Python)
6. Arguments: `C:\src\Tablet-HA\main.py`
7. Start in: `C:\src\Tablet-HA`

### Method 2: Startup Folder

1. Create a batch file `start_tablet.bat`:
```batch
@echo off
cd /d C:\src\Tablet-HA
pythonw.exe main.py
```

2. Press `Win+R`, type `shell:startup`, press Enter
3. Copy the batch file to the Startup folder

## Troubleshooting

### Camera Not Working

- Check Windows camera permissions: Settings > Privacy > Camera
- Ensure no other application is using the camera
- Try a different camera index in `presence_detector.py` (change `cv2.VideoCapture(0)` to `cv2.VideoCapture(1)`)

### Screen Control Not Working

- Run application as Administrator
- Check Windows power settings
- Verify display drivers are up to date

### MQTT Connection Issues

- Verify broker address and port
- Check username/password
- Ensure MQTT broker is running
- Check firewall settings

### Web Page Not Loading

- Verify internet connection
- Check URL in config.json
- Try loading the URL in a regular browser first

## Architecture

```
main.py                 # Main application and UI
├── presence_detector.py   # Webcam face detection
├── screen_controller.py   # Windows screen control
├── mqtt_client.py         # MQTT communication
└── config.json           # Configuration file
```

## Dependencies

- **PyQt6**: GUI and web rendering
- **OpenCV**: Camera capture
- **MediaPipe**: Face detection
- **paho-mqtt**: MQTT client
- **screen-brightness-control**: Brightness management

## Performance Tips

1. **Reduce check interval**: Increase `check_interval_ms` for lower CPU usage
2. **Lower resolution**: Camera resolution is set to 640x480 for performance
3. **Adjust confidence**: Lower `detection_confidence` for better detection but more false positives
4. **Disable when not needed**: Turn off presence detection via MQTT when tablet is in a fixed location

## License

This project is provided as-is for personal use.

## Support

For issues or questions, please check the troubleshooting section or review the configuration options.
