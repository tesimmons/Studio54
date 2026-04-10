"""
Studio54 Configuration Module
Manages application settings from environment variables
"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application configuration settings"""

    # Database Configuration
    database_url: str

    # Redis Configuration
    redis_url: str

    # Ollama Configuration (for AI analysis)
    ollama_url: str = "http://ollama:11434"
    ollama_embedding_model: str = "nomic-embed-text"
    ollama_model: str = "llama3.1:8b"

    # Encryption
    studio54_encryption_key: str

    # SABnzbd Configuration
    sabnzbd_host: str = "localhost"
    sabnzbd_port: int = 8080
    sabnzbd_api_key: Optional[str] = None
    sabnzbd_download_dir: str = "/downloads/music"

    # Music Library Path
    music_library_path: str = "/music"

    # MUSE Integration
    muse_service_url: str = "http://muse-service:8007"

    # Download Settings
    download_monitor_interval: int = 30  # seconds between download status checks
    max_concurrent_downloads: int = 3
    download_retry_limit: int = 3

    # Quality Profile Defaults
    default_quality_min_bitrate: int = 192  # kbps
    default_quality_max_size_mb: int = 500  # per album
    default_quality_preferred_formats: str = "FLAC,MP3-320"  # comma-separated

    # MusicBrainz Settings
    musicbrainz_rate_limit: float = 1.0  # requests per second
    musicbrainz_cache_ttl: int = 3600  # seconds (1 hour)
    fanart_api_key: Optional[str] = None  # Fanart.tv API key for artist images

    # Celery Configuration
    celery_broker_url: Optional[str] = None
    celery_result_backend: Optional[str] = None

    # Application Info
    app_name: str = "Studio54 - Music Acquisition System"
    app_version: str = "1.0.0"
    debug: bool = False

    # Security Configuration
    allowed_origins: str = "http://localhost:8009,http://localhost:3000"  # Comma-separated list

    # Pagination Configuration
    max_page_size: int = 1000  # Maximum items per page
    default_page_size: int = 100  # Default page size
    max_offset: int = 100000  # Maximum offset

    class Config:
        env_file = ".env"
        case_sensitive = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Set Celery URLs from Redis URL if not explicitly provided
        if not self.celery_broker_url:
            self.celery_broker_url = self.redis_url
        if not self.celery_result_backend:
            self.celery_result_backend = self.redis_url


# Global settings instance
settings = Settings()
