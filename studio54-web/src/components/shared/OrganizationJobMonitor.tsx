/**
 * Organization Job Monitor Component
 * Shared component for monitoring file organization jobs
 * Can be used by both MUSE and Studio54
 */

import React, { useState, useEffect } from 'react'
import { authFetch } from '../../api/client'
import {
  Box,
  Card,
  CardContent,
  Typography,
  LinearProgress,
  Chip,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  IconButton,
  Tooltip,
  Alert,
  Stack,
  Button,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
} from '@mui/material'
import {
  Refresh as RefreshIcon,
  CheckCircle as CompletedIcon,
  Error as ErrorIcon,
  HourglassEmpty as PendingIcon,
  PlayArrow as RunningIcon,
  Undo as UndoIcon,
  Info as InfoIcon,
} from '@mui/icons-material'

// Types
export interface OrganizationJob {
  id: string
  job_type: string
  status: string
  progress_percent: number
  current_action?: string
  files_total: number
  files_processed: number
  files_renamed: number
  files_moved: number
  files_failed: number
  started_at?: string
  completed_at?: string
  error_message?: string
}

export interface OrganizationJobMonitorProps {
  apiBaseUrl: string
  autoRefresh?: boolean
  refreshInterval?: number
  showRollback?: boolean
  onRollback?: (jobId: string) => Promise<void>
}

export const OrganizationJobMonitor: React.FC<OrganizationJobMonitorProps> = ({
  apiBaseUrl,
  autoRefresh = true,
  refreshInterval = 5000,
  showRollback = true,
  onRollback,
}) => {
  const [jobs, setJobs] = useState<OrganizationJob[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [rollbackDialogOpen, setRollbackDialogOpen] = useState(false)
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)

  // Load jobs
  const loadJobs = async () => {
    try {
      const response = await authFetch(`${apiBaseUrl}/jobs?limit=50`)
      if (!response.ok) {
        throw new Error('Failed to load jobs')
      }
      const data = await response.json()
      setJobs(Array.isArray(data) ? data : [])
      setError(null)
    } catch (err: any) {
      console.error('Failed to load organization jobs:', err)
      setError(err.message || 'Failed to load jobs')
    } finally {
      setLoading(false)
    }
  }

  // Load on mount
  useEffect(() => {
    loadJobs()
  }, [])

  // Auto-refresh
  useEffect(() => {
    if (!autoRefresh) return

    const interval = setInterval(() => {
      loadJobs()
    }, refreshInterval)

    return () => clearInterval(interval)
  }, [autoRefresh, refreshInterval])

  // Status badge
  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'completed':
        return <Chip icon={<CompletedIcon />} label="Completed" color="success" size="small" />
      case 'failed':
        return <Chip icon={<ErrorIcon />} label="Failed" color="error" size="small" />
      case 'running':
        return <Chip icon={<RunningIcon />} label="Running" color="primary" size="small" />
      case 'pending':
        return <Chip icon={<PendingIcon />} label="Pending" color="default" size="small" />
      case 'rolled_back':
        return <Chip icon={<UndoIcon />} label="Rolled Back" color="warning" size="small" />
      default:
        return <Chip label={status} size="small" />
    }
  }

  // Job type label
  const getJobTypeLabel = (jobType: string) => {
    switch (jobType) {
      case 'organize_library':
        return 'Library Organization'
      case 'organize_artist':
        return 'Artist Organization'
      case 'organize_album':
        return 'Album Organization'
      case 'validate_structure':
        return 'Structure Validation'
      case 'rollback':
        return 'Rollback'
      default:
        return jobType
    }
  }

  // Format date
  const formatDate = (dateString?: string) => {
    if (!dateString) return '-'
    return new Date(dateString).toLocaleString()
  }

  // Handle rollback
  const handleRollbackClick = (jobId: string) => {
    setSelectedJobId(jobId)
    setRollbackDialogOpen(true)
  }

  const handleRollbackConfirm = async () => {
    if (!selectedJobId || !onRollback) return

    try {
      await onRollback(selectedJobId)
      setRollbackDialogOpen(false)
      setSelectedJobId(null)
      loadJobs()
    } catch (err: any) {
      console.error('Rollback failed:', err)
      setError(err.message || 'Rollback failed')
    }
  }

  if (loading && jobs.length === 0) {
    return (
      <Box sx={{ p: 3, textAlign: 'center' }}>
        <Typography>Loading jobs...</Typography>
      </Box>
    )
  }

  return (
    <Box>
      {/* Header */}
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
        <Typography variant="h6">Organization Jobs</Typography>
        <IconButton onClick={loadJobs} size="small">
          <RefreshIcon />
        </IconButton>
      </Stack>

      {/* Error alert */}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Jobs table */}
      {jobs.length === 0 ? (
        <Card>
          <CardContent>
            <Typography color="text.secondary" align="center">
              No organization jobs found
            </Typography>
          </CardContent>
        </Card>
      ) : (
        <TableContainer component={Paper}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Type</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Progress</TableCell>
                <TableCell align="right">Files</TableCell>
                <TableCell align="right">Renamed</TableCell>
                <TableCell align="right">Moved</TableCell>
                <TableCell align="right">Failed</TableCell>
                <TableCell>Started</TableCell>
                <TableCell>Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {jobs.map((job) => (
                <TableRow key={job.id}>
                  <TableCell>
                    <Typography variant="body2">{getJobTypeLabel(job.job_type)}</Typography>
                    {job.current_action && job.status === 'running' && (
                      <Typography variant="caption" color="text.secondary">
                        {job.current_action}
                      </Typography>
                    )}
                  </TableCell>
                  <TableCell>{getStatusBadge(job.status)}</TableCell>
                  <TableCell>
                    <Box sx={{ minWidth: 120 }}>
                      <LinearProgress
                        variant="determinate"
                        value={job.progress_percent}
                        sx={{ mb: 0.5 }}
                      />
                      <Typography variant="caption">{job.progress_percent.toFixed(1)}%</Typography>
                    </Box>
                  </TableCell>
                  <TableCell align="right">
                    {job.files_processed}/{job.files_total}
                  </TableCell>
                  <TableCell align="right">{job.files_renamed}</TableCell>
                  <TableCell align="right">{job.files_moved}</TableCell>
                  <TableCell align="right">
                    {job.files_failed > 0 ? (
                      <Typography color="error">{job.files_failed}</Typography>
                    ) : (
                      job.files_failed
                    )}
                  </TableCell>
                  <TableCell>
                    <Typography variant="caption">{formatDate(job.started_at)}</Typography>
                  </TableCell>
                  <TableCell>
                    <Stack direction="row" spacing={1}>
                      {job.error_message && (
                        <Tooltip title={job.error_message}>
                          <IconButton size="small" color="error">
                            <InfoIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      )}
                      {showRollback && job.status === 'completed' && (
                        <Tooltip title="Rollback this job">
                          <IconButton
                            size="small"
                            color="warning"
                            onClick={() => handleRollbackClick(job.id)}
                          >
                            <UndoIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      )}
                    </Stack>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* Rollback confirmation dialog */}
      <Dialog open={rollbackDialogOpen} onClose={() => setRollbackDialogOpen(false)}>
        <DialogTitle>Confirm Rollback</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Are you sure you want to rollback this organization job? This will reverse all file
            operations performed by this job.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRollbackDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleRollbackConfirm} color="warning" variant="contained">
            Rollback
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
