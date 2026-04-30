#!/usr/bin/env python3
"""Configuration management for Script Manager UI."""

import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable support."""
    
    # App
    APP_TITLE: str = "Script Manager UI"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # Database (MariaDB)
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_NAME: str = "script_manager"
    DB_USER: str = "script_manager"
    DB_PASS: str = ""
    
    # Paths
    BASE_DIR: Path = Path(__file__).parent
    SCRIPTS_YAML: Path = BASE_DIR / "scripts.yaml"
    LOGS_DIR: Path = Path("/var/log/script-manager-ui")  # Production: /var/log/script-manager-ui, Dev: ./logs
    
    # Authentik Forward Auth
    AUTHENTIK_HEADER: str = "X-Authentik-Username"
    AUTH_REQUIRED: bool = True
    
    # Job Management
    JOB_OUTPUT_MAX_SIZE: int = 10 * 1024 * 1024  # 10 MB max log size
    JOB_POLL_INTERVAL: int = 2  # seconds
    JOB_TIMEOUT_DEFAULT: int = 3600  # 1 hour default timeout
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Ensure logs directory exists
        self.LOGS_DIR.mkdir(parents=True, exist_ok=True)


# Global settings instance
settings = Settings()
