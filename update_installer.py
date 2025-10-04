"""
Update Installer Script
This script is spawned by the main application to install updates after it exits.
"""

import sys
import json
import time
import shutil
import zipfile
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('update_install.log'),
        logging.StreamHandler()
    ]
)

def wait_for_process_exit(pid, timeout=30):
    """Wait for a process to exit."""
    import psutil
    try:
        process = psutil.Process(pid)
        logging.info(f"Waiting for process {pid} to exit...")
        process.wait(timeout=timeout)
        logging.info(f"Process {pid} has exited")
        return True
    except psutil.NoSuchProcess:
        logging.info(f"Process {pid} already exited")
        return True
    except psutil.TimeoutExpired:
        logging.error(f"Timeout waiting for process {pid} to exit")
        return False
    except Exception as e:
        logging.error(f"Error waiting for process: {e}")
        return False

def install_update(app_dir, zip_path, old_config_json):
    """
    Install the update after the main application has exited.
    
    Args:
        app_dir: Application directory path
        zip_path: Path to update ZIP file
        old_config_json: JSON string of old config to preserve
    """
    try:
        app_dir = Path(app_dir)
        zip_path = Path(zip_path)
        
        logging.info(f"Installing update from {zip_path} to {app_dir}")
        
        # Extract to temporary directory
        update_dir = app_dir / "updates"
        temp_extract_dir = update_dir / "temp_extract"
        if temp_extract_dir.exists():
            shutil.rmtree(temp_extract_dir)
        temp_extract_dir.mkdir(parents=True, exist_ok=True)
        
        logging.info(f"Extracting update to {temp_extract_dir}")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_extract_dir)
        
        # Find the TabletHA directory in the extracted files
        extracted_items = list(temp_extract_dir.iterdir())
        if len(extracted_items) == 1 and extracted_items[0].is_dir():
            source_dir = extracted_items[0]
        else:
            source_dir = temp_extract_dir
        
        # Parse old config
        old_config = None
        if old_config_json:
            try:
                old_config = json.loads(old_config_json)
            except Exception as e:
                logging.warning(f"Could not parse old config: {e}")
        
        # Copy new files (excluding certain directories)
        logging.info("Installing update files...")
        for item in source_dir.iterdir():
            if item.name in ['webdata', 'updates', '__pycache__']:
                logging.info(f"Skipping {item.name}")
                continue
            
            dest_path = app_dir / item.name
            
            # Remove old file/directory
            if dest_path.exists():
                if dest_path.is_dir():
                    logging.info(f"Removing old directory: {dest_path}")
                    shutil.rmtree(dest_path)
                else:
                    logging.info(f"Removing old file: {dest_path}")
                    dest_path.unlink()
            
            # Copy new file/directory
            if item.is_dir():
                logging.info(f"Copying directory: {item} -> {dest_path}")
                shutil.copytree(item, dest_path)
            else:
                logging.info(f"Copying file: {item} -> {dest_path}")
                shutil.copy2(item, dest_path)
        
        # Merge user config with new config
        if old_config:
            new_config_file = app_dir / "_internal" / "config.json"
            if new_config_file.exists():
                try:
                    logging.info("Merging user configuration with new version...")
                    new_config = json.loads(new_config_file.read_text(encoding='utf-8'))
                    
                    # Preserve user settings from all sections except 'updates'
                    for section in old_config:
                        if section == 'updates':
                            # Keep new version number but preserve user preferences
                            if 'updates' in new_config:
                                new_config['updates']['enabled'] = old_config['updates'].get('enabled', True)
                                new_config['updates']['check_on_startup'] = old_config['updates'].get('check_on_startup', True)
                                new_config['updates']['auto_install'] = old_config['updates'].get('auto_install', False)
                        else:
                            # Preserve all other user settings
                            new_config[section] = old_config[section]
                    
                    new_config_file.write_text(json.dumps(new_config, indent=2), encoding='utf-8')
                    logging.info("Configuration merged successfully")
                except Exception as e:
                    logging.error(f"Error merging config: {e}")
        
        # Clean up
        logging.info("Cleaning up temporary files...")
        shutil.rmtree(temp_extract_dir)
        zip_path.unlink()
        
        logging.info("Update installed successfully!")
        return True
        
    except Exception as e:
        logging.error(f"Error installing update: {e}", exc_info=True)
        return False

def restart_application(app_dir):
    """Restart the application after update."""
    import subprocess
    try:
        exe_path = Path(app_dir) / "TabletHA.exe"
        if exe_path.exists():
            logging.info(f"Restarting application: {exe_path}")
            subprocess.Popen([str(exe_path)], cwd=str(app_dir))
            return True
        else:
            logging.error(f"Executable not found: {exe_path}")
            return False
    except Exception as e:
        logging.error(f"Error restarting application: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    if len(sys.argv) < 5:
        logging.error("Usage: update_installer.py <pid> <app_dir> <zip_path> <config_json>")
        sys.exit(1)
    
    pid = int(sys.argv[1])
    app_dir = sys.argv[2]
    zip_path = sys.argv[3]
    old_config_json = sys.argv[4]
    
    logging.info("="*60)
    logging.info("TabletHA Update Installer")
    logging.info("="*60)
    logging.info(f"PID to wait for: {pid}")
    logging.info(f"App directory: {app_dir}")
    logging.info(f"Update ZIP: {zip_path}")
    
    # Wait for main app to exit
    if not wait_for_process_exit(pid):
        logging.error("Failed to wait for process to exit")
        sys.exit(1)
    
    # Give it a moment to fully release file handles
    time.sleep(2)
    
    # Install the update
    if install_update(app_dir, zip_path, old_config_json):
        logging.info("Update installation complete!")
        
        # Restart the application
        if restart_application(app_dir):
            logging.info("Application restarted successfully")
            sys.exit(0)
        else:
            logging.error("Failed to restart application")
            sys.exit(1)
    else:
        logging.error("Update installation failed")
        sys.exit(1)
