# xstrm-suite

[English](./README.md) | [中文](./README.zh-CN.md)

STRM file management system for Emby + AList integration. Automatically generates `.strm` files that point to AList-hosted media files, enabling Emby to play directly from AList storage.

> This project is based on [embyExternalUrl](https://github.com/bpking1/embyExternalUrl) and modified to address specific needs.

## Project Purpose

xstrm-suite is designed to solve common challenges when using Emby with cloud storage (like AList):

1. **Prevent Account Risks**: Avoid cloud storage account bans caused by Emby's aggressive scraping
2. **Improve Performance**: Eliminate slow metadata refresh, recognition, and fetching issues
3. **Flexible Configuration**: No need to modify existing Emby or AList configurations
4. **Auto-Discovery**: Automatically obtain Emby and AList configurations/paths via API
5. **Unified Port**: Works alongside direct proxy on the same port, plugin-style management

## Features

- **AList Integration**: Direct integration with AList for media scanning
- **Automatic STRM Generation**: Automatically generates `.strm` files for your media library
- **Admin Web UI**: Browse AList directories and trigger scans from web interface
- **Incremental Sync**: Only generates missing STRM files, skips existing ones
- **State Management**: Tracks generated files to avoid duplicates
- **Flexible Scanning**: Scan all sources or specify individual directories
- **HTTPS Support**: Full HTTPS configuration with Let's Encrypt or custom certificates

## Architecture

```
xstrm-suite/
├── src/                      # Core runtime code
│   ├── config.py             # Configuration loading
│   ├── state.py              # State management
│   ├── alist_client.py       # AList API client
│   ├── scanner.py            # Media scanning logic
│   └── generator.py          # STRM file generation
├── cmd/                      # CLI entry point
├── scripts/                  # Installation and运维 scripts
├── config/                   # Configuration templates
├── nginx/                    # Nginx configuration
├── web/admin/                # Admin web UI
└── data/                     # Runtime data (state, logs)
```

## Requirements

- **Python 3.8+**
- **PyYAML**
- **Docker & Docker Compose**
- **AList v3+** (external or self-hosted)
- **Emby Server** (for media playback)

## Installation

### Quick Start

```bash
# Clone the repository
git clone https://github.com/hrd201/xstrm-suite.git
cd xstrm-suite

# Run bootstrap installation
cd scripts
sudo ./bootstrap.sh
```

The bootstrap script will interactively prompt for:
- Emby server address and API key
- AList installation method (Docker/local/custom)
- AList protocol, host, port, token, and public URL
- Nginx port and HTTPS configuration
- Media mount root path
- STRM output directory
- Scan source list

### Manual Installation

If you prefer manual installation:

#### 1. Install Dependencies

```bash
# Install Python dependencies
pip3 install pyyaml

# Install Docker (if not already installed)
curl -fsSL https://get.docker.com | sh
systemctl enable docker
systemctl start docker

# Install Docker Compose
pip3 install docker-compose
```

#### 2. Configure AList

Make sure your AList server is running and you have:
- AList base URL (e.g., `http://YOUR_ALIST_HOST:5388`)
- Admin token

#### 3. Create Configuration

```bash
# Copy the template configuration
cp config/strm-sync.yaml.example config/strm-sync.yaml

# Edit the configuration
vim config/strm-sync.yaml
```

Required configuration:

```yaml
output_root: /emby-strm
mode: mirror
alist:
  base_url: http://YOUR_ALIST_IP:5388
  token: YOUR_ALIST_TOKEN
  public_url: https://your-domain.com:5388
scan:
  default_depth: 1
  incremental_only: true
  include_ext:
    - .mp4
    - .mkv
    - .avi
    - .ts
    - .m2ts
sources:
  - path: /115/电影
    library_type: movie
    watch_depth: 1
    output_prefix: /115/电影
    scan_path: /mnt/115/电影
  - path: /115/剧集
    library_type: series
    watch_depth: 1
    output_prefix: /115/剧集
    scan_path: /mnt/115/剧集
```

#### 4. Render and Apply Configuration

```bash
# Render runtime configuration
python3 scripts/render_runtime.py

# Apply configuration
python3 scripts/apply_runtime.py
```

#### 5. Start Services

```bash
# Start nginx and emby2alist via Docker
docker-compose up -d

# Start admin API
systemctl enable xstrm-admin-api
systemctl start xstrm-admin-api
```

### Docker Installation

The easiest way to run the entire stack:

```bash
# Using docker-compose
docker-compose up -d
```

## Usage

### Command Line Interface

```bash
# Run xstrm CLI
xstrm

# Or directly
/opt/xstrm-suite/bin/xstrm
```

Options:
- `1` - Scan from configured AList directories
- `2` - Scan specified AList directory
- `3` - View integration config
- `4` - Configure cron jobs
- `5` - View current config
- `6` - View state file
- `0` - Exit

### Web Admin Interface

Access the admin UI at: `http://YOUR_SERVER:8095/admin/xstrm/`

Features:
- View scan status and logs
- Browse AList directories
- Trigger scans on specific directories
- View configuration

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/admin/xstrm/status` | GET | Get scan status |
| `/api/admin/xstrm/sources` | GET | List configured sources |
| `/api/admin/xstrm/scan-path` | POST | Scan specified path |
| `/api/admin/xstrm/scan-all` | POST | Scan all sources |
| `/api/admin/xstrm/alist/list` | GET | Browse AList directory |
| `/api/admin/xstrm/logs` | GET | Get scan logs |

## Scanning Workflow

### How It Works

1. **Configuration**: Define your media sources in `config/strm-sync.yaml`
2. **AList Scanning**: The scanner connects to AList API and recursively walks directories
3. **Path Mapping**: AList mount paths (e.g., `/mnt/115/电影`) are mapped to logical paths (e.g., `/115/电影`)
4. **STRM Generation**: For each media file found, a `.strm` file is created in the output directory
5. **State Tracking**: Generated files are tracked in state to avoid duplicates

### Path Mapping Example

```
AList Path:    /mnt/115/电影/角斗士2 Gladiator II/GladiatorII.mkv
               ↓ (path mapping)
Logical Path:  /115/电影/角斗士2 Gladiator II/GladiatorII.mkv
               ↓ (STRM generation)
STRM File:     /emby-strm/115/电影/角斗士2 Gladiator II/GladiatorII.strm
               ↓ (content)
STRM Content:  /115/电影/角斗士2 Gladiator II/GladiatorII.mkv
```

### Incremental Mode

By default, incremental mode is enabled:
- Existing STRM files are skipped
- Only new media files trigger STRM generation
- Missing STRM files are automatically regenerated

To disable incremental mode:

```yaml
scan:
  incremental_only: false
```

## Troubleshooting

### Check Service Status

```bash
# Check xstrm-admin API
systemctl status xstrm-admin-api

# Check Docker containers
docker-compose ps

# Check nginx
nginx -t
```

### View Logs

```bash
# Admin API logs
journalctl -u xstrm-admin-api -f

# Scan logs
tail -f /opt/xstrm-suite/data/tasks/logs/scan_path-*.log
```

### Common Issues

1. **Token Invalid**: Update your AList token in `config/strm-sync.yaml`
2. **Path Not Found**: Ensure AList storage paths match your configuration
3. **Permission Denied**: Ensure the output directory is writable

## Development

### Project Structure

```
src/
├── config.py       # Configuration loading and inference
├── state.py        # State file management
├── alist_client.py # AList API client
├── scanner.py      # Media scanning logic
└── generator.py    # STRM file generation
```

### Running Tests

```bash
# Test scanning
python3 -m cmd.cli --scan-path "/mnt/115/电影"

# View configuration
python3 -m cmd.cli --config
```

## Acknowledgments

Special thanks to [bpking1](https://github.com/bpking1) for creating [embyExternalUrl](https://github.com/bpking1/embyExternalUrl), which inspired this project.

## License

MIT License

## Support

For issues and questions, please open an issue on GitHub.
