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
            # ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED | ES_AWAYMODE_REQUIRED
            # This prevents Windows from sleeping/locking while screen is "off"
            ES_CONTINUOUS = 0x80000000
            ES_SYSTEM_REQUIRED = 0x00000001
            ES_DISPLAY_REQUIRED = 0x00000002
            ES_AWAYMODE_REQUIRED = 0x00000040
            
            # Set thread execution state to prevent sleep and lock
            # Using ES_DISPLAY_REQUIRED keeps display available even when "off"
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED | ES_AWAYMODE_REQUIRED
            )
            
            logging.debug("Keep-awake mechanism started (prevents lock screen)")
            
            # Schedule periodic activity simulation every 45 seconds
            self._keep_awake_timer = Timer(45.0, self._refresh_keep_awake)
            self._keep_awake_timer.daemon = True
            self._keep_awake_timer.start()
            
        except Exception as e:
            logging.error(f"Error starting keep-awake: {e}")
    
    def _simulate_user_activity(self):
        """Simulate minimal user activity to prevent screen lock."""
        try:
            # Use INPUT structure to simulate keyboard input
            # Press and release Shift key (0x10) - least intrusive
            # This prevents lock screen without affecting running applications
            
            # INPUT structure for keyboard
            class KEYBDINPUT(ctypes.Structure):
                _fields_ = [
                    ("wVk", ctypes.c_ushort),
                    ("wScan", ctypes.c_ushort),
                    ("dwFlags", ctypes.c_ulong),
                    ("time", ctypes.c_ulong),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))
                ]
            
            class INPUT(ctypes.Structure):
                _fields_ = [
                    ("type", ctypes.c_ulong),
                    ("ki", KEYBDINPUT)
                ]
            
            # Send F15 key (rarely used, won't interfere)
            # F15 = 0x7E
            extra = ctypes.c_ulong(0)
            
            # Key down
            ii_ = INPUT()
            ii_.type = 1  # INPUT_KEYBOARD
            ii_.ki = KEYBDINPUT(0x7E, 0, 0, 0, ctypes.pointer(extra))
            ctypes.windll.user32.SendInput(1, ctypes.pointer(ii_), ctypes.sizeof(ii_))
            
            # Key up
            ii_.ki.dwFlags = 0x0002  # KEYEVENTF_KEYUP
            ctypes.windll.user32.SendInput(1, ctypes.pointer(ii_), ctypes.sizeof(ii_))
            
            logging.debug("User activity simulated (F15 key)")
            
        except Exception as e:
            logging.warning(f"Could not simulate user activity: {e}")
    
    def _refresh_keep_awake(self):
        """Refresh the keep-awake state periodically."""
        if self._screen_is_off and self.is_windows:
            try:
                # Refresh execution state
                ES_CONTINUOUS = 0x80000000
                ES_SYSTEM_REQUIRED = 0x00000001
                ES_DISPLAY_REQUIRED = 0x00000002
                ES_AWAYMODE_REQUIRED = 0x00000040
                
                ctypes.windll.kernel32.SetThreadExecutionState(
                    ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED | ES_AWAYMODE_REQUIRED
                )
                
                # Simulate user activity to prevent lock
                self._simulate_user_activity()
                
                logging.debug("Keep-awake refreshed with activity simulation")
                
                # Schedule next refresh
                self._keep_awake_timer = Timer(45.0, self._refresh_keep_awake)
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

