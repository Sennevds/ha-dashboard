import sys
import json
import time
import os
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QMessageBox, QProgressDialog
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage, QWebEngineProfile
from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal, QObject, QThread
from PyQt6.QtGui import QKeySequence, QScreen, QShortcut
from presence_detector import PresenceDetector
from screen_controller import ScreenController
from mqtt_client import MQTTClient
from updater import UpdateManager


class UpdateWorker(QThread):
    """Worker thread for checking and downloading updates."""
    update_available = pyqtSignal(dict)
    download_progress = pyqtSignal(int, int)
    download_complete = pyqtSignal(bool)
    
    def __init__(self, update_manager, update_info=None):
        super().__init__()
        self.update_manager = update_manager
        self.update_info = update_info
        self.should_download = update_info is not None
    
    def run(self):
        """Run the update check or download."""
        if self.should_download and self.update_info:
            # Download and install
            success = self.update_manager.download_and_install(
                self.update_info,
                progress_callback=lambda current, total: self.download_progress.emit(current, total),
                completion_callback=lambda success: self.download_complete.emit(success)
            )
        else:
            # Just check
            update_info = self.update_manager.check_and_notify()
            if update_info:
                self.update_available.emit(update_info)


class SignalEmitter(QObject):
    """Helper class to emit Qt signals from background threads."""
    presence_changed = pyqtSignal(bool)
    mqtt_command = pyqtSignal(str, str)


class TabletApp(QMainWindow):
    """Main application window for the tablet."""
    
    def __init__(self, config_path: str = None):
        super().__init__()
        
        # Determine application directory (works for both script and exe)
        if getattr(sys, 'frozen', False):
            # Running as compiled executable
            # PyInstaller stores data files in _internal subdirectory
            self.app_dir = Path(sys.executable).parent
            if (self.app_dir / "_internal").exists():
                self.data_dir = self.app_dir / "_internal"
            else:
                self.data_dir = self.app_dir
        else:
            # Running as script
            self.app_dir = Path(__file__).parent
            self.data_dir = self.app_dir
        
        # Set default config path if not provided
        if config_path is None:
            # Look for config in data directory first, then app directory
            if (self.data_dir / "config.json").exists():
                config_path = self.data_dir / "config.json"
            else:
                config_path = self.app_dir / "config.json"
        
        # Load configuration
        self.config = self._load_config(config_path)
        
        # Initialize components
        self.signal_emitter = SignalEmitter()
        self.presence_detector = None
        self.screen_controller = ScreenController()
        self.mqtt_client = None
        self.current_app = "home_assistant"  # or "cookbook"
        self.last_presence_time = time.time()
        self.screen_is_off = False
        
        # Setup update manager
        self.update_manager = UpdateManager(self.config)
        self.update_worker = None
        self.progress_dialog = None
        
        # Setup UI
        self._setup_ui()
        self._setup_shortcuts()
        
        # Setup presence detection
        if self.config["presence_detection"]["enabled"]:
            self._setup_presence_detection()
        
        # Setup MQTT
        if self.config["mqtt"]["enabled"]:
            self._setup_mqtt()
        
        # Setup presence timeout timer
        self.presence_timer = QTimer()
        self.presence_timer.timeout.connect(self._check_presence_timeout)
        self.presence_timer.start(5000)  # Check every 5 seconds
        
        # Check for updates on startup if enabled
        if self.update_manager.check_on_startup:
            QTimer.singleShot(5000, self._check_for_updates)  # Check after 5 seconds
        
        print("Application initialized")
    
    def _load_config(self, config_path: str) -> dict:
        """Load configuration from JSON file."""
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            print(f"Configuration loaded from {config_path}")
            return config
        except Exception as e:
            print(f"Error loading config: {e}")
            print("Using default configuration")
            return self._default_config()
    
    def _default_config(self) -> dict:
        """Return default configuration."""
        return {
            "home_assistant": {"url": "http://homeassistant.local:8123", "token": ""},
            "cookbook": {"url": "https://www.allrecipes.com"},
            "mqtt": {"enabled": False},
            "presence_detection": {"enabled": True, "check_interval_ms": 1000, 
                                   "presence_timeout_seconds": 30, "detection_confidence": 0.5},
            "screen": {"turn_off_when_no_presence": True, "dim_brightness_when_no_presence": False,
                      "dim_level": 20, "normal_brightness": 100}
        }
    
    def _setup_ui(self):
        """Setup the user interface."""
        self.setWindowTitle("Tablet HA")
        
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Create layout
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Create web view
        self.web_view = QWebEngineView()
        
        # Setup persistent web profile for cookies and cache
        profile_dir = self.app_dir / "webdata"
        profile_dir.mkdir(exist_ok=True)
        self.profile = self.web_view.page().profile()
        self.profile.setPersistentStoragePath(str(profile_dir))
        self.profile.setCachePath(str(profile_dir / "cache"))
        
        # Configure web engine settings
        settings = self.profile.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
        
        layout.addWidget(self.web_view)
        
        # Load initial URL
        self._load_app("home_assistant")
        
        # Set fullscreen
        self.showFullScreen()
        
        # Hide cursor after inactivity
        QApplication.setOverrideCursor(Qt.CursorShape.BlankCursor)
    
    def _setup_shortcuts(self):
        """Setup keyboard shortcuts."""
        # Switch between apps
        switch_shortcut = QShortcut(QKeySequence(self.config.get("shortcuts", {}).get("switch_app", "F1")), self)
        switch_shortcut.activated.connect(self._switch_app)
        
        # Exit fullscreen
        exit_fs_shortcut = QShortcut(QKeySequence(self.config.get("shortcuts", {}).get("exit_fullscreen", "F11")), self)
        exit_fs_shortcut.activated.connect(self._toggle_fullscreen)
        
        # Quit application
        quit_shortcut = QShortcut(QKeySequence(self.config.get("shortcuts", {}).get("quit_app", "Ctrl+Q")), self)
        quit_shortcut.activated.connect(self.close)
    
    def _load_app(self, app_name: str):
        """Load specified application URL."""
        if app_name == "home_assistant":
            url = self.config["home_assistant"]["url"]
            self.current_app = "home_assistant"
        elif app_name == "cookbook":
            url = self.config["cookbook"]["url"]
            self.current_app = "cookbook"
        else:
            return
        
        self.web_view.setUrl(QUrl(url))
        print(f"Loaded {app_name}: {url}")
        
        # Publish state via MQTT
        if self.mqtt_client:
            self.mqtt_client.publish_state("current_app", app_name)
    
    def _switch_app(self):
        """Switch between Home Assistant and Cookbook."""
        if self.current_app == "home_assistant":
            self._load_app("cookbook")
        else:
            self._load_app("home_assistant")
    
    def _toggle_fullscreen(self):
        """Toggle fullscreen mode."""
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
    
    def _setup_presence_detection(self):
        """Setup presence detection."""
        config = self.config["presence_detection"]
        check_interval = config["check_interval_ms"] / 1000.0
        confidence = config["detection_confidence"]
        detection_mode = config.get("detection_mode", "both")
        
        self.presence_detector = PresenceDetector(
            detection_confidence=confidence,
            check_interval=check_interval,
            detection_mode=detection_mode
        )
        
        # Connect signals
        self.signal_emitter.presence_changed.connect(self._on_presence_changed)
        
        # Add callback
        self.presence_detector.add_callback(
            lambda present: self.signal_emitter.presence_changed.emit(present)
        )
        
        # Start detection
        self.presence_detector.start()
    
    def _on_presence_changed(self, present: bool):
        """Handle presence change."""
        print(f"Presence changed: {'Person detected' if present else 'No person detected'}")
        
        if present:
            self.last_presence_time = time.time()
            
            # Turn screen on or restore brightness
            if self.screen_is_off:
                self.screen_controller.turn_screen_on()
                self.screen_is_off = False
            elif self.config["screen"]["dim_brightness_when_no_presence"]:
                self.screen_controller.restore_brightness()
        
        # Publish to MQTT
        if self.mqtt_client:
            status = "detected" if present else "not_detected"
            self.mqtt_client.publish_state("presence", status)
    
    def _check_presence_timeout(self):
        """Check if presence timeout has been reached."""
        if not self.config["presence_detection"]["enabled"]:
            return
        
        if not self.presence_detector:
            return
        
        timeout = self.config["presence_detection"]["presence_timeout_seconds"]
        time_since_last = time.time() - self.last_presence_time
        
        if time_since_last > timeout:
            if self.config["screen"]["turn_off_when_no_presence"] and not self.screen_is_off:
                print("No presence detected for timeout period, turning screen off")
                self.screen_controller.turn_screen_off()
                self.screen_is_off = True
            elif self.config["screen"]["dim_brightness_when_no_presence"]:
                dim_level = self.config["screen"]["dim_level"]
                self.screen_controller.dim_screen(dim_level)
    
    def _setup_mqtt(self):
        """Setup MQTT client."""
        self.mqtt_client = MQTTClient(self.config["mqtt"])
        
        # Register callbacks
        self.mqtt_client.register_callback("brightness", self._handle_brightness_command)
        self.mqtt_client.register_callback("screen", self._handle_screen_command)
        self.mqtt_client.register_callback("switch_app", self._handle_switch_app_command)
        self.mqtt_client.register_callback("presence_detection", self._handle_presence_detection_command)
        
        # Connect
        self.mqtt_client.connect()
        
        # Wait a bit for connection, then publish discovery
        QTimer.singleShot(2000, self.mqtt_client.publish_discovery_config)
    
    def _handle_brightness_command(self, payload: str):
        """Handle brightness command from MQTT."""
        try:
            brightness = int(payload)
            self.screen_controller.set_brightness(brightness)
            
            # Publish state
            if self.mqtt_client:
                self.mqtt_client.publish_state("brightness", brightness)
        except ValueError:
            print(f"Invalid brightness value: {payload}")
    
    def _handle_screen_command(self, payload: str):
        """Handle screen command from MQTT."""
        payload = payload.lower()
        
        if payload == "on":
            self.screen_controller.turn_screen_on()
            self.screen_is_off = False
        elif payload == "off":
            self.screen_controller.turn_screen_off()
            self.screen_is_off = True
    
    def _handle_switch_app_command(self, payload: str):
        """Handle switch app command from MQTT."""
        payload = payload.lower()
        
        if payload in ["home_assistant", "cookbook"]:
            self._load_app(payload)
        elif payload == "toggle":
            self._switch_app()
    
    def _handle_presence_detection_command(self, payload: str):
        """Handle presence detection command from MQTT."""
        payload = payload.lower()
        
        if payload == "on" and self.presence_detector:
            if not self.presence_detector.is_running:
                self.presence_detector.start()
        elif payload == "off" and self.presence_detector:
            if self.presence_detector.is_running:
                self.presence_detector.stop()
    def _check_for_updates(self):
        """Check for available updates."""
        if not self.update_manager.enabled:
            return
        
        print("Checking for updates...")
        self.update_worker = UpdateWorker(self.update_manager)
        self.update_worker.update_available.connect(self._on_update_available)
        self.update_worker.start()
    
    def _on_update_available(self, update_info: dict):
        """Handle update available notification."""
        version = update_info['version']
        size_mb = update_info['size'] / 1024 / 1024
        
        # Show update notification
        msg = QMessageBox(self)
        msg.setWindowTitle("Update Available")
        msg.setText(f"A new version is available: v{version}")
        msg.setInformativeText(
            f"Size: {size_mb:.1f} MB\n\n"
            f"Would you like to download and install this update?\n\n"
            f"Release Notes:\n{update_info.get('release_notes', '')[:200]}..."
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | 
                              QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.Yes)
        
        if msg.exec() == QMessageBox.StandardButton.Yes:
            self._download_and_install_update(update_info)
    
    def _download_and_install_update(self, update_info: dict):
        """Download and install an update."""
        # Show progress dialog
        self.progress_dialog = QProgressDialog(
            "Downloading update...", "Cancel", 0, 100, self
        )
        self.progress_dialog.setWindowTitle("Updating Tablet-HA")
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setValue(0)
        
        # Start download worker
        self.update_worker = UpdateWorker(self.update_manager, update_info)
        self.update_worker.download_progress.connect(self._on_download_progress)
        self.update_worker.download_complete.connect(self._on_download_complete)
        self.update_worker.start()
    
    def _on_download_progress(self, current: int, total: int):
        """Update download progress."""
        if self.progress_dialog:
            percent = int((current / total) * 100)
            self.progress_dialog.setValue(percent)
            
            # Update label with size info
            current_mb = current / 1024 / 1024
            total_mb = total / 1024 / 1024
            self.progress_dialog.setLabelText(
                f"Downloading update: {current_mb:.1f} MB / {total_mb:.1f} MB"
            )
    
    def _on_download_complete(self, success: bool):
        """Handle download completion."""
        if self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
        
        if success:
            # Show restart prompt
            msg = QMessageBox(self)
            msg.setWindowTitle("Update Installed")
            msg.setText("Update installed successfully!")
            msg.setInformativeText(
                "The application needs to restart to complete the update.\n\n"
                "Restart now?"
            )
            msg.setStandardButtons(QMessageBox.StandardButton.Yes | 
                                  QMessageBox.StandardButton.No)
            msg.setDefaultButton(QMessageBox.StandardButton.Yes)
            
            if msg.exec() == QMessageBox.StandardButton.Yes:
                self.update_manager.checker.restart_application()
        else:
            # Show error
            QMessageBox.critical(
                self, "Update Failed",
                "Failed to download or install the update.\n\n"
                "Please try again later or download manually from GitHub."
            )
    
    def closeEvent(self, event):
        """Handle application close."""
        print("Closing application...")
        
        # Stop presence detection
        if self.presence_detector:
            self.presence_detector.stop()
        
        # Disconnect MQTT
        if self.mqtt_client:
            self.mqtt_client.publish_state("availability", "offline")
            self.mqtt_client.disconnect()
        
        event.accept()


def main():
    """Main entry point."""
    app = QApplication(sys.argv)
    
    # Set application properties
    app.setApplicationName("Tablet HA")
    app.setApplicationDisplayName("Tablet Home Assistant")
    
    # Create main window
    window = TabletApp()
    
    # Run application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
