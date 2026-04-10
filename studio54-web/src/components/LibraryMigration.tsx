/**
 * Library Migration Component
 * Migrate files between libraries with MBID validation and metadata correction
 */

import React, { useState, useEffect } from 'react'
import {
  Box,
  Card,
  CardContent,
  CardHeader,
  Typography,
  Button,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  TextField,
  Slider,
  FormControlLabel,
  Switch,
  Alert,
  LinearProgress,
  Divider,
  Grid,
  Chip,
  Stack,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Tabs,
  Tab,
  CircularProgress,
} from '@mui/material'
import {
  SwapHoriz as MigrateIcon,
  FolderOpen as FolderIcon,
  Add as AddIcon,
  Refresh as RefreshIcon,
  CheckCircle as SuccessIcon,
  Error as ErrorIcon,
  Warning as WarningIcon,
  PlayArrow as StartIcon,
} from '@mui/icons-material'
import { fileOrganizationApi } from '../api/client'
import FileBrowser from './FileBrowser'

interface LibraryPath {
  id: string
  name: string
  path: string
}

interface MigrationJob {
  id: string
  status: string
  progress_percent: number
  current_action: string | null
  files_total: number
  files_processed: number
  files_with_mbid: number
  files_mbid_fetched: number
  files_metadata_corrected: number
  files_validated: number
  files_moved: number
  files_failed: number
  followup_job_id: string | null
}

interface Props {
  libraryPaths: LibraryPath[]
  onJobStarted?: () => void
}

interface TabPanelProps {
  children?: React.ReactNode
  index: number
  value: number
}

function TabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props
  return (
    <div role="tabpanel" hidden={value !== index} {...other}>
      {value === index && <Box sx={{ py: 2 }}>{children}</Box>}
    </div>
  )
}

export const LibraryMigration: React.FC<Props> = ({ libraryPaths, onJobStarted }) => {
  // Form state
  const [sourceLibraryId, setSourceLibraryId] = useState('')
  const [destinationType, setDestinationType] = useState<'existing' | 'new'>('existing')
  const [destinationLibraryId, setDestinationLibraryId] = useState('')
  const [newLibraryName, setNewLibraryName] = useState('')
  const [newLibraryPath, setNewLibraryPath] = useState('')
  const [minConfidence, setMinConfidence] = useState(80)
  const [correctMetadata, setCorrectMetadata] = useState(true)
  const [createMetadataFiles, setCreateMetadataFiles] = useState(true)

  // UI state
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [showFileBrowser, setShowFileBrowser] = useState(false)
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [jobStatus, setJobStatus] = useState<MigrationJob | null>(null)
  const [logsTabValue, setLogsTabValue] = useState(0)
  const [successLog, setSuccessLog] = useState<any[]>([])
  const [failedLog, setFailedLog] = useState<any[]>([])
  const [skippedLog, setSkippedLog] = useState<any[]>([])
  const [summary, setSummary] = useState<any>(null)

  // Filter out source library from destination options
  const availableDestinations = libraryPaths.filter(lp => lp.id !== sourceLibraryId)

  // Poll job status
  useEffect(() => {
    let interval: ReturnType<typeof setInterval> | null = null

    if (activeJobId) {
      const pollStatus = async () => {
        try {
          const status = await fileOrganizationApi.getMigrationStatus(activeJobId)
          setJobStatus(status)

          // If job completed, load logs
          if (status.status === 'completed' || status.status === 'failed') {
            loadLogs(activeJobId)
            if (interval) {
              clearInterval(interval)
            }
          }
        } catch (err) {
          console.error('Failed to get job status:', err)
        }
      }

      pollStatus()
      interval = setInterval(pollStatus, 3000)
    }

    return () => {
      if (interval) {
        clearInterval(interval)
      }
    }
  }, [activeJobId])

  const loadLogs = async (jobId: string) => {
    try {
      const [successData, failedData, skippedData, summaryData] = await Promise.all([
        fileOrganizationApi.getMigrationSuccessLog(jobId),
        fileOrganizationApi.getMigrationFailedLog(jobId),
        fileOrganizationApi.getMigrationSkippedLog(jobId),
        fileOrganizationApi.getMigrationSummary(jobId),
      ])
      setSuccessLog(successData.files || [])
      setFailedLog(failedData.files || [])
      setSkippedLog(skippedData.files || [])
      setSummary(summaryData)
    } catch (err) {
      console.error('Failed to load logs:', err)
    }
  }

  const handleStartMigration = async () => {
    // Validation
    if (!sourceLibraryId) {
      setError('Please select a source library')
      return
    }

    if (destinationType === 'existing' && !destinationLibraryId) {
      setError('Please select a destination library')
      return
    }

    if (destinationType === 'new' && (!newLibraryName || !newLibraryPath)) {
      setError('Please enter both name and path for the new library')
      return
    }

    setLoading(true)
    setError(null)
    setSuccess(null)

    try {
      const params: any = {
        source_library_id: sourceLibraryId,
        min_confidence: minConfidence,
        correct_metadata: correctMetadata,
        create_metadata_files: createMetadataFiles,
      }

      if (destinationType === 'existing') {
        params.destination_library_id = destinationLibraryId
      } else {
        params.new_library_name = newLibraryName
        params.new_library_path = newLibraryPath
      }

      const result = await fileOrganizationApi.startMigration(params)
      setSuccess(result.message)
      setActiveJobId(result.job_id)
      onJobStarted?.()
    } catch (err: any) {
      console.error('Failed to start migration:', err)
      setError(err.response?.data?.detail || err.message || 'Failed to start migration')
    } finally {
      setLoading(false)
    }
  }

  const handlePathSelected = (path: string) => {
    setNewLibraryPath(path)
    setShowFileBrowser(false)
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed':
        return 'success'
      case 'failed':
        return 'error'
      case 'running':
        return 'primary'
      default:
        return 'default'
    }
  }

  return (
    <Card>
      <CardHeader
        title={
          <Box display="flex" alignItems="center" gap={1}>
            <MigrateIcon />
            <Typography variant="h6">Library Migration</Typography>
          </Box>
        }
        subheader="Migrate files between libraries with MBID validation and metadata correction"
      />
      <CardContent>
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

        {/* Source Library Selection */}
        <FormControl fullWidth sx={{ mb: 3 }}>
          <InputLabel>Source Library</InputLabel>
          <Select
            value={sourceLibraryId}
            label="Source Library"
            onChange={(e) => setSourceLibraryId(e.target.value)}
            disabled={loading || !!activeJobId}
          >
            {libraryPaths.map((lp) => (
              <MenuItem key={lp.id} value={lp.id}>
                {lp.name} ({lp.path})
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        {/* Destination Options */}
        <Box sx={{ mb: 3 }}>
          <Typography variant="subtitle2" gutterBottom>
            Destination Library
          </Typography>
          <Stack direction="row" spacing={2} sx={{ mb: 2 }}>
            <Button
              variant={destinationType === 'existing' ? 'contained' : 'outlined'}
              onClick={() => setDestinationType('existing')}
              disabled={loading || !!activeJobId}
            >
              Use Existing Library
            </Button>
            <Button
              variant={destinationType === 'new' ? 'contained' : 'outlined'}
              onClick={() => setDestinationType('new')}
              startIcon={<AddIcon />}
              disabled={loading || !!activeJobId}
            >
              Create New Library
            </Button>
          </Stack>

          {destinationType === 'existing' ? (
            <FormControl fullWidth>
              <InputLabel>Destination Library</InputLabel>
              <Select
                value={destinationLibraryId}
                label="Destination Library"
                onChange={(e) => setDestinationLibraryId(e.target.value)}
                disabled={loading || !!activeJobId || availableDestinations.length === 0}
              >
                {availableDestinations.map((lp) => (
                  <MenuItem key={lp.id} value={lp.id}>
                    {lp.name} ({lp.path})
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          ) : (
            <Grid container spacing={2}>
              <Grid item xs={12} md={6}>
                <TextField
                  fullWidth
                  label="New Library Name"
                  value={newLibraryName}
                  onChange={(e) => setNewLibraryName(e.target.value)}
                  disabled={loading || !!activeJobId}
                />
              </Grid>
              <Grid item xs={12} md={6}>
                <Box display="flex" gap={1}>
                  <TextField
                    fullWidth
                    label="Library Path"
                    value={newLibraryPath}
                    onChange={(e) => setNewLibraryPath(e.target.value)}
                    disabled={loading || !!activeJobId}
                  />
                  <Button
                    variant="outlined"
                    onClick={() => setShowFileBrowser(true)}
                    disabled={loading || !!activeJobId}
                  >
                    <FolderIcon />
                  </Button>
                </Box>
              </Grid>
            </Grid>
          )}
        </Box>

        <Divider sx={{ my: 3 }} />

        {/* Migration Options */}
        <Typography variant="subtitle2" gutterBottom>
          Migration Options
        </Typography>

        <Box sx={{ mb: 3 }}>
          <Typography gutterBottom>
            Minimum Confidence Threshold: {minConfidence}%
          </Typography>
          <Slider
            value={minConfidence}
            onChange={(_, value) => setMinConfidence(value as number)}
            min={50}
            max={100}
            step={5}
            marks={[
              { value: 50, label: '50%' },
              { value: 70, label: '70%' },
              { value: 80, label: '80%' },
              { value: 90, label: '90%' },
              { value: 100, label: '100%' },
            ]}
            disabled={loading || !!activeJobId}
          />
          <Typography variant="caption" color="text.secondary">
            Files below this confidence will be sent to Ponder for fingerprint identification
          </Typography>
        </Box>

        <Stack direction="row" spacing={3}>
          <FormControlLabel
            control={
              <Switch
                checked={correctMetadata}
                onChange={(e) => setCorrectMetadata(e.target.checked)}
                disabled={loading || !!activeJobId}
              />
            }
            label="Correct metadata to match MusicBrainz"
          />
          <FormControlLabel
            control={
              <Switch
                checked={createMetadataFiles}
                onChange={(e) => setCreateMetadataFiles(e.target.checked)}
                disabled={loading || !!activeJobId}
              />
            }
            label="Create .mbid.json files in album directories"
          />
        </Stack>

        <Divider sx={{ my: 3 }} />

        {/* Start Button */}
        {!activeJobId && (
          <Button
            variant="contained"
            color="primary"
            size="large"
            startIcon={loading ? <CircularProgress size={20} /> : <StartIcon />}
            onClick={handleStartMigration}
            disabled={loading || !sourceLibraryId}
            fullWidth
          >
            {loading ? 'Starting Migration...' : 'Start Migration'}
          </Button>
        )}

        {/* Job Progress */}
        {activeJobId && jobStatus && (
          <Box sx={{ mt: 3 }}>
            <Box display="flex" justifyContent="space-between" alignItems="center" mb={1}>
              <Typography variant="subtitle2">
                Migration Progress
              </Typography>
              <Chip
                label={jobStatus.status.toUpperCase()}
                color={getStatusColor(jobStatus.status) as any}
                size="small"
              />
            </Box>

            <LinearProgress
              variant="determinate"
              value={jobStatus.progress_percent}
              sx={{ mb: 1, height: 10, borderRadius: 5 }}
            />

            <Typography variant="body2" color="text.secondary" gutterBottom>
              {jobStatus.current_action || `Processing files...`}
            </Typography>

            <Grid container spacing={2} sx={{ mt: 1 }}>
              <Grid item xs={6} sm={3}>
                <Typography variant="caption" color="text.secondary">Total Files</Typography>
                <Typography variant="h6">{jobStatus.files_total}</Typography>
              </Grid>
              <Grid item xs={6} sm={3}>
                <Typography variant="caption" color="text.secondary">Processed</Typography>
                <Typography variant="h6">{jobStatus.files_processed}</Typography>
              </Grid>
              <Grid item xs={6} sm={3}>
                <Typography variant="caption" color="text.secondary">Migrated</Typography>
                <Typography variant="h6" color="success.main">{jobStatus.files_moved}</Typography>
              </Grid>
              <Grid item xs={6} sm={3}>
                <Typography variant="caption" color="text.secondary">Failed</Typography>
                <Typography variant="h6" color="error.main">{jobStatus.files_failed}</Typography>
              </Grid>
            </Grid>

            <Grid container spacing={2} sx={{ mt: 1 }}>
              <Grid item xs={6} sm={3}>
                <Typography variant="caption" color="text.secondary">Had MBID</Typography>
                <Typography>{jobStatus.files_with_mbid}</Typography>
              </Grid>
              <Grid item xs={6} sm={3}>
                <Typography variant="caption" color="text.secondary">MBID Fetched</Typography>
                <Typography>{jobStatus.files_mbid_fetched}</Typography>
              </Grid>
              <Grid item xs={6} sm={3}>
                <Typography variant="caption" color="text.secondary">Metadata Corrected</Typography>
                <Typography>{jobStatus.files_metadata_corrected}</Typography>
              </Grid>
              <Grid item xs={6} sm={3}>
                <Typography variant="caption" color="text.secondary">Validated</Typography>
                <Typography>{jobStatus.files_validated}</Typography>
              </Grid>
            </Grid>

            {jobStatus.followup_job_id && (
              <Alert severity="info" sx={{ mt: 2 }}>
                Ponder fingerprint job created for unmatched files: {jobStatus.followup_job_id}
              </Alert>
            )}
          </Box>
        )}

        {/* Results Summary */}
        {summary && (jobStatus?.status === 'completed' || jobStatus?.status === 'failed') && (
          <Box sx={{ mt: 3 }}>
            <Divider sx={{ mb: 2 }} />
            <Typography variant="subtitle2" gutterBottom>
              Migration Results
            </Typography>

            <Grid container spacing={2}>
              <Grid item xs={6} sm={2.4}>
                <Card variant="outlined">
                  <CardContent sx={{ textAlign: 'center', py: 1 }}>
                    <SuccessIcon color="success" />
                    <Typography variant="h5">{summary.success_count}</Typography>
                    <Typography variant="caption">Success</Typography>
                  </CardContent>
                </Card>
              </Grid>
              <Grid item xs={6} sm={2.4}>
                <Card variant="outlined">
                  <CardContent sx={{ textAlign: 'center', py: 1 }}>
                    <ErrorIcon color="error" />
                    <Typography variant="h5">{summary.failed_count}</Typography>
                    <Typography variant="caption">Failed</Typography>
                  </CardContent>
                </Card>
              </Grid>
              <Grid item xs={6} sm={2.4}>
                <Card variant="outlined">
                  <CardContent sx={{ textAlign: 'center', py: 1 }}>
                    <WarningIcon color="warning" />
                    <Typography variant="h5">{summary.skipped_count}</Typography>
                    <Typography variant="caption">Skipped</Typography>
                  </CardContent>
                </Card>
              </Grid>
              <Grid item xs={6} sm={2.4}>
                <Card variant="outlined">
                  <CardContent sx={{ textAlign: 'center', py: 1 }}>
                    <RefreshIcon color="info" />
                    <Typography variant="h5">{summary.ponder_count}</Typography>
                    <Typography variant="caption">Ponder Queue</Typography>
                  </CardContent>
                </Card>
              </Grid>
              <Grid item xs={12} sm={2.4}>
                <Card variant="outlined">
                  <CardContent sx={{ textAlign: 'center', py: 1 }}>
                    <Typography variant="h5">{summary.total_files}</Typography>
                    <Typography variant="caption">Total Files</Typography>
                  </CardContent>
                </Card>
              </Grid>
            </Grid>

            {/* Logs Tabs */}
            <Box sx={{ mt: 3 }}>
              <Tabs value={logsTabValue} onChange={(_, v) => setLogsTabValue(v)}>
                <Tab label={`Success (${successLog.length})`} />
                <Tab label={`Failed (${failedLog.length})`} />
                <Tab label={`Skipped (${skippedLog.length})`} />
              </Tabs>

              <TabPanel value={logsTabValue} index={0}>
                <TableContainer component={Paper} sx={{ maxHeight: 300 }}>
                  <Table size="small" stickyHeader>
                    <TableHead>
                      <TableRow>
                        <TableCell>Source Path</TableCell>
                        <TableCell>Destination Path</TableCell>
                        <TableCell>Confidence</TableCell>
                        <TableCell>Validation Tag</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {successLog.slice(0, 100).map((item, idx) => (
                        <TableRow key={idx}>
                          <TableCell sx={{ fontSize: '0.75rem' }}>{item.source_path}</TableCell>
                          <TableCell sx={{ fontSize: '0.75rem' }}>{item.destination_path}</TableCell>
                          <TableCell>{item.confidence_score}%</TableCell>
                          <TableCell>
                            <Chip label={item.validation_tag} size="small" color="success" />
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </TabPanel>

              <TabPanel value={logsTabValue} index={1}>
                <TableContainer component={Paper} sx={{ maxHeight: 300 }}>
                  <Table size="small" stickyHeader>
                    <TableHead>
                      <TableRow>
                        <TableCell>File Path</TableCell>
                        <TableCell>Operation</TableCell>
                        <TableCell>Error</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {failedLog.slice(0, 100).map((item, idx) => (
                        <TableRow key={idx}>
                          <TableCell sx={{ fontSize: '0.75rem' }}>{item.file_path}</TableCell>
                          <TableCell>{item.operation}</TableCell>
                          <TableCell sx={{ fontSize: '0.75rem', color: 'error.main' }}>
                            {item.error}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </TabPanel>

              <TabPanel value={logsTabValue} index={2}>
                <TableContainer component={Paper} sx={{ maxHeight: 300 }}>
                  <Table size="small" stickyHeader>
                    <TableHead>
                      <TableRow>
                        <TableCell>File Path</TableCell>
                        <TableCell>Reason</TableCell>
                        <TableCell>Ponder Eligible</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {skippedLog.slice(0, 100).map((item, idx) => (
                        <TableRow key={idx}>
                          <TableCell sx={{ fontSize: '0.75rem' }}>{item.file_path}</TableCell>
                          <TableCell>{item.reason}</TableCell>
                          <TableCell>
                            {item.ponder_eligible ? (
                              <Chip label="Yes" size="small" color="info" />
                            ) : (
                              <Chip label="No" size="small" />
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </TabPanel>
            </Box>

            {/* New Migration Button */}
            <Button
              variant="outlined"
              onClick={() => {
                setActiveJobId(null)
                setJobStatus(null)
                setSummary(null)
                setSuccessLog([])
                setFailedLog([])
                setSkippedLog([])
              }}
              sx={{ mt: 2 }}
            >
              Start New Migration
            </Button>
          </Box>
        )}

        {/* File Browser Dialog */}
        <Dialog open={showFileBrowser} onClose={() => setShowFileBrowser(false)} maxWidth="md" fullWidth>
          <DialogTitle>Select Library Path</DialogTitle>
          <DialogContent>
            <FileBrowser onSelect={handlePathSelected} initialPath="/" />
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setShowFileBrowser(false)}>Cancel</Button>
          </DialogActions>
        </Dialog>
      </CardContent>
    </Card>
  )
}

export default LibraryMigration
