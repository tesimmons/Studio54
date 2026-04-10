# Studio54 Web UI

React-based web interface for Studio54 Music Acquisition System

## Overview

Modern, responsive web UI for managing music acquisition with:
- Real-time updates via React Query
- Dark mode support
- Mobile-responsive design
- Type-safe API client

## Tech Stack

- **React 18.3** - UI framework
- **TypeScript** - Type safety
- **Vite** - Build tool and dev server
- **React Router 6** - Client-side routing
- **TanStack Query** - Data fetching and caching
- **TanStack Table** - Data tables
- **Tailwind CSS** - Utility-first styling
- **Axios** - HTTP client

## Features

### Pages

- **Dashboard** - System stats, active downloads, MUSE status
- **Artists** - Manage monitored artists
- **Albums** - Browse and search albums
- **Calendar** - Upcoming releases
- **Activity** - Download queue and history
- **Settings** - Configure indexers, SABnzbd, MUSE

### Components

- Responsive navigation sidebar
- Real-time stat cards
- Data tables with sorting/filtering
- Status badges
- Progress indicators
- Search and filter controls

## Development

```bash
# Install dependencies
npm install

# Start development server
npm run dev

# Access at http://localhost:5173
```

The development server proxies API requests to `http://studio54-service:8010`.

## Production Build

```bash
# Build for production
npm run build

# Preview production build
npm run preview
```

## Docker Deployment

The production container uses:
- **nginx 1.27-alpine** - Web server
- **Multi-stage build** - Optimized image size
- **Health checks** - Container monitoring
- **API proxying** - Seamless backend integration

```bash
# Via MasterControl CLI
./mastercontrol studio54 enable
./mastercontrol start

# Direct Docker build
docker build -t mastercontrol/studio54-web:latest .
```

## Configuration

Environment variables (`.env`):

```bash
# API URL (leave empty to use nginx proxy)
VITE_API_URL=/api/v1
```

For development:
```bash
VITE_API_URL=http://localhost:8010/api/v1
```

## nginx Configuration

The production container includes:
- API request proxying to backend
- WebSocket support (future)
- Static asset caching (1 year)
- Gzip compression
- Security headers
- SPA routing support

## API Integration

The `src/api/client.ts` provides a type-safe API client with modules:
- `artistsApi` - Artist management
- `albumsApi` - Album operations
- `indexersApi` - Indexer configuration
- `museApi` - MUSE integration
- `systemApi` - System stats and health

## Styling

Tailwind CSS with custom components:
- `.card` - Card container
- `.btn-*` - Button variants
- `.badge-*` - Status badges
- `.input` - Form inputs
- `.table` - Data tables

Dark mode supported via Tailwind's dark mode utility classes.

## Browser Support

- Chrome/Edge (latest)
- Firefox (latest)
- Safari (latest)

## License

Part of the MasterControl Suite
