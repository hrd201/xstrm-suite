# CHANGELOG

All notable changes to this project will be documented in this file.

## [Unreleased]

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
