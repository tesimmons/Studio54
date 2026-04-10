"""
Local MusicBrainz Database Query Service

Direct read-only queries against a local MusicBrainz PostgreSQL mirror.
Eliminates API rate limits for metadata lookups during library imports.

MusicBrainz DB schema reference:
  https://musicbrainz.org/doc/MusicBrainz_Database/Schema
"""

import os
import logging
from typing import Optional, List, Dict, Any

from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool

logger = logging.getLogger(__name__)


class MusicBrainzLocalDB:
    """Direct queries against local MusicBrainz PostgreSQL mirror"""

    def __init__(self, db_url: str):
        """
        Initialize connection to local MusicBrainz database.

        Args:
            db_url: PostgreSQL connection URL
                    e.g. postgresql://musicbrainz:musicbrainz@musicbrainz-db:5432/musicbrainz_db
        """
        self.engine = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            poolclass=QueuePool,
            # Read-only: prevent accidental writes
            execution_options={"isolation_level": "AUTOCOMMIT"},
        )
        # Verify connection
        with self.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("MusicBrainz local DB connected successfully")

    def get_artist(self, mbid: str) -> Optional[Dict[str, Any]]:
        """
        Get artist by MusicBrainz ID.

        Returns dict matching the MusicBrainz API JSON format for compatibility
        with the existing MusicBrainzClient.
        """
        query = text("""
            SELECT
                a.gid::text AS id,
                a.name,
                a.sort_name AS "sort-name",
                at.name AS type,
                a.comment AS disambiguation,
                area.name AS area_name,
                a.begin_date_year,
                a.begin_date_month,
                a.begin_date_day,
                a.end_date_year,
                a.end_date_month,
                a.end_date_day,
                a.ended
            FROM musicbrainz.artist a
            LEFT JOIN musicbrainz.artist_type at ON a.type = at.id
            LEFT JOIN musicbrainz.area area ON a.area = area.id
            WHERE a.gid = CAST(:mbid AS uuid)
        """)

        with self.engine.connect() as conn:
            row = conn.execute(query, {"mbid": mbid}).mappings().first()

        if not row:
            return None

        result = {
            "id": row["id"],
            "name": row["name"],
            "sort-name": row["sort-name"],
            "type": row["type"],
            "disambiguation": row["disambiguation"] or "",
        }

        # Build life-span
        life_span = {}
        if row["begin_date_year"]:
            life_span["begin"] = self._format_date(
                row["begin_date_year"], row["begin_date_month"], row["begin_date_day"]
            )
        if row["end_date_year"]:
            life_span["end"] = self._format_date(
                row["end_date_year"], row["end_date_month"], row["end_date_day"]
            )
        if row["ended"] is not None:
            life_span["ended"] = bool(row["ended"])
        if life_span:
            result["life-span"] = life_span

        if row["area_name"]:
            result["area"] = {"name": row["area_name"]}

        # Get tags
        tags = self._get_artist_tags(row["id"])
        if tags:
            result["tags"] = tags

        # Get genres
        genres = self._get_artist_genres(row["id"])
        if genres:
            result["genres"] = genres

        return result

    def _get_artist_tags(self, artist_mbid: str) -> List[Dict[str, Any]]:
        """Get tags for an artist"""
        query = text("""
            SELECT t.name, at.count
            FROM musicbrainz.artist_tag at
            JOIN musicbrainz.artist a ON at.artist = a.id
            JOIN musicbrainz.tag t ON at.tag = t.id
            WHERE a.gid = CAST(:mbid AS uuid)
            ORDER BY at.count DESC
            LIMIT 20
        """)
        with self.engine.connect() as conn:
            rows = conn.execute(query, {"mbid": artist_mbid}).mappings().all()
        return [{"name": r["name"], "count": r["count"]} for r in rows]

    def _get_artist_genres(self, artist_mbid: str) -> List[Dict[str, Any]]:
        """Get genres for an artist"""
        query = text("""
            SELECT g.name, ag.count
            FROM musicbrainz.artist_tag ag
            JOIN musicbrainz.artist a ON ag.artist = a.id
            JOIN musicbrainz.tag g ON ag.tag = g.id
            WHERE a.gid = CAST(:mbid AS uuid)
              AND g.name IN (
                  SELECT name FROM musicbrainz.genre
              )
            ORDER BY ag.count DESC
            LIMIT 10
        """)
        with self.engine.connect() as conn:
            rows = conn.execute(query, {"mbid": artist_mbid}).mappings().all()
        return [{"name": r["name"], "count": r["count"]} for r in rows]

    def search_artist(self, name: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Fuzzy artist search by name.

        Uses PostgreSQL trigram similarity for fuzzy matching.
        Returns results in the same format as MusicBrainz API search.
        """
        query = text("""
            SELECT
                a.gid::text AS id,
                a.name,
                a.sort_name AS "sort-name",
                at.name AS type,
                a.comment AS disambiguation,
                similarity(lower(a.name), lower(:name)) AS score
            FROM musicbrainz.artist a
            LEFT JOIN musicbrainz.artist_type at ON a.type = at.id
            WHERE lower(a.name) % lower(:name)
               OR lower(a.name) = lower(:name)
            ORDER BY
                CASE WHEN lower(a.name) = lower(:name) THEN 0 ELSE 1 END,
                similarity(lower(a.name), lower(:name)) DESC
            LIMIT :limit
        """)

        with self.engine.connect() as conn:
            rows = conn.execute(query, {"name": name, "limit": limit}).mappings().all()

        artists = []
        for row in rows:
            artists.append({
                "id": row["id"],
                "name": row["name"],
                "sort-name": row["sort-name"],
                "type": row["type"],
                "disambiguation": row["disambiguation"] or "",
                "score": int(row["score"] * 100),
            })

        return artists

    def search_release_group(
        self, name: str, artist_name: Optional[str] = None, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Fuzzy release group (album) search by name.

        Uses PostgreSQL trigram similarity for fuzzy matching.
        Optionally filter by artist name.
        """
        artist_filter = ""
        params: Dict[str, Any] = {"name": name, "limit": limit}

        if artist_name:
            artist_filter = "AND lower(a.name) % lower(:artist_name)"
            params["artist_name"] = artist_name

        query = text(f"""
            SELECT
                rg.gid::text AS id,
                rg.name AS title,
                rgpt.name AS primary_type,
                a.name AS artist_name,
                MIN(rc.date_year) AS first_release_year,
                similarity(lower(rg.name), lower(:name)) AS score
            FROM musicbrainz.release_group rg
            JOIN musicbrainz.artist_credit_name acn ON rg.artist_credit = acn.artist_credit
            JOIN musicbrainz.artist a ON acn.artist = a.id
            LEFT JOIN musicbrainz.release_group_primary_type rgpt ON rg.type = rgpt.id
            LEFT JOIN musicbrainz.release r ON r.release_group = rg.id
            LEFT JOIN musicbrainz.release_country rc ON r.id = rc.release
            WHERE (lower(rg.name) % lower(:name) OR lower(rg.name) = lower(:name))
            {artist_filter}
            GROUP BY rg.id, rg.gid, rg.name, rgpt.name, a.name
            ORDER BY
                CASE WHEN lower(rg.name) = lower(:name) THEN 0 ELSE 1 END,
                similarity(lower(rg.name), lower(:name)) DESC
            LIMIT :limit
        """)

        with self.engine.connect() as conn:
            rows = conn.execute(query, params).mappings().all()

        results = []
        for row in rows:
            results.append({
                "id": row["id"],
                "title": row["title"],
                "primary_type": row["primary_type"],
                "artist_name": row["artist_name"],
                "first_release_year": row["first_release_year"],
                "score": int(row["score"] * 100),
            })

        return results

    def search_recording(
        self, name: str, artist_name: Optional[str] = None, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Fuzzy recording (track) search by name.

        Uses PostgreSQL trigram similarity for fuzzy matching.
        Optionally filter by artist name.
        """
        artist_filter = ""
        params: Dict[str, Any] = {"name": name, "limit": limit}

        if artist_name:
            artist_filter = "AND lower(a.name) % lower(:artist_name)"
            params["artist_name"] = artist_name

        query = text(f"""
            SELECT
                rec.gid::text AS id,
                rec.name AS title,
                rec.length,
                a.name AS artist_name,
                similarity(lower(rec.name), lower(:name)) AS score
            FROM musicbrainz.recording rec
            JOIN musicbrainz.artist_credit_name acn ON rec.artist_credit = acn.artist_credit
            JOIN musicbrainz.artist a ON acn.artist = a.id
            WHERE (lower(rec.name) % lower(:name) OR lower(rec.name) = lower(:name))
            {artist_filter}
            GROUP BY rec.id, rec.gid, rec.name, rec.length, a.name
            ORDER BY
                CASE WHEN lower(rec.name) = lower(:name) THEN 0 ELSE 1 END,
                similarity(lower(rec.name), lower(:name)) DESC
            LIMIT :limit
        """)

        with self.engine.connect() as conn:
            rows = conn.execute(query, params).mappings().all()

        results = []
        for row in rows:
            results.append({
                "id": row["id"],
                "title": row["title"],
                "length": row["length"],
                "artist_name": row["artist_name"],
                "score": int(row["score"] * 100),
            })

        return results

    def get_artist_albums(
        self,
        artist_mbid: str,
        types: Optional[List[str]] = None,
        exclude_secondary: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Get release groups (albums) for an artist.

        Returns results in MusicBrainz API format for compatibility.
        """
        # Build type filter
        type_filter = ""
        params: Dict[str, Any] = {"mbid": artist_mbid}

        if types:
            type_placeholders = ", ".join([f":type_{i}" for i in range(len(types))])
            type_filter = f"AND rgpt.name IN ({type_placeholders})"
            for i, t in enumerate(types):
                params[f"type_{i}"] = t

        query = text(f"""
            SELECT
                rg.gid::text AS id,
                rg.name AS title,
                rgpt.name AS "primary-type",
                rg.artist_credit AS artist_credit_id,
                array_agg(DISTINCT rgst.name) FILTER (WHERE rgst.name IS NOT NULL) AS "secondary-types",
                MIN(rc.date_year) AS first_release_year
            FROM musicbrainz.release_group rg
            JOIN musicbrainz.artist_credit_name acn ON rg.artist_credit = acn.artist_credit
            JOIN musicbrainz.artist a ON acn.artist = a.id
            LEFT JOIN musicbrainz.release_group_primary_type rgpt ON rg.type = rgpt.id
            LEFT JOIN musicbrainz.release_group_secondary_type_join rgstj ON rg.id = rgstj.release_group
            LEFT JOIN musicbrainz.release_group_secondary_type rgst ON rgstj.secondary_type = rgst.id
            LEFT JOIN musicbrainz.release r ON r.release_group = rg.id
            LEFT JOIN musicbrainz.release_country rc ON r.id = rc.release
            WHERE a.gid = CAST(:mbid AS uuid)
            {type_filter}
            GROUP BY rg.id, rg.gid, rg.name, rgpt.name, rg.artist_credit
            ORDER BY first_release_year ASC NULLS LAST, rg.name
            LIMIT 5000
        """)

        with self.engine.connect() as conn:
            rows = conn.execute(query, params).mappings().all()

        # Secondary types to exclude (keep Live, Compilation, Soundtrack, Audiobook for filtering)
        excluded_secondary = {
            "Remix", "Spokenword", "Interview", "Audio drama",
            "DJ-mix", "Mixtape/Street", "Demo"
        }

        results = []
        for row in rows:
            secondary_types = [s for s in (row["secondary-types"] or []) if s]

            if exclude_secondary and any(st in excluded_secondary for st in secondary_types):
                continue

            rg = {
                "id": row["id"],
                "title": row["title"],
                "primary-type": row["primary-type"],
                "secondary-types": secondary_types,
            }

            if row["first_release_year"]:
                rg["first-release-date"] = str(row["first_release_year"])

            # Get artist credits
            credits = self._get_artist_credits(row["artist_credit_id"])
            if credits:
                rg["artist-credit"] = credits

            results.append(rg)

        return results

    def select_best_release(
        self,
        release_group_mbid: str,
        preferred_countries: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Select the best release from a release group.

        Scoring: Official > Promotion > Bootleg, preferred countries, track count.
        """
        if preferred_countries is None:
            preferred_countries = ["US", "GB", "XW"]

        query = text("""
            SELECT
                r.gid::text AS id,
                r.name,
                rs.name AS status,
                rc.date_year,
                rc.date_month,
                rc.date_day,
                iso.code AS country,
                rg.gid::text AS release_group_id,
                (SELECT SUM(m.track_count) FROM musicbrainz.medium m WHERE m.release = r.id) AS total_tracks
            FROM musicbrainz.release r
            JOIN musicbrainz.release_group rg ON r.release_group = rg.id
            LEFT JOIN musicbrainz.release_status rs ON r.status = rs.id
            LEFT JOIN musicbrainz.release_country rc ON r.id = rc.release
            LEFT JOIN musicbrainz.country_area ca ON rc.country = ca.area
            LEFT JOIN musicbrainz.iso_3166_1 iso ON ca.area = iso.area
            WHERE rg.gid = CAST(:mbid AS uuid)
            ORDER BY
                CASE rs.name
                    WHEN 'Official' THEN 0
                    WHEN 'Promotion' THEN 1
                    WHEN 'Bootleg' THEN 2
                    ELSE 3
                END,
                total_tracks DESC NULLS LAST
        """)

        with self.engine.connect() as conn:
            rows = conn.execute(query, {"mbid": release_group_mbid}).mappings().all()

        if not rows:
            return None

        # Score releases
        def score_release(row):
            score = 0
            status_scores = {"Official": 100, "Promotion": 50, "Bootleg": 10}
            score += status_scores.get(row["status"] or "", 0)

            country = row["country"]
            if country and preferred_countries:
                try:
                    idx = preferred_countries.index(country)
                    score += (len(preferred_countries) - idx) * 10
                except ValueError:
                    pass

            score += (row["total_tracks"] or 0)
            return score

        best = max(rows, key=score_release)
        return self.get_release(best["id"])

    def get_release(self, release_mbid: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed release with media and tracks.

        Returns dict matching MusicBrainz API format.
        """
        # Get release info
        release_query = text("""
            SELECT
                r.gid::text AS id,
                r.name AS title,
                rs.name AS status,
                r.artist_credit AS artist_credit_id,
                rg.gid::text AS release_group_id,
                rgpt.name AS release_group_type,
                r.barcode,
                rc.date_year,
                rc.date_month,
                rc.date_day,
                iso.code AS country
            FROM musicbrainz.release r
            LEFT JOIN musicbrainz.release_status rs ON r.status = rs.id
            LEFT JOIN musicbrainz.release_group rg ON r.release_group = rg.id
            LEFT JOIN musicbrainz.release_group_primary_type rgpt ON rg.type = rgpt.id
            LEFT JOIN musicbrainz.release_country rc ON r.id = rc.release
            LEFT JOIN musicbrainz.country_area ca ON rc.country = ca.area
            LEFT JOIN musicbrainz.iso_3166_1 iso ON ca.area = iso.area
            WHERE r.gid = CAST(:mbid AS uuid)
            LIMIT 1
        """)

        with self.engine.connect() as conn:
            release_row = conn.execute(release_query, {"mbid": release_mbid}).mappings().first()

        if not release_row:
            return None

        result = {
            "id": release_row["id"],
            "title": release_row["title"],
            "status": release_row["status"],
            "barcode": release_row["barcode"] or "",
        }

        if release_row["date_year"]:
            result["date"] = self._format_date(
                release_row["date_year"],
                release_row["date_month"],
                release_row["date_day"],
            )

        if release_row["country"]:
            result["country"] = release_row["country"]

        # Release group info
        if release_row["release_group_id"]:
            result["release-group"] = {
                "id": release_row["release_group_id"],
                "primary-type": release_row["release_group_type"],
            }

        # Artist credits
        credits = self._get_artist_credits(release_row["artist_credit_id"])
        if credits:
            result["artist-credit"] = credits

        # Get media with tracks
        result["media"] = self._get_release_media(release_mbid)

        return result

    def _get_release_media(self, release_mbid: str) -> List[Dict[str, Any]]:
        """Get media (discs) with tracks for a release"""
        media_query = text("""
            SELECT
                m.id AS medium_id,
                m.position,
                m.name AS medium_name,
                mf.name AS format,
                m.track_count
            FROM musicbrainz.medium m
            JOIN musicbrainz.release r ON m.release = r.id
            LEFT JOIN musicbrainz.medium_format mf ON m.format = mf.id
            WHERE r.gid = CAST(:mbid AS uuid)
            ORDER BY m.position
        """)

        tracks_query = text("""
            SELECT
                t.position,
                t.name AS track_name,
                t.length AS track_length,
                t.gid::text AS track_id,
                rec.gid::text AS recording_id,
                rec.name AS recording_name,
                rec.length AS recording_length,
                rec.artist_credit AS recording_artist_credit_id
            FROM musicbrainz.track t
            JOIN musicbrainz.recording rec ON t.recording = rec.id
            WHERE t.medium = :medium_id
            ORDER BY t.position
        """)

        media = []
        with self.engine.connect() as conn:
            medium_rows = conn.execute(media_query, {"mbid": release_mbid}).mappings().all()

            for medium_row in medium_rows:
                medium = {
                    "position": medium_row["position"],
                    "format": medium_row["format"] or "CD",
                    "track-count": medium_row["track_count"],
                }

                if medium_row["medium_name"]:
                    medium["title"] = medium_row["medium_name"]

                track_rows = conn.execute(
                    tracks_query, {"medium_id": medium_row["medium_id"]}
                ).mappings().all()

                tracks = []
                for t_row in track_rows:
                    track = {
                        "id": t_row["track_id"],
                        "position": t_row["position"],
                        "title": t_row["track_name"],
                        "length": t_row["track_length"],
                        "recording": {
                            "id": t_row["recording_id"],
                            "title": t_row["recording_name"],
                            "length": t_row["recording_length"],
                        },
                    }

                    # Artist credits for the recording
                    rec_credits = self._get_artist_credits(
                        t_row["recording_artist_credit_id"]
                    )
                    if rec_credits:
                        track["recording"]["artist-credit"] = rec_credits

                    tracks.append(track)

                medium["tracks"] = tracks
                media.append(medium)

        return media

    def get_release_tracks(self, release_group_mbid: str) -> List[Dict[str, Any]]:
        """
        Get all tracks for a release group by selecting the best release.

        Returns list of tracks matching the MusicBrainzClient.get_release_tracks() format.
        """
        release = self.select_best_release(release_group_mbid)
        if not release or "media" not in release:
            return []

        tracks = []
        track_offset = 0

        for medium in release["media"]:
            disc_number = medium.get("position", 1)

            for track_data in medium.get("tracks", []):
                recording = track_data.get("recording", {})
                duration_ms = track_data.get("length") or recording.get("length")

                position = track_data.get("position")
                track_number = int(position) if position else track_offset + 1

                tracks.append({
                    "track_number": track_number,
                    "disc_number": disc_number,
                    "title": track_data.get("title") or recording.get("title", "Unknown Track"),
                    "duration_ms": int(duration_ms) if duration_ms else None,
                    "musicbrainz_id": recording.get("id"),
                })
                track_offset += 1

        return tracks

    def get_recording(
        self,
        mbid: str,
        includes: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get recording with artist credits"""
        query = text("""
            SELECT
                rec.gid::text AS id,
                rec.name AS title,
                rec.length,
                rec.artist_credit AS artist_credit_id,
                rec.comment AS disambiguation
            FROM musicbrainz.recording rec
            WHERE rec.gid = CAST(:mbid AS uuid)
        """)

        with self.engine.connect() as conn:
            row = conn.execute(query, {"mbid": mbid}).mappings().first()

        if not row:
            return None

        result = {
            "id": row["id"],
            "title": row["title"],
            "length": row["length"],
            "disambiguation": row["disambiguation"] or "",
        }

        credits = self._get_artist_credits(row["artist_credit_id"])
        if credits:
            result["artist-credit"] = credits

        # Include releases if requested
        if includes and "releases" in includes:
            result["releases"] = self._get_recording_releases(mbid)

        return result

    def _get_recording_releases(self, recording_mbid: str) -> List[Dict[str, Any]]:
        """Get releases that contain a recording"""
        query = text("""
            SELECT DISTINCT
                r.gid::text AS id,
                r.name AS title,
                rs.name AS status,
                rg.gid::text AS release_group_id
            FROM musicbrainz.track t
            JOIN musicbrainz.recording rec ON t.recording = rec.id
            JOIN musicbrainz.medium m ON t.medium = m.id
            JOIN musicbrainz.release r ON m.release = r.id
            LEFT JOIN musicbrainz.release_status rs ON r.status = rs.id
            LEFT JOIN musicbrainz.release_group rg ON r.release_group = rg.id
            WHERE rec.gid = CAST(:mbid AS uuid)
            LIMIT 10
        """)
        with self.engine.connect() as conn:
            rows = conn.execute(query, {"mbid": recording_mbid}).mappings().all()

        return [
            {
                "id": r["id"],
                "title": r["title"],
                "status": r["status"],
                "release-group": {"id": r["release_group_id"]} if r["release_group_id"] else {},
            }
            for r in rows
        ]

    def get_cover_art(self, release_mbid: str) -> Optional[str]:
        """
        Cover art is hosted on the Cover Art Archive, not in the local DB.
        Always returns None — the caller should fall through to the remote API.
        """
        return None

    def get_cover_art_for_release_group(self, release_group_mbid: str) -> Optional[str]:
        """Cover art requires external API — always returns None"""
        return None

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics for the settings UI"""
        queries = {
            "artists": "SELECT count(*) FROM musicbrainz.artist",
            "recordings": "SELECT count(*) FROM musicbrainz.recording",
            "release_groups": "SELECT count(*) FROM musicbrainz.release_group",
            "releases": "SELECT count(*) FROM musicbrainz.release",
        }

        stats = {}
        try:
            with self.engine.connect() as conn:
                for key, q in queries.items():
                    result = conn.execute(text(q)).scalar()
                    stats[key] = result or 0

                # Get last replication info
                try:
                    repl = conn.execute(text(
                        "SELECT current_replication_sequence, last_replication_date "
                        "FROM musicbrainz.replication_control LIMIT 1"
                    )).mappings().first()
                    if repl:
                        stats["replication_sequence"] = repl["current_replication_sequence"]
                        stats["last_replication"] = (
                            repl["last_replication_date"].isoformat()
                            if repl["last_replication_date"]
                            else None
                        )
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Failed to get MB local DB stats: {e}")

        return stats

    def test_connection(self) -> bool:
        """Test if the local database is reachable and populated"""
        try:
            with self.engine.connect() as conn:
                count = conn.execute(
                    text("SELECT count(*) FROM musicbrainz.artist")
                ).scalar()
                return (count or 0) > 0
        except Exception:
            return False

    def _get_artist_credits(self, artist_credit_id: int) -> List[Dict[str, Any]]:
        """Get artist credits for a release, recording, etc."""
        if not artist_credit_id:
            return []

        query = text("""
            SELECT
                acn.name AS credited_name,
                acn.join_phrase,
                a.gid::text AS artist_id,
                a.name AS artist_name,
                a.sort_name AS artist_sort_name
            FROM musicbrainz.artist_credit_name acn
            JOIN musicbrainz.artist a ON acn.artist = a.id
            WHERE acn.artist_credit = :credit_id
            ORDER BY acn.position
        """)

        with self.engine.connect() as conn:
            rows = conn.execute(query, {"credit_id": artist_credit_id}).mappings().all()

        return [
            {
                "name": row["credited_name"],
                "joinphrase": row["join_phrase"] or "",
                "artist": {
                    "id": row["artist_id"],
                    "name": row["artist_name"],
                    "sort-name": row["artist_sort_name"],
                },
            }
            for row in rows
        ]

    def _format_date(
        self,
        year: Optional[int],
        month: Optional[int] = None,
        day: Optional[int] = None,
    ) -> str:
        """Format date components into YYYY-MM-DD string"""
        if not year:
            return ""
        if day and month:
            return f"{year:04d}-{month:02d}-{day:02d}"
        if month:
            return f"{year:04d}-{month:02d}"
        return f"{year:04d}"

    def get_series_for_release_group(self, release_group_mbid: str) -> Optional[Dict[str, Any]]:
        """
        Find which series a release group belongs to.

        Queries l_release_group_series (link_type 742 = "part of") to find the
        series relationship for a given release group.

        Args:
            release_group_mbid: Release group MBID (UUID string)

        Returns:
            Dict with {series_mbid, series_name, series_position} or None
        """
        query = text("""
            SELECT
                s.gid::text AS series_mbid,
                s.name AS series_name,
                latv.text_value AS series_position_text
            FROM musicbrainz.release_group rg
            JOIN musicbrainz.l_release_group_series lrgs ON lrgs.entity0 = rg.id
            JOIN musicbrainz.link l ON l.id = lrgs.link AND l.link_type = 742
            JOIN musicbrainz.series s ON s.id = lrgs.entity1
            LEFT JOIN musicbrainz.link_attribute_text_value latv
                ON latv.link = l.id AND latv.attribute_type = 788
            WHERE rg.gid = CAST(:rg_mbid AS uuid)
            LIMIT 1
        """)

        try:
            with self.engine.connect() as conn:
                row = conn.execute(query, {"rg_mbid": release_group_mbid}).mappings().first()

            if not row:
                return None

            pos_text = row["series_position_text"]
            try:
                position = int(float(pos_text)) if pos_text else None
            except (ValueError, TypeError):
                position = None

            return {
                "series_mbid": row["series_mbid"],
                "series_name": row["series_name"],
                "series_position": position,
            }
        except Exception as e:
            logger.error(f"Error querying series for release group {release_group_mbid}: {e}")
            return None

    def get_series_release_group_order(self, series_mbid: str) -> List[Dict[str, Any]]:
        """
        Get ordered release groups for a series from the local MusicBrainz DB.

        Queries the series -> l_release_group_series link table (link_type 742 = "part of")
        and gets ordering from link_attribute_text_value (attribute_type 788 = "number").

        Returns list of dicts sorted by position:
            [{release_group_mbid, release_group_name, series_position}, ...]
        """
        query = text("""
            SELECT
                rg.gid::text AS release_group_mbid,
                rg.name AS release_group_name,
                latv.text_value AS series_position_text
            FROM musicbrainz.series s
            JOIN musicbrainz.l_release_group_series lrgs ON lrgs.entity1 = s.id
            JOIN musicbrainz.link l ON l.id = lrgs.link
            JOIN musicbrainz.release_group rg ON rg.id = lrgs.entity0
            LEFT JOIN musicbrainz.link_attribute_text_value latv
                ON latv.link = l.id AND latv.attribute_type = 788
            WHERE s.gid = CAST(:series_mbid AS uuid)
              AND l.link_type = 742
            ORDER BY
                CASE
                    WHEN latv.text_value ~ '^[0-9]+(\\.?[0-9]*)$'
                    THEN CAST(latv.text_value AS numeric)
                    ELSE 999999
                END,
                rg.name
        """)

        try:
            with self.engine.connect() as conn:
                rows = conn.execute(query, {"series_mbid": series_mbid}).mappings().all()

            results = []
            for idx, row in enumerate(rows):
                pos_text = row["series_position_text"]
                try:
                    position = int(float(pos_text)) if pos_text else idx + 1
                except (ValueError, TypeError):
                    position = idx + 1

                results.append({
                    "release_group_mbid": row["release_group_mbid"],
                    "release_group_name": row["release_group_name"],
                    "series_position": position,
                })

            logger.info(f"Series {series_mbid}: found {len(results)} release groups in local DB")
            return results
        except Exception as e:
            logger.error(f"Error querying series release groups for {series_mbid}: {e}")
            return []

    def get_series_for_artist(self, artist_mbid: str) -> List[Dict[str, Any]]:
        """
        Get all series containing release groups by this artist from the local MB DB.

        Queries l_release_group_series (link_type 742 = "part of") to find series
        that include any release group credited to the given artist.

        Args:
            artist_mbid: MusicBrainz artist MBID (UUID string)

        Returns:
            List of dicts: [{series_mbid, series_name, series_type}, ...]
        """
        query = text("""
            SELECT DISTINCT
                s.gid::text AS series_mbid,
                s.name AS series_name,
                st.name AS series_type
            FROM musicbrainz.artist a
            JOIN musicbrainz.artist_credit_name acn ON acn.artist = a.id
            JOIN musicbrainz.release_group rg ON rg.artist_credit = acn.artist_credit
            JOIN musicbrainz.l_release_group_series lrgs ON lrgs.entity0 = rg.id
            JOIN musicbrainz.link l ON l.id = lrgs.link AND l.link_type = 742
            JOIN musicbrainz.series s ON s.id = lrgs.entity1
            LEFT JOIN musicbrainz.series_type st ON st.id = s.type
            WHERE a.gid = CAST(:artist_mbid AS uuid)
            ORDER BY s.name
        """)

        try:
            with self.engine.connect() as conn:
                rows = conn.execute(query, {"artist_mbid": artist_mbid}).mappings().all()

            results = [
                {
                    "series_mbid": row["series_mbid"],
                    "series_name": row["series_name"],
                    "series_type": row["series_type"],
                }
                for row in rows
            ]

            logger.info(f"Artist {artist_mbid}: found {len(results)} series in local DB")
            return results
        except Exception as e:
            logger.error(f"Error querying series for artist {artist_mbid}: {e}")
            return []


# Singleton instance
_local_db: Optional[MusicBrainzLocalDB] = None


def get_musicbrainz_local_db() -> Optional[MusicBrainzLocalDB]:
    """
    Get singleton MusicBrainzLocalDB instance.

    Returns None if local DB is not configured or not available.
    """
    global _local_db
    if _local_db is not None:
        return _local_db

    db_url = os.getenv("MUSICBRAINZ_LOCAL_DB_URL")
    enabled = os.getenv("MUSICBRAINZ_LOCAL_DB_ENABLED", "false").lower() == "true"

    if not db_url or not enabled:
        return None

    try:
        _local_db = MusicBrainzLocalDB(db_url)
        return _local_db
    except Exception as e:
        logger.warning(f"MusicBrainz local DB unavailable: {e}")
        return None
