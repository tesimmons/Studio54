"""
Audit Logger Service

Logs all file operations to the database for audit trail and rollback capability:
- Track all file operations (move, rename, delete, restore)
- Store before/after paths
- Record MBID associations
- Enable operation reversal
- Generate reports
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc

from .atomic_file_ops import FileOperationResult, OperationType


logger = logging.getLogger(__name__)


class AuditLogger:
    """
    Service for logging file operations to database

    Features:
    - Log all file operations with complete details
    - Track MBID associations
    - Enable operation rollback
    - Query operations by various filters
    - Generate audit reports
    """

    def __init__(self, db: Session):
        """
        Initialize AuditLogger service

        Args:
            db: Database session
        """
        self.db = db

    def log_operation(
        self,
        operation_result: FileOperationResult,
        file_id: Optional[UUID] = None,
        artist_id: Optional[UUID] = None,
        album_id: Optional[UUID] = None,
        track_id: Optional[UUID] = None,
        recording_mbid: Optional[UUID] = None,
        release_mbid: Optional[UUID] = None,
        job_id: Optional[UUID] = None,
        performed_by: str = "system"
    ) -> Optional[UUID]:
        """
        Log a file operation to the database

        Args:
            operation_result: Result from AtomicFileOps operation
            file_id: Reference to music_files or library_files record
            artist_id: Associated artist ID
            album_id: Associated album ID
            track_id: Associated track ID
            recording_mbid: MusicBrainz Recording ID
            release_mbid: MusicBrainz Release ID
            job_id: Associated file organization job ID
            performed_by: Who performed the operation

        Returns:
            UUID of created audit record, or None if failed
        """
        try:
            # Import here to avoid circular dependencies
            from sqlalchemy import text

            # Insert audit record
            query = text("""
                INSERT INTO file_operation_audit (
                    operation_type,
                    file_id,
                    source_path,
                    destination_path,
                    artist_id,
                    album_id,
                    track_id,
                    recording_mbid,
                    release_mbid,
                    job_id,
                    success,
                    error_message,
                    rollback_possible,
                    backup_path,
                    performed_by,
                    performed_at
                ) VALUES (
                    :operation_type,
                    :file_id,
                    :source_path,
                    :destination_path,
                    :artist_id,
                    :album_id,
                    :track_id,
                    :recording_mbid,
                    :release_mbid,
                    :job_id,
                    :success,
                    :error_message,
                    :rollback_possible,
                    :backup_path,
                    :performed_by,
                    NOW()
                )
                RETURNING id
            """)

            result = self.db.execute(query, {
                'operation_type': operation_result.operation_type.value,
                'file_id': str(file_id) if file_id else None,
                'source_path': operation_result.source_path,
                'destination_path': operation_result.destination_path,
                'artist_id': str(artist_id) if artist_id else None,
                'album_id': str(album_id) if album_id else None,
                'track_id': str(track_id) if track_id else None,
                'recording_mbid': str(recording_mbid) if recording_mbid else None,
                'release_mbid': str(release_mbid) if release_mbid else None,
                'job_id': str(job_id) if job_id else None,
                'success': operation_result.success,
                'error_message': operation_result.error_message,
                'rollback_possible': operation_result.backup_path is not None or operation_result.destination_path is not None,
                'backup_path': operation_result.backup_path,
                'performed_by': performed_by
            })

            audit_id = result.scalar_one()
            self.db.commit()

            logger.debug(f"Logged file operation: {operation_result.operation_type.value} - {operation_result.source_path}")

            return UUID(str(audit_id))

        except Exception as e:
            logger.error(f"Error logging file operation: {e}")
            self.db.rollback()
            return None

    def log_batch_operations(
        self,
        operation_results: List[FileOperationResult],
        job_id: Optional[UUID] = None,
        file_mappings: Optional[Dict[str, Dict[str, Any]]] = None,
        performed_by: str = "system"
    ) -> int:
        """
        Log multiple file operations in batch

        Args:
            operation_results: List of operation results
            job_id: Associated file organization job ID
            file_mappings: Dict mapping source_path to metadata (file_id, artist_id, etc.)
            performed_by: Who performed the operations

        Returns:
            Number of operations successfully logged
        """
        logged_count = 0

        for result in operation_results:
            # Get metadata from file_mappings if provided
            metadata = {}
            if file_mappings and result.source_path in file_mappings:
                metadata = file_mappings[result.source_path]

            audit_id = self.log_operation(
                operation_result=result,
                file_id=metadata.get('file_id'),
                artist_id=metadata.get('artist_id'),
                album_id=metadata.get('album_id'),
                track_id=metadata.get('track_id'),
                recording_mbid=metadata.get('recording_mbid'),
                release_mbid=metadata.get('release_mbid'),
                job_id=job_id,
                performed_by=performed_by
            )

            if audit_id:
                logged_count += 1

        logger.info(f"Logged {logged_count}/{len(operation_results)} file operations")

        return logged_count

    def get_operations(
        self,
        operation_type: Optional[str] = None,
        artist_id: Optional[UUID] = None,
        album_id: Optional[UUID] = None,
        track_id: Optional[UUID] = None,
        job_id: Optional[UUID] = None,
        success: Optional[bool] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Query file operations with filters

        Args:
            operation_type: Filter by operation type
            artist_id: Filter by artist
            album_id: Filter by album
            track_id: Filter by track
            job_id: Filter by organization job
            success: Filter by success status
            start_date: Filter by date range
            end_date: Filter by date range
            limit: Maximum results to return
            offset: Results offset for pagination

        Returns:
            List of operation records
        """
        try:
            from sqlalchemy import text

            # Build query with filters
            where_clauses = []
            params = {}

            if operation_type:
                where_clauses.append("operation_type = :operation_type")
                params['operation_type'] = operation_type

            if artist_id:
                where_clauses.append("artist_id = :artist_id")
                params['artist_id'] = str(artist_id)

            if album_id:
                where_clauses.append("album_id = :album_id")
                params['album_id'] = str(album_id)

            if track_id:
                where_clauses.append("track_id = :track_id")
                params['track_id'] = str(track_id)

            if job_id:
                where_clauses.append("job_id = :job_id")
                params['job_id'] = str(job_id)

            if success is not None:
                where_clauses.append("success = :success")
                params['success'] = success

            if start_date:
                where_clauses.append("performed_at >= :start_date")
                params['start_date'] = start_date

            if end_date:
                where_clauses.append("performed_at <= :end_date")
                params['end_date'] = end_date

            where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

            params['limit'] = limit
            params['offset'] = offset

            query = text(f"""
                SELECT
                    id,
                    operation_type,
                    source_path,
                    destination_path,
                    artist_id,
                    album_id,
                    track_id,
                    recording_mbid,
                    release_mbid,
                    job_id,
                    success,
                    error_message,
                    rollback_possible,
                    rolled_back,
                    backup_path,
                    performed_by,
                    performed_at
                FROM file_operation_audit
                WHERE {where_sql}
                ORDER BY performed_at DESC
                LIMIT :limit OFFSET :offset
            """)

            result = self.db.execute(query, params)

            operations = []
            for row in result:
                operations.append({
                    'id': str(row.id),
                    'operation_type': row.operation_type,
                    'source_path': row.source_path,
                    'destination_path': row.destination_path,
                    'artist_id': str(row.artist_id) if row.artist_id else None,
                    'album_id': str(row.album_id) if row.album_id else None,
                    'track_id': str(row.track_id) if row.track_id else None,
                    'recording_mbid': str(row.recording_mbid) if row.recording_mbid else None,
                    'release_mbid': str(row.release_mbid) if row.release_mbid else None,
                    'job_id': str(row.job_id) if row.job_id else None,
                    'success': row.success,
                    'error_message': row.error_message,
                    'rollback_possible': row.rollback_possible,
                    'rolled_back': row.rolled_back,
                    'backup_path': row.backup_path,
                    'performed_by': row.performed_by,
                    'performed_at': row.performed_at.isoformat() if row.performed_at else None
                })

            return operations

        except Exception as e:
            logger.error(f"Error querying file operations: {e}")
            return []

    def get_operation_stats(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        job_id: Optional[UUID] = None
    ) -> Dict[str, Any]:
        """
        Get statistics about file operations

        Args:
            start_date: Filter by date range
            end_date: Filter by date range
            job_id: Filter by organization job

        Returns:
            Dict with operation statistics
        """
        try:
            from sqlalchemy import text

            where_clauses = []
            params = {}

            if start_date:
                where_clauses.append("performed_at >= :start_date")
                params['start_date'] = start_date

            if end_date:
                where_clauses.append("performed_at <= :end_date")
                params['end_date'] = end_date

            if job_id:
                where_clauses.append("job_id = :job_id")
                params['job_id'] = str(job_id)

            where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

            query = text(f"""
                SELECT
                    COUNT(*) as total_operations,
                    SUM(CASE WHEN success = true THEN 1 ELSE 0 END) as successful_operations,
                    SUM(CASE WHEN success = false THEN 1 ELSE 0 END) as failed_operations,
                    SUM(CASE WHEN operation_type = 'move' THEN 1 ELSE 0 END) as move_operations,
                    SUM(CASE WHEN operation_type = 'rename' THEN 1 ELSE 0 END) as rename_operations,
                    SUM(CASE WHEN operation_type = 'delete' THEN 1 ELSE 0 END) as delete_operations,
                    SUM(CASE WHEN rolled_back = true THEN 1 ELSE 0 END) as rolled_back_operations
                FROM file_operation_audit
                WHERE {where_sql}
            """)

            result = self.db.execute(query, params).first()

            return {
                'total_operations': result.total_operations or 0,
                'successful_operations': result.successful_operations or 0,
                'failed_operations': result.failed_operations or 0,
                'move_operations': result.move_operations or 0,
                'rename_operations': result.rename_operations or 0,
                'delete_operations': result.delete_operations or 0,
                'rolled_back_operations': result.rolled_back_operations or 0
            }

        except Exception as e:
            logger.error(f"Error getting operation stats: {e}")
            return {
                'total_operations': 0,
                'successful_operations': 0,
                'failed_operations': 0,
                'move_operations': 0,
                'rename_operations': 0,
                'delete_operations': 0,
                'rolled_back_operations': 0,
                'error': str(e)
            }

    def mark_rolled_back(self, audit_id: UUID) -> bool:
        """
        Mark an operation as rolled back

        Args:
            audit_id: Audit record ID

        Returns:
            True if successful
        """
        try:
            from sqlalchemy import text

            query = text("""
                UPDATE file_operation_audit
                SET rolled_back = true
                WHERE id = :audit_id
            """)

            self.db.execute(query, {'audit_id': str(audit_id)})
            self.db.commit()

            logger.info(f"Marked operation as rolled back: {audit_id}")

            return True

        except Exception as e:
            logger.error(f"Error marking operation as rolled back: {e}")
            self.db.rollback()
            return False

    def get_rollback_operations(
        self,
        job_id: UUID,
        reverse: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Get operations for a job that can be rolled back

        Args:
            job_id: File organization job ID
            reverse: Return in reverse chronological order (for rollback)

        Returns:
            List of operations that can be rolled back
        """
        try:
            from sqlalchemy import text

            order = "DESC" if reverse else "ASC"

            query = text(f"""
                SELECT
                    id,
                    operation_type,
                    source_path,
                    destination_path,
                    backup_path,
                    file_id,
                    artist_id,
                    album_id,
                    track_id
                FROM file_operation_audit
                WHERE job_id = :job_id
                  AND success = true
                  AND rollback_possible = true
                  AND rolled_back = false
                ORDER BY performed_at {order}
            """)

            result = self.db.execute(query, {'job_id': str(job_id)})

            operations = []
            for row in result:
                operations.append({
                    'id': str(row.id),
                    'operation_type': row.operation_type,
                    'source_path': row.source_path,
                    'destination_path': row.destination_path,
                    'backup_path': row.backup_path,
                    'file_id': str(row.file_id) if row.file_id else None,
                    'artist_id': str(row.artist_id) if row.artist_id else None,
                    'album_id': str(row.album_id) if row.album_id else None,
                    'track_id': str(row.track_id) if row.track_id else None
                })

            return operations

        except Exception as e:
            logger.error(f"Error getting rollback operations: {e}")
            return []

    def cleanup_old_audit_logs(self, retention_days: int = 90) -> int:
        """
        Delete audit logs older than retention period

        Args:
            retention_days: Days to retain audit logs

        Returns:
            Number of records deleted
        """
        try:
            from sqlalchemy import text

            cutoff_date = datetime.now() - timedelta(days=retention_days)

            query = text("""
                DELETE FROM file_operation_audit
                WHERE performed_at < :cutoff_date
                  AND rolled_back = false
                  AND success = true
                RETURNING id
            """)

            result = self.db.execute(query, {'cutoff_date': cutoff_date})
            deleted_count = len(result.fetchall())
            self.db.commit()

            logger.info(f"Cleaned up {deleted_count} audit log records older than {retention_days} days")

            return deleted_count

        except Exception as e:
            logger.error(f"Error cleaning up audit logs: {e}")
            self.db.rollback()
            return 0
