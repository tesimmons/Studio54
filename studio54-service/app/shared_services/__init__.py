"""
Shared File Management Services

This package provides file management services used by both MUSE and Studio54:
- AtomicFileOps: Safe file operations with rollback capability
- AuditLogger: Audit trail for all file operations
- NamingEngine: Template-based filename generation
- FileOrganizer: Core file organization logic
- MetadataFileManager: Album metadata file management
- PathValidator: Directory structure validation

All services use MBID-based matching for accurate file organization.
"""

from .atomic_file_ops import (
    AtomicFileOps,
    FileOperationResult,
    BatchOperationResult,
    OperationType
)
from .audit_logger import AuditLogger
from .naming_engine import (
    NamingEngine,
    TrackContext,
    AlbumContext,
    ArtistContext
)
from .file_organizer import (
    FileOrganizer,
    OrganizationResult,
    ValidationResult as FileOrgValidationResult
)
from .metadata_file_manager import (
    MetadataFileManager,
    TrackMetadata,
    AlbumMetadata,
    ValidationResult as MetadataValidationResult
)
from .path_validator import (
    PathValidator,
    ValidationResult as PathValidationResult,
    MisnamedFile,
    MisplacedFile,
    IncorrectDirectory
)

__all__ = [
    # Core Services
    'AtomicFileOps',
    'AuditLogger',
    'NamingEngine',
    'FileOrganizer',
    'MetadataFileManager',
    'PathValidator',

    # AtomicFileOps types
    'FileOperationResult',
    'BatchOperationResult',
    'OperationType',

    # NamingEngine types
    'TrackContext',
    'AlbumContext',
    'ArtistContext',

    # FileOrganizer types
    'OrganizationResult',
    'FileOrgValidationResult',

    # MetadataFileManager types
    'TrackMetadata',
    'AlbumMetadata',
    'MetadataValidationResult',

    # PathValidator types
    'PathValidationResult',
    'MisnamedFile',
    'MisplacedFile',
    'IncorrectDirectory',
]

__version__ = '1.0.0'
