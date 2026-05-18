/* Shared layout for the full prototype — desktop sidebar + mobile shell.
   Routes are managed via a tiny hash router on window.location.hash. */

const useRoute = () => {
  const [route, setRoute] = React.useState(() => window.location.hash.slice(1) || "disco");
  React.useEffect(() => {
    const h = () => setRoute(window.location.hash.slice(1) || "disco");
    window.addEventListener("hashchange", h);
    return () => window.removeEventListener("hashchange", h);
  }, []);
  const nav = (id) => { window.location.hash = id; };
  return [route, nav];
};

const useViewport = () => {
  const [w, setW] = React.useState(() => window.innerWidth);
  React.useEffect(() => {
    const h = () => setW(window.innerWidth);
    window.addEventListener("resize", h);
    return () => window.removeEventListener("resize", h);
  }, []);
  return w < 820 ? "mobile" : "desktop";
};

const PageHeader = ({ group, title, subtitle, actions }) => (
  <div style={{ marginBottom: 24 }}>
    <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
      <div>
        <div style={{ fontSize: 11, color: T.muted, letterSpacing: 1.5, textTransform: "uppercase", marginBottom: 6 }}>{group} · {title}</div>
        <h1 style={{ fontSize: 32, fontWeight: 700, margin: 0, letterSpacing: -0.5 }}>{title}</h1>
        {subtitle && <div style={{ marginTop: 4, color: T.muted, fontSize: 14 }}>{subtitle}</div>}
      </div>
      {actions && <div style={{ display: "flex", gap: 8 }}>{actions}</div>}
    </div>
  </div>
);

const Btn = ({ primary, children, ...props }) => (
  <button {...props} style={{
    padding: "8px 14px",
    background: primary ? `linear-gradient(135deg, ${T.pink}, ${T.orange})` : "transparent",
    border: primary ? "none" : `1px solid ${T.border}`,
    color: primary ? "white" : T.text,
    borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: "pointer",
    boxShadow: primary ? "0 4px 16px rgba(255,20,147,0.35)" : "none",
    ...props.style,
  }}>{children}</button>
);

const Card = ({ children, style }) => (
  <div style={{ background: T.bg2, border: `1px solid ${T.border}`, borderRadius: 12, padding: 20, ...style }}>{children}</div>
);

const Sidebar = ({ active, nav, onSearch }) => (
  <aside style={{ width: 248, background: T.bg2, borderRight: `1px solid ${T.border}`, display: "flex", flexDirection: "column", height: "100%", flexShrink: 0 }}>
    <div style={{ padding: "20px 20px 16px", borderBottom: `1px solid ${T.border}`, display: "flex", alignItems: "center", gap: 12 }}>
      <div style={{ width: 44, height: 44, borderRadius: 10, background: "#000", display: "flex", alignItems: "center", justifyContent: "center", boxShadow: `0 0 20px rgba(255,20,147,0.45), inset 0 0 0 1px ${T.pinkBorder}` }}>
        <img src="images/logo.png" style={{ width: 38, height: 38, objectFit: "contain" }} />
      </div>
      <div>
        <div style={{ fontSize: 16, fontWeight: 700 }}>Studio<span style={{ color: T.pink }}>54</span></div>
        <div style={{ fontSize: 10, color: T.muted, letterSpacing: 1.5, textTransform: "uppercase" }}>Music · Books · Mix</div>
      </div>
    </div>

    <div style={{ padding: "12px 16px 8px" }}>
      <button onClick={onSearch} style={{ width: "100%", display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", borderRadius: 8, background: T.bg, border: `1px solid ${T.border}`, color: T.muted, fontSize: 12, cursor: "pointer", textAlign: "left" }}>
        <span style={{ fontSize: 14 }}>⌕</span>
        <span style={{ flex: 1 }}>Jump to anywhere…</span>
        <kbd style={{ fontSize: 10, background: T.bg3, padding: "2px 6px", borderRadius: 4, border: `1px solid ${T.border}`, fontFamily: "ui-monospace, monospace" }}>⌘K</kbd>
      </button>
    </div>

    <nav style={{ flex: 1, overflowY: "auto", padding: "4px 12px 16px" }}>
      {NAV_GROUPS.map((g) => (
        <div key={g.label} style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 10, letterSpacing: 2, textTransform: "uppercase", color: T.mutedDim, fontWeight: 700, padding: "8px 8px 6px" }}>{g.label}</div>
          {g.items.map((it) => {
            const isActive = active === it.id;
            return (
              <button key={it.id} onClick={() => nav(it.id)} style={{
                width: "100%", display: "flex", alignItems: "center", gap: 12,
                padding: "6px 8px", marginBottom: 2, borderRadius: 8,
                background: isActive ? T.pinkSoft : "transparent",
                border: "none", cursor: "pointer", textAlign: "left",
                color: isActive ? T.pink : T.text,
                transition: "background 0.15s",
              }}
                onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.background = T.bg3; }}
                onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.background = "transparent"; }}
              >
                <div style={{
                  width: 36, height: 36, borderRadius: 8, flexShrink: 0,
                  background: "#000",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  boxShadow: isActive ? `0 0 14px rgba(255,20,147,0.55), inset 0 0 0 1px ${T.pinkBorder}` : `inset 0 0 0 1px rgba(255,255,255,0.05)`,
                }}>
                  <img src={it.icon} alt="" style={{ width: 28, height: 28, objectFit: "contain", filter: isActive ? "none" : "saturate(0.85) brightness(0.92)" }} />
                </div>
                <span style={{ flex: 1, fontSize: 13, fontWeight: isActive ? 600 : 500 }}>{it.label}</span>
                {it.badge && <span style={{ background: T.pink, color: "white", fontSize: 10, fontWeight: 700, padding: "1px 6px", borderRadius: 10 }}>{it.badge}</span>}
                {it.role === "director" && <span style={{ fontSize: 9, color: T.orange, letterSpacing: 1, fontWeight: 700 }}>DIR</span>}
                {it.role === "dj" && <span style={{ fontSize: 9, color: T.pink, letterSpacing: 1, fontWeight: 700 }}>DJ</span>}
              </button>
            );
          })}
        </div>
      ))}
    </nav>

    <div style={{ padding: "10px 14px", borderTop: `1px solid ${T.border}`, display: "flex", alignItems: "center", gap: 10, background: T.bg }}>
      <img src={NOW_PLAYING.cover} style={{ width: 36, height: 36, borderRadius: 4, objectFit: "cover" }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{NOW_PLAYING.title}</div>
        <div style={{ fontSize: 10, color: T.muted, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{NOW_PLAYING.artist}</div>
      </div>
      <button style={{ width: 28, height: 28, borderRadius: "50%", background: T.pink, border: "none", color: "white", fontSize: 11, cursor: "pointer" }}>⏸</button>
    </div>

    <div style={{ padding: "10px 14px", borderTop: `1px solid ${T.border}`, display: "flex", alignItems: "center", gap: 10 }}>
      <div style={{ width: 32, height: 32, borderRadius: "50%", background: `linear-gradient(135deg, ${T.pink}, ${T.orange})`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 700, color: "#000" }}>JD</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>Jordan Diaz</div>
        <div style={{ display: "inline-block", fontSize: 9, fontWeight: 700, padding: "1px 6px", borderRadius: 4, background: "rgba(255,140,0,0.18)", color: T.orange, letterSpacing: 0.5 }}>CLUB DIRECTOR</div>
      </div>
    </div>
  </aside>
);

const MobileShell = ({ active, nav, children, onSearch }) => {
  const [drawer, setDrawer] = React.useState(false);
  const tabs = [
    { id: "disco", label: "Listen", icon: "images/disco-lounge.png" },
    { id: "albums", label: "Library", icon: "images/albums.png" },
    { id: "playlists", label: "Playlists", icon: "images/playlists.png" },
    { id: "requests", label: "Requests", icon: "images/dj-requests.png", badge: 4 },
  ];
  const activeItem = FLAT_ITEMS.find(i => i.id === active);
  const groupLabel = NAV_GROUPS.find(g => g.items.some(i => i.id === active))?.label || "";

  return (
    <div style={{ position: "fixed", inset: 0, background: T.bg, color: T.text, display: "flex", flexDirection: "column" }}>
      <div style={{ height: 56, background: T.bg2, borderBottom: `1px solid ${T.border}`, display: "flex", alignItems: "center", padding: "0 16px", gap: 12, flexShrink: 0 }}>
        <div style={{ width: 32, height: 32, borderRadius: 8, background: "#000", display: "flex", alignItems: "center", justifyContent: "center", boxShadow: `0 0 12px rgba(255,20,147,0.5), inset 0 0 0 1px ${T.pinkBorder}` }}>
          <img src="images/logo.png" style={{ width: 26, height: 26, objectFit: "contain" }} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 9, color: T.muted, letterSpacing: 1.5, textTransform: "uppercase" }}>{groupLabel}</div>
          <div style={{ fontWeight: 700, fontSize: 16 }}>{activeItem?.label || "Studio54"}</div>
        </div>
        <button onClick={onSearch} style={{ width: 36, height: 36, borderRadius: 18, background: T.bg, border: `1px solid ${T.border}`, color: T.muted, fontSize: 14 }}>⌕</button>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: 16, paddingBottom: 160 }}>
        {children}
      </div>

      <div style={{ position: "absolute", left: 12, right: 12, bottom: 84, height: 52, background: T.bg2, borderRadius: 10, border: `1px solid ${T.pinkBorder}`, display: "flex", alignItems: "center", padding: "0 10px", gap: 10, boxShadow: `0 4px 16px rgba(0,0,0,0.4), 0 0 16px rgba(255,20,147,0.15)` }}>
        <img src={NOW_PLAYING.cover} style={{ width: 36, height: 36, borderRadius: 4, objectFit: "cover" }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{NOW_PLAYING.title}</div>
          <div style={{ height: 2, background: T.bg3, borderRadius: 2, marginTop: 4 }}>
            <div style={{ width: "42%", height: "100%", background: T.pink, borderRadius: 2 }} />
          </div>
        </div>
        <button style={{ width: 32, height: 32, borderRadius: "50%", background: T.pink, border: "none", color: "white", fontSize: 12 }}>⏸</button>
      </div>

      <div style={{ height: 72, background: T.bg2, borderTop: `1px solid ${T.border}`, display: "flex", flexShrink: 0 }}>
        {tabs.map((t) => {
          const isActive = active === t.id;
          return (
            <button key={t.id} onClick={() => nav(t.id)} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 4, background: "transparent", border: "none", color: isActive ? T.pink : T.muted, position: "relative" }}>
              <div style={{ width: 32, height: 32, borderRadius: 8, background: isActive ? "#000" : "transparent", display: "flex", alignItems: "center", justifyContent: "center", boxShadow: isActive ? `0 0 10px rgba(255,20,147,0.5), inset 0 0 0 1px ${T.pinkBorder}` : "none", position: "relative" }}>
                <img src={t.icon} style={{ width: 26, height: 26, objectFit: "contain", filter: isActive ? "none" : "saturate(0.7) brightness(0.85)" }} />
                {t.badge && <div style={{ position: "absolute", top: -4, right: -4, minWidth: 16, height: 16, padding: "0 4px", borderRadius: 8, background: T.pink, color: "white", fontSize: 9, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>{t.badge}</div>}
              </div>
              <span style={{ fontSize: 10, fontWeight: 600 }}>{t.label}</span>
            </button>
          );
        })}
        <button onClick={() => setDrawer(true)} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 4, background: "transparent", border: "none", color: T.muted }}>
          <div style={{ width: 32, height: 32, display: "flex", flexDirection: "column", justifyContent: "center", gap: 4, alignItems: "center" }}>
            <div style={{ width: 18, height: 2, background: T.muted, borderRadius: 1 }} />
            <div style={{ width: 18, height: 2, background: T.muted, borderRadius: 1 }} />
            <div style={{ width: 18, height: 2, background: T.muted, borderRadius: 1 }} />
          </div>
          <span style={{ fontSize: 10, fontWeight: 600 }}>More</span>
        </button>
      </div>

      {drawer && (
        <div style={{ position: "absolute", inset: 0, background: T.bg2, zIndex: 50, display: "flex", flexDirection: "column" }}>
          <div style={{ padding: "16px 20px 12px", borderBottom: `1px solid ${T.border}`, display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ width: 44, height: 44, borderRadius: 10, background: "#000", display: "flex", alignItems: "center", justifyContent: "center", boxShadow: `0 0 16px rgba(255,20,147,0.5), inset 0 0 0 1px ${T.pinkBorder}` }}>
              <img src="images/logo.png" style={{ width: 38, height: 38, objectFit: "contain" }} />
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 16, fontWeight: 700 }}>Studio<span style={{ color: T.pink }}>54</span></div>
              <div style={{ fontSize: 10, color: T.muted, letterSpacing: 1.5, textTransform: "uppercase" }}>All sections</div>
            </div>
            <button onClick={() => setDrawer(false)} style={{ width: 32, height: 32, borderRadius: 16, background: T.bg, border: `1px solid ${T.border}`, color: T.muted, fontSize: 14 }}>✕</button>
          </div>
          <div style={{ flex: 1, overflowY: "auto", padding: "4px 12px 16px" }}>
            {NAV_GROUPS.map((g) => (
              <div key={g.label} style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 10, letterSpacing: 2, textTransform: "uppercase", color: T.mutedDim, fontWeight: 700, padding: "10px 8px 8px" }}>{g.label}</div>
                {g.items.map((it) => {
                  const isActive = it.id === active;
                  return (
                    <button key={it.id} onClick={() => { nav(it.id); setDrawer(false); }} style={{ width: "100%", display: "flex", alignItems: "center", gap: 14, padding: "10px 8px", borderRadius: 10, marginBottom: 2, background: isActive ? T.pinkSoft : "transparent", color: isActive ? T.pink : T.text, border: "none", textAlign: "left" }}>
                      <div style={{ width: 40, height: 40, borderRadius: 10, flexShrink: 0, background: "#000", display: "flex", alignItems: "center", justifyContent: "center", boxShadow: isActive ? `0 0 14px rgba(255,20,147,0.55), inset 0 0 0 1px ${T.pinkBorder}` : `inset 0 0 0 1px rgba(255,255,255,0.05)` }}>
                        <img src={it.icon} alt="" style={{ width: 32, height: 32, objectFit: "contain" }} />
                      </div>
                      <span style={{ flex: 1, fontSize: 15, fontWeight: isActive ? 600 : 500 }}>{it.label}</span>
                      {it.badge && <span style={{ background: T.pink, color: "white", fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 10 }}>{it.badge}</span>}
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

window.useRoute = useRoute;
window.useViewport = useViewport;
window.PageHeader = PageHeader;
window.Btn = Btn;
window.Card = Card;
window.Sidebar = Sidebar;
window.MobileShell = MobileShell;
