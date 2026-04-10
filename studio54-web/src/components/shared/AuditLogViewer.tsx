/**
 * Audit Log Viewer Component
 * Shared component for viewing file operation audit logs
 * Can be used by both MUSE and Studio54
 */

import React, { useState, useEffect } from 'react'
import { authFetch } from '../../api/client'
import {
  Box,
  Card,
  CardContent,
  Typography,
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
  Chip,
  TextField,
  MenuItem,
  Grid,
  Pagination,
} from '@mui/material'
import {
  Refresh as RefreshIcon,
  CheckCircle as SuccessIcon,
  Error as ErrorIcon,
  DriveFileMove as MoveIcon,
  Edit as RenameIcon,
  Delete as DeleteIcon,
  Undo as UndoIcon,
} from '@mui/icons-material'

// Types
export interface AuditLogEntry {
  id: string
  operation_type: string
  source_path: string
  destination_path?: string
  artist_id?: string
  album_id?: string
  recording_mbid?: string
  success: boolean
  error_message?: string
  rollback_possible: boolean
  performed_at: string
}

export interface AuditLogResponse {
  entries: AuditLogEntry[]
  total: number
  limit: number
  offset: number
}

export interface AuditLogViewerProps {
  apiBaseUrl: string
  autoRefresh?: boolean
  refreshInterval?: number
}

export const AuditLogViewer: React.FC<AuditLogViewerProps> = ({
  apiBaseUrl,
  autoRefresh = false,
  refreshInterval = 10000,
}) => {
  const [entries, setEntries] = useState<AuditLogEntry[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Filters
  const [operationType, setOperationType] = useState<string>('all')
  const [page, setPage] = useState(1)
  const [limit] = useState(50)

  // Load audit log
  const loadAuditLog = async () => {
    try {
      const params = new URLSearchParams({
        limit: limit.toString(),
        offset: ((page - 1) * limit).toString(),
      })

      if (operationType !== 'all') {
        params.append('operation_type', operationType)
      }

      const response = await authFetch(`${apiBaseUrl}/audit/operations?${params}`)
      if (!response.ok) {
        throw new Error('Failed to load audit log')
      }

      const data: AuditLogResponse = await response.json()
      setEntries(data.entries)
      setTotal(data.total)
      setError(null)
    } catch (err: any) {
      console.error('Failed to load audit log:', err)
      setError(err.message || 'Failed to load audit log')
    } finally {
      setLoading(false)
    }
  }

  // Load on mount
  useEffect(() => {
    loadAuditLog()
  }, [])

  // Reload when filters change
  useEffect(() => {
    loadAuditLog()
  }, [operationType, page])

  // Auto-refresh
  useEffect(() => {
    if (!autoRefresh) return

    const interval = setInterval(() => {
      loadAuditLog()
    }, refreshInterval)

    return () => clearInterval(interval)
  }, [autoRefresh, refreshInterval, operationType, page])

  // Operation type icon
  const getOperationIcon = (type: string) => {
    switch (type) {
      case 'move':
        return <MoveIcon fontSize="small" />
      case 'rename':
        return <RenameIcon fontSize="small" />
      case 'delete':
        return <DeleteIcon fontSize="small" />
      default:
        return null
    }
  }

  // Operation type badge
  const getOperationBadge = (type: string) => {
    const colors: Record<string, 'primary' | 'secondary' | 'error' | 'warning'> = {
      move: 'primary',
      rename: 'secondary',
      delete: 'error',
    }

    const icon = getOperationIcon(type)

    return (
      <Chip
        {...(icon ? { icon } : {})}
        label={type.toUpperCase()}
        color={colors[type] || 'default'}
        size="small"
      />
    )
  }

  // Format date
  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleString()
  }

  // Truncate path
  const truncatePath = (path: string, maxLength: number = 50) => {
    if (path.length <= maxLength) return path
    return '...' + path.slice(-(maxLength - 3))
  }

  if (loading && entries.length === 0) {
    return (
      <Box sx={{ p: 3, textAlign: 'center' }}>
        <Typography>Loading audit log...</Typography>
      </Box>
    )
  }

  const totalPages = Math.ceil(total / limit)

  return (
    <Box>
      {/* Header */}
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
        <Typography variant="h6">File Operation Audit Log</Typography>
        <Stack direction="row" spacing={1} alignItems="center">
          <Typography variant="body2" color="text.secondary">
            {total} total operations
          </Typography>
          <IconButton onClick={loadAuditLog} size="small">
            <RefreshIcon />
          </IconButton>
        </Stack>
      </Stack>

      {/* Filters */}
      <Card sx={{ mb: 2 }}>
        <CardContent>
          <Grid container spacing={2}>
            <Grid item xs={12} sm={6} md={3}>
              <TextField
                select
                fullWidth
                label="Operation Type"
                value={operationType}
                onChange={(e) => setOperationType(e.target.value)}
                size="small"
              >
                <MenuItem value="all">All Operations</MenuItem>
                <MenuItem value="move">Move</MenuItem>
                <MenuItem value="rename">Rename</MenuItem>
                <MenuItem value="delete">Delete</MenuItem>
              </TextField>
            </Grid>
          </Grid>
        </CardContent>
      </Card>

      {/* Error alert */}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Audit log table */}
      {entries.length === 0 ? (
        <Card>
          <CardContent>
            <Typography color="text.secondary" align="center">
              No audit log entries found
            </Typography>
          </CardContent>
        </Card>
      ) : (
        <>
          <TableContainer component={Paper}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Operation</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Source Path</TableCell>
                  <TableCell>Destination Path</TableCell>
                  <TableCell>Timestamp</TableCell>
                  <TableCell>Rollback</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {entries.map((entry) => (
                  <TableRow key={entry.id} sx={{ '&:hover': { bgcolor: 'action.hover' } }}>
                    <TableCell>{getOperationBadge(entry.operation_type)}</TableCell>
                    <TableCell>
                      {entry.success ? (
                        <Tooltip title="Operation succeeded">
                          <SuccessIcon color="success" fontSize="small" />
                        </Tooltip>
                      ) : (
                        <Tooltip title={entry.error_message || 'Operation failed'}>
                          <ErrorIcon color="error" fontSize="small" />
                        </Tooltip>
                      )}
                    </TableCell>
                    <TableCell>
                      <Tooltip title={entry.source_path}>
                        <Typography variant="body2" noWrap sx={{ maxWidth: 300 }}>
                          {truncatePath(entry.source_path)}
                        </Typography>
                      </Tooltip>
                    </TableCell>
                    <TableCell>
                      {entry.destination_path ? (
                        <Tooltip title={entry.destination_path}>
                          <Typography variant="body2" noWrap sx={{ maxWidth: 300 }}>
                            {truncatePath(entry.destination_path)}
                          </Typography>
                        </Tooltip>
                      ) : (
                        <Typography variant="body2" color="text.secondary">
                          -
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell>
                      <Typography variant="caption">{formatDate(entry.performed_at)}</Typography>
                    </TableCell>
                    <TableCell>
                      {entry.rollback_possible ? (
                        <Chip
                          icon={<UndoIcon fontSize="small" />}
                          label="Possible"
                          color="success"
                          size="small"
                          variant="outlined"
                        />
                      ) : (
                        <Typography variant="caption" color="text.secondary">
                          Not possible
                        </Typography>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>

          {/* Pagination */}
          {totalPages > 1 && (
            <Box sx={{ mt: 2, display: 'flex', justifyContent: 'center' }}>
              <Pagination
                count={totalPages}
                page={page}
                onChange={(_, value) => setPage(value)}
                color="primary"
              />
            </Box>
          )}
        </>
      )}
    </Box>
  )
}
