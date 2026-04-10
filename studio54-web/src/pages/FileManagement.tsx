/**
 * File Management Dashboard for Studio54
 * MBID-based file organization for library paths and artists
 */

import React, { useState, useEffect } from 'react'
import {
  Container,
  Typography,
  Box,
  Card,
  CardContent,
  Grid,
  Button,
  Stack,
  Alert,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  MenuItem,
  FormControlLabel,
  Switch,
  Divider,
  Tab,
  Tabs,
  Chip,
  CircularProgress,
  Tooltip,
} from '@mui/material'
import {
  FolderOpen as OrganizeIcon,
  Assessment as ValidateIcon,
  Person as ArtistIcon,
  Search as SearchIcon,
  Link as LinkIcon,
  Refresh as RefreshIcon,
  Verified as VerifyIcon,
  CleaningServices as CleanupIcon,
  PersonAdd as ImportArtistIcon,
  AutoFixHigh as AutoResolveIcon,
} from '@mui/icons-material'
import { OrganizationJobMonitor } from '../components/shared/OrganizationJobMonitor'
import { AuditLogViewer } from '../components/shared/AuditLogViewer'
import { authFetch } from '../api/client'
import LibraryImport from './LibraryImport'

const API_BASE_URL = '/api/v1'

interface LibraryPath {
  id: string
  name: string
  path: string
  is_enabled: boolean
}

interface Artist {
  id: string
  name: string
  musicbrainz_id?: string
}

interface TabPanelProps {
  children?: React.ReactNode
  index: number
  value: number
}

function TabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props

  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      id={`tabpanel-${index}`}
      aria-labelledby={`tab-${index}`}
      {...other}
    >
      {value === index && <Box sx={{ p: 3 }}>{children}</Box>}
    </div>
  )
}

const FileManagement: React.FC = () => {
  const [tabValue, setTabValue] = useState(0)
  const [libraryPaths, setLibraryPaths] = useState<LibraryPath[]>([])
  const [artists, setArtists] = useState<Artist[]>([])
  const [selectedLibraryPath, setSelectedLibraryPath] = useState<string>('')
  const [selectedArtist, setSelectedArtist] = useState<string>('')
  const [organizeDialogOpen, setOrganizeDialogOpen] = useState(false)
  const [organizeArtistDialogOpen, setOrganizeArtistDialogOpen] = useState(false)
  const [validateDialogOpen, setValidateDialogOpen] = useState(false)
  const [fetchMetadataDialogOpen, setFetchMetadataDialogOpen] = useState(false)
  const [validateMbidDialogOpen, setValidateMbidDialogOpen] = useState(false)
  const [validateMbidMetadataDialogOpen, setValidateMbidMetadataDialogOpen] = useState(false)
  const [linkFilesDialogOpen, setLinkFilesDialogOpen] = useState(false)
  const [autoImportArtists, setAutoImportArtists] = useState(false)
  const [importUnlinkedDialogOpen, setImportUnlinkedDialogOpen] = useState(false)
  const [resolveUnlinkedDialogOpen, setResolveUnlinkedDialogOpen] = useState(false)
  const [reindexDialogOpen, setReindexDialogOpen] = useState(false)
  const [verifyAudioDialogOpen, setVerifyAudioDialogOpen] = useState(false)
  const [cleanupLogsDialogOpen, setCleanupLogsDialogOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  // Organization options
  const [dryRun, setDryRun] = useState(false)
  const [createMetadata, setCreateMetadata] = useState(true)
  const [onlyWithMbid, setOnlyWithMbid] = useState(true)
  const [onlyUnorganized, setOnlyUnorganized] = useState(true)

  // Verification options
  const [verifyDaysBack, setVerifyDaysBack] = useState(90)

  // Cleanup options
  const [cleanupRetentionDays, setCleanupRetentionDays] = useState(120)
  const [cleanupPreview, setCleanupPreview] = useState<any>(null)

  // Load library paths
  const loadLibraryPaths = async () => {
    try {
      const response = await authFetch(`${API_BASE_URL}/library/paths`)
      if (!response.ok) throw new Error('Failed to load library paths')
      const data = await response.json()
      setLibraryPaths(data.library_paths || [])
    } catch (err: any) {
      console.error('Failed to load library paths:', err)
      setError(err.message || 'Failed to load library paths')
    }
  }

  // Load artists
  const loadArtists = async () => {
    try {
      const response = await authFetch(`${API_BASE_URL}/artists?limit=1000`)
      if (!response.ok) throw new Error('Failed to load artists')
      const data = await response.json()
      setArtists(data.artists || [])
    } catch (err: any) {
      console.error('Failed to load artists:', err)
      setError(err.message || 'Failed to load artists')
    }
  }

  useEffect(() => {
    loadLibraryPaths()
    loadArtists()
  }, [])

  // Handle organize library
  const handleOrganizeLibrary = async () => {
    if (!selectedLibraryPath) {
      setError('Please select a library path')
      return
    }

    setLoading(true)
    setError(null)
    setSuccess(null)

    try {
      const response = await authFetch(
        `${API_BASE_URL}/file-organization/library-paths/${selectedLibraryPath}/organize`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            dry_run: dryRun,
            create_metadata_files: createMetadata,
            backup_before_move: false,  // No backup - use checksum validation
            only_with_mbid: onlyWithMbid,
            only_unorganized: onlyUnorganized,
          }),
        }
      )

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Failed to start organization job')
      }

      const data = await response.json()
      setSuccess(
        `Organization job started! Job ID: ${data.job_id}. Estimated files: ${data.estimated_files || 0}`
      )
      setOrganizeDialogOpen(false)
    } catch (err: any) {
      console.error('Failed to organize library:', err)
      setError(err.message || 'Failed to start organization job')
    } finally {
      setLoading(false)
    }
  }

  // Handle organize artist
  const handleOrganizeArtist = async () => {
    if (!selectedArtist) {
      setError('Please select an artist')
      return
    }

    setLoading(true)
    setError(null)
    setSuccess(null)

    try {
      const response = await authFetch(`${API_BASE_URL}/file-organization/artists/${selectedArtist}/organize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          dry_run: dryRun,
          create_metadata_files: createMetadata,
          backup_before_move: false,  // No backup - use checksum validation
          only_with_mbid: onlyWithMbid,
          only_unorganized: onlyUnorganized,
        }),
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Failed to start organization job')
      }

      const data = await response.json()
      setSuccess(`Artist organization job started! Job ID: ${data.job_id}`)
      setOrganizeArtistDialogOpen(false)
    } catch (err: any) {
      console.error('Failed to organize artist:', err)
      setError(err.message || 'Failed to start organization job')
    } finally {
      setLoading(false)
    }
  }

  // Handle validate library
  const handleValidateLibrary = async () => {
    if (!selectedLibraryPath) {
      setError('Please select a library path')
      return
    }

    setLoading(true)
    setError(null)
    setSuccess(null)

    try {
      const response = await authFetch(
        `${API_BASE_URL}/file-organization/library-paths/${selectedLibraryPath}/validate`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        }
      )

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Failed to start validation job')
      }

      const data = await response.json()
      setSuccess(`Validation job started! Job ID: ${data.job_id}`)
      setValidateDialogOpen(false)
    } catch (err: any) {
      console.error('Failed to validate library:', err)
      setError(err.message || 'Failed to start validation job')
    } finally {
      setLoading(false)
    }
  }

  // Handle fetch metadata job
  const handleFetchMetadata = async () => {
    if (!selectedLibraryPath) {
      setError('Please select a library path')
      return
    }

    setLoading(true)
    setError(null)
    setSuccess(null)

    try {
      const response = await authFetch(
        `${API_BASE_URL}/file-organization/library-paths/${selectedLibraryPath}/fetch-metadata`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        }
      )

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Failed to start fetch metadata job')
      }

      const data = await response.json()
      setSuccess(`Fetch metadata job started! Job ID: ${data.job_id}. This will write MBIDs to files.`)
      setFetchMetadataDialogOpen(false)
    } catch (err: any) {
      console.error('Failed to start fetch metadata job:', err)
      setError(err.message || 'Failed to start fetch metadata job')
    } finally {
      setLoading(false)
    }
  }

  // Handle validate MBID job
  const handleValidateMbid = async () => {
    if (!selectedLibraryPath) {
      setError('Please select a library path')
      return
    }

    setLoading(true)
    setError(null)
    setSuccess(null)

    try {
      const response = await authFetch(
        `${API_BASE_URL}/file-organization/library-paths/${selectedLibraryPath}/validate-mbid`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        }
      )

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Failed to start MBID validation job')
      }

      const data = await response.json()
      setSuccess(`MBID validation job started! Job ID: ${data.job_id}. Verifying MBIDs in file comments.`)
      setValidateMbidDialogOpen(false)
    } catch (err: any) {
      console.error('Failed to start MBID validation job:', err)
      setError(err.message || 'Failed to start MBID validation job')
    } finally {
      setLoading(false)
    }
  }

  // Handle validate MBID metadata job
  const handleValidateMbidMetadata = async () => {
    if (!selectedLibraryPath) {
      setError('Please select a library path')
      return
    }

    setLoading(true)
    setError(null)
    setSuccess(null)

    try {
      const response = await authFetch(
        `${API_BASE_URL}/file-organization/library-paths/${selectedLibraryPath}/validate-mbid-metadata`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        }
      )

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Failed to start MBID metadata validation job')
      }

      const data = await response.json()
      setSuccess(`MBID metadata validation job started! Job ID: ${data.job_id}. Comparing file metadata with MusicBrainz.`)
      setValidateMbidMetadataDialogOpen(false)
    } catch (err: any) {
      console.error('Failed to start MBID metadata validation job:', err)
      setError(err.message || 'Failed to start MBID metadata validation job')
    } finally {
      setLoading(false)
    }
  }

  // Handle link files job
  const handleLinkFiles = async () => {
    if (!selectedLibraryPath) {
      setError('Please select a library path')
      return
    }

    setLoading(true)
    setError(null)
    setSuccess(null)

    try {
      const params = new URLSearchParams()
      if (autoImportArtists) params.set('auto_import_artists', 'true')
      const url = `${API_BASE_URL}/file-organization/library-paths/${selectedLibraryPath}/link-files${params.toString() ? '?' + params.toString() : ''}`
      const response = await authFetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Failed to start link files job')
      }

      const data = await response.json()
      setSuccess(`Link files job started! Job ID: ${data.job_id}. ${data.message}`)
      setLinkFilesDialogOpen(false)
    } catch (err: any) {
      console.error('Failed to start link files job:', err)
      setError(err.message || 'Failed to start link files job')
    } finally {
      setLoading(false)
    }
  }

  // Handle import unlinked artists
  const handleImportUnlinked = async () => {
    setLoading(true)
    setError(null)
    setSuccess(null)

    try {
      const response = await authFetch(`${API_BASE_URL}/artists/import-unlinked`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          library_path_id: selectedLibraryPath || undefined,
          is_monitored: false,
          auto_sync: true,
        }),
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Failed to import unlinked artists')
      }

      const data = await response.json()
      setSuccess(`Task queued — ${data.message}. Check Activity page for progress.`)
      setImportUnlinkedDialogOpen(false)
    } catch (err: any) {
      console.error('Failed to import unlinked artists:', err)
      setError(err.message || 'Failed to import unlinked artists')
    } finally {
      setLoading(false)
    }
  }

  // Handle resolve unlinked files
  const handleResolveUnlinked = async () => {
    setLoading(true)
    setError(null)
    setSuccess(null)

    try {
      const params: Record<string, string> = {}
      if (selectedLibraryPath) {
        params.library_path_id = selectedLibraryPath
      }
      const queryString = new URLSearchParams(params).toString()
      const url = `${API_BASE_URL}/file-organization/files/resolve-unlinked${queryString ? '?' + queryString : ''}`

      const response = await authFetch(url, {
        method: 'POST',
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Failed to start resolve job')
      }

      const data = await response.json()
      setSuccess(`Resolve job started (${data.estimated_files} files). Job ID: ${data.job_id}`)
      setResolveUnlinkedDialogOpen(false)
    } catch (err: any) {
      console.error('Failed to resolve unlinked files:', err)
      setError(err.message || 'Failed to resolve unlinked files')
    } finally {
      setLoading(false)
    }
  }

  // Handle reindex albums job
  const handleReindexAlbums = async () => {
    if (!selectedLibraryPath) {
      setError('Please select a library path')
      return
    }

    setLoading(true)
    setError(null)
    setSuccess(null)

    try {
      const response = await authFetch(
        `${API_BASE_URL}/file-organization/library-paths/${selectedLibraryPath}/reindex-albums`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        }
      )

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Failed to start reindex albums job')
      }

      const data = await response.json()
      setSuccess(`Reindex albums job started! Job ID: ${data.job_id}. Reindexing albums from file metadata.`)
      setReindexDialogOpen(false)
    } catch (err: any) {
      console.error('Failed to start reindex albums job:', err)
      setError(err.message || 'Failed to start reindex albums job')
    } finally {
      setLoading(false)
    }
  }

  // Handle verify audio job
  const handleVerifyAudio = async () => {
    if (!selectedLibraryPath) {
      setError('Please select a library path')
      return
    }

    setLoading(true)
    setError(null)
    setSuccess(null)

    try {
      const response = await authFetch(
        `${API_BASE_URL}/file-organization/library-paths/${selectedLibraryPath}/verify-audio`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ days_back: verifyDaysBack }),
        }
      )

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Failed to start audio verification job')
      }

      const data = await response.json()
      setSuccess(`Audio verification job started! Job ID: ${data.job_id}. Verifying files downloaded in last ${verifyDaysBack} days.`)
      setVerifyAudioDialogOpen(false)
    } catch (err: any) {
      console.error('Failed to start audio verification job:', err)
      setError(err.message || 'Failed to start audio verification job')
    } finally {
      setLoading(false)
    }
  }

  // Handle validate file links job
  const handleValidateFileLinks = async () => {
    setLoading(true)
    setError(null)
    setSuccess(null)

    try {
      const url = selectedLibraryPath
        ? `${API_BASE_URL}/file-organization/library-paths/${selectedLibraryPath}/validate-file-links`
        : `${API_BASE_URL}/file-organization/validate-file-links`

      const response = await authFetch(url, { method: 'POST' })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Failed to start file link validation job')
      }

      const data = await response.json()
      setSuccess(`File link validation job started! Job ID: ${data.job_id}. Checking ${data.estimated_files || 0} linked tracks.`)
    } catch (err: any) {
      console.error('Failed to start file link validation job:', err)
      setError(err.message || 'Failed to start file link validation job')
    } finally {
      setLoading(false)
    }
  }

  // Handle preview cleanup
  const handlePreviewCleanup = async () => {
    setLoading(true)
    try {
      const response = await authFetch(
        `${API_BASE_URL}/jobs/cleanup-logs/preview?retention_days=${cleanupRetentionDays}`
      )
      if (!response.ok) throw new Error('Failed to preview cleanup')
      const data = await response.json()
      setCleanupPreview(data)
    } catch (err: any) {
      setError(err.message || 'Failed to preview cleanup')
    } finally {
      setLoading(false)
    }
  }

  // Handle cleanup logs
  const handleCleanupLogs = async () => {
    setLoading(true)
    setError(null)
    setSuccess(null)

    try {
      const response = await authFetch(`${API_BASE_URL}/jobs/cleanup-logs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ retention_days: cleanupRetentionDays }),
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || 'Failed to start cleanup job')
      }

      const data = await response.json()
      setSuccess(`Log cleanup task queued! Task ID: ${data.task_id}. Cleaning up files older than ${cleanupRetentionDays} days.`)
      setCleanupLogsDialogOpen(false)
      setCleanupPreview(null)
    } catch (err: any) {
      console.error('Failed to start cleanup job:', err)
      setError(err.message || 'Failed to start cleanup job')
    } finally {
      setLoading(false)
    }
  }

  // Handle rollback
  const handleRollback = async (jobId: string) => {
    const response = await authFetch(`${API_BASE_URL}/jobs/${jobId}/rollback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirm: true }),
    })

    if (!response.ok) {
      const errorData = await response.json()
      throw new Error(errorData.detail || 'Failed to rollback job')
    }

    setSuccess('Rollback job queued successfully')
  }

  return (
    <Container maxWidth="xl" sx={{ mt: 4, mb: 4, color: 'text.primary' }}>
      {/* Header */}
      <Box sx={{ mb: 4 }}>
        <Typography variant="h4" component="h1" gutterBottom>
          File Management
        </Typography>
        <Typography variant="body1" color="text.secondary">
          MBID-based file organization for Studio54
        </Typography>
      </Box>

      {/* Alerts */}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}
      {success && (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSuccess(null)}>
          {success}
        </Alert>
      )}

      {/* Tabs */}
      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 2 }}>
        <Tabs value={tabValue} onChange={(_, newValue) => setTabValue(newValue)}>
          <Tab label="Library Jobs" />
          <Tab label="Artist Organization" />
          <Tab label="Jobs & Audit" />
          <Tab label="Maintenance" />
          <Tab label="Library Import" />
        </Tabs>
      </Box>

      {/* Library Jobs Tab */}
      <TabPanel value={tabValue} index={0}>
        <Card sx={{ mb: 3 }}>
          <CardContent>
            <Typography variant="h6" gutterBottom>
              Select Library Path
            </Typography>
            <Grid container spacing={2} sx={{ mb: 3 }}>
              <Grid item xs={12} md={8}>
                <TextField
                  select
                  fullWidth
                  label="Library Path"
                  value={selectedLibraryPath}
                  onChange={(e) => setSelectedLibraryPath(e.target.value)}
                  size="small"
                >
                  <MenuItem value="">
                    <em>Select a library path</em>
                  </MenuItem>
                  {libraryPaths.map((path) => (
                    <MenuItem key={path.id} value={path.id}>
                      {path.name} - {path.path}
                    </MenuItem>
                  ))}
                </TextField>
              </Grid>
            </Grid>

            <Divider sx={{ my: 2 }} />

            <Typography variant="subtitle1" gutterBottom sx={{ fontWeight: 'bold' }}>
              Organization Jobs
            </Typography>
            <Grid container spacing={2} sx={{ mb: 3 }}>
              <Grid item xs={12} sm={6} md={3}>
                <Button
                  variant="contained"
                  color="primary"
                  startIcon={<OrganizeIcon />}
                  onClick={() => setOrganizeDialogOpen(true)}
                  disabled={!selectedLibraryPath}
                  fullWidth
                >
                  Organize Library
                </Button>
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <Button
                  variant="outlined"
                  color="secondary"
                  startIcon={<ValidateIcon />}
                  onClick={() => setValidateDialogOpen(true)}
                  disabled={!selectedLibraryPath}
                  fullWidth
                >
                  Validate Structure
                </Button>
              </Grid>
            </Grid>

            <Typography variant="subtitle1" gutterBottom sx={{ fontWeight: 'bold' }}>
              MBID Jobs
            </Typography>
            <Grid container spacing={2} sx={{ mb: 3 }}>
              <Grid item xs={12} sm={6} md={3}>
                <Tooltip title="Fetch MBIDs from MusicBrainz and write to file comments">
                  <Button
                    variant="outlined"
                    startIcon={<SearchIcon />}
                    onClick={() => setFetchMetadataDialogOpen(true)}
                    disabled={!selectedLibraryPath}
                    fullWidth
                  >
                    Fetch Metadata
                  </Button>
                </Tooltip>
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <Tooltip title="Verify MBIDs exist in file comments, update database">
                  <Button
                    variant="outlined"
                    startIcon={<VerifyIcon />}
                    onClick={() => setValidateMbidDialogOpen(true)}
                    disabled={!selectedLibraryPath}
                    fullWidth
                  >
                    Validate MBIDs
                  </Button>
                </Tooltip>
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <Tooltip title="Link files with MBIDs to album tracks">
                  <Button
                    variant="outlined"
                    startIcon={<LinkIcon />}
                    onClick={() => setLinkFilesDialogOpen(true)}
                    disabled={!selectedLibraryPath}
                    fullWidth
                  >
                    Link Files
                  </Button>
                </Tooltip>
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <Tooltip title="Import artists from unlinked files (files with MBIDs but no matching artist in library)">
                  <Button
                    variant="outlined"
                    color="success"
                    startIcon={<ImportArtistIcon />}
                    onClick={() => setImportUnlinkedDialogOpen(true)}
                    fullWidth
                  >
                    Import Unlinked
                  </Button>
                </Tooltip>
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <Tooltip title="Auto-resolve unlinked files: imports missing albums, re-links via MBID, fuzzy matches files without MBIDs">
                  <Button
                    variant="outlined"
                    color="secondary"
                    startIcon={<AutoResolveIcon />}
                    onClick={() => setResolveUnlinkedDialogOpen(true)}
                    fullWidth
                  >
                    Auto-Resolve
                  </Button>
                </Tooltip>
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <Tooltip title="Reindex albums/singles from file metadata">
                  <Button
                    variant="outlined"
                    startIcon={<RefreshIcon />}
                    onClick={() => setReindexDialogOpen(true)}
                    disabled={!selectedLibraryPath}
                    fullWidth
                  >
                    Reindex Albums
                  </Button>
                </Tooltip>
              </Grid>
            </Grid>

            <Typography variant="subtitle1" gutterBottom sx={{ fontWeight: 'bold' }}>
              Verification Jobs
            </Typography>
            <Grid container spacing={2}>
              <Grid item xs={12} sm={6} md={3}>
                <Tooltip title="Verify audio integrity of recently downloaded files">
                  <Button
                    variant="outlined"
                    color="warning"
                    startIcon={<VerifyIcon />}
                    onClick={() => setVerifyAudioDialogOpen(true)}
                    disabled={!selectedLibraryPath}
                    fullWidth
                  >
                    Verify Audio
                  </Button>
                </Tooltip>
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <Tooltip title="Validate file metadata matches MusicBrainz MBID data">
                  <Button
                    variant="outlined"
                    color="info"
                    startIcon={<VerifyIcon />}
                    onClick={() => setValidateMbidMetadataDialogOpen(true)}
                    disabled={!selectedLibraryPath}
                    fullWidth
                  >
                    Validate Metadata
                  </Button>
                </Tooltip>
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <Tooltip title="Check that all linked track files still exist on disk. Clears stale links for missing files.">
                  <Button
                    variant="outlined"
                    color="warning"
                    startIcon={<LinkIcon />}
                    onClick={handleValidateFileLinks}
                    disabled={loading}
                    fullWidth
                  >
                    Validate File Links
                  </Button>
                </Tooltip>
              </Grid>
            </Grid>
          </CardContent>
        </Card>
      </TabPanel>

      {/* Artist Organization Tab */}
      <TabPanel value={tabValue} index={1}>
        <Card sx={{ mb: 3 }}>
          <CardContent>
            <Typography variant="h6" gutterBottom>
              Organize Artist Files
            </Typography>
            <Grid container spacing={2}>
              <Grid item xs={12} md={8}>
                <TextField
                  select
                  fullWidth
                  label="Select Artist"
                  value={selectedArtist}
                  onChange={(e) => setSelectedArtist(e.target.value)}
                  size="small"
                >
                  <MenuItem value="">
                    <em>Select an artist</em>
                  </MenuItem>
                  {artists.map((artist) => (
                    <MenuItem key={artist.id} value={artist.id}>
                      {artist.name}
                      {artist.musicbrainz_id && (
                        <Chip
                          label="MBID"
                          size="small"
                          color="success"
                          sx={{ ml: 1 }}
                        />
                      )}
                    </MenuItem>
                  ))}
                </TextField>
              </Grid>
              <Grid item xs={12} md={4}>
                <Button
                  variant="contained"
                  color="primary"
                  startIcon={<ArtistIcon />}
                  onClick={() => setOrganizeArtistDialogOpen(true)}
                  disabled={!selectedArtist}
                  fullWidth
                >
                  Organize Artist
                </Button>
              </Grid>
            </Grid>
          </CardContent>
        </Card>
      </TabPanel>

      {/* Jobs & Audit Tab */}
      <TabPanel value={tabValue} index={2}>
        <Card sx={{ mb: 3 }}>
          <CardContent>
            <OrganizationJobMonitor
              apiBaseUrl={`${API_BASE_URL}/file-organization`}
              autoRefresh={true}
              refreshInterval={5000}
              showRollback={true}
              onRollback={handleRollback}
            />
          </CardContent>
        </Card>

        <Card>
          <CardContent>
            <AuditLogViewer apiBaseUrl={`${API_BASE_URL}/file-organization`} autoRefresh={false} />
          </CardContent>
        </Card>
      </TabPanel>

      {/* Maintenance Tab */}
      <TabPanel value={tabValue} index={3}>
        <Card>
          <CardContent>
            <Typography variant="h6" gutterBottom>
              Log File Cleanup
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Clean up old job log files to free disk space. Log files older than the retention period will be deleted.
            </Typography>
            <Button
              variant="outlined"
              color="warning"
              startIcon={<CleanupIcon />}
              onClick={() => setCleanupLogsDialogOpen(true)}
            >
              Cleanup Old Logs
            </Button>
          </CardContent>
        </Card>
      </TabPanel>

      {/* Library Import Tab */}
      <TabPanel value={tabValue} index={4}>
        <LibraryImport />
      </TabPanel>

      {/* Organize Library Dialog */}
      <Dialog
        open={organizeDialogOpen}
        onClose={() => setOrganizeDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Organize Library Files</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Alert severity="info">
              This will organize all files in the selected library path based on MBID metadata.
              Files will be moved to Artist/Album structure with checksum validation.
            </Alert>
            <FormControlLabel
              control={<Switch checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />}
              label="Dry Run (Preview only)"
            />
            <FormControlLabel
              control={
                <Switch
                  checked={createMetadata}
                  onChange={(e) => setCreateMetadata(e.target.checked)}
                />
              }
              label="Create .mbid.json files (MANDATORY)"
            />
            <Divider />
            <FormControlLabel
              control={
                <Switch checked={onlyWithMbid} onChange={(e) => setOnlyWithMbid(e.target.checked)} />
              }
              label="Only files with MBIDs"
            />
            <FormControlLabel
              control={
                <Switch
                  checked={onlyUnorganized}
                  onChange={(e) => setOnlyUnorganized(e.target.checked)}
                />
              }
              label="Only unorganized files"
            />
            <Alert severity="warning" sx={{ mt: 1 }}>
              Job will fail if more than 5 file move operations fail.
            </Alert>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOrganizeDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleOrganizeLibrary}
            variant="contained"
            disabled={loading}
          >
            {loading ? <CircularProgress size={24} /> : dryRun ? 'Preview' : 'Organize'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Organize Artist Dialog */}
      <Dialog
        open={organizeArtistDialogOpen}
        onClose={() => setOrganizeArtistDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Organize Artist Files</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Alert severity="info">
              This will organize all files for the selected artist based on MBID metadata.
            </Alert>
            <FormControlLabel
              control={<Switch checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />}
              label="Dry Run (Preview only)"
            />
            <FormControlLabel
              control={
                <Switch
                  checked={createMetadata}
                  onChange={(e) => setCreateMetadata(e.target.checked)}
                />
              }
              label="Create .mbid.json files"
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOrganizeArtistDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleOrganizeArtist}
            variant="contained"
            disabled={loading}
          >
            {loading ? <CircularProgress size={24} /> : dryRun ? 'Preview' : 'Organize'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Validate Dialog */}
      <Dialog
        open={validateDialogOpen}
        onClose={() => setValidateDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Validate Library Structure</DialogTitle>
        <DialogContent>
          <Alert severity="info" sx={{ mt: 1 }}>
            This will validate the library structure and identify:
            <ul>
              <li>Misnamed files</li>
              <li>Misplaced files</li>
              <li>Incorrect directory names</li>
              <li>Files without MBIDs</li>
            </ul>
            If files without MBIDs are found, a Fetch Metadata job will be created in PAUSED state.
          </Alert>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setValidateDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleValidateLibrary}
            variant="contained"
            color="secondary"
            disabled={loading}
          >
            {loading ? <CircularProgress size={24} /> : 'Validate'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Fetch Metadata Dialog */}
      <Dialog
        open={fetchMetadataDialogOpen}
        onClose={() => setFetchMetadataDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Fetch Metadata from MusicBrainz</DialogTitle>
        <DialogContent>
          <Alert severity="info" sx={{ mt: 1 }}>
            This will:
            <ul>
              <li>Find files without MBIDs in the database</li>
              <li>Search MusicBrainz for matches based on artist/title</li>
              <li>Write MBIDs to the file Comment tags (CRITICAL)</li>
              <li>Update the database with found MBIDs</li>
            </ul>
          </Alert>
          <Alert severity="warning" sx={{ mt: 2 }}>
            This writes directly to your audio files. Changes are permanent.
          </Alert>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setFetchMetadataDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleFetchMetadata}
            variant="contained"
            disabled={loading}
          >
            {loading ? <CircularProgress size={24} /> : 'Start Fetch'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Validate MBID Dialog */}
      <Dialog
        open={validateMbidDialogOpen}
        onClose={() => setValidateMbidDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Validate MBIDs in Files</DialogTitle>
        <DialogContent>
          <Alert severity="info" sx={{ mt: 1 }}>
            This will:
            <ul>
              <li>Read the Comment tag from each audio file</li>
              <li>Check if Recording MBID is present</li>
              <li>Update the database mbid_in_file flag</li>
              <li>Track verification time</li>
            </ul>
          </Alert>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setValidateMbidDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleValidateMbid}
            variant="contained"
            disabled={loading}
          >
            {loading ? <CircularProgress size={24} /> : 'Start Validation'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Validate MBID Metadata Dialog */}
      <Dialog
        open={validateMbidMetadataDialogOpen}
        onClose={() => setValidateMbidMetadataDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Validate Metadata Against MusicBrainz</DialogTitle>
        <DialogContent>
          <Alert severity="info" sx={{ mt: 1 }}>
            This will compare file metadata with MusicBrainz data:
            <ul>
              <li>Read Recording MBID from the Comment tag</li>
              <li>Look up the recording on MusicBrainz</li>
              <li>Compare title, artist, album with MusicBrainz</li>
              <li>Calculate confidence score for each file</li>
              <li>Report files with low confidence for review</li>
            </ul>
          </Alert>
          <Alert severity="warning" sx={{ mt: 2 }}>
            <strong>Prerequisite:</strong> Run "Validate MBIDs" first to identify files with MBIDs.
          </Alert>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setValidateMbidMetadataDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleValidateMbidMetadata}
            variant="contained"
            disabled={loading}
          >
            {loading ? <CircularProgress size={24} /> : 'Start Metadata Validation'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Link Files Dialog */}
      <Dialog
        open={linkFilesDialogOpen}
        onClose={() => setLinkFilesDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Link Files to Album Tracks</DialogTitle>
        <DialogContent>
          <Alert severity="info" sx={{ mt: 1 }}>
            This will:
            <ul>
              <li>Find files with Recording MBIDs</li>
              <li>Match to existing album tracks by MBID</li>
              <li>Link files to tracks in the database</li>
              <li>Update track has_file status</li>
            </ul>
          </Alert>
          <FormControlLabel
            control={
              <Switch
                checked={autoImportArtists}
                onChange={(e) => setAutoImportArtists(e.target.checked)}
              />
            }
            label="Auto-import unlinked artists"
            sx={{ mt: 2 }}
          />
          {autoImportArtists && (
            <Alert severity="warning" sx={{ mt: 1 }}>
              Artists with unlinked files will be automatically added to the library (unmonitored) and their albums synced from MusicBrainz.
            </Alert>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setLinkFilesDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleLinkFiles}
            variant="contained"
            disabled={loading}
          >
            {loading ? <CircularProgress size={24} /> : 'Start Linking'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Import Unlinked Artists Dialog */}
      <Dialog
        open={importUnlinkedDialogOpen}
        onClose={() => setImportUnlinkedDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Import Unlinked Artists</DialogTitle>
        <DialogContent>
          <Alert severity="info" sx={{ mt: 1 }}>
            This will:
            <ul>
              <li>Find files with MBIDs that have no matching track in the library</li>
              <li>Extract unique artist MBIDs from those files</li>
              <li>Add new artists to the library (unmonitored)</li>
              <li>Sync albums and tracks from MusicBrainz</li>
            </ul>
          </Alert>
          <Alert severity="warning" sx={{ mt: 1 }}>
            After import completes, run "Link Files" again to link the files to the newly synced tracks.
          </Alert>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setImportUnlinkedDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleImportUnlinked}
            variant="contained"
            color="success"
            disabled={loading}
          >
            {loading ? <CircularProgress size={24} /> : 'Import Artists'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Resolve Unlinked Files Dialog */}
      <Dialog
        open={resolveUnlinkedDialogOpen}
        onClose={() => setResolveUnlinkedDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Auto-Resolve Unlinked Files</DialogTitle>
        <DialogContent>
          <Alert severity="info" sx={{ mt: 1 }}>
            This will run 5 phases to maximize file linking:
            <ol>
              <li><strong>Auto-Import Albums</strong> - Import missing release groups from MusicBrainz for files where the artist exists but the album doesn't</li>
              <li><strong>MBID Matching</strong> - Re-run direct Recording MBID matching (fast path + ambiguous resolution)</li>
              <li><strong>Release Group Fallback</strong> - Fuzzy match via local MusicBrainz DB for different Recording MBIDs of the same song</li>
              <li><strong>Fuzzy Matching</strong> - Match files without MBIDs by title + artist + duration</li>
              <li><strong>Re-categorize</strong> - Update unlinked files table with latest reasons</li>
            </ol>
          </Alert>
          <Alert severity="warning" sx={{ mt: 1 }}>
            This may take a while for large libraries. MusicBrainz API rate limits are respected (1 req/sec).
          </Alert>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setResolveUnlinkedDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleResolveUnlinked}
            variant="contained"
            color="secondary"
            disabled={loading}
          >
            {loading ? <CircularProgress size={24} /> : 'Start Resolving'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Reindex Albums Dialog */}
      <Dialog
        open={reindexDialogOpen}
        onClose={() => setReindexDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Reindex Albums from File Metadata</DialogTitle>
        <DialogContent>
          <Alert severity="info" sx={{ mt: 1 }}>
            This will:
            <ul>
              <li>Read Release MBIDs from file comments</li>
              <li>Group files by album</li>
              <li>Detect albums vs singles based on track count</li>
              <li>Update album information in database</li>
            </ul>
          </Alert>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setReindexDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleReindexAlbums}
            variant="contained"
            disabled={loading}
          >
            {loading ? <CircularProgress size={24} /> : 'Start Reindex'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Verify Audio Dialog */}
      <Dialog
        open={verifyAudioDialogOpen}
        onClose={() => setVerifyAudioDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Verify Audio Files</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Alert severity="info">
              Verify that downloaded files have their MBIDs correctly written to the Comment tag.
              This checks files that were downloaded within the specified time period.
            </Alert>
            <TextField
              label="Days Back"
              type="number"
              value={verifyDaysBack}
              onChange={(e) => setVerifyDaysBack(parseInt(e.target.value) || 90)}
              inputProps={{ min: 1, max: 365 }}
              fullWidth
              helperText="Check files downloaded within this many days"
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setVerifyAudioDialogOpen(false)}>Cancel</Button>
          <Button
            onClick={handleVerifyAudio}
            variant="contained"
            color="warning"
            disabled={loading}
          >
            {loading ? <CircularProgress size={24} /> : 'Start Verification'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Cleanup Logs Dialog */}
      <Dialog
        open={cleanupLogsDialogOpen}
        onClose={() => {
          setCleanupLogsDialogOpen(false)
          setCleanupPreview(null)
        }}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Cleanup Old Log Files</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Alert severity="warning">
              This will permanently delete job log files older than the specified retention period.
            </Alert>
            <TextField
              label="Retention Days"
              type="number"
              value={cleanupRetentionDays}
              onChange={(e) => setCleanupRetentionDays(parseInt(e.target.value) || 120)}
              inputProps={{ min: 1, max: 365 }}
              fullWidth
              helperText="Keep log files newer than this many days"
            />
            <Button
              variant="outlined"
              onClick={handlePreviewCleanup}
              disabled={loading}
            >
              {loading ? <CircularProgress size={24} /> : 'Preview Cleanup'}
            </Button>

            {cleanupPreview && (
              <Card variant="outlined" sx={{ p: 2 }}>
                <Typography variant="subtitle2" gutterBottom>
                  Cleanup Preview:
                </Typography>
                <Typography variant="body2">
                  Cutoff Date: {new Date(cleanupPreview.cutoff_date).toLocaleDateString()}
                </Typography>
                <Typography variant="body2">
                  Jobs with logs to clean: {cleanupPreview.jobs_with_logs_to_clean?.total || 0}
                </Typography>
                <Typography variant="body2">
                  Orphan log files: {cleanupPreview.orphan_log_files || 0}
                </Typography>
                <Typography variant="body2">
                  Estimated space freed: {cleanupPreview.estimated_orphan_size || 'N/A'}
                </Typography>
              </Card>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => {
            setCleanupLogsDialogOpen(false)
            setCleanupPreview(null)
          }}>Cancel</Button>
          <Button
            onClick={handleCleanupLogs}
            variant="contained"
            color="warning"
            disabled={loading}
          >
            {loading ? <CircularProgress size={24} /> : 'Run Cleanup'}
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
  )
}

export default FileManagement
