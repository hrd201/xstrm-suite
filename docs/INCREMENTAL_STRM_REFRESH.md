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
- Main config: `config/strm-sync.yaml`
- Safe example: `config/strm-sync.yaml.example`
- Legacy JSON example: `config/incremental-strm.json.example`
- Suggested state database: `data/incremental-strm.sqlite3`

The runtime config may contain AList tokens and local paths. It is ignored by Git; only commit the `.example` files.

## How It Works

1. `entries` stores known AList files and generated `.strm` paths.
2. `dir_queue` stores candidate directories to refresh.
3. Each run lists only queued directories, up to `incremental_refresh.max_dirs_per_run`.
4. Regular polling only queues new or metadata-changed children. Manual queue requests recurse so a show root reaches existing season folders.
5. New media files generate `.strm` files and are recorded as active entries for later rechecks.
6. If a media file is already indexed but its `.strm` file is missing, the refresher regenerates it.
7. Recently active parents are rechecked frequently; a bounded cold-directory sample provides eventual integrity coverage.
8. Repeated failures move to a dead-letter table instead of retrying forever.
9. Ignored paths are never regenerated, while remote-missing items follow the configured keep, quarantine, or delete policy.

## Configuration

Copy the example:

```bash
cp config/strm-sync.yaml.example config/strm-sync.yaml
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
  --config config/strm-sync.yaml \
  queue-dir "/mnt/cloud/series/Example Show" \
  --reason manual
```

Run one refresh cycle:

```bash
python3 scripts/incremental_strm_refresh.py \
  --config config/strm-sync.yaml \
  run-once
```

Run as a simple daemon with fixed intervals:

```bash
python3 scripts/incremental_strm_refresh.py \
  --config config/strm-sync.yaml \
  daemon --interval-minutes 120
```

Run as a daemon using configured times:

```bash
python3 scripts/incremental_strm_refresh.py \
  --config config/strm-sync.yaml \
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
ExecStart=/opt/xstrm-suite/scripts/task_incremental_refresh.sh
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
```

The wrapper provides a shared write lock and Web task status.

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

- The Web task selector offers `new` (last 24 hours) and `all`. The recent mode refreshes and walks every configured source directory so it can find additions below old parent folders, but only generates media and subtitles inside the time window.
- A recent directory makes its whole subtree eligible. This handles copied season folders whose video files retain old source timestamps.
- CLI equivalent: `python3 scripts/strm_x.py --scan-all --recent-hours 24`.
- Keep `max_dirs_per_run` conservative because child directories discovered during a run can now consume the same run budget.
- New, changed, and never-scanned child directories are prioritized, so a parent scan reaches newly added nested seasons within the same budget.
- Scheduled runs use `max_dirs_per_run` (default 20). Explicit `run-path`/Web scans use `target_max_dirs_per_run` (default 50) and do not enqueue unchanged child directories.
- Incremental scans also download missing subtitle files when `scan.subtitle_sync` is enabled (the default).
- Use request intervals and jitter to avoid bursty AList access.
- A transient timeout or TLS handshake failure gets one delayed retry; persistent failures remain queued for the configured retry window.
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

- Web 扫描模式可选择“新增（最近 24 小时）”或“全部文件”。新增模式会刷新并遍历全部已配置媒体源，以发现旧父目录深处的新增内容，但只生成时间窗口内的视频和字幕；如果目录本身是近期新增，则其全部后代都会纳入。
- 对应命令行为 `python3 scripts/strm_x.py --scan-all --recent-hours 24`。
- 新增、发生变化以及从未实际扫描的子目录会优先于旧目录处理；
- 扫描父级剧集目录时，新加入的剧集/季目录可在同一轮预算内继续向下扫描；
- 定时任务默认最多处理 20 个目录；Web 指定扫描默认最多处理 50 个新增/变化目录，完全未变化的旧目录不会被递归入队；
- `scan.subtitle_sync` 启用时（默认启用），增量扫描也会下载缺失字幕到对应的本地 STRM 目录。
- AList/115 瞬时超时或 TLS 握手失败只会延迟重试一次；持续失败仍按配置进入延迟重试队列，避免无限请求。

1. `entries` 表记录已见过的远程文件和对应 `.strm`。
2. `dir_queue` 表记录待刷新的目录。
3. 每轮只刷新少量候选目录。
4. 刷新时发现的子目录会加入队列，只要本轮目录预算还够，就可以在同一轮继续处理。
5. 发现新增媒体文件后生成 `.strm`，并记录为活跃条目，供后续复查。
6. 如果数据库已记录媒体文件，但本地 `.strm` 缺失，会自动补生成。

运行配置中可能包含 AList token 和本机路径。真实 `config/strm-sync.yaml` 已被 Git 忽略，只提交 `.example` 示例文件。

永久删除某个版本前可执行：

```bash
python3 scripts/incremental_strm_refresh.py --config config/strm-sync.yaml ignore-path "/mnt/cloud/series/Example/Episode.mkv"
```

取消忽略并补生成：

```bash
python3 scripts/incremental_strm_refresh.py --config config/strm-sync.yaml unignore-path "/mnt/cloud/series/Example/Episode.mkv"
```
