# Bootstrap Usage

## Install

```bash
cd /path/to/xstrm-suite/scripts
sudo ./bootstrap.sh
```

## What it does

- checks python3
- installs PyYAML if missing
- checks docker / docker compose
- syncs project to `/opt/xstrm-suite`
- interactively collects required runtime config
- separates AList host and port during install
- renders runtime-derived config files
- renders Docker compose according to HTTP / HTTPS mode
- applies runtime-derived config into live nginx/emby2alist files
- installs `xstrm` command to `/usr/local/bin/xstrm`
- installs `xstrm-admin` command to `/usr/local/bin/xstrm-admin`
- installs `xstrm.service` template to systemd directory

## Management Entry

After deployment you can use:

```bash
xstrm
xstrm-admin
```

For nginx helper actions:

```bash
/opt/xstrm-suite/scripts/nginx_ctl.sh test
/opt/xstrm-suite/scripts/nginx_ctl.sh reload
```

`xstrm-admin` also exposes:
- nginx test/reload
- docker up/down/status
- re-render + apply + restart flow
- HTTP/HTTPS mode switch guide

or directly:

```bash
/opt/xstrm-suite/bin/xstrm
/opt/xstrm-suite/bin/xstrm-admin
```

It provides:
- bootstrap
- upgrade
- repair
- uninstall
- config/docs quick access

## Current Safety Checks

- validates runtime config before render/apply
- checks ssl cert/key existence only when HTTPS is enabled
- skips ssl checks when HTTP-only mode is selected
- checks nginx port conflicts inside runtime config
- runs nginx test in bootstrap flow
- provides nginx test/reload helper

## What it does not fully automate yet

- production nginx enable/reload wiring
- emby2alist daemonization details
- cron/periodic scan jobs
- full interactive system service management
