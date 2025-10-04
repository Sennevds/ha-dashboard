import ctypes
import screen_brightness_control as sbc
import platform


class ScreenController:
    """Controls screen power and brightness on Windows."""
    
    def __init__(self):
        self.is_windows = platform.system() == "Windows"
        self._original_brightness = None
        self._screen_is_off = False
    
    def turn_screen_off(self):
        """Turn off the screen by dimming to 0% (avoids lock screen)."""
        if not self.is_windows:
            print("Screen control only supported on Windows")
            return
        
        try:
            # Save current brightness if not already saved
            if self._original_brightness is None:
                self._original_brightness = self.get_brightness()
            
            # Dim to 0% instead of using monitor power management
            # This avoids triggering the Windows lock screen
            self.set_brightness(0)
            self._screen_is_off = True
            print("Screen turned off (brightness set to 0%)")
        except Exception as e:
            print(f"Error turning screen off: {e}")
    
    def turn_screen_on(self):
        """Turn on the screen by restoring brightness."""
        if not self.is_windows:
            print("Screen control only supported on Windows")
            return
        
        try:
            # Restore previous brightness
            if self._original_brightness is not None:
                self.set_brightness(self._original_brightness)
                self._screen_is_off = False
                print(f"Screen turned on (brightness restored to {self._original_brightness}%)")
            else:
                # Default to 80% if no saved brightness
                self.set_brightness(80)
                self._screen_is_off = False
                print("Screen turned on (brightness set to 80%)")
        except Exception as e:
            print(f"Error turning screen on: {e}")
    
    def set_brightness(self, level: int):
        """
        Set screen brightness.
        
        Args:
            level: Brightness level (0-100)
        """
        try:
            level = max(0, min(100, level))
            sbc.set_brightness(level)
            print(f"Brightness set to {level}%")
        except Exception as e:
            print(f"Error setting brightness: {e}")
    
    def get_brightness(self) -> int:
        """Get current screen brightness."""
        try:
            brightness = sbc.get_brightness()
            if isinstance(brightness, list):
                return brightness[0] if brightness else 50
            return brightness
        except Exception as e:
            print(f"Error getting brightness: {e}")
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
