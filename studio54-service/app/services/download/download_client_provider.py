"""
Download Client Provider - Manages download client selection

Provides selection logic for choosing the appropriate download client
based on availability, priority, and configuration.

Based on Lidarr's provider pattern from:
- src/NzbDrone.Core/Download/DownloadService.cs
"""
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import DownloadClient
from app.services.encryption import get_encryption_service
from app.services.sabnzbd_client import SABnzbdClient

logger = logging.getLogger(__name__)


class DownloadClientProvider:
    """
    Provides download client selection and management

    Handles:
    - Building client instances from database configuration
    - Selecting appropriate client based on availability
    - Testing client connections
    - Providing client status information
    """

    def __init__(self, db: Session):
        """
        Initialize the download client provider

        Args:
            db: Database session
        """
        self.db = db
        self._encryption_service = None
        self._client_cache: Dict[str, SABnzbdClient] = {}

    @property
    def encryption_service(self):
        """Lazy initialization of encryption service"""
        if self._encryption_service is None:
            self._encryption_service = get_encryption_service()
        return self._encryption_service

    def get_client(
        self,
        protocol: str = "usenet",
        client_id: Optional[str] = None
    ) -> Optional[SABnzbdClient]:
        """
        Get an appropriate download client

        Args:
            protocol: Download protocol (usenet or torrent)
            client_id: Optional specific client ID

        Returns:
            SABnzbdClient instance or None if no client available
        """
        if protocol != "usenet":
            logger.warning(f"Unsupported protocol: {protocol}")
            return None

        if client_id:
            # Get specific client
            client_model = self.db.query(DownloadClient).filter(
                DownloadClient.id == client_id,
                DownloadClient.is_enabled == True
            ).first()
        else:
            # Get default or first available client
            client_model = self.db.query(DownloadClient).filter(
                DownloadClient.is_enabled == True,
                DownloadClient.client_type == "sabnzbd"
            ).order_by(
                DownloadClient.is_default.desc(),
                DownloadClient.priority.desc()
            ).first()

        if not client_model:
            logger.warning("No enabled download client found")
            return None

        return self._build_client(client_model)

    def get_all_clients(self) -> List[SABnzbdClient]:
        """
        Get all enabled download clients

        Returns:
            List of SABnzbdClient instances
        """
        clients = self.db.query(DownloadClient).filter(
            DownloadClient.is_enabled == True,
            DownloadClient.client_type == "sabnzbd"
        ).all()

        result = []
        for client_model in clients:
            client = self._build_client(client_model)
            if client:
                result.append(client)

        return result

    def get_client_by_id(self, client_id: str) -> Optional[SABnzbdClient]:
        """
        Get a specific download client by ID

        Args:
            client_id: UUID of the download client

        Returns:
            SABnzbdClient instance or None
        """
        client_model = self.db.query(DownloadClient).filter(
            DownloadClient.id == client_id
        ).first()

        if not client_model:
            return None

        return self._build_client(client_model)

    def get_client_model(self, client_id: str) -> Optional[DownloadClient]:
        """
        Get download client database model

        Args:
            client_id: UUID of the download client

        Returns:
            DownloadClient model or None
        """
        return self.db.query(DownloadClient).filter(
            DownloadClient.id == client_id
        ).first()

    def test_client(self, client_id: str) -> Dict[str, Any]:
        """
        Test connection to a download client

        Args:
            client_id: UUID of the download client

        Returns:
            Dict with test results
        """
        client_model = self.db.query(DownloadClient).filter(
            DownloadClient.id == client_id
        ).first()

        if not client_model:
            return {
                "success": False,
                "error": "Download client not found"
            }

        client = self._build_client(client_model)
        if not client:
            return {
                "success": False,
                "error": "Failed to build client instance"
            }

        try:
            if client.test_connection():
                return {
                    "success": True,
                    "client_name": client_model.name,
                    "client_type": client_model.client_type
                }
            else:
                return {
                    "success": False,
                    "error": "Connection test failed"
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def get_client_status(self, client_id: str) -> Optional[Dict[str, Any]]:
        """
        Get status information for a download client

        Args:
            client_id: UUID of the download client

        Returns:
            Status dict with queue info, speed, etc.
        """
        client = self.get_client_by_id(client_id)
        if not client:
            return None

        try:
            stats = client.get_server_stats()
            queue = client.get_queue()

            return {
                "online": True,
                "stats": stats,
                "queue_count": len(queue),
                "queue": queue[:10]  # First 10 items
            }
        except Exception as e:
            logger.error(f"Failed to get client status: {e}")
            return {
                "online": False,
                "error": str(e)
            }

    def update_client_stats(
        self,
        client_id: str,
        success: bool = True,
        error_message: Optional[str] = None
    ):
        """
        Update client statistics after download attempt

        Args:
            client_id: UUID of the download client
            success: Whether the operation was successful
            error_message: Optional error message
        """
        client_model = self.db.query(DownloadClient).filter(
            DownloadClient.id == client_id
        ).first()

        if client_model:
            if success:
                client_model.successful_downloads = (client_model.successful_downloads or 0) + 1
            else:
                client_model.failed_downloads = (client_model.failed_downloads or 0) + 1
                if error_message:
                    client_model.last_error = error_message

            client_model.last_used_at = datetime.now(timezone.utc)
            self.db.commit()

    def _build_client(self, client_model: DownloadClient) -> Optional[SABnzbdClient]:
        """
        Build SABnzbdClient instance from database model

        Args:
            client_model: DownloadClient database model

        Returns:
            SABnzbdClient instance or None
        """
        # Check cache first
        cache_key = str(client_model.id)
        if cache_key in self._client_cache:
            return self._client_cache[cache_key]

        try:
            # Decrypt API key
            api_key = self.encryption_service.decrypt(client_model.api_key_encrypted)

            # Build client
            client = SABnzbdClient(
                base_url=client_model.base_url,
                api_key=api_key
            )

            # Cache the client
            self._client_cache[cache_key] = client

            logger.debug(f"Built client for: {client_model.name}")
            return client

        except Exception as e:
            logger.error(f"Failed to build client {client_model.name}: {e}")
            return None

    def clear_cache(self):
        """Clear the client cache"""
        self._client_cache.clear()
