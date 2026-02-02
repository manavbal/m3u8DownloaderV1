"""
Settings module for DDS Downloader
Handles persistent storage of user preferences.
"""

import os
import json
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, asdict


def get_app_data_dir() -> Path:
    """Get the application data directory for macOS."""
    home = Path.home()
    app_dir = home / "Library" / "Application Support" / "DDS Downloader"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


@dataclass
class AppSettings:
    """Application settings."""
    last_download_folder: str = ""
    preferred_quality: str = "best"
    auto_retry: bool = True
    max_retries: int = 5
    window_width: int = 800
    window_height: int = 600
    window_x: Optional[int] = None
    window_y: Optional[int] = None


class SettingsManager:
    """Manages persistent application settings."""

    def __init__(self):
        """Initialize the settings manager."""
        self.settings_file = get_app_data_dir() / "settings.json"
        self.settings = self._load_settings()

    def _load_settings(self) -> AppSettings:
        """Load settings from file."""
        if self.settings_file.exists():
            try:
                with open(self.settings_file, 'r') as f:
                    data = json.load(f)
                    return AppSettings(**data)
            except Exception as e:
                print(f"Error loading settings: {e}")

        return AppSettings()

    def save(self):
        """Save current settings to file."""
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(asdict(self.settings), f, indent=2)
        except Exception as e:
            print(f"Error saving settings: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value."""
        return getattr(self.settings, key, default)

    def set(self, key: str, value: Any):
        """Set a setting value and save."""
        if hasattr(self.settings, key):
            setattr(self.settings, key, value)
            self.save()

    @property
    def last_download_folder(self) -> str:
        """Get the last used download folder."""
        folder = self.settings.last_download_folder
        if folder and Path(folder).exists():
            return folder
        # Default to Downloads folder
        return str(Path.home() / "Downloads")

    @last_download_folder.setter
    def last_download_folder(self, value: str):
        """Set the last used download folder."""
        self.settings.last_download_folder = value
        self.save()

    @property
    def preferred_quality(self) -> str:
        """Get the preferred video quality."""
        return self.settings.preferred_quality

    @preferred_quality.setter
    def preferred_quality(self, value: str):
        """Set the preferred video quality."""
        self.settings.preferred_quality = value
        self.save()

    def get_window_geometry(self) -> tuple:
        """Get saved window geometry."""
        return (
            self.settings.window_width,
            self.settings.window_height,
            self.settings.window_x,
            self.settings.window_y
        )

    def save_window_geometry(self, width: int, height: int, x: int, y: int):
        """Save window geometry."""
        self.settings.window_width = width
        self.settings.window_height = height
        self.settings.window_x = x
        self.settings.window_y = y
        self.save()


# Global settings instance
_settings_manager: Optional[SettingsManager] = None


def get_settings() -> SettingsManager:
    """Get the global settings manager instance."""
    global _settings_manager
    if _settings_manager is None:
        _settings_manager = SettingsManager()
    return _settings_manager


if __name__ == "__main__":
    # Test settings
    settings = get_settings()
    print(f"Last download folder: {settings.last_download_folder}")
    print(f"Preferred quality: {settings.preferred_quality}")
