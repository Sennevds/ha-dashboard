"""
Test script to verify the Tablet-HA application setup.
Run this before starting the main application.
"""

import sys
import importlib.util


def check_module(module_name, package_name=None):
    """Check if a Python module is installed."""
    if package_name is None:
        package_name = module_name
    
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        print(f"❌ {package_name} is NOT installed")
        return False
    else:
        print(f"✓ {package_name} is installed")
        return True


def check_camera():
    """Check if camera is accessible."""
    try:
        import cv2
        camera = cv2.VideoCapture(0)
        if camera.isOpened():
            ret, frame = camera.read()
            camera.release()
            if ret:
                print("✓ Camera is accessible")
                return True
            else:
                print("❌ Camera opened but cannot read frames")
                return False
        else:
            print("❌ Cannot open camera")
            return False
    except Exception as e:
        print(f"❌ Camera check failed: {e}")
        return False


def check_config():
    """Check if config.json exists and is valid."""
    try:
        import json
        with open('config.json', 'r') as f:
            config = json.load(f)
        print("✓ config.json exists and is valid")
        
        # Check required keys
        required_keys = ['home_assistant', 'cookbook', 'mqtt', 'presence_detection', 'screen']
        missing_keys = [key for key in required_keys if key not in config]
        
        if missing_keys:
            print(f"⚠ Warning: Missing config keys: {missing_keys}")
            return False
        
        return True
    except FileNotFoundError:
        print("❌ config.json not found")
        return False
    except json.JSONDecodeError:
        print("❌ config.json is not valid JSON")
        return False
    except Exception as e:
        print(f"❌ Config check failed: {e}")
        return False


def check_python_version():
    """Check Python version."""
    version = sys.version_info
    if version.major >= 3 and version.minor >= 9:
        print(f"✓ Python {version.major}.{version.minor}.{version.micro} (requirement: 3.9+)")
        return True
    else:
        print(f"❌ Python {version.major}.{version.minor}.{version.micro} (requirement: 3.9+)")
        return False


def check_platform():
    """Check if running on Windows."""
    import platform
    if platform.system() == "Windows":
        print(f"✓ Running on Windows ({platform.release()})")
        return True
    else:
        print(f"⚠ Warning: Running on {platform.system()} (application designed for Windows)")
        return False


def main():
    """Run all checks."""
    print("=" * 60)
    print("Tablet-HA Application Setup Test")
    print("=" * 60)
    print()
    
    all_passed = True
    
    # Check Python version
    print("Checking Python version...")
    if not check_python_version():
        all_passed = False
    print()
    
    # Check platform
    print("Checking platform...")
    check_platform()  # Warning only, not failure
    print()
    
    # Check required modules
    print("Checking required Python packages...")
    modules_to_check = [
        ("PyQt6", "PyQt6"),
        ("PyQt6.QtWebEngineWidgets", "PyQt6-WebEngine"),
        ("cv2", "opencv-python"),
        ("mediapipe", "mediapipe"),
        ("paho.mqtt.client", "paho-mqtt"),
        ("screen_brightness_control", "screen-brightness-control"),
        ("PIL", "Pillow")
    ]
    
    for module, package in modules_to_check:
        if not check_module(module, package):
            all_passed = False
    print()
    
    # Check camera
    print("Checking camera access...")
    if not check_camera():
        print("⚠ Warning: Camera not accessible. Presence detection will not work.")
        print("  Make sure:")
        print("  - No other application is using the camera")
        print("  - Camera permissions are enabled in Windows Settings")
    print()
    
    # Check config
    print("Checking configuration...")
    if not check_config():
        all_passed = False
    print()
    
    # Summary
    print("=" * 60)
    if all_passed:
        print("✓ All checks passed! You can run the application with:")
        print("  python main.py")
    else:
        print("❌ Some checks failed. Please fix the issues above.")
        print("  To install missing packages, run:")
        print("  pip install -r requirements.txt")
    print("=" * 60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = main()
    input("\nPress Enter to exit...")
    sys.exit(exit_code)
