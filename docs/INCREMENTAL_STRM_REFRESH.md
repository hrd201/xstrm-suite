# Incremental STRM Refresh

This document describes the queue-based incremental refresher in `scripts/incremental_strm_refresh.py`.

## Why It Exists

The regular scanner walks AList directories recursively. That is useful for a full rebuild, but it can be too heavy for daily operations on cloud-drive storage. The incremental refresher keeps a local SQLite index and only lists a small queue of candidate directories each run.

It is designed for these cases:

- new episodes are added inside an existing show folder;
- a new directory should be prioritized without scanning every source;
- Emby deletes a local `.strm` file and the file should be restored if the remote media still exists;
- requests to AList should be rate-limited to reduce cloud-drive account risk.

## Files

- Script: `scripts/incremental_strm_refresh.py`
- Task wrapper: `scripts/task_incremental_refresh.sh`
- Example config: `config/incremental-strm.json.example`
- Runtime config: `config/incremental-strm.json`
- Suggested state database: `data/incremental-strm.sqlite3`

The runtime config may contain AList tokens and local paths. Do not commit it.

## How It Works

1. `entries` stores known AList files and generated `.strm` paths.
2. `dir_queue` stores candidate directories to refresh.
3. Each run lists only queued directories, up to `incremental_refresh.max_dirs_per_run`.
4. Subdirectories found during a refresh are queued and may be processed in the same run while the directory budget allows.
5. New media files generate `.strm` files and are recorded as active entries for later rechecks.
6. If a media file is already indexed but its `.strm` file is missing, the refresher regenerates it.
7. Recently active parent directories are periodically rechecked.

## Configuration

Copy the example:

```bash
cp config/incremental-strm.json.example config/incremental-strm.json
```

Edit these fields:

- `alist_base_url`: internal AList URL used by the server.
- `alist_token`: AList token. Keep this out of git.
- `strm_output_dir`: local STRM root visible to Emby.
- `state_db`: SQLite state path.
- `watch_dirs`: top-level AList directories that seed the refresh queue.
- `sources`: maps AList `scan_path` to the logical path written into `.strm`.
- `strm_url_template`: usually `{media_path}` when using emby2alist path resolution.

Example path mapping:

```json
{
  "scan_path": "/mnt/cloud/movies",
  "output_prefix": "/cloud/movies"
}
```

For a media file at:

```text
/mnt/cloud/movies/Example Movie/Example.mkv
```

the generated `.strm` file will be:

```text
<strm_output_dir>/cloud/movies/Example Movie/Example.strm
```

and its content will be:

```text
/cloud/movies/Example Movie/Example.mkv
```

## Commands

Queue a directory manually:

```bash
python3 scripts/incremental_strm_refresh.py \
  --config config/incremental-strm.json \
  queue-dir "/mnt/cloud/series/Example Show" \
  --reason manual
```

Run one refresh cycle:

```bash
python3 scripts/incremental_strm_refresh.py \
  --config config/incremental-strm.json \
  run-once
```

Run as a simple daemon with fixed intervals:

```bash
python3 scripts/incremental_strm_refresh.py \
  --config config/incremental-strm.json \
  daemon --interval-minutes 120
```

Run as a daemon using configured times:

```bash
python3 scripts/incremental_strm_refresh.py \
  --config config/incremental-strm.json \
  daemon --schedule
```

For production, prefer a systemd timer or cron so process restarts are managed by the OS.

## systemd Example

`/etc/systemd/system/xstrm-incremental-refresh.service`:

```ini
[Unit]
Description=xstrm incremental STRM refresh
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/opt/xstrm-suite
ExecStart=/usr/bin/python3 /opt/xstrm-suite/scripts/incremental_strm_refresh.py --config /opt/xstrm-suite/config/incremental-strm.json run-once
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
```

If you want xstrm task locking and task status output, call the wrapper instead:

```ini
ExecStart=/opt/xstrm-suite/scripts/task_incremental_refresh.sh
```

`/etc/systemd/system/xstrm-incremental-refresh.timer`:

```ini
[Unit]
Description=Run xstrm incremental STRM refresh twice daily

[Timer]
OnCalendar=*-*-* 02:30:00
OnCalendar=*-*-* 14:30:00
Persistent=false
RandomizedDelaySec=10min
Unit=xstrm-incremental-refresh.service

[Install]
WantedBy=timers.target
```

Enable it:

```bash
systemctl daemon-reload
systemctl enable --now xstrm-incremental-refresh.timer
```

## Operational Notes

- Keep `max_dirs_per_run` conservative because child directories discovered during a run can now consume the same run budget.
- Use request intervals and jitter to avoid bursty AList access.
- Queue newly pinned directories with `queue-dir`.
- Do not use this as a replacement for full rebuilds. It is for daily small changes.

## 中文说明

`scripts/incremental_strm_refresh.py` 是一个基于队列的增量刷新工具。它不会每次递归扫描所有网盘目录，而是把需要关注的目录放入本地 SQLite 队列，每次只刷新少量候选目录。

适用场景：

- 新剧集被加入到原来的剧集目录中，目录本身没有变化；
- 新增目录需要优先处理；
- Emby 删除了某个本地 `.strm`，但远程媒体仍然存在，需要自动补生成；
- 希望限制 AList 请求量，降低网盘风控风险。

核心机制：

1. `entries` 表记录已见过的远程文件和对应 `.strm`。
2. `dir_queue` 表记录待刷新的目录。
3. 每轮只刷新少量候选目录。
4. 刷新时发现的子目录会加入队列，只要本轮目录预算还够，就可以在同一轮继续处理。
5. 发现新增媒体文件后生成 `.strm`，并记录为活跃条目，供后续复查。
6. 如果数据库已记录媒体文件，但本地 `.strm` 缺失，会自动补生成。

运行配置中可能包含 AList token 和本机路径，请只保留 `config/incremental-strm.json.example`，不要提交真实 `config/incremental-strm.json`。
