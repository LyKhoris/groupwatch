# AGENTS.md — groupwatch

> This file is the project bible. It exists to give any agent (or human) full context to work on
> this repo effectively. Keep it updated whenever a decision, convention, or structure changes.

---

## 1. Project overview

**groupwatch** (all lowercase, everywhere: repo, package, binary) is a Windows + Linux desktop app
that lets a private group of friends watch video files together over the internet, in perfect sync,
with near-zero ongoing effort.

It combines two upstream projects:

- **[Syncthing](https://github.com/syncthing/syncthing.git)** — keeps a dedicated folder of video
  files automatically synchronized across every group member's machine (peer-to-peer).
- **[Syncplay](https://github.com/Syncplay/syncplay.git)** — synchronizes playback (play, pause,
  seek) of the group's media players over a client/server protocol.

Neither project is ever visible to the end user. groupwatch wraps, configures, and drives both
behind its own UI. The design goal is **"set it and forget it"**: after a one-time setup, using the
app on movie night is indistinguishable from opening a video player.

### The "seamless" spec (canonical walkthroughs)

**Leader's first run (the group organizer):**
1. Downloads and installs groupwatch (Windows `.exe` installer wizard or Linux AppImage).
2. First-run wizard asks: "Create a group or join one?" → **Create**.
3. Picks the folder that holds the videos. Done. groupwatch silently configures Syncthing and the
   embedded Syncplay server behind the scenes.
4. Clicks "Invite a friend" → gets an invite code/file to send over Discord/text.

**Friend's first run (non-technical person — the most important user):**
1. Downloads and installs groupwatch the same way.
2. First-run wizard → **Join a group** → pastes the invite code.
3. Picks where the synced folder should live. Done. Everything else — device approval, folder
   sharing, server address, room — is automatic.

**A movie night, every time after that:**
1. The leader drops new episodes into their folder days or minutes ahead; Syncthing distributes
   them to everyone in the background, no router configuration required.
2. Everyone opens groupwatch (it's already running in the tray from autostart).
3. Anyone picks an episode from the library list.
4. groupwatch shows "Waiting for &lt;friend&gt; (60%)…" until **every** connected member has the
   complete file, then starts playback for everyone simultaneously.
5. Anyone can pause/seek; it applies to the whole group. The group talks over their usual
   external voice chat.

---

## 2. Hard constraints & non-goals

These are non-negotiable product laws. Do not ship anything that violates them.

- **NO TERMINAL, EVER.** Not for the leader, not for friends, not for "advanced" setup. Every
  capability must be reachable through the GUI. Installers must be graphical
  (Next → Next → Finish on Windows; double-click AppImage on Linux).
- **Non-technical-friend-first design.** The least technical member of the group is the
  benchmark. All user-facing text is plain language; errors say what happened and what to do
  ("Sam's copy of the file hasn't finished downloading yet") — never stack traces or codes.
- **Private-use scope.** This is for one trusted friend group. No authentication UX, no accounts,
  no permissions system, no security hardening beyond what the underlying tools do invisibly.
- **No social features.** No chat, no reactions, no presence fluff. The group uses external voice
  chat (e.g., Discord) while watching.
- **Windows + Linux only.** No macOS, no mobile, no web.
- **Minimal dependencies.** Every new dependency must be justified; the app bundles what it needs
  so users install exactly one thing.

---

## 3. Architecture

groupwatch is a single Python application running as a **24/7 background service with a UI**.
High-level components and how they communicate:

```
┌────────────────────────────────────────────────────────────────┐
│ groupwatch app (Python 3 + PySide6)                            │
│                                                                │
│  ┌──────────────┐   ┌───────────────┐   ┌───────────────────┐  │
│  │ Tray icon +  │   │ Sync engine   │   │ Syncplay engine   │  │
│  │ popup window │   │ (wrapper over │   │ (custom protocol  │  │
│  │ (PySide6/Qt) │   │  stock        │   │  client +         │  │
│  │              │   │  Syncthing)   │   │  embedded server) │  │
│  └──────┬───────┘   └───────┬───────┘   └─────────┬─────────┘  │
│         │                   │                     │            │
│         │             REST API (localhost)  JSON-over-TCP      │
│         │                   │                     │            │
│  ┌──────┴───────────────────┴─────────────────────┴─────────┐  │
│  │ Player adapter layer:  mpv (JSON IPC)  |  VLC (HTTP/Lua) │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

### 3.1 Background service + UI

- The app autostarts at login (toggle in Settings, **ON by default**) and lives in the system tray.
- The **tray icon** shows at-a-glance status (sync %, who's in the room) and quick actions
  (Open, Invite a friend, Quit).
- The **popup window** (opened from the tray) contains: the **library list** (videos in the synced
  folder, sorted), the **people panel** (who's online + per-member sync progress), **invite**
  generation, and **settings** (player choice, autostart toggle, folder location, server override).
- Closing the window never stops the service. Quitting is an explicit tray action.
- **Linux tray visibility quirk:** tray icons are not universal on Linux. GNOME hides them unless
  the "AppIndicator and KStatusNotifierItem Support" extension is installed; on Wayland compositors
  (e.g. Hyprland) they appear only if the bar/shell has a tray module. Because "launched but
  invisible" reads as broken to non-technical users, **the app shows its window on launch** (first
  run behavior), then lives in the tray afterward.

### 3.2 Sync engine (Syncthing wrapper)

- Uses the **stock, unmodified Syncthing binary**, bundled per-platform. Syncthing's own UI is
  never exposed; groupwatch generates Syncthing's entire config and drives it via its localhost
  REST API and events stream.
- **One-way sync topology — this is how sync conflicts are eliminated:**
  - Leader's folder: `sendOnly`
  - Every friend's folder: `receiveOnly`
  - With exactly one writer, conflicts are **structurally impossible**. Friends request new shows
    out-of-band. Defensive fallback, should a conflict file ever appear anyway: leader's copy
    wins, silently.
- **Device onboarding is fully automatic:** the invite code carries the leader's Syncthing device
  ID + folder ID. The friend's app adds the leader locally; the leader's app watches Syncthing's
  pending-device events and auto-approves + shares the folder. No human clicks "approve" anywhere.
- Syncthing's own NAT traversal (relays/hole-punching) means file sync needs **no router config**.
- The sync engine exposes per-device, per-file completion state (via the Syncthing API) to power
  the readiness gate and the people panel.

### 3.3 Syncplay engine (invisible to users)

- **Custom client:** groupwatch implements Syncplay's client protocol itself (JSON-over-TCP;
  reference implementation: Syncplay's own Python source, same language). Friends never see any
  Syncplay UI. The client auto-joins the group's single fixed room on every launch and handles
  play/pause/seek state sync and latency correction.
- **Embedded server (leader only):** the leader's app runs the Syncplay server (vendored from
  upstream, GPLv3 — see §6 licensing) as a managed background component, auto-started whenever the
  leader's machine is on. The app auto-forwards the server TCP port via **UPnP**; if UPnP fails,
  it shows plain-language manual port-forwarding guidance.
- **Server address is a config value.** Leader-hosted is the default, but a VPS or a public
  Syncplay server can be substituted in settings without any code change.
- No chat or social protocol features are surfaced, even though the protocol supports them.

### 3.4 Player adapter layer

Each group member independently picks their player in settings. Syncplay syncs playback *state*,
not video data — one member can use VLC while another uses mpv, as long as everyone plays the same
file from the synced folder.

| Player | Integration | Notes |
|---|---|---|
| **mpv** (default) | Bundled with the app; controlled via JSON IPC socket | Event-driven, clean; zero setup for the user |
| **VLC** | Detects an existing system install; controlled via its HTTP/Lua remote interface | Polling-based, coarser seeks; mpv is recommended in settings copy. Not bundled (too big; most VLC users already have it) |

Adapters share a common interface: open file, play, pause, seek, get position/state, events.

### 3.5 Invite system

- Leader clicks "Invite a friend" → app produces an **invite code** (copy-pastable string) or file
  containing: leader's Syncthing device ID, shared folder ID, Syncplay server address:port, room
  name, leader display name.
- Friend's app decodes it and performs the entire join automatically (§3.2).

### 3.6 Readiness gate

Before playback of a title starts, the app verifies **every connected member has 100% of that
file** (per-device file completion from the sync engine). Until then it shows plain progress
("Waiting for Sam (60%)…") and starts automatically when everyone is ready. If a member is
offline, the leader gets a plain "X is offline — start anyway?" choice.

### 3.7 Autostart

- Settings toggle, **ON by default**, both platforms:
  - **Windows:** `HKCU\...\CurrentVersion\Run` registry key.
  - **Linux:** XDG autostart `.desktop` entry.
- The app re-registers the entry on every launch while the toggle is on, so moving the AppImage or
  reinstalling never silently breaks autostart.

---

## 4. Decision log

Settled decisions, with rationale and rejected alternatives. **Do not re-open these without the
project owner's explicit approval.**

| Decision | Choice | Why | Rejected alternatives (why not) |
|---|---|---|---|
| Name | `groupwatch` (all lowercase) | Owner's choice | — |
| Platforms | Windows + Linux | Group's machines | macOS/mobile (out of scope) |
| Language/UI stack | **Python 3 + PySide6 (Qt)** | App is ~90% background-service "plumbing" (process orchestration, two network protocols, player IPC), Python's strength; Syncplay is Python → its source is our reference in the same language; most readable language for the non-programmer owner; Qt has battle-tested cross-platform tray+window support | **Electron** — heavy (150–300MB RAM) for a 24/7 tray daemon, fights its own foreground-app design; **Wails (Go)** — smaller UI/tray ecosystem, Go less readable for owner; **Tauri (Rust)** — steepest maintenance curve |
| File sync | **Stock Syncthing, wrapped & hidden** (app-generated config, REST-API-driven, auto-approve) | Battle-tested NAT traversal, delta sync, resume; zero user-visible surface after wrapping | **Build our own P2P sync** — NAT traversal + delta sync + conflicts = rebuilding years of hardening, strictly worse; **Fork/strip Syncthing source** — maintaining a fork of a ~100k-line Go codebase for no functional gain |
| Sync conflicts | **One-way topology: leader send-only, friends receive-only** | Conflicts become structurally impossible (single writer); friends can't delete/overwrite the group's files | Two-way sync + conflict resolution UX (owner: "I'd rather not deal with that") |
| Syncplay server location | **Leader's PC, bundled server, UPnP port-forward** | Free; leader attends every session anyway; address is a config value so VPS/public servers are drop-in upgrades | **VPS** (costs money, setup burden — kept as an option), **public Syncplay servers** (shared with strangers, no uptime control) |
| Syncplay client | **Invisible custom protocol client** | Only way to hit the zero-friction bar: friends never see or operate Syncplay's own window (no ready-buttons, foreign fields, mismatch dialogs) | **Wrap the official client** — faster, but forces non-technical friends to operate a second app every session; "wrapped v1 → custom v2" considered, rejected because v1 friction lands exactly on the least technical users |
| Media players | **mpv (bundled, default) + VLC (detected install)** via adapter layer | mpv = zero-setup clean IPC; VLC = most common player non-technical users already have | VLC-only, mpv-only, bundling VLC (too large) |
| UI form | **24/7 background service + tray icon + popup window** | Syncthing must run 24/7 regardless → background service is mandatory; tray = glanceable zero-friction; window = room for library/progress/invites. Dropbox/SyncTrayzor pattern | Tray-only (cramped), window-only (accidental-close risk) |
| Join flow | **Invite code/file**, everything else automatic | One paste beats manual device-ID/address exchange for non-technical friends | Manual exchange (error-prone), QR (friends are remote) |
| Playback behavior | **Library-list selection; anyone can pause/seek** | Like watching in the same room; Syncplay's default; fine for trusted friends | Auto-play-next-episode (fragile when members watch at different times — library + manual pick is predictable), leader-only controls (annoying in small groups) |
| Sync readiness | **Auto-wait gate**: start only when everyone has 100% of the file | Maximally seamless; prevents "file missing/partial" desyncs | Warn-but-allow (lets people break their own night), no check (glitches) |
| Social features | **None** | Group uses external voice chat | Built-in text chat, reactions |
| Autostart | **Toggle in Settings, ON by default**, both OSes, self-healing re-registration | "Set it and forget it" must survive reboots | Installer-only autostart, no toggle, off-by-default |
| Packaging | Windows `.exe` installer wizard; Linux **AppImage** (distro-universal) | Double-click install on every target; no terminal | Per-distro packages (.deb/.rpm — AppImage covers all with one artifact) |
| Hosting/CI | **git + GitHub**, GitHub Actions builds all binaries into Releases | Owner requirement; also means no one needs build tools locally | — |

### Owner context (read this before making UX/product calls)

- The project owner is **not a programmer**. Explain technical decisions in plain language with
  pros/cons when asked; keep code and docs readable; avoid cleverness.
- The friends are non-technical. When in doubt, choose the option with fewer user-visible steps.

---

## 5. Planned repo layout

```
groupwatch/
├── AGENTS.md                  ← this file
├── README.md
├── LICENSE                    ← GPLv3 (see §6)
├── pyproject.toml
├── src/groupwatch/
│   ├── __main__.py            ← entry point
│   ├── app.py                 ← service orchestration, component lifecycle
│   ├── config.py              ← settings, first-run state
│   ├── sync/                  ← Syncthing wrapper
│   │   ├── process.py         ← start/stop/monitor bundled syncthing
│   │   ├── api.py             ← localhost REST + events client
│   │   ├── setup.py           ← config generation, folder/device wiring, auto-approve
│   │   └── readiness.py       ← per-device per-file completion
│   ├── syncplay/
│   │   ├── protocol.py        ← message framing (JSON-over-TCP)
│   │   ├── client.py          ← room join, state sync, latency correction
│   │   └── server.py          ← embedded leader-side server (vendored upstream)
│   ├── players/
│   │   ├── base.py            ← adapter interface
│   │   ├── mpv.py             ← JSON IPC (bundled default)
│   │   └── vlc.py             ← HTTP/Lua interface (detected install)
│   ├── ui/
│   │   ├── tray.py
│   │   ├── main_window.py     ← library, people panel, invites
│   │   ├── wizard.py          ← first-run: create / join
│   │   └── settings.py        ← player choice, autostart toggle, paths
│   ├── invite.py              ← encode/decode invite codes & files
│   └── platform/
│       ├── autostart.py       ← Windows Run key / XDG autostart
│       └── upnp.py            ← port forwarding for the leader's server
├── vendor/                    ← bundled upstream pieces + their licenses
├── assets/                    ← icons
├── packaging/
│   ├── windows/               ← installer definition (e.g., Inno Setup)
│   └── linux/                 ← AppImage recipe
└── .github/workflows/
    └── release.yml            ← matrix build → GitHub Releases
```

---

## 6. Build & release workflow

- **Version control:** git, hosted on GitHub. Small, focused commits; plain commit messages.
- **Licensing:** groupwatch is **GPLv3**. Rationale: the embedded Syncplay server components are
  GPLv3 (vendored in `vendor/` with attribution). Syncthing is MPL-2.0 and is bundled as an
  **unmodified binary** driven via its API — permissible alongside GPL. Keep upstream licenses in
  `vendor/` and `LICENSE` files accurate.
- **Releases:** tagging a version triggers **GitHub Actions** matrix builds producing:
  - `groupwatch-setup-x.y.z.exe` (Windows installer wizard)
  - `groupwatch-x.y.z.AppImage` (Linux, distro-universal)
  published to GitHub Releases. No developer or user machine needs build tooling.
- **Bundled binaries:** Syncthing and mpv are pinned to specific upstream versions, fetched at
  CI/build time per platform, never hand-updated in the repo.
- Never commit secrets (Syncthing API keys, device IDs are per-install, generated at first run).

---

## 7. Phased roadmap

**Status:** Phase 0 **complete** — repo live at <https://github.com/LyKhoris/groupwatch>
(**public**, so group members can download releases without GitHub accounts). Tag a `vX.Y.Z` on
`main` and GitHub Actions builds both installers into Releases. Next up: **Phase 1 — sync engine**.

| Phase | Deliverable | Exit criteria |
|---|---|---|
| **0. Scaffold** | Repo, pyproject, CI skeleton, hello-world tray app building on Win+Linux | Actions produces both installers from a tag |
| **1. Sync engine** | Syncthing wrapper: config generation, one-way folder, invite create/accept, device auto-approve | Two machines sync a folder end-to-end with zero Syncthing UI visible |
| **2. Syncplay engine + mpv** | Custom protocol client talking to a real Syncplay server; mpv adapter; then embedded leader server + UPnP | Two clients play/pause/seek the same file in sync, mpv only |
| **3. UI** | Tray + popup window: library list, people panel, invite, settings, autostart toggle | Full create/join/watch flow doable entirely from the GUI |
| **4. Readiness gate** | Auto-wait on per-device file completion, plain-language waiting screen | Playback refuses to start early; starts automatically when all synced |
| **5. VLC adapter** | Detection + HTTP/Lua control | VLC user can join the same session as mpv users |
| **6. Polish** | Plain-language error pass, edge cases (UPnP failure, offline member, moved AppImage), release | Non-technical friend completes install→watch with zero help |

Build phases in order; each phase must leave the app runnable.

---

## 8. Working conventions for agents

- **Read this file first.** If a change contradicts it, stop and ask the owner before proceeding.
- **Update this file** whenever decisions, structure, roadmap state, or conventions change.
- Honor §2 constraints in every line of code and copy: no terminal, plain-language errors,
  non-technical-friend-first.
- Keep dependencies minimal and pinned; justify any addition.
- Never modify vendored/bundled upstream code; integrate at config/API level only.
- Follow existing code style; keep modules aligned with §5 layout.
- Every phase ends with working builds on **both** Windows and Linux.
- Test before claiming done; verify on both platforms where feasible.
- Reference repos (read-only, for protocol/behavior reference — do not fork them):
  - Syncplay: <https://github.com/Syncplay/syncplay.git>
  - Syncthing: <https://github.com/syncthing/syncthing.git>
