import sys
import json
import time
import os
import logging
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
    mqtt_brightness = pyqtSignal(str)
    mqtt_screen = pyqtSignal(str)
    mqtt_switch_app = pyqtSignal(str)
    mqtt_presence_detection = pyqtSignal(str)


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
        
        # Connect MQTT signals to handlers (for thread-safe UI updates)
        self.signal_emitter.mqtt_brightness.connect(self._handle_brightness_command_ui)
        self.signal_emitter.mqtt_screen.connect(self._handle_screen_command_ui)
        self.signal_emitter.mqtt_switch_app.connect(self._handle_switch_app_command_ui)
        self.signal_emitter.mqtt_presence_detection.connect(self._handle_presence_detection_command_ui)
        
        self.presence_detector = None
        self.screen_controller = ScreenController()
        self.mqtt_client = None
        self.current_app = "home_assistant"  # or "cookbook"
        self.last_presence_time = time.time()
        self.last_user_activity_time = time.time()
        self.screen_is_off = False
        self.user_activity_enabled = self.config.get("screen", {}).get("wake_on_user_input", True)
        
        # Setup update manager
        self.update_manager = UpdateManager(self.config)
        self.update_worker = None
        self.progress_dialog = None
        
        # Setup UI
        self._setup_ui()
        self._setup_shortcuts()
        
        # Install event filter for user activity detection
        self._setup_user_activity_detection()
        
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
        
        logging.info("Application initialized")
    
    def _load_config(self, config_path: str) -> dict:
        """Load configuration from JSON file."""
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            logging.info(f"Configuration loaded from {config_path}")
            return config
        except Exception as e:
            logging.error(f"Error loading config: {e}")
            logging.warning("Using default configuration")
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
                      "dim_level": 20, "normal_brightness": 100, "wake_on_user_input": True}
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
        
        # Setup persistent web profile BEFORE creating web view
        profile_dir = self.app_dir / "webdata"
        profile_dir.mkdir(exist_ok=True)
        
        # Create persistent profile with a unique name (parent is self for proper cleanup)
        self.profile = QWebEngineProfile("TabletHA", self)
        self.profile.setPersistentStoragePath(str(profile_dir))
        self.profile.setCachePath(str(profile_dir / "cache"))
        
        # Enable persistent cookies
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )
        
        # Configure web engine settings
        settings = self.profile.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, False)
        
        # Create web page with our persistent profile (profile is parent)
        self.web_page = QWebEnginePage(self.profile, self.profile)
        
        # Create web view and set our custom page
        self.web_view = QWebEngineView()
        self.web_view.setPage(self.web_page)
        
        layout.addWidget(self.web_view)
        
        logging.info(f"Web profile initialized with storage at: {profile_dir}")
        
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
    
    def _setup_user_activity_detection(self):
        """Setup event filter to detect user activity (mouse, keyboard, touch)."""
        if not self.user_activity_enabled:
            logging.info("User activity detection disabled in config")
            return
        
        # Install event filter on the application
        QApplication.instance().installEventFilter(self)
        logging.info("User activity detection enabled (mouse, keyboard, touch)")
    
    def eventFilter(self, obj, event):
        """Filter events to detect user activity and wake screen."""
        from PyQt6.QtCore import QEvent
        
        # Only process events if screen is off and user activity is enabled
        if self.screen_is_off and self.user_activity_enabled:
            # Detect mouse movement
            if event.type() == QEvent.Type.MouseMove:
                self._on_user_activity("mouse movement")
            
            # Detect mouse button press
            elif event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
                self._on_user_activity("mouse click")
            
            # Detect keyboard input
            elif event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                self._on_user_activity("keyboard")
            
            # Detect touch events
            elif event.type() in (QEvent.Type.TouchBegin, QEvent.Type.TouchUpdate, QEvent.Type.TouchEnd):
                self._on_user_activity("touch")
            
            # Detect tablet/stylus events
            elif event.type() in (QEvent.Type.TabletPress, QEvent.Type.TabletMove, QEvent.Type.TabletRelease):
                self._on_user_activity("stylus")
        
        # Always update last activity time when not in "off" state
        elif not self.screen_is_off:
            current_time = time.time()
            # Update activity time (throttle to once per second to avoid excessive updates)
            if current_time - self.last_user_activity_time > 1.0:
                if event.type() in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, 
                                   QEvent.Type.KeyPress, QEvent.Type.TouchBegin):
                    self.last_user_activity_time = current_time
        
        # Pass event to the base class
        return super().eventFilter(obj, event)
    
    def _on_user_activity(self, activity_type: str):
        """Handle detected user activity."""
        current_time = time.time()
        
        # Throttle activity detection (avoid multiple triggers within 500ms)
        if current_time - self.last_user_activity_time < 0.5:
            return
        
        self.last_user_activity_time = current_time
        logging.info(f"User activity detected ({activity_type}), waking screen")
        
        # Wake the screen
        if self.screen_is_off:
            self.screen_controller.turn_screen_on()
            self.screen_is_off = False
            
            # Also update presence time to prevent immediate timeout
            self.last_presence_time = current_time
            
            # Publish to MQTT
            if self.mqtt_client:
                self.mqtt_client.publish_state("screen_wake_reason", activity_type)
    
    def _load_app(self, app_name: str):
        """Load specified application URL."""
        try:
            if app_name == "home_assistant":
                url = self.config["home_assistant"]["url"]
                self.current_app = "home_assistant"
            elif app_name == "cookbook":
                url = self.config["cookbook"]["url"]
                self.current_app = "cookbook"
            else:
                logging.warning(f"Unknown app name: {app_name}")
                return
            
            self.web_view.setUrl(QUrl(url))
            logging.info(f"Loaded {app_name}: {url}")
            
            # Publish state via MQTT
            if self.mqtt_client:
                self.mqtt_client.publish_state("current_app", app_name)
        except Exception as e:
            logging.error(f"Error loading app '{app_name}': {e}", exc_info=True)
            QMessageBox.critical(
                self, "Error Loading Application",
                f"Failed to load {app_name}:\n{str(e)}"
            )
    
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
        logging.info(f"Presence changed: {'Person detected' if present else 'No person detected'}")
        
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
                logging.info("No presence detected for timeout period, turning screen off")
                self.screen_controller.turn_screen_off()
                self.screen_is_off = True
            elif self.config["screen"]["dim_brightness_when_no_presence"]:
                dim_level = self.config["screen"]["dim_level"]
                self.screen_controller.dim_screen(dim_level)
    
    def _setup_mqtt(self):
        """Setup MQTT client."""
        self.mqtt_client = MQTTClient(self.config["mqtt"])
        
        # Register callbacks that emit signals (thread-safe)
        self.mqtt_client.register_callback("brightness", 
                                          lambda payload: self.signal_emitter.mqtt_brightness.emit(payload))
        self.mqtt_client.register_callback("screen", 
                                          lambda payload: self.signal_emitter.mqtt_screen.emit(payload))
        self.mqtt_client.register_callback("switch_app", 
                                          lambda payload: self.signal_emitter.mqtt_switch_app.emit(payload))
        self.mqtt_client.register_callback("presence_detection", 
                                          lambda payload: self.signal_emitter.mqtt_presence_detection.emit(payload))
        
        # Connect
        self.mqtt_client.connect()
        
        # Wait a bit for connection, then publish discovery
        QTimer.singleShot(2000, self.mqtt_client.publish_discovery_config)
    
    def _handle_brightness_command_ui(self, payload: str):
        """Handle brightness command from MQTT (runs on UI thread)."""
        try:
            brightness = int(payload)
            self.screen_controller.set_brightness(brightness)
            
            # Publish state
            if self.mqtt_client:
                self.mqtt_client.publish_state("brightness", brightness)
        except ValueError:
            logging.error(f"Invalid brightness value: {payload}")
        except Exception as e:
            logging.error(f"Error handling brightness command: {e}", exc_info=True)
    
    def _handle_screen_command_ui(self, payload: str):
        """Handle screen command from MQTT (runs on UI thread)."""
        try:
            payload = payload.lower()
            
            if payload == "on":
                self.screen_controller.turn_screen_on()
                self.screen_is_off = False
            elif payload == "off":
                self.screen_controller.turn_screen_off()
                self.screen_is_off = True
        except Exception as e:
            logging.error(f"Error handling screen command: {e}", exc_info=True)
    
    def _handle_switch_app_command_ui(self, payload: str):
        """Handle switch app command from MQTT (runs on UI thread)."""
        try:
            payload = payload.lower()
            
            if payload in ["home_assistant", "cookbook"]:
                self._load_app(payload)
            elif payload == "toggle":
                self._switch_app()
        except Exception as e:
            logging.error(f"Error handling switch app command: {e}", exc_info=True)
    
    def _handle_presence_detection_command_ui(self, payload: str):
        """Handle presence detection command from MQTT (runs on UI thread)."""
        try:
            payload = payload.lower()
            
            if payload == "on" and self.presence_detector:
                if not self.presence_detector.is_running:
                    self.presence_detector.start()
            elif payload == "off" and self.presence_detector:
                if self.presence_detector.is_running:
                    self.presence_detector.stop()
        except Exception as e:
            logging.error(f"Error handling presence detection command: {e}", exc_info=True)
    def _check_for_updates(self):
        """Check for available updates."""
        if not self.update_manager.enabled:
            return
        
        logging.info("Checking for updates...")
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
        logging.info("Closing application...")
        
        # Clean up web engine components in proper order
        # Order: view -> page -> profile (reverse of creation)
        if hasattr(self, 'web_view'):
            logging.info("Cleaning up web view...")
            # Clear the page from the view first
            self.web_view.setPage(None)
            # Process events to ensure cleanup
            QApplication.processEvents()
        
        if hasattr(self, 'web_page'):
            logging.info("Deleting web page...")
            # Explicitly delete the page before profile
            self.web_page.deleteLater()
            self.web_page = None
            QApplication.processEvents()
        
        if hasattr(self, 'profile'):
            logging.info("Flushing web profile data to disk...")
            # Let the profile save cookies and local storage
            QApplication.processEvents()
        
        # Clean up screen controller
        if hasattr(self, 'screen_controller') and self.screen_controller:
            logging.info("Cleaning up screen controller...")
            self.screen_controller.cleanup()
        
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
    # Setup logging
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.FileHandler('tablet_ha.log'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    logging.info("Starting Tablet HA application")
    
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
