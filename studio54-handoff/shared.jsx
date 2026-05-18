/* Shared mock data + atoms used by all artboards */

const NAV_GROUPS = [
  {
    label: "Listen",
    items: [
      { id: "disco", to: "/disco-lounge", icon: "images/disco-lounge.png", label: "Disco Lounge", sub: "Music library" },
      { id: "reading", to: "/reading-room", icon: "images/reading-room.png", label: "Reading Room", sub: "Audiobooks" },
      { id: "booth", to: "/sound-booth", icon: "images/sound-booth.png", label: "Sound Booth", sub: "Live mix" },
      { id: "listen", to: "/listen", icon: "images/listen.png", label: "Listen & Add", sub: "Discover new" },
    ],
  },
  {
    label: "Collection",
    items: [
      { id: "albums", to: "/albums", icon: "images/albums.png", label: "Albums" },
      { id: "playlists", to: "/playlists", icon: "images/playlists.png", label: "Playlists" },
      { id: "files", to: "/file-management", icon: "images/file-management.png", label: "File Mgmt", role: "dj" },
    ],
  },
  {
    label: "Activity",
    items: [
      { id: "dashboard", to: "/dashboard", icon: "images/dashboard.png", label: "Dashboard", role: "dj" },
      { id: "requests", to: "/dj-requests", icon: "images/dj-requests.png", label: "DJ Requests", badge: 4 },
      { id: "calendar", to: "/calendar", icon: "images/calendar.png", label: "Calendar" },
      { id: "activity", to: "/activity", icon: "images/activity.png", label: "Activity", role: "dj" },
    ],
  },
  {
    label: "System",
    items: [
      { id: "settings", to: "/settings", icon: "images/settings.png", label: "Settings", role: "director" },
      { id: "howto", to: "/how-to", icon: "images/how-to.png", label: "How To" },
    ],
  },
];

const FLAT_ITEMS = NAV_GROUPS.flatMap((g) => g.items);

// Mock "now playing" track for context
const NOW_PLAYING = {
  title: "Lost in Music",
  artist: "Sister Sledge",
  album: "We Are Family",
  cover: "images/playlist-cover.jpg",
  progress: 0.42,
};

// Brand tokens
const T = {
  pink: "#FF1493",
  pinkSoft: "rgba(255,20,147,0.14)",
  pinkBorder: "rgba(255,20,147,0.45)",
  orange: "#FF8C00",
  bg: "#0D1117",
  bg2: "#161B22",
  bg3: "#1C2128",
  border: "#30363D",
  text: "#E6EDF3",
  muted: "#8B949E",
  mutedDim: "#484F58",
};

window.NAV_GROUPS = NAV_GROUPS;
window.FLAT_ITEMS = FLAT_ITEMS;
window.NOW_PLAYING = NOW_PLAYING;
window.T = T;
