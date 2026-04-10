import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider, createTheme, CssBaseline } from '@mui/material'
import App from './App.tsx'
import './index.css'

// Create React Query client
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

// Create dark theme for MUI components — Studio54 palette
const darkTheme = createTheme({
  palette: {
    mode: 'dark',
    primary: {
      main: '#FF1493', // s54-pink
      light: '#ff4da6',
      dark: '#d10f7a',
    },
    secondary: {
      main: '#FF8C00', // s54-orange
      light: '#ffa333',
      dark: '#cc7000',
    },
    background: {
      default: '#0D1117', // s54-dark
      paper: '#161B22', // s54-surface
    },
    text: {
      primary: '#E6EDF3', // s54-text
      secondary: '#8B949E', // s54-text-muted
    },
    error: {
      main: '#ef4444',
    },
    warning: {
      main: '#f59e0b',
    },
    success: {
      main: '#22c55e',
    },
    info: {
      main: '#FF1493', // s54-pink
    },
    divider: '#30363D', // s54-border
  },
  components: {
    MuiCard: {
      styleOverrides: {
        root: {
          backgroundColor: '#161B22',
          borderColor: '#30363D',
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundColor: '#161B22',
        },
      },
    },
    MuiDialog: {
      styleOverrides: {
        paper: {
          backgroundColor: '#161B22',
        },
      },
    },
    MuiTextField: {
      styleOverrides: {
        root: {
          '& .MuiOutlinedInput-root': {
            '& fieldset': {
              borderColor: '#30363D',
            },
            '&:hover fieldset': {
              borderColor: '#484F58',
            },
          },
          '& .MuiInputLabel-root': {
            color: '#8B949E',
          },
          '& .MuiInputBase-input': {
            color: '#E6EDF3',
          },
        },
      },
    },
    MuiSelect: {
      styleOverrides: {
        root: {
          '& .MuiOutlinedInput-notchedOutline': {
            borderColor: '#30363D',
          },
          '&:hover .MuiOutlinedInput-notchedOutline': {
            borderColor: '#484F58',
          },
          '& .MuiSelect-icon': {
            color: '#8B949E',
          },
        },
      },
    },
    MuiMenuItem: {
      styleOverrides: {
        root: {
          '&:hover': {
            backgroundColor: '#1C2128',
          },
          '&.Mui-selected': {
            backgroundColor: '#1C2128',
            '&:hover': {
              backgroundColor: '#30363D',
            },
          },
        },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: {
          color: '#8B949E',
          '&.Mui-selected': {
            color: '#FF1493',
          },
        },
      },
    },
    MuiTabs: {
      styleOverrides: {
        indicator: {
          backgroundColor: '#FF1493',
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          '&.MuiChip-colorDefault': {
            backgroundColor: '#30363D',
            color: '#E6EDF3',
          },
        },
      },
    },
    MuiSwitch: {
      styleOverrides: {
        root: {
          '& .MuiSwitch-track': {
            backgroundColor: '#30363D',
          },
        },
      },
    },
    MuiSlider: {
      styleOverrides: {
        root: {
          '& .MuiSlider-markLabel': {
            color: '#8B949E',
          },
        },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        root: {
          borderColor: '#30363D',
        },
        head: {
          backgroundColor: '#0D1117',
          color: '#E6EDF3',
        },
      },
    },
    MuiTableRow: {
      styleOverrides: {
        root: {
          '&:hover': {
            backgroundColor: '#1C2128',
          },
        },
      },
    },
    MuiLinearProgress: {
      styleOverrides: {
        root: {
          backgroundColor: '#30363D',
        },
      },
    },
    MuiAlert: {
      styleOverrides: {
        root: {
          '&.MuiAlert-standardError': {
            backgroundColor: 'rgba(239, 68, 68, 0.1)',
            color: '#fca5a5',
          },
          '&.MuiAlert-standardSuccess': {
            backgroundColor: 'rgba(34, 197, 94, 0.1)',
            color: '#86efac',
          },
          '&.MuiAlert-standardWarning': {
            backgroundColor: 'rgba(245, 158, 11, 0.1)',
            color: '#fcd34d',
          },
          '&.MuiAlert-standardInfo': {
            backgroundColor: 'rgba(255, 20, 147, 0.1)',
            color: '#ff8cb8',
          },
        },
      },
    },
    MuiDivider: {
      styleOverrides: {
        root: {
          borderColor: '#30363D',
        },
      },
    },
    MuiInputLabel: {
      styleOverrides: {
        root: {
          color: '#8B949E',
          '&.Mui-focused': {
            color: '#FF1493',
          },
        },
      },
    },
    MuiFormControlLabel: {
      styleOverrides: {
        label: {
          color: '#8B949E',
        },
      },
    },
  },
  typography: {
    fontFamily: '"Inter", "Roboto", "Helvetica", "Arial", sans-serif',
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={darkTheme}>
        <CssBaseline />
        <App />
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
)
