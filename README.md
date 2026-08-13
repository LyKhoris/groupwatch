# groupwatch

Watch videos together with your friends over the internet — one auto-synced
folder of video files, perfectly synchronized playback. Powered, invisibly, by
[Syncthing](https://github.com/syncthing/syncthing) (file sync) and
[Syncplay](https://github.com/Syncplay/syncplay) (playback sync).

**Status: early development.** The full project spec, decisions, and roadmap
live in [AGENTS.md](AGENTS.md).

> **Personal use only.** This is built for one private friend group, not for
> public deployment. It was also fully vibecoded with opencode + kimi k3 — so
> expect rough edges and no warranty.

## Downloads (for group members)

Installers are built automatically and published on the
[Releases](../../releases) page (public — no account needed to download):

- **Windows:** `groupwatch-setup-x.y.z.exe` — a normal installer wizard
  (Next → Next → Finish).
- **Linux:** `groupwatch-x.y.z.AppImage` — download, allow executing
  (right-click → Properties), double-click.

No terminal, no configuration files, no accounts.

## Development

- Python 3 + PySide6 (Qt). Structure, conventions, and the phased roadmap are
  documented in [AGENTS.md](AGENTS.md) — read it first.
- Releases are built by GitHub Actions: push a tag `vX.Y.Z` and both
  installers appear on the Releases page.
