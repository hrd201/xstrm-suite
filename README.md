# xstrm-suite

[English](README.md) | [中文](README.zh-CN.md)

A Web control plane for cloud-backed Emby libraries: generate local STRMs from AList/OpenList, schedule scans, diagnose redirects and repair movie identification through Emby's metadata providers. Playback supports MediaWarp or the existing Nginx/njs/emby2Alist backend.

## Architecture

```text
AList/OpenList directories → xstrm → local STRMs + optional subtitles → Emby
VidHub / Emby client → Nginx gateway → playback backend → OpenList → cloud CDN
```

STRMs retain original logical cloud paths. The playback backend resolves them on demand. Identity repair updates Emby through its API and saves a confirmed local binding; it does not rename cloud videos or rewrite STRMs.

## Web pages

| Page | Purpose |
| --- | --- |
| Overview | Task status, queue summary and recent logs |
| Scan tasks | Scan sources or a subtree, browse directories, explicitly rebuild local STRMs |
| Scheduled tasks | Per-source interval/daily/Cron plans, run now, enable/disable, bounded retries and history |
| Movie identification | Find unidentified/incomplete movie STRMs, preview candidates and confirm a match |
| Media sources | Save remote directories and output prefixes |
| Settings | Connections, credentials, subtitles and playback backend selection |

Saving sources does not start a scan. Saving playback settings does not reload the gateway; review and apply them using the deployment script.

## Scanning and limits

- **All files:** enumerate selected trees and generate missing STRMs, skipping existing files. Use this for the initial import.
- **Recent:** still enumerate the trees, but generate only files within the creation/modification window. Zero means no eligible files in that window, not an empty library.
- **Queue-based refresh:** a separate existing CLI workflow prioritizes candidate directories using a local index and request budget.
- **Subtitles:** optionally download supported sidecars to the matching STRM tree.

Request pacing and serialized writes reduce unnecessary pressure; they cannot guarantee avoidance of provider rate limits or account restrictions. Recent scans still list older directories and currently refresh those listings. Schedule large libraries conservatively.

## Requirements and installation

Linux, Bash, flock (util-linux), OpenSSL, **Python 3.10+**, and the packages in [requirements.txt](requirements.txt). The admin image uses Python 3.13. Docker deployments require Docker Engine and Compose v2. Emby and the admin service must read the shared STRM directory at the same configured path.

Start with the [isolated Docker guide](deploy/README.en.md), which prepares separate admin, gateway, Emby and OpenList containers and optionally enables pinned MediaWarp:

```bash
git clone https://github.com/hrd201/xstrm-suite.git
cd xstrm-suite
docker compose -f deploy/compose.test.yaml build admin
# Continue with preparation and a unique password in deploy/README.en.md.
```

Published ports default to 127.0.0.1. Set XSTRM_BIND_IP for LAN access; configure certificates and XSTRM_HTTPS_BIND_IP before exposing TLS. Runtime credentials, certificates and databases are excluded from Git and image build contexts.

The native installer maintains the legacy Nginx/njs deployment separately:

```bash
sudo bash scripts/install.sh
# scripts/bootstrap.sh is a compatibility alias.
```

Prepare Python 3.10+, venv support, rsync, Docker and system tools first. Install/upgrade scripts install all Python dependencies in the installation's .venv; systemd and task wrappers use it. The standalone API-service installer requires the main installer to create the xstrm user first. Configure a unique Basic Auth password before using the gateway; no working shared password is shipped.

## First use

1. Initialize Emby/OpenList and authorize storage. Save their connections in Settings. Signed downloads need the OpenList permanent token, not a temporary login JWT.
2. Save a small source. Logical STRM targets must match actual OpenList paths; using the same scan_path and output_prefix is straightforward.
3. Run **All files**, add the shared output directory to an Emby Movies or TV library, and enable metadata/image providers.
4. Apply the backend and connect VidHub to the gateway address to exercise redirect playback.
5. Create a scheduled task after checking the initial scan. Scheduling runs inside admin, without a second host Cron process.
6. In Movie identification, click **Search movie and posters** (the UI is currently Chinese). A dialog opens and searches unambiguous names automatically. Conflicting years/IDs need review. Check title, year and poster before confirming.

## Identification and health checks

Movie repair supports movie STRMs inside the configured output root. Use All movies to correct existing wrong matches. Posters appear in the search dialog; failed loads show a retry action. Some providers omit candidate overviews, which are labelled unavailable.

After confirmation, the service submits to Emby and reads back ID, title, overview and poster availability. Ambiguous timeouts or unverified requested image replacement are not reported as complete. Bindings persist by server identity, original STRM path and target-content fingerprint. After library rebuilding, a matching binding can be searched and explicitly confirmed again. Path/content changes require reassociation.

Health checks verify file presence and an HTTP(S) redirect. They do not follow CDN links or prove playable video, seeking, subtitles or audio selection; validate those in VidHub.

## Backup, upgrade and validation

Back up configuration, STRMs, Emby data, data/scheduler.sqlite3, data/identity/ and scan state/indexes. Identity records contain private media paths/provider responses. Terminal jobs remove their execution snapshots.

For Docker, check active tasks, rebuild admin and recreate only that service. Apply backend configuration with deploy/apply_playback.sh mediawarp or emby2alist. Legacy rollback requires a saved legacy gateway and Nginx with njs. Keep production until client acceptance and parallel observation are complete.

- [Deployment](deploy/README.en.md) / [部署说明](deploy/README.md)
- [Scheduling](docs/SCHEDULER.en.md) / [定时任务](docs/SCHEDULER.md)
- [Identity repair](docs/IDENTITY.en.md) / [识别修复](docs/IDENTITY.md)
- [Changelog](CHANGELOG.md) / [更新日志](CHANGELOG.zh-CN.md)

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
for script in scripts/*.sh deploy/*.sh bin/xstrm bin/xstrm-admin; do bash -n "$script"; done
node --check web/admin/identity.js
```

Full process-group and kernel-lock checks require Linux. CI covers Python 3.10 and 3.13. Temporary-data tests do not replace client acceptance.

## Credits and license

Playback integration builds on [embyExternalUrl](https://github.com/bpking1/embyExternalUrl). Scheduling references [AutoFilm](https://github.com/AkimioJR/AutoFilm); [MediaWarp](https://github.com/AkimioJR/MediaWarp) is an optional external backend. See [LICENSE](LICENSE) and upstream licenses.
