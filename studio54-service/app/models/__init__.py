"""
Database models for Studio54
"""
from app.models.user import User, UserRole
from app.models.artist import Artist, MonitorType
from app.models.album import Album
from app.models.track import Track
from app.models.track_rating import TrackRating
from app.models.author import Author
from app.models.series import Series
from app.models.book import Book, BookStatus
from app.models.chapter import Chapter
from app.models.book_playlist import BookPlaylist, BookPlaylistChapter
from app.models.quality_profile import QualityProfile
from app.models.indexer import Indexer
from app.models.download_client import DownloadClient
from app.models.download_queue import DownloadQueue, DownloadStatus
from app.models.playlist import Playlist, PlaylistTrack
from app.models.library import LibraryPath, LibraryFile, ScanJob, LibraryType
from app.models.job_state import JobState, JobType, JobStatus
from app.models.media_management import MediaManagementConfig
from app.models.library_import import LibraryImportJob, LibraryArtistMatch
from app.models.notification import NotificationProfile, NotificationEvent, NotificationProvider
from app.models.unlinked_file import UnlinkedFile
from app.models.dj_request import DjRequest
from app.models.scheduled_job import ScheduledJob, ScheduleFrequency
from app.models.storage_mount import StorageMount, MountType, MountStatus
from app.models.download_decision import (
    RejectionType,
    TrackedDownloadState,
    DownloadEventType,
    Rejection,
    ReleaseInfo,
    RemoteAlbum,
    DownloadDecision,
    TrackedDownload,
    PendingRelease,
    DownloadHistory,
    Blacklist,
)

__all__ = [
    "User",
    "UserRole",
    "Artist",
    "MonitorType",
    "Album",
    "Track",
    "TrackRating",
    "Author",
    "Series",
    "Book",
    "BookStatus",
    "Chapter",
    "BookPlaylist",
    "BookPlaylistChapter",
    "LibraryType",
    "QualityProfile",
    "Indexer",
    "DownloadClient",
    "DownloadQueue",
    "DownloadStatus",
    "Playlist",
    "PlaylistTrack",
    "LibraryPath",
    "LibraryFile",
    "ScanJob",
    "JobState",
    "JobType",
    "JobStatus",
    "MediaManagementConfig",
    "LibraryImportJob",
    "LibraryArtistMatch",
    "NotificationProfile",
    "NotificationEvent",
    "NotificationProvider",
    "UnlinkedFile",
    "DjRequest",
    "ScheduledJob",
    "ScheduleFrequency",
    "StorageMount",
    "MountType",
    "MountStatus",
    # Decision engine models
    "RejectionType",
    "TrackedDownloadState",
    "DownloadEventType",
    "Rejection",
    "ReleaseInfo",
    "RemoteAlbum",
    "DownloadDecision",
    "TrackedDownload",
    "PendingRelease",
    "DownloadHistory",
    "Blacklist",
]
