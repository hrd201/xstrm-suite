# Isolated Docker deployment

[English](README.en.md) | [中文](README.md)

The stack runs separate admin, Nginx/njs gateway, Emby and OpenList containers, plus optional MediaWarp. Use a separate directory, volumes and ports from production. Existing configuration and storage authorization are not imported automatically.

## Prepare

Install Docker Engine, Compose v2, OpenSSL and htpasswd (apache2-utils on Debian/Ubuntu). From the Linux checkout:

```bash
docker compose -f deploy/compose.test.yaml build admin
docker run --rm -v "$PWD:/bootstrap" xstrm-test-admin python /bootstrap/deploy/prepare_test.py
sudo chown 1001:1001 deploy/test-openlist
htpasswd -cB deploy/test-nginx/conf.d/.htpasswd-xstrm-admin admin
chmod 644 deploy/test-nginx/conf.d/.htpasswd-xstrm-admin
docker compose -f deploy/compose.test.yaml up -d
```

Preparation refuses to overwrite existing test directories. Choose a unique password interactively. The hash must be readable by the gateway worker; keep the file private.

All published ports bind to 127.0.0.1 by default: gateway 18091, Emby 18096, OpenList 15244, optional TLS listener 18443. Admin is at http://127.0.0.1:18091/admin/xstrm/. Set XSTRM_BIND_IP in a private root .env for LAN access. XSTRM_DNS_SERVER defaults to 1.1.1.1; override it with a trusted resolver reachable from this host. Recreate affected services after changing bindings.

## Initialize and validate a small source

1. Complete the Emby/OpenList wizards, authorize storage and create an Emby API key.
2. Save internal connections http://emby:8096 and http://openlist:5244, credentials and a client-reachable public_url in Settings. Signed downloads require the permanent OpenList token.
3. Save a small source. For logical paths, use the actual OpenList path for scan_path and output_prefix. Start with All files to initialize a baseline.
4. Add /emby-strm to an Emby Movies or TV library and enable its metadata/image providers. Both services already mount deploy/test-media.
5. Connect VidHub to the gateway using an Emby user. Basic Auth is a separate admin login.

Libraries created through API calls may omit provider defaults. After reviewing settings, python deploy/configure_emby_metadata.py --library YOUR_LIBRARY --tmdb-only inside admin explicitly selects TMDB, after backing up the original settings.

## MediaWarp and rollback

Preparation starts with the legacy njs gateway. After saving valid connections:

```bash
bash deploy/apply_playback.sh mediawarp
# Requires a saved legacy gateway:
bash deploy/apply_playback.sh emby2alist
```

The script renders private configuration, starts pinned akimio/mediawarp:v0.2.5, waits for readiness, tests Nginx and reloads. Failure restores prior files. Web settings only save choices; they do not apply them. Emby, OpenList and STRMs are not recreated by this switch.

MediaWarp port 9000 is internal. The edge verifies playback client credentials before redirecting. STRMs retain cloud paths; signed OpenList /d/ links redirect to the CDN. Original video mounts are not supplied, so fallback/transcoding is not guaranteed. xstrm still handles sidecar subtitle sync.

Edge access logs omit query parameters; MediaWarp logs that could contain signed URLs are disabled. Private test-* runtime files and rollback snapshots are excluded from Git and image builds.

## HTTPS and network helpers

Supply a domain and valid certificate. Put privatekey.pem and fullchain.pem in deploy/test-nginx/cert; install deploy/https-test.conf as test-nginx/conf.d/includes/https.conf. Review the OpenList endpoint/signing settings before installing deploy/download-test.conf in the custom location directory.

Set OpenList public_url to the actual HTTPS gateway. Set XSTRM_HTTPS_BIND_IP explicitly when publishing port 18443 beyond loopback. Verify router forwarding, firewall, TLS and admin authentication, then test/reload Nginx. Configure certificate renewal separately.

The firewall, DNS relay and Mihomo examples are lab helpers, not universal installation steps. The relay assumes bridge 172.18.0.1/16 and upstream 127.0.0.1:1053; adapt and verify these before enabling it. Ordinary installations do not require TUN or system DNS changes.

## Operations and upgrade

Schedules run inside admin. Configuration is in config/strm-sync.yaml; durable queue/history is in data/scheduler.sqlite3. Manual and scheduled scans share a queue and kernel write lock. Movie identity repair uses Emby's own candidate APIs without a new provider key; private bindings are in data/identity/.

Health checks cover local files and redirects, not video downloading. Verify actual bytes, seeking, subtitles, audio and resume separately in VidHub.

Check active jobs and back up private configuration, STRMs, Emby data, scan indexes, scheduler.sqlite3 and identity/ before upgrading:

```bash
docker compose -f deploy/compose.test.yaml build admin
docker compose -f deploy/compose.test.yaml up -d --no-deps admin
docker compose -f deploy/compose.test.yaml exec -T gateway nginx -t
```

For offline builds, supply matching wheels for requirements and dependencies in deploy/wheels and build with --build-arg PIP_NO_INDEX=1. Git contains only a directory placeholder. Do not run the native upgrade.sh over this Docker stack. Keep production through a complete daily observation period and client acceptance before a separate migration.
