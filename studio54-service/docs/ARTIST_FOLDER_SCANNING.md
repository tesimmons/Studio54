# Artist Folder Scanning

Automatically assign album folder paths when selecting an artist folder.

## Overview

When you select an artist's root folder (e.g., `/music/Pink Floyd/`), Studio54 will:
1. Scan all subdirectories in the artist folder
2. Match folder names to album titles using intelligent fuzzy matching
3. Automatically assign `custom_folder_path` for high-confidence matches (≥70%)
4. Provide suggestions for lower-confidence matches (≥50%)

## API Endpoint

```
POST /api/v1/artists/{artist_id}/scan-folder
```

### Request Body

```json
{
  "folder_path": "/music/Pink Floyd"
}
```

### Response

```json
{
  "artist_id": "uuid-here",
  "artist_name": "Pink Floyd",
  "folder_path": "/music/Pink Floyd",
  "subdirectories_found": 6,
  "albums_matched": 6,
  "message": "Successfully assigned 6 album folder paths",
  "matches": [
    {
      "album_id": "album-uuid-1",
      "album_title": "The Wall",
      "folder_name": "The Wall",
      "folder_path": "/music/Pink Floyd/The Wall",
      "confidence": 100.0,
      "auto_assigned": true
    },
    {
      "album_id": "album-uuid-2",
      "album_title": "The Dark Side of the Moon",
      "folder_name": "The Dark Side of the Moon",
      "folder_path": "/music/Pink Floyd/The Dark Side of the Moon",
      "confidence": 100.0,
      "auto_assigned": true
    },
    {
      "album_id": "album-uuid-3",
      "album_title": "The Piper at the Gates of Dawn",
      "folder_name": "Piper at Gates of Dawn",
      "folder_path": "/music/Pink Floyd/Piper at Gates of Dawn",
      "confidence": 85.3,
      "auto_assigned": true
    },
    {
      "album_id": "album-uuid-4",
      "album_title": "Obscured by Clouds",
      "folder_name": "Misc Tracks",
      "folder_path": "/music/Pink Floyd/Misc Tracks",
      "confidence": 52.1,
      "auto_assigned": false
    }
  ]
}
```

## Matching Algorithm

### Confidence Levels

- **100%**: Exact match (folder name == album title)
- **90%+**: Album title contained in folder name
- **70-89%**: High fuzzy similarity (auto-assigned)
- **50-69%**: Moderate similarity (manual review needed)
- **<50%**: Low similarity (not included in results)

### Normalization

The matching algorithm normalizes strings by:
- Converting to lowercase
- Removing special characters
- Removing common articles ("the", "a", "an")

Examples:
- "The Wall" → "wall"
- "The Dark Side of the Moon" → "dark side moon"

### Examples

| Folder Name | Album Title | Confidence | Auto-Assigned |
|-------------|-------------|------------|---------------|
| `The Wall` | `The Wall` | 100.0% | ✓ Yes |
| `Dark Side of the Moon` | `The Dark Side of the Moon` | 100.0% | ✓ Yes |
| `WYWH [1975]` | `Wish You Were Here` | 71.2% | ✓ Yes |
| `Animals` | `Animals` | 100.0% | ✓ Yes |
| `Live Bootleg 1977` | `Animals` | 42.3% | ✗ No |

## Usage Workflow

### 1. Select Artist Folder

When configuring an artist in Studio54, select their root folder path.

### 2. Auto-Scan

The system will:
- Update `artist.root_folder_path`
- Scan for subdirectories
- Match folders to albums
- Auto-assign paths for high-confidence matches

### 3. Review Results

Check the `matches` array in the response:
- **auto_assigned: true** - Path was automatically set
- **auto_assigned: false** - Manual review recommended

### 4. Manual Assignment (if needed)

For low-confidence matches, manually assign using the album detail page.

## Benefits

- **Faster Setup**: Automatically configures folder paths for entire artist catalogs
- **Accurate Matching**: 70% confidence threshold prevents false positives
- **MBID Integration**: Once folder paths are set, tracks are matched via MusicBrainz IDs
- **Bulk Processing**: Handles all albums in one API call

## Integration with MBID Matching

After folder paths are assigned:
1. Use album file matcher to scan each folder
2. Files with MusicBrainz IDs in comments (from MUSE Ponder) are matched at 100% accuracy
3. Fallback to track number and title matching for other files

## Example: Complete Workflow

```bash
# 1. Scan artist folder
curl -X POST "http://localhost:8010/api/v1/artists/{artist_id}/scan-folder" \
  -H "Content-Type: application/json" \
  -d '{"folder_path": "/music/Pink Floyd"}'

# Response shows 6 albums auto-assigned

# 2. For each album, scan and match files
curl -X POST "http://localhost:8010/api/v1/albums/{album_id}/scan-folder"

# Files are matched via:
# - MBID (100% accurate for MUSE Ponder tagged files)
# - Track number (95% accurate)
# - Title similarity (60-95% accurate)
```

## Error Handling

### Folder Not Found
```json
{
  "detail": "Folder path does not exist: /music/Pink Floyd"
}
```

### Not a Directory
```json
{
  "detail": "Path is not a directory: /music/album.mp3"
}
```

### No Albums Found
```json
{
  "artist_id": "uuid-here",
  "artist_name": "Pink Floyd",
  "folder_path": "/music/Pink Floyd",
  "subdirectories_found": 6,
  "albums_matched": 0,
  "matches": [],
  "message": "No albums found for this artist"
}
```

## Notes

- Only subdirectories are scanned (non-recursive)
- Hidden folders (starting with `.`) are ignored by default
- Symbolic links are followed
- Permissions must allow read access to the folder
- Artist's `root_folder_path` is updated regardless of match success
