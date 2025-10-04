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
        Install the downloaded update.
        
        Args:
            zip_path: Path to the downloaded ZIP file
            backup: Whether to create a backup before updating
            
        Returns:
            True if successful, False otherwise
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
            
            # Extract to temporary directory
            temp_extract_dir = self.update_dir / "temp_extract"
            if temp_extract_dir.exists():
                shutil.rmtree(temp_extract_dir)
            temp_extract_dir.mkdir(exist_ok=True)
            
            logging.info(f"Extracting update to {temp_extract_dir}")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_extract_dir)
            
            # Find the TabletHA directory in the extracted files
            extracted_items = list(temp_extract_dir.iterdir())
            if len(extracted_items) == 1 and extracted_items[0].is_dir():
                source_dir = extracted_items[0]
            else:
                source_dir = temp_extract_dir
            
            # Preserve user data
            config_file = self.app_dir / "_internal" / "config.json"
            webdata_dir = self.app_dir / "webdata"
            
            config_backup = None
            if config_file.exists():
                config_backup = config_file.read_text(encoding='utf-8')
            
            # Copy new files (excluding certain directories)
            logging.info("Installing update files...")
            for item in source_dir.iterdir():
                if item.name in ['webdata', 'updates', '__pycache__']:
                    continue
                    
                dest_path = self.app_dir / item.name
                
                if dest_path.exists():
                    if dest_path.is_dir():
                        shutil.rmtree(dest_path)
                    else:
                        dest_path.unlink()
                
                if item.is_dir():
                    shutil.copytree(item, dest_path)
                else:
                    shutil.copy2(item, dest_path)
            
            # Restore user config if it existed
            if config_backup:
                new_config_file = self.app_dir / "_internal" / "config.json"
                if new_config_file.exists():
                    logging.info("Restoring user configuration...")
                    new_config_file.write_text(config_backup, encoding='utf-8')
            
            # Clean up
            shutil.rmtree(temp_extract_dir)
            zip_path.unlink()
            
            logging.info("Update installed successfully!")
            return True
            
        except Exception as e:
            logging.error(f"Error installing update: {e}", exc_info=True)
            return False
    
    def restart_application(self):
        """Restart the application after update."""
        try:
            exe_path = self.app_dir / "TabletHA.exe"
            if exe_path.exists():
                logging.info("Restarting application...")
                subprocess.Popen([str(exe_path)], cwd=str(self.app_dir))
                sys.exit(0)
        except Exception as e:
            logging.error(f"Error restarting application: {e}", exc_info=True)


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
