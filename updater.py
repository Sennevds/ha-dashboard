"""
Automatic Update System for Tablet-HA
Checks for updates from GitHub releases and downloads/installs them.
"""

import sys
import json
import logging
import requests
import zipfile
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Dict, Tuple
from packaging import version as pkg_version


class UpdateChecker:
    """Checks for and manages application updates."""
    
    def __init__(self, current_version: str, repo_owner: str, repo_name: str):
        """
        Initialize the update checker.
        
        Args:
            current_version: Current application version (e.g., "1.0.0")
            repo_owner: GitHub repository owner
            repo_name: GitHub repository name
        """
        self.current_version = current_version
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.github_api_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/releases/latest"
        
        # Determine application directory
        if getattr(sys, 'frozen', False):
            self.app_dir = Path(sys.executable).parent
        else:
            self.app_dir = Path(__file__).parent
            
        self.update_dir = self.app_dir / "updates"
        self.update_dir.mkdir(exist_ok=True)
    
    def check_for_updates(self) -> Optional[Dict]:
        """
        Check if a newer version is available.
        
        Returns:
            Dict with update info if available, None otherwise
        """
        try:
            logging.info(f"Checking for updates from {self.github_api_url}")
            response = requests.get(self.github_api_url, timeout=10)
            response.raise_for_status()
            
            release_info = response.json()
            latest_version = release_info['tag_name'].lstrip('v')
            
            logging.info(f"Current version: {self.current_version}")
            logging.info(f"Latest version: {latest_version}")
            
            # Compare versions
            if pkg_version.parse(latest_version) > pkg_version.parse(self.current_version):
                # Find the Windows portable ZIP asset
                for asset in release_info['assets']:
                    if 'portable' in asset['name'].lower() and asset['name'].endswith('.zip'):
                        return {
                            'version': latest_version,
                            'download_url': asset['browser_download_url'],
                            'filename': asset['name'],
                            'size': asset['size'],
                            'release_notes': release_info.get('body', ''),
                            'published_at': release_info.get('published_at', '')
                        }
                
                logging.info("No portable ZIP found in latest release")
                return None
            else:
                logging.info("Application is up to date")
                return None
                
        except requests.exceptions.RequestException as e:
            logging.error(f"Error checking for updates: {e}")
            return None
        except Exception as e:
            logging.error(f"Unexpected error: {e}", exc_info=True)
            return None
    
    def download_update(self, update_info: Dict, progress_callback=None) -> Optional[Path]:
        """
        Download the update file.
        
        Args:
            update_info: Update information from check_for_updates()
            progress_callback: Optional callback function(bytes_downloaded, total_bytes)
            
        Returns:
            Path to downloaded file, or None on error
        """
        try:
            download_url = update_info['download_url']
            filename = update_info['filename']
            total_size = update_info['size']
            
            download_path = self.update_dir / filename
            
            logging.info(f"Downloading update from {download_url}")
            logging.info(f"Saving to {download_path}")
            
            response = requests.get(download_url, stream=True, timeout=30)
            response.raise_for_status()
            
            bytes_downloaded = 0
            with open(download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        bytes_downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(bytes_downloaded, total_size)
            
            logging.info(f"Download complete: {download_path}")
            return download_path
            
        except Exception as e:
            logging.error(f"Error downloading update: {e}", exc_info=True)
            return None
    
    def install_update(self, zip_path: Path, backup: bool = True) -> bool:
        """
        Prepare and launch the update installer.
        This spawns a separate process to install the update after this app exits.
        
        Args:
            zip_path: Path to the downloaded ZIP file
            backup: Whether to create a backup before updating
            
        Returns:
            True if installer was launched, False otherwise
        """
        try:
            # Create backup if requested
            if backup:
                backup_dir = self.app_dir.parent / f"TabletHA_backup_{self.current_version}"
                if backup_dir.exists():
                    shutil.rmtree(backup_dir)
                logging.info(f"Creating backup at {backup_dir}")
                shutil.copytree(self.app_dir, backup_dir, 
                              ignore=shutil.ignore_patterns('webdata', 'updates', '__pycache__'))
            
            # Read current config to pass to installer
            config_file = self.app_dir / "_internal" / "config.json"
            old_config_json = ""
            if config_file.exists():
                try:
                    old_config_json = config_file.read_text(encoding='utf-8')
                except Exception as e:
                    logging.warning(f"Could not read old config: {e}")
            
            # Find the update installer script
            if getattr(sys, 'frozen', False):
                # Running as exe - installer should be in _internal
                installer_script = self.app_dir / "_internal" / "update_installer.py"
                python_exe = sys.executable  # Use the bundled Python
            else:
                # Running as script
                installer_script = Path(__file__).parent / "update_installer.py"
                python_exe = sys.executable
            
            if not installer_script.exists():
                logging.error(f"Update installer not found: {installer_script}")
                return False
            
            # Get current process ID
            import os
            current_pid = os.getpid()
            
            # Launch the update installer as a separate process
            logging.info(f"Launching update installer: {installer_script}")
            logging.info(f"Current PID: {current_pid}")
            
            # Use pythonw to run without console window
            if getattr(sys, 'frozen', False):
                # For frozen exe, we need to run Python script differently
                # Extract update_installer.py to updates folder and run with Python
                import shutil
                installer_copy = self.update_dir / "update_installer.py"
                shutil.copy2(installer_script, installer_copy)
                
                # Try to find python.exe in the system
                import subprocess
                cmd = [
                    'python',
                    str(installer_copy),
                    str(current_pid),
                    str(self.app_dir),
                    str(zip_path),
                    old_config_json
                ]
            else:
                cmd = [
                    python_exe,
                    str(installer_script),
                    str(current_pid),
                    str(self.app_dir),
                    str(zip_path),
                    old_config_json
                ]
            
            # Launch installer in background
            subprocess.Popen(
                cmd,
                cwd=str(self.update_dir),
                creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == 'win32' else 0
            )
            
            logging.info("Update installer launched successfully")
            logging.info("Application will now exit to allow update installation")
            return True
            
        except Exception as e:
            logging.error(f"Error launching update installer: {e}", exc_info=True)
            return False


class UpdateManager:
    """High-level update management with UI integration."""
    
    def __init__(self, config: Dict):
        """
        Initialize the update manager.
        
        Args:
            config: Application configuration dictionary
        """
        self.config = config
        update_settings = config.get('updates', {})
        
        self.enabled = update_settings.get('enabled', True)
        self.check_on_startup = update_settings.get('check_on_startup', True)
        self.auto_install = update_settings.get('auto_install', False)
        self.current_version = update_settings.get('current_version', '1.0.0')
        
        repo_url = update_settings.get('repo_url', 'owner/repo')
        parts = repo_url.split('/')
        self.repo_owner = parts[0] if len(parts) >= 2 else 'owner'
        self.repo_name = parts[1] if len(parts) >= 2 else 'repo'
        
        self.checker = UpdateChecker(self.current_version, self.repo_owner, self.repo_name)
    
    def check_and_notify(self, notification_callback=None) -> Optional[Dict]:
        """
        Check for updates and notify via callback.
        
        Args:
            notification_callback: Function to call with update info
            
        Returns:
            Update info if available, None otherwise
        """
        if not self.enabled:
            logging.info("Updates are disabled")
            return None
        
        update_info = self.checker.check_for_updates()
        
        if update_info and notification_callback:
            notification_callback(update_info)
        
        return update_info
    
    def download_and_install(self, update_info: Dict, 
                            progress_callback=None,
                            completion_callback=None) -> bool:
        """
        Download and install an update.
        
        Args:
            update_info: Update information from check
            progress_callback: Progress callback(bytes, total)
            completion_callback: Called when complete with success bool
            
        Returns:
            True if successful
        """
        # Download
        zip_path = self.checker.download_update(update_info, progress_callback)
        if not zip_path:
            if completion_callback:
                completion_callback(False)
            return False
        
        # Install
        success = self.checker.install_update(zip_path, backup=True)
        
        if completion_callback:
            completion_callback(success)
        
        return success


def main():
    """Test the updater from command line."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Tablet-HA Update Manager')
    parser.add_argument('--check', action='store_true', help='Check for updates')
    parser.add_argument('--download', action='store_true', help='Download update')
    parser.add_argument('--install', action='store_true', help='Install update')
    parser.add_argument('--version', default='1.0.0', help='Current version')
    parser.add_argument('--repo', default='owner/repo', help='GitHub repo (owner/name)')
    
    args = parser.parse_args()
    
    parts = args.repo.split('/')
    checker = UpdateChecker(args.version, parts[0], parts[1])
    
    if args.check:
        update_info = checker.check_for_updates()
        if update_info:
            logging.info(f"\nUpdate available: v{update_info['version']}")
            logging.info(f"Download: {update_info['filename']}")
            logging.info(f"Size: {update_info['size'] / 1024 / 1024:.2f} MB")
            logging.info(f"\nRelease Notes:\n{update_info.get('release_notes', '')}")
        else:
            logging.info("No updates available")
    
    if args.download and update_info:
        def progress(current, total):
            percent = (current / total) * 100
            logging.info(f"\rDownload progress: {percent:.1f}%")
        
        zip_path = checker.download_update(update_info, progress)
        logging.info(f"\n\nDownloaded to: {zip_path}")
        
        if args.install and zip_path:
            success = checker.install_update(zip_path)
            if success:
                logging.info("Update installed successfully!")


if __name__ == '__main__':
    main()
