# CHANGELOG

All notable changes to this project will be documented in this file.

## [0.3.0] - 2026-07-11

### Added
- Unified incremental refresh settings into `config/strm-sync.yaml`, while retaining JSON compatibility.
- Added active and cold-directory scheduling, dead-letter handling, ignored paths, remote-missing tracking, and configurable remote deletion policy.
- Added async Web tasks, queue health counters, explicit incremental/full-scan actions, and ignore/unignore controls.
- Added automated regression tests and GitHub Actions checks.

### Security
- Removed tracked runtime credentials, generated runtime files, deployment hostnames, and backup artifacts; added safe example configs and CI secret checks.
- Added POST request verification, atomic configuration writes, restrictive runtime permissions, service hardening, and upgrade backups.

### Fixed
- Regular polling no longer recursively requeues every known child directory.
- New and restored STRM files are reported separately, and partial directory failures return a non-zero exit status.
- Upgrade and rebuild failures now preserve production data and produce accurate task state.
- STRM health checks now read the rotated Emby key and service URLs from runtime configuration and discover a user dynamically.
- NJS playback routing now normalizes non-string and repeated `MediaSourceId` query values before path lookup.

## [0.2.2] - 2026-06-23

### Added
- **Queue-based incremental STRM refresh**: Added `scripts/incremental_strm_refresh.py`, which keeps a local SQLite index and refreshes only queued candidate directories instead of recursively scanning every source.
- **Task wrapper**: Added `scripts/task_incremental_refresh.sh` for lock-protected task execution with existing xstrm task status output.
- **Missing STRM regeneration**: If Emby deletes a local `.strm` file but the media still exists in AList, the incremental refresher can regenerate the missing `.strm` during the next directory refresh.
- **Refresh queue controls**: Added support for manual directory queueing, active parent directory rechecks, request intervals, jitter, retry delays, and scheduled daemon mode.
- **Example configuration and documentation**: Added `config/incremental-strm.json.example` and `docs/INCREMENTAL_STRM_REFRESH.md` with generic placeholders and systemd timer examples.

### Security
- Added ignore rules for real incremental refresh configs and SQLite state files so local AList tokens and runtime state are not committed accidentally.

### Fixed
- Incremental refresh now keeps consuming newly queued child directories within the same run budget, so refreshing a show folder can discover media added under season subdirectories.
- Avoided immediately requeueing the directory currently being scanned after generating a new `.strm`, reducing duplicate requests in the same run.

## [0.2.1]2026-04-26

### Added
- **Subtitle Synchronization**: Introduced `src/subtitle_syncer.py` to automatically download subtitles (`.srt`, `.ass`, etc.) from AList to the local strm folder during scans.
- **Web Admin UI Sorting**: AList directory browser now sorts items by modification date (newest first) and displays timestamps for better accessibility.
- **Configuration Expansion**: Added `scan.subtitle_sync` and `scan.subtitle_exts` settings to `strm-sync.yaml`.
- **Extended media format support**: Expanded scan whitelist for more video and audio extensions.
  - Video: `.mov`, `.wmv`, `.flv`, `.webm`, `.m4v`, `.mpg`, `.mpeg`, `.rmvb`, `.iso`
  - Audio: `.mp3`, `.m4a`, `.flac`, `.aac`, `.ape`, `.wav`, `.ogg`, `.opus`, `.wma`, `.alac`, `.aiff`, `.aif`, `.amr`
- **Template sync update**: `config/templates/strm-sync.yaml.template` now includes the same extension set to keep fresh deployments consistent.

### Fixed
- **Subtitle download 403 error**: Switched to AList proxy download interface (`/d/<path>`) to resolve 403 issues when directly requesting cloud drive links (like 115) without cookies.
- **URL encoding in subtitle sync**: Fixed download failures caused by spaces or special characters in file paths.
- **Scanner extension loading**: `src/scanner.py` now respects `scan.include_ext` from configuration instead of relying only on the built-in constant set.
- **Music directory scanning**: Fixed the issue where audio extensions could be configured but were not actually picked up during scans, allowing paths like `/mnt/115/音乐` to detect audio media correctly.

## [0.2.0] - 2026-03-16

### Added
- **AList Directory Browser**: Admin UI now supports browsing AList directories directly
  - New API endpoint: `GET /api/admin/xstrm/alist/list?path=/`
  - Frontend UI with breadcrumb navigation
  - Click-to-select functionality for scan paths
- **Scan Mode Refactor**: Changed from local mount scanning to AList API scanning
  - Direct AList API integration via `src/alist_client.py`
  - Recursive directory walking via AList API
- **Path Mapping**: Automatic mapping of AList mount paths to logical STRM prefixes
  - e.g., `/mnt/115/电影` → `/115/电影` in output
- **Modular Architecture**: Core logic extracted into `src/` package
  - `src/config.py`: Configuration loading and inference
  - `src/state.py`: State management
  - `src/alist_client.py`: AList API client
  - `src/scanner.py`: Core scanning logic
  - `src/generator.py`: STRM file generation
  - `cmd/cli.py`: CLI entry point

### Fixed
- **Admin API Routing**: Fixed 404 errors when accessing `/api/admin/xstrm/*`
  - Corrected `backend_port` from 8095 to 18095
  - Properly route `/admin/xstrm/` and `/api/admin/xstrm/*` to internal API
- **Empty File Sync Issue**: Fixed case where `strm_x.py` was synced as empty file
- **Stale State Cleanup**: Added automatic pruning of missing STRM files from state
- **Task Lock Cleanup**: Fixed stuck scan tasks due to stale lock files

### Changed
- **Scan Sources Configuration**: Changed from mount-path based to AList-path based
  - Now uses `scan_mode: alist` instead of local filesystem scanning
  - Sources use AList paths like `/mnt/115/电影` instead of logical paths
- **Token Management**: Updated AList token handling

### Dependencies
- Updated to work with AList v3+

---

## [0.1.0] - 2026-03-11

### Added
- Initial release of `xstrm-suite` project
- `xstrm` / `xstrm-admin` command entry points
- Integration with `emby2alist` for source configuration
- Mirror-mode STRM file generation
- Directory selection from discovered sources
- Specified directory scanning
- STRM file deduplication
- Docker-based nginx/emby2alist control scripts
- Runtime configuration with template rendering
- HTTP/HTTPS support with certificate paths
- Bootstrap/installation scripts
- Upgrade and repair scripts

### Features
- Configuration-driven runtime generation
- Interactive setup via bootstrap.sh
- Nginx test and reload utilities
- Docker compose integration
- Profile-based nginx configuration
