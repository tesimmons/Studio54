/* Pages 1-7: Listen group + Collection group */

const Tile = ({ i, label, sub, ratio = "1" }) => (
  <div>
    <div style={{ aspectRatio: ratio, background: `linear-gradient(${120 + i * 18}deg, #2a1a3a, #1a2a3a)`, borderRadius: 8, position: "relative", overflow: "hidden", cursor: "pointer" }}>
      <div style={{ position: "absolute", inset: 0, background: "repeating-linear-gradient(45deg, transparent 0 6px, rgba(255,255,255,0.02) 6px 12px)" }} />
      <div style={{ position: "absolute", bottom: 6, left: 8, fontSize: 9, color: T.mutedDim, fontFamily: "ui-monospace, monospace" }}>cover.{i}</div>
    </div>
    <div style={{ marginTop: 6, fontSize: 12, fontWeight: 600 }}>{label}</div>
    {sub && <div style={{ fontSize: 11, color: T.muted }}>{sub}</div>}
  </div>
);

const TabBar = ({ tabs, active, onChange }) => (
  <div style={{ display: "flex", gap: 24, borderBottom: `1px solid ${T.border}`, marginBottom: 20 }}>
    {tabs.map((t) => (
      <button key={t} onClick={() => onChange?.(t)} style={{ padding: "10px 0", fontSize: 13, fontWeight: 600, color: active === t ? T.pink : T.muted, borderBottom: active === t ? `2px solid ${T.pink}` : "2px solid transparent", background: "transparent", border: "none", cursor: "pointer" }}>{t}</button>
    ))}
  </div>
);

const PageDisco = () => {
  const [tab, setTab] = React.useState("Browse");
  return (
    <div>
      <PageHeader group="Listen" title="Disco Lounge" subtitle="1,247 albums · 18,492 tracks · 64 artists monitored" actions={<><Btn>Add Artist</Btn><Btn primary>Sync All</Btn></>} />
      <TabBar tabs={["Browse", "Scanner", "Import", "Unlinked", "Unorganized"]} active={tab} onChange={setTab} />
      <div style={{ display: "flex", gap: 12, marginBottom: 16 }}>
        <input placeholder="Search artists or albums…" style={{ flex: 1, padding: "8px 12px", background: T.bg2, border: `1px solid ${T.border}`, borderRadius: 8, color: T.text, fontSize: 13 }} />
        <select style={{ padding: "8px 12px", background: T.bg2, border: `1px solid ${T.border}`, borderRadius: 8, color: T.text, fontSize: 13 }}>
          <option>All artists</option><option>Monitored</option><option>Unmonitored</option>
        </select>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 16 }}>
        {Array.from({ length: 18 }).map((_, i) => <Tile key={i} i={i} label={`Album ${i + 1}`} sub="Artist Name" />)}
      </div>
    </div>
  );
};

const PageReading = () => (
  <div>
    <PageHeader group="Listen" title="Reading Room" subtitle="184 books · 32 series · 14 in progress" actions={<><Btn>Add Book</Btn><Btn primary>Import</Btn></>} />
    <TabBar tabs={["All", "In Progress", "Series", "Authors", "Wishlist"]} active="In Progress" />
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 18 }}>
      {Array.from({ length: 8 }).map((_, i) => (
        <Card key={i} style={{ padding: 0, overflow: "hidden" }}>
          <div style={{ aspectRatio: "2/3", background: `linear-gradient(${135 + i * 24}deg, #3a1a2a, #1a1a3a)`, position: "relative" }}>
            <div style={{ position: "absolute", inset: 0, background: "repeating-linear-gradient(0deg, transparent 0 14px, rgba(255,255,255,0.03) 14px 16px)" }} />
            <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, padding: 8 }}>
              <div style={{ height: 3, background: "rgba(0,0,0,0.5)", borderRadius: 2 }}>
                <div style={{ width: `${20 + i * 8}%`, height: "100%", background: T.pink, borderRadius: 2 }} />
              </div>
            </div>
          </div>
          <div style={{ padding: 12 }}>
            <div style={{ fontSize: 13, fontWeight: 600 }}>Book Title {i + 1}</div>
            <div style={{ fontSize: 11, color: T.muted, marginTop: 2 }}>Author Name · {3 + i}h left</div>
          </div>
        </Card>
      ))}
    </div>
  </div>
);

const PageBooth = () => (
  <div>
    <PageHeader group="Listen" title="Sound Booth" subtitle="Live mix engineering" actions={<Btn primary>Start Set</Btn>} />
    <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 20 }}>
      <Card style={{ padding: 0, overflow: "hidden" }}>
        <div style={{ padding: 20, borderBottom: `1px solid ${T.border}`, display: "flex", alignItems: "center", gap: 16 }}>
          <img src={NOW_PLAYING.cover} style={{ width: 96, height: 96, borderRadius: 8, objectFit: "cover", boxShadow: "0 8px 24px rgba(0,0,0,0.5)" }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 10, color: T.pink, letterSpacing: 2, fontWeight: 700 }}>DECK A — PLAYING</div>
            <div style={{ fontSize: 22, fontWeight: 700 }}>{NOW_PLAYING.title}</div>
            <div style={{ fontSize: 13, color: T.muted }}>{NOW_PLAYING.artist} · 124 BPM · Am</div>
          </div>
        </div>
        <div style={{ padding: 20 }}>
          <div style={{ height: 80, background: T.bg, borderRadius: 8, position: "relative", overflow: "hidden", marginBottom: 16 }}>
            {Array.from({ length: 80 }).map((_, i) => {
              const h = 20 + Math.abs(Math.sin(i * 0.4) * 50) + Math.random() * 20;
              return <div key={i} style={{ position: "absolute", left: `${i * 1.25}%`, bottom: "50%", width: "1%", height: `${h / 2}%`, background: i < 32 ? T.pink : T.mutedDim, transform: "translateY(50%)" }} />;
            })}
            <div style={{ position: "absolute", top: 0, bottom: 0, left: "40%", width: 2, background: T.orange, boxShadow: `0 0 6px ${T.orange}` }} />
          </div>
          <div style={{ display: "flex", justifyContent: "center", gap: 12 }}>
            {["⏮", "⏪", "⏸", "⏩", "⏭"].map((c, i) => (
              <button key={i} style={{ width: i === 2 ? 56 : 44, height: i === 2 ? 56 : 44, borderRadius: "50%", background: i === 2 ? T.pink : T.bg, border: i === 2 ? "none" : `1px solid ${T.border}`, color: i === 2 ? "white" : T.text, fontSize: i === 2 ? 18 : 14, cursor: "pointer", boxShadow: i === 2 ? `0 0 20px ${T.pink}` : "none" }}>{c}</button>
            ))}
          </div>
        </div>
      </Card>
      <Card>
        <div style={{ fontSize: 11, color: T.mutedDim, letterSpacing: 2, fontWeight: 700, marginBottom: 12 }}>UP NEXT</div>
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 0", borderBottom: i < 5 ? `1px solid ${T.border}` : "none" }}>
            <div style={{ width: 36, height: 36, borderRadius: 4, background: `linear-gradient(${i * 60}deg, #2a1a3a, #1a2a3a)`, flexShrink: 0 }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>Track Name {i + 1}</div>
              <div style={{ fontSize: 11, color: T.muted }}>Artist · {120 + i * 2} BPM</div>
            </div>
          </div>
        ))}
      </Card>
    </div>
  </div>
);

const PageListen = () => (
  <div>
    <PageHeader group="Listen" title="Listen & Add" subtitle="Discover new music · 30s previews from iTunes" />
    <div style={{ display: "flex", gap: 12, marginBottom: 24 }}>
      <input placeholder="Search artists, albums, tracks…" style={{ flex: 1, padding: "12px 16px", background: T.bg2, border: `1px solid ${T.pinkBorder}`, borderRadius: 10, color: T.text, fontSize: 14, boxShadow: `0 0 16px rgba(255,20,147,0.1)` }} />
      <Btn primary>Search</Btn>
    </div>
    <div style={{ marginBottom: 12, fontSize: 12, color: T.muted, letterSpacing: 1.5, textTransform: "uppercase", fontWeight: 700 }}>RESULTS · 24 ALBUMS</div>
    <div style={{ display: "grid", gap: 8 }}>
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 14, padding: 12, background: T.bg2, border: `1px solid ${T.border}`, borderRadius: 10 }}>
          <div style={{ width: 56, height: 56, borderRadius: 6, background: `linear-gradient(${i * 50}deg, #3a1a2a, #1a2a3a)`, flexShrink: 0 }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 600 }}>Discovery Album {i + 1}</div>
            <div style={{ fontSize: 12, color: T.muted }}>Artist Name · {2018 + i} · 12 tracks</div>
          </div>
          <button style={{ width: 36, height: 36, borderRadius: 18, background: T.bg, border: `1px solid ${T.border}`, color: T.pink, fontSize: 14 }}>▶</button>
          <Btn>+ Add to Library</Btn>
        </div>
      ))}
    </div>
  </div>
);

const PageAlbums = () => (
  <div>
    <PageHeader group="Collection" title="Albums" subtitle="1,247 in library · 89 monitored · 14 missing files" actions={<><Btn>Filter</Btn><Btn primary>+ Add Album</Btn></>} />
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 18 }}>
      {Array.from({ length: 24 }).map((_, i) => <Tile key={i} i={i} label={`Album ${i + 1}`} sub="Artist Name" />)}
    </div>
  </div>
);

const PagePlaylists = () => (
  <div>
    <PageHeader group="Collection" title="Playlists" subtitle="42 playlists · 6 collaborative" actions={<Btn primary>+ New Playlist</Btn>} />
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 18 }}>
      {[
        { l: "Friday Night Disco", c: 84, by: "Jordan", img: true },
        { l: "Slow Burn", c: 32, by: "DJ Marco" },
        { l: "Audiobook Wishlist", c: 12, by: "Jordan" },
        { l: "BPM 120-128", c: 156, by: "Auto" },
        { l: "Dance Floor Heat", c: 67, by: "DJ Marco" },
        { l: "Late Night Lounge", c: 41, by: "Jordan" },
        { l: "Vocal House", c: 88, by: "Auto" },
        { l: "Encore Set", c: 24, by: "DJ Marco" },
      ].map((p, i) => (
        <Card key={i} style={{ padding: 0, overflow: "hidden", cursor: "pointer" }}>
          <div style={{ aspectRatio: "1", background: p.img ? `url(images/playlist-cover.jpg) center/cover` : `linear-gradient(${135 + i * 40}deg, ${T.pink}30, ${T.orange}30, #1a1a3a)`, position: "relative" }}>
            <div style={{ position: "absolute", inset: 0, background: "linear-gradient(180deg, transparent 50%, rgba(0,0,0,0.7))" }} />
            <div style={{ position: "absolute", bottom: 8, right: 8, width: 40, height: 40, borderRadius: "50%", background: T.pink, display: "flex", alignItems: "center", justifyContent: "center", color: "white", fontSize: 14, boxShadow: `0 0 16px ${T.pink}` }}>▶</div>
          </div>
          <div style={{ padding: 12 }}>
            <div style={{ fontSize: 14, fontWeight: 600 }}>{p.l}</div>
            <div style={{ fontSize: 11, color: T.muted, marginTop: 2 }}>{p.c} tracks · {p.by}</div>
          </div>
        </Card>
      ))}
    </div>
  </div>
);

const PageFiles = () => {
  const [tab, setTab] = React.useState("Storage");
  return (
    <div>
      <PageHeader group="Collection" title="File Management" subtitle="DJ tools — organize, scan, repair" actions={<><Btn>Scan Now</Btn><Btn primary>Reorganize</Btn></>} />
      <TabBar tabs={["Storage", "Unlinked (124)", "Unorganized (38)", "Quality Profiles", "Naming"]} active={tab} onChange={setTab} />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 24 }}>
        {[
          { l: "Total storage", v: "4.2 TB", s: "/ 8 TB · Synology NAS" },
          { l: "Audio files", v: "18,492", s: "FLAC · MP3 · M4A" },
          { l: "Last scan", v: "2h ago", s: "All clean" },
        ].map((s, i) => (
          <Card key={i}>
            <div style={{ fontSize: 11, color: T.muted, letterSpacing: 1, textTransform: "uppercase", fontWeight: 700, marginBottom: 8 }}>{s.l}</div>
            <div style={{ fontSize: 28, fontWeight: 700, color: T.pink }}>{s.v}</div>
            <div style={{ fontSize: 11, color: T.muted, marginTop: 4 }}>{s.s}</div>
          </Card>
        ))}
      </div>
      <Card>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 12 }}>Storage mounts</div>
        {["/mnt/synology/music", "/mnt/synology/audiobooks", "/mnt/local/incoming"].map((m, i) => (
          <div key={m} style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 0", borderTop: i > 0 ? `1px solid ${T.border}` : "none" }}>
            <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#10B981", boxShadow: "0 0 6px #10B981" }} />
            <div style={{ flex: 1, fontFamily: "ui-monospace, monospace", fontSize: 12 }}>{m}</div>
            <div style={{ fontSize: 11, color: T.muted }}>{["3.1 TB", "1.0 TB", "120 GB"][i]}</div>
          </div>
        ))}
      </Card>
    </div>
  );
};

window.PageDisco = PageDisco;
window.PageReading = PageReading;
window.PageBooth = PageBooth;
window.PageListen = PageListen;
window.PageAlbums = PageAlbums;
window.PagePlaylists = PagePlaylists;
window.PageFiles = PageFiles;
