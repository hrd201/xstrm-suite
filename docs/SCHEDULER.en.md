# Scheduled scanning

[English](SCHEDULER.en.md) | [中文](SCHEDULER.md)

Each task binds one saved media source and defines timing, scan mode, retry limits and execution timeout. The design references AutoFilm's per-task schedule structure while retaining xstrm's existing Python scanner and subtitle logic.

## Page workflow

Save a source first, then create a task in Scheduled tasks. Choose interval, daily time or Cron; select All files or a 1–720 hour recent window. Enable the task and optionally notify Emby after success. Saving activates the next planned run; Run now is explicit.

All displayed schedule times use Asia/Shanghai. Disabling cancels pending automatic work/retries but does not interrupt a running scan. Manual Run now remains available. Deleting a plan preserves media and history. Changing a source path/output prefix invalidates the old association until it is selected again.

## Timing

- Intervals: 1–43200 minutes, based on initial save/re-enable. Restart preserves future times; missed periods coalesce rather than replaying individually.
- Daily: HH:MM in Asia/Shanghai.
- Cron: five fields are minute/hour/day/month/weekday; six fields prepend a fixed second, 0–59. Fastest recurrence is once per minute.
- Use mon…sun for clarity; 0/7 mean Sunday. Restricted day-of-month and weekday use standard Cron OR semantics.
- Year fields, random/hash fields and sub-minute expressions are rejected.

For example, 0 */6 * * * runs every six hours on the hour; 0 0 20 * * * runs at 20:00:00 daily. A 360-minute interval can have a different phase.

Recent mode still traverses directories to find nested updates. Zero eligible files does not mean an empty source. For initial population, use All files. Scheduling never runs full rebuild or deletes original videos.

## Persistence and failure behavior

Plans live in config/strm-sync.yaml under scheduled_tasks. Source keys derive from source path and output prefix. Runtime queue/history is in data/scheduler.sqlite3. The admin service owns one scheduler and one worker; no additional host Cron is needed. Manual Web scans join the same durable queue. Bash tasks and identification writes also use a shared kernel flock.

Each queued execution freezes a private configuration snapshot. Terminal executions remove snapshots and credentials from queue rows. Restart preserves future plans/history, marks unverifiable running jobs interrupted and does not replay every missed period. Pending work can recover, while changed/disabled automatic plans cancel old queued work.

Retry count is 0–3, delay 1–120 minutes, timeout 1–1440 minutes. A busy write lock defers without consuming a failure retry. Timeout/shutdown terminate process groups. Inaccessible sources and subtitle failures return failure. If scanning succeeds but Emby refresh notification fails, the result is a warning rather than a repeated scan.

## API and backup

GET /api/admin/xstrm/scheduler returns plans, source options, queue size and history. POST scheduler/save and scheduler/delete require a configuration revision. POST scheduler/run enqueues an ID. GET task-run?id=... tracks one execution. Existing Basic Auth and write verification apply.

Back up configuration, scheduler.sqlite3, identity bindings, STRMs and any separate incremental indexes before migration. Linux provides the process/lock integration tests. Small-source tests do not establish full-library throughput or long-term client stability.
