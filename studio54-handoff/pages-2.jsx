/* Pages 8-13: Activity group + System group */

const PageDashboard = () => (
  <div>
    <PageHeader group="Activity" title="Dashboard" subtitle="Real-time overview · DJ + Director view" actions={<Btn>Customize</Btn>} />
    <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 20 }}>
      {[
        { l: "Tracks today", v: "1,284", d: "+12%", c: T.pink },
        { l: "Active listeners", v: "47", d: "Live now", c: T.orange },
        { l: "Queue depth", v: "23", d: "Healthy", c: "#10B981" },
        { l: "Storage", v: "52%", d: "4.2/8 TB", c: T.muted },
      ].map((s, i) => (
        <Card key={i}>
          <div style={{ fontSize: 11, color: T.muted, letterSpacing: 1, textTransform: "uppercase", fontWeight: 700 }}>{s.l}</div>
          <div style={{ fontSize: 32, fontWeight: 700, color: s.c, marginTop: 8 }}>{s.v}</div>
          <div style={{ fontSize: 11, color: T.muted, marginTop: 2 }}>{s.d}</div>
        </Card>
      ))}
    </div>
    <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 20 }}>
      <Card>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 16 }}>Plays · last 7 days</div>
        <div style={{ display: "flex", alignItems: "flex-end", gap: 8, height: 180 }}>
          {[60, 80, 45, 95, 120, 140, 110].map((h, i) => (
            <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
              <div style={{ width: "100%", height: `${h}px`, background: `linear-gradient(180deg, ${T.pink}, ${T.orange})`, borderRadius: "4px 4px 0 0", boxShadow: `0 0 8px rgba(255,20,147,0.3)` }} />
              <div style={{ fontSize: 10, color: T.muted }}>{["M", "T", "W", "T", "F", "S", "S"][i]}</div>
            </div>
          ))}
        </div>
      </Card>
      <Card>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 12 }}>Top artists</div>
        {["Sister Sledge", "Donna Summer", "Chic", "Bee Gees", "KC and Sunshine"].map((a, i) => (
          <div key={a} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0" }}>
            <div style={{ width: 24, height: 24, borderRadius: 4, background: `linear-gradient(${i * 60}deg, ${T.pink}50, ${T.orange}30)`, fontSize: 11, fontWeight: 700, color: T.text, display: "flex", alignItems: "center", justifyContent: "center" }}>{i + 1}</div>
            <div style={{ flex: 1, fontSize: 12 }}>{a}</div>
            <div style={{ fontSize: 11, color: T.muted }}>{124 - i * 18}</div>
          </div>
        ))}
      </Card>
    </div>
  </div>
);

const PageRequests = () => (
  <div>
    <PageHeader group="Activity" title="DJ Requests" subtitle="4 pending · 28 played tonight" actions={<Btn primary>Open Mode</Btn>} />
    <TabBar tabs={["Pending (4)", "Played", "Declined", "All time"]} active="Pending (4)" />
    <div style={{ display: "grid", gap: 10 }}>
      {[
        { t: "Lost in Music", a: "Sister Sledge", by: "Sarah", time: "2 min ago", tip: "$5" },
        { t: "I Will Survive", a: "Gloria Gaynor", by: "Mike", time: "8 min ago", tip: "$10" },
        { t: "Le Freak", a: "Chic", by: "Anonymous", time: "14 min ago" },
        { t: "Dancing Queen", a: "ABBA", by: "Jenna", time: "22 min ago", tip: "$3" },
      ].map((r, i) => (
        <Card key={i} style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <div style={{ width: 48, height: 48, borderRadius: 6, background: `linear-gradient(${i * 50}deg, #2a1a3a, #1a2a3a)`, flexShrink: 0 }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 600 }}>{r.t}</div>
            <div style={{ fontSize: 12, color: T.muted }}>{r.a}</div>
            <div style={{ fontSize: 11, color: T.mutedDim, marginTop: 2 }}>{r.by} · {r.time}{r.tip ? ` · tipped ${r.tip}` : ""}</div>
          </div>
          {r.tip && <div style={{ background: "rgba(255,140,0,0.18)", color: T.orange, padding: "4px 10px", borderRadius: 12, fontSize: 11, fontWeight: 700 }}>{r.tip}</div>}
          <div style={{ display: "flex", gap: 6 }}>
            <button style={{ width: 36, height: 36, borderRadius: 18, background: "transparent", border: `1px solid ${T.border}`, color: T.muted, fontSize: 14 }}>✕</button>
            <button style={{ width: 36, height: 36, borderRadius: 18, background: T.pink, border: "none", color: "white", fontSize: 14, boxShadow: `0 0 12px ${T.pink}` }}>▶</button>
          </div>
        </Card>
      ))}
    </div>
  </div>
);

const PageCalendar = () => (
  <div>
    <PageHeader group="Activity" title="Calendar" subtitle="Upcoming sets · scheduled scans · releases" actions={<><Btn>Today</Btn><Btn primary>+ Event</Btn></>} />
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
      <div style={{ fontSize: 18, fontWeight: 700 }}>April 2026</div>
      <div style={{ display: "flex", gap: 6 }}>
        <button style={{ width: 32, height: 32, borderRadius: 16, background: "transparent", border: `1px solid ${T.border}`, color: T.text }}>‹</button>
        <button style={{ width: 32, height: 32, borderRadius: 16, background: "transparent", border: `1px solid ${T.border}`, color: T.text }}>›</button>
      </div>
    </div>
    <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 4 }}>
      {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map(d => <div key={d} style={{ padding: "8px 4px", fontSize: 11, color: T.muted, textAlign: "center", fontWeight: 600 }}>{d}</div>)}
      {Array.from({ length: 35 }).map((_, i) => {
        const day = i - 2;
        const events = day === 25 ? ["Friday Disco"] : day === 27 ? ["Library scan"] : day === 30 ? ["DJ Marco set", "Release: Chic"] : [];
        const isToday = day === 25;
        return (
          <div key={i} style={{ minHeight: 80, padding: 6, background: T.bg2, border: `1px solid ${isToday ? T.pinkBorder : T.border}`, borderRadius: 6, opacity: day < 1 || day > 30 ? 0.3 : 1, boxShadow: isToday ? `0 0 16px rgba(255,20,147,0.2)` : "none" }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: isToday ? T.pink : T.text }}>{day > 0 && day <= 30 ? day : ""}</div>
            {events.map((e, ei) => (
              <div key={ei} style={{ marginTop: 4, padding: "2px 4px", background: ei === 0 ? T.pinkSoft : "rgba(255,140,0,0.15)", color: ei === 0 ? T.pink : T.orange, fontSize: 9, borderRadius: 3, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{e}</div>
            ))}
          </div>
        );
      })}
    </div>
  </div>
);

const PageActivity = () => (
  <div>
    <PageHeader group="Activity" title="Activity" subtitle="Downloads · imports · scans · errors" actions={<><Btn>Filter</Btn><Btn primary>Clear Done</Btn></>} />
    <TabBar tabs={["All", "Downloads", "Imports", "Scans", "Errors (2)"]} active="All" />
    <Card style={{ padding: 0 }}>
      {[
        { st: "✓", c: "#10B981", t: "Sync complete", d: "Sister Sledge — 4 albums updated", time: "2 min ago" },
        { st: "↓", c: T.pink, t: "Downloading", d: "Donna Summer · I Feel Love (1977) · 47%", time: "5 min ago", prog: 47 },
        { st: "✓", c: "#10B981", t: "Auto-import", d: "/incoming/chic-risque.flac → Library", time: "12 min ago" },
        { st: "!", c: "#EF4444", t: "Indexer error", d: "Prowlarr returned 503 — retry queued", time: "18 min ago" },
        { st: "↓", c: T.pink, t: "Downloaded", d: "KC and the Sunshine Band · 12 tracks", time: "1h ago" },
        { st: "✓", c: "#10B981", t: "Scan complete", d: "Synology mount · 18,492 files indexed", time: "2h ago" },
      ].map((row, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 14, padding: "14px 20px", borderBottom: i < 5 ? `1px solid ${T.border}` : "none" }}>
          <div style={{ width: 28, height: 28, borderRadius: "50%", background: `${row.c}25`, color: row.c, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 700, flexShrink: 0 }}>{row.st}</div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13, fontWeight: 600 }}>{row.t}</div>
            <div style={{ fontSize: 12, color: T.muted }}>{row.d}</div>
            {row.prog != null && (
              <div style={{ height: 3, background: T.bg3, borderRadius: 2, marginTop: 6, maxWidth: 280 }}>
                <div style={{ width: `${row.prog}%`, height: "100%", background: T.pink, borderRadius: 2 }} />
              </div>
            )}
          </div>
          <div style={{ fontSize: 11, color: T.mutedDim }}>{row.time}</div>
        </div>
      ))}
    </Card>
  </div>
);

const PageSettings = () => {
  const [tab, setTab] = React.useState("General");
  return (
    <div>
      <PageHeader group="System" title="Settings" subtitle="Director-only configuration" actions={<Btn primary>Save Changes</Btn>} />
      <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", gap: 24 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {["General", "Indexers", "Download Clients", "Quality Profiles", "Storage Mounts", "API Keys", "Workers", "Scheduler", "Users & Roles"].map(s => (
            <button key={s} onClick={() => setTab(s)} style={{ padding: "8px 12px", borderRadius: 6, background: tab === s ? T.pinkSoft : "transparent", color: tab === s ? T.pink : T.text, border: "none", textAlign: "left", fontSize: 13, cursor: "pointer", fontWeight: tab === s ? 600 : 500 }}>{s}</button>
          ))}
        </div>
        <Card>
          <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 4 }}>{tab}</div>
          <div style={{ fontSize: 12, color: T.muted, marginBottom: 20 }}>Configure {tab.toLowerCase()} for your Studio54 instance.</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
            {[
              { l: "Instance name", v: "Studio54 — The Loft" },
              { l: "Default audio quality", v: "FLAC (preferred) · MP3 320 (fallback)" },
              { l: "Library root", v: "/mnt/synology/music" },
              { l: "Theme", v: "Neon (dark)" },
            ].map(f => (
              <div key={f.l}>
                <div style={{ fontSize: 11, color: T.muted, fontWeight: 600, marginBottom: 6, letterSpacing: 0.5, textTransform: "uppercase" }}>{f.l}</div>
                <input defaultValue={f.v} style={{ width: "100%", padding: "10px 12px", background: T.bg, border: `1px solid ${T.border}`, borderRadius: 8, color: T.text, fontSize: 13 }} />
              </div>
            ))}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 0", borderTop: `1px solid ${T.border}` }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600 }}>Auto-sync on schedule</div>
                <div style={{ fontSize: 11, color: T.muted, marginTop: 2 }}>Every 6h · MusicBrainz + iTunes</div>
              </div>
              <div style={{ width: 44, height: 24, borderRadius: 12, background: T.pink, position: "relative", boxShadow: `0 0 8px ${T.pink}` }}>
                <div style={{ position: "absolute", top: 2, right: 2, width: 20, height: 20, borderRadius: "50%", background: "white" }} />
              </div>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
};

const PageHowTo = () => (
  <div>
    <PageHeader group="System" title="How To" subtitle="Guides, shortcuts, troubleshooting" />
    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
      {[
        { i: "images/disco-lounge.png", t: "Add your first artist", d: "Search MusicBrainz, monitor an artist, sync their discography." },
        { i: "images/playlists.png", t: "Build a smart playlist", d: "Combine BPM, key, and genre filters. Auto-update as library grows." },
        { i: "images/sound-booth.png", t: "Run a live set", d: "Cue tracks across two decks, beatmatch, record the mix." },
        { i: "images/dj-requests.png", t: "Take requests from the floor", d: "Open Request Mode — partygoers scan a QR code to request songs." },
        { i: "images/file-management.png", t: "Fix unlinked files", d: "AcoustID + manual matching to repair broken metadata." },
        { i: "images/settings.png", t: "Set up indexers", d: "Connect Prowlarr or your own indexer for automatic discovery." },
      ].map((g, i) => (
        <Card key={i} style={{ cursor: "pointer", display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ width: 56, height: 56, borderRadius: 12, background: "#000", display: "flex", alignItems: "center", justifyContent: "center", boxShadow: `0 0 16px rgba(255,20,147,0.35), inset 0 0 0 1px ${T.pinkBorder}` }}>
            <img src={g.i} style={{ width: 44, height: 44, objectFit: "contain" }} />
          </div>
          <div style={{ fontSize: 14, fontWeight: 700 }}>{g.t}</div>
          <div style={{ fontSize: 12, color: T.muted, lineHeight: 1.5 }}>{g.d}</div>
          <div style={{ marginTop: "auto", fontSize: 11, color: T.pink, fontWeight: 600 }}>Read guide →</div>
        </Card>
      ))}
    </div>
  </div>
);

window.PageDashboard = PageDashboard;
window.PageRequests = PageRequests;
window.PageCalendar = PageCalendar;
window.PageActivity = PageActivity;
window.PageSettings = PageSettings;
window.PageHowTo = PageHowTo;
