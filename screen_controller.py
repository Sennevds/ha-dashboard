import ctypes
import logging
import screen_brightness_control as sbc
import platform
import time
from threading import Timer


class ScreenController:
    """Controls screen power and brightness on Windows."""
    
    # Windows API constants for monitor power control
    WM_SYSCOMMAND = 0x0112
    SC_MONITORPOWER = 0xF170
    MONITOR_ON = -1
    MONITOR_OFF = 2
    MONITOR_STANDBY = 1
    
    def __init__(self):
        self.is_windows = platform.system() == "Windows"
        self._original_brightness = None
        self._screen_is_off = False
        self._hwnd = None
        self._keep_awake_timer = None
        
        if self.is_windows:
            # Get window handle for sending messages
            try:
                self._hwnd = ctypes.windll.user32.GetForegroundWindow()
            except Exception as e:
                logging.warning(f"Could not get window handle: {e}")
    
    def turn_screen_off(self):
        """Turn off the screen completely without triggering lock screen."""
        if not self.is_windows:
            logging.warning("Screen control only supported on Windows")
            return
        
        try:
            # Save current brightness if not already saved
            if self._original_brightness is None:
                self._original_brightness = self.get_brightness()
            
            # Method 1: Use Windows API to turn off monitor (most effective)
            try:
                # Send the monitor to standby/off state
                # Using PostMessage instead of SendMessage to avoid blocking
                ctypes.windll.user32.PostMessageW(
                    0xFFFF,  # HWND_BROADCAST - send to all windows
                    self.WM_SYSCOMMAND,
                    self.SC_MONITORPOWER,
                    self.MONITOR_OFF
                )
                logging.info("Screen turned off via Windows API (monitor power off)")
                self._screen_is_off = True
                
                # Start keep-awake mechanism to prevent Windows from locking
                self._start_keep_awake()
                
            except Exception as api_error:
                logging.warning(f"Windows API method failed: {api_error}, falling back to brightness")
                # Fallback: Dim to 0% if API fails
                self.set_brightness(0)
                self._screen_is_off = True
                logging.info("Screen turned off (brightness set to 0% - fallback method)")
                
        except Exception as e:
            logging.error(f"Error turning screen off: {e}", exc_info=True)
    
    def turn_screen_on(self):
        """Turn on the screen by restoring brightness."""
        if not self.is_windows:
            logging.warning("Screen control only supported on Windows")
            return
        
        try:
            # Stop keep-awake mechanism
            self._stop_keep_awake()
            
            # Method 1: Use Windows API to turn on monitor
            try:
                ctypes.windll.user32.PostMessageW(
                    0xFFFF,  # HWND_BROADCAST
                    self.WM_SYSCOMMAND,
                    self.SC_MONITORPOWER,
                    self.MONITOR_ON
                )
                logging.info("Screen turned on via Windows API")
                
                # Small delay to let monitor wake up
                time.sleep(0.1)
                
            except Exception as api_error:
                logging.warning(f"Windows API wake failed: {api_error}")
            
            # Always restore brightness to ensure screen is visible
            if self._original_brightness is not None:
                self.set_brightness(self._original_brightness)
                self._screen_is_off = False
                logging.info(f"Screen brightness restored to {self._original_brightness}%")
            else:
                # Default to 80% if no saved brightness
                self.set_brightness(80)
                self._screen_is_off = False
                logging.info("Screen turned on (brightness set to 80%)")
                
        except Exception as e:
            logging.error(f"Error turning screen on: {e}", exc_info=True)
    
    def set_brightness(self, level: int):
        """
        Set screen brightness.
        
        Args:
            level: Brightness level (0-100)
        """
        try:
            level = max(0, min(100, level))
            sbc.set_brightness(level)
            logging.debug(f"Brightness set to {level}%")
        except Exception as e:
            logging.error(f"Error setting brightness: {e}")
    
    def get_brightness(self) -> int:
        """Get current screen brightness."""
        try:
            brightness = sbc.get_brightness()
            if isinstance(brightness, list):
                return brightness[0] if brightness else 50
            return brightness
        except Exception as e:
            logging.error(f"Error getting brightness: {e}")
            return 50
    
    def save_brightness(self):
        """Save current brightness level."""
        current = self.get_brightness()
        # Only save if brightness is not 0 (screen not "off")
        if current > 0:
            self._original_brightness = current
    
    def restore_brightness(self):
        """Restore saved brightness level."""
        if self._original_brightness is not None:
            self.set_brightness(self._original_brightness)
    
    def dim_screen(self, dim_level: int = 20):
        """Dim the screen to specified level."""
        if self._original_brightness is None or self._original_brightness == 0:
            self.save_brightness()
        self.set_brightness(dim_level)
    
    def is_screen_off(self) -> bool:
        """Check if screen is currently off."""
        return self._screen_is_off
    
    def _start_keep_awake(self):
        """Start periodic system activity to prevent lock screen."""
        if not self.is_windows:
            return
        
        # Stop any existing timer
        self._stop_keep_awake()
        
        try:
            # ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
            # This prevents Windows from sleeping/locking while screen is "off"
            ES_CONTINUOUS = 0x80000000
            ES_SYSTEM_REQUIRED = 0x00000001
            ES_DISPLAY_REQUIRED = 0x00000002
            
            # Set thread execution state to prevent sleep
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED
            )
            
            logging.debug("Keep-awake mechanism started (prevents lock screen)")
            
            # Schedule periodic refresh every 30 seconds to maintain the state
            self._keep_awake_timer = Timer(30.0, self._refresh_keep_awake)
            self._keep_awake_timer.daemon = True
            self._keep_awake_timer.start()
            
        except Exception as e:
            logging.error(f"Error starting keep-awake: {e}")
    
    def _refresh_keep_awake(self):
        """Refresh the keep-awake state periodically."""
        if self._screen_is_off and self.is_windows:
            try:
                ES_CONTINUOUS = 0x80000000
                ES_SYSTEM_REQUIRED = 0x00000001
                
                ctypes.windll.kernel32.SetThreadExecutionState(
                    ES_CONTINUOUS | ES_SYSTEM_REQUIRED
                )
                
                logging.debug("Keep-awake refreshed")
                
                # Schedule next refresh
                self._keep_awake_timer = Timer(30.0, self._refresh_keep_awake)
                self._keep_awake_timer.daemon = True
                self._keep_awake_timer.start()
                
            except Exception as e:
                logging.error(f"Error refreshing keep-awake: {e}")
    
    def _stop_keep_awake(self):
        """Stop the keep-awake mechanism."""
        if self._keep_awake_timer:
            self._keep_awake_timer.cancel()
            self._keep_awake_timer = None
        
        if self.is_windows:
            try:
                # Reset execution state to normal
                ES_CONTINUOUS = 0x80000000
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
                logging.debug("Keep-awake mechanism stopped")
            except Exception as e:
                logging.error(f"Error stopping keep-awake: {e}")
    
    def cleanup(self):
        """Clean up resources when controller is destroyed."""
        self._stop_keep_awake()

