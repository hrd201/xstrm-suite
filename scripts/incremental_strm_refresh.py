#!/usr/bin/env python3
"""
Incremental Alist -> STRM refresher.

The tool keeps a local SQLite index of known Alist files. Each run only lists a
small queue of candidate directories, compares returned items with the index,
and generates .strm files for newly discovered video files.
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen


VIDEO_EXTENSIONS = {
    ".3g2",
    ".3gp",
    ".avi",
    ".flv",
    ".m2ts",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".mts",
    ".rmvb",
    ".ts",
    ".webm",
    ".wmv",
}


def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def normalize_remote_path(path: str) -> str:
    path = "/" + path.strip("/")
    return "/" if path == "/" else path.rstrip("/")


def remote_parent(path: str) -> str:
    path = normalize_remote_path(path)
    if path == "/":
        return "/"
    parent = path.rsplit("/", 1)[0]
    return parent or "/"


def remote_join(parent: str, name: str) -> str:
    parent = normalize_remote_path(parent)
    if parent == "/":
        return "/" + name.strip("/")
    return parent + "/" + name.strip("/")


def safe_rel_path(remote_path: str) -> Path:
    parts = [part for part in normalize_remote_path(remote_path).split("/") if part]
    safe_parts = []
    for part in parts:
        safe = part.replace(":", "_").replace("\\", "_")
        safe_parts.append(safe)
    return Path(*safe_parts)


def encode_remote_path(path: str) -> str:
    return "/".join(quote(part) for part in normalize_remote_path(path).split("/"))


@dataclass
class SourceMapping:
    scan_path: str
    output_prefix: str


@dataclass
class Config:
    alist_base_url: str
    alist_token: str
    strm_output_dir: Path
    state_db: Path
    watch_dirs: list[str]
    sources: list[SourceMapping]
    strm_url_template: str
    max_dirs_per_run: int
    request_interval_seconds: float
    jitter_seconds: float
    active_dir_ttl_days: int
    recheck_active_after_hours: int
    retry_after_minutes: int
    schedule_times: list[str]
    include_extensions: set[str]
    exclude_name_contains: list[str]

    @classmethod
    def load(cls, path: Path) -> "Config":
        with path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)

        inc = raw.get("incremental_refresh", {})
        extensions = raw.get("include_extensions") or sorted(VIDEO_EXTENSIONS)
        sources = []
        for source in raw.get("sources", []):
            scan_path = source.get("scan_path") or source.get("path")
            output_prefix = source.get("output_prefix") or scan_path
            if scan_path and output_prefix:
                sources.append(SourceMapping(normalize_remote_path(scan_path), normalize_remote_path(output_prefix)))

        watch_dirs = [normalize_remote_path(p) for p in raw.get("watch_dirs", [])]
        if not watch_dirs and sources:
            watch_dirs = [source.scan_path for source in sources]

        return cls(
            alist_base_url=raw["alist_base_url"].rstrip("/") + "/",
            alist_token=raw.get("alist_token", ""),
            strm_output_dir=Path(raw["strm_output_dir"]).expanduser(),
            state_db=Path(raw.get("state_db", "incremental_strm_state.sqlite3")).expanduser(),
            watch_dirs=watch_dirs,
            sources=sources,
            strm_url_template=raw.get("strm_url_template", "{alist_base_url}d{remote_path}"),
            max_dirs_per_run=int(inc.get("max_dirs_per_run", 20)),
            request_interval_seconds=float(inc.get("request_interval_seconds", 3)),
            jitter_seconds=float(inc.get("jitter_seconds", 10)),
            active_dir_ttl_days=int(inc.get("active_dir_ttl_days", 14)),
            recheck_active_after_hours=int(inc.get("recheck_active_after_hours", 6)),
            retry_after_minutes=int(inc.get("retry_after_minutes", 30)),
            schedule_times=list(inc.get("schedule_times", [])),
            include_extensions={ext.lower() for ext in extensions},
            exclude_name_contains=[s.lower() for s in raw.get("exclude_name_contains", [])],
        )


class AlistClient:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url
        self.token = token

    def list_dir(self, path: str) -> list[dict[str, Any]]:
        payload = json.dumps(
            {
                "path": normalize_remote_path(path),
                "password": "",
                "page": 1,
                "per_page": 0,
                "refresh": False,
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = self.token
        request = Request(
            urljoin(self.base_url, "api/fs/list"),
            data=payload,
            headers=headers,
            method="POST",
        )

        try:
            with urlopen(request, timeout=60) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Alist HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Alist request failed: {exc.reason}") from exc

        parsed = json.loads(body)
        if parsed.get("code") not in (200, "200"):
            raise RuntimeError(f"Alist API error: {parsed}")
        content = parsed.get("data", {}).get("content") or []
        return content


class State:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.init_schema()

    def init_schema(self) -> None:
        self.conn.executescript(
            """
            create table if not exists entries (
                remote_path text primary key,
                parent_path text not null,
                name text not null,
                is_dir integer not null,
                size integer,
                modified text,
                sign text,
                strm_path text,
                strm_created integer not null default 0,
                first_seen_at text not null,
                last_seen_at text not null
            );

            create table if not exists dir_queue (
                remote_path text primary key,
                reason text not null,
                priority integer not null default 100,
                not_before text not null,
                attempts integer not null default 0,
                updated_at text not null
            );

            create table if not exists runs (
                id integer primary key autoincrement,
                started_at text not null,
                finished_at text,
                dirs_scanned integer not null default 0,
                new_files integer not null default 0,
                new_dirs integer not null default 0,
                errors integer not null default 0
            );
            """
        )
        self.conn.commit()

    def start_run(self) -> int:
        cur = self.conn.execute("insert into runs (started_at) values (?)", (utc_now(),))
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, stats: dict[str, int]) -> None:
        self.conn.execute(
            """
            update runs
            set finished_at = ?, dirs_scanned = ?, new_files = ?, new_dirs = ?, errors = ?
            where id = ?
            """,
            (
                utc_now(),
                stats["dirs_scanned"],
                stats["new_files"],
                stats["new_dirs"],
                stats["errors"],
                run_id,
            ),
        )
        self.conn.commit()

    def queue_dir(
        self,
        remote_path: str,
        reason: str,
        priority: int = 100,
        not_before: str | None = None,
    ) -> None:
        path = normalize_remote_path(remote_path)
        when = not_before or utc_now()
        self.conn.execute(
            """
            insert into dir_queue (remote_path, reason, priority, not_before, attempts, updated_at)
            values (?, ?, ?, ?, 0, ?)
            on conflict(remote_path) do update set
                reason = excluded.reason,
                priority = min(dir_queue.priority, excluded.priority),
                not_before = min(dir_queue.not_before, excluded.not_before),
                updated_at = excluded.updated_at
            """,
            (path, reason, priority, when, utc_now()),
        )
        self.conn.commit()

    def pop_dirs(self, limit: int) -> list[str]:
        rows = self.conn.execute(
            """
            select remote_path
            from dir_queue
            where not_before <= ?
            order by priority asc, updated_at asc
            limit ?
            """,
            (utc_now(), limit),
        ).fetchall()
        paths = [row["remote_path"] for row in rows]
        self.conn.executemany("delete from dir_queue where remote_path = ?", [(p,) for p in paths])
        self.conn.commit()
        return paths

    def mark_dir_failed(self, path: str, reason: str, retry_after_minutes: int) -> None:
        not_before = (datetime.utcnow() + timedelta(minutes=retry_after_minutes)).replace(microsecond=0).isoformat() + "Z"
        row = self.conn.execute(
            "select attempts from dir_queue where remote_path = ?",
            (normalize_remote_path(path),),
        ).fetchone()
        attempts = int(row["attempts"]) + 1 if row else 1
        priority = min(500, 100 + attempts * 25)
        self.conn.execute(
            """
            insert into dir_queue (remote_path, reason, priority, not_before, attempts, updated_at)
            values (?, ?, ?, ?, ?, ?)
            on conflict(remote_path) do update set
                reason = excluded.reason,
                priority = excluded.priority,
                not_before = excluded.not_before,
                attempts = excluded.attempts,
                updated_at = excluded.updated_at
            """,
            (normalize_remote_path(path), reason, priority, not_before, attempts, utc_now()),
        )
        self.conn.commit()

    def get_entry(self, path: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "select * from entries where remote_path = ?",
            (normalize_remote_path(path),),
        ).fetchone()

    def upsert_entry(
        self,
        remote_path: str,
        name: str,
        is_dir: bool,
        size: int | None,
        modified: str | None,
        sign: str | None,
        strm_path: str | None = None,
        strm_created: bool = False,
    ) -> bool:
        path = normalize_remote_path(remote_path)
        existing = self.get_entry(path)
        first_seen = existing["first_seen_at"] if existing else utc_now()
        self.conn.execute(
            """
            insert into entries (
                remote_path, parent_path, name, is_dir, size, modified, sign,
                strm_path, strm_created, first_seen_at, last_seen_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(remote_path) do update set
                parent_path = excluded.parent_path,
                name = excluded.name,
                is_dir = excluded.is_dir,
                size = excluded.size,
                modified = excluded.modified,
                sign = excluded.sign,
                strm_path = coalesce(excluded.strm_path, entries.strm_path),
                strm_created = max(entries.strm_created, excluded.strm_created),
                last_seen_at = excluded.last_seen_at
            """,
            (
                path,
                remote_parent(path),
                name,
                1 if is_dir else 0,
                size,
                modified,
                sign,
                strm_path,
                1 if strm_created else 0,
                first_seen,
                utc_now(),
            ),
        )
        self.conn.commit()
        return existing is None

    def active_dirs_due(self, ttl_days: int, recheck_after_hours: int, limit: int) -> list[str]:
        cutoff = (datetime.utcnow() - timedelta(days=ttl_days)).replace(microsecond=0).isoformat() + "Z"
        due_before = (datetime.utcnow() - timedelta(hours=recheck_after_hours)).replace(microsecond=0).isoformat() + "Z"
        rows = self.conn.execute(
            """
            select distinct parent_path
            from entries
            where is_dir = 0 and first_seen_at >= ? and last_seen_at <= ?
            order by last_seen_at asc
            limit ?
            """,
            (cutoff, due_before, limit),
        ).fetchall()
        return [row["parent_path"] for row in rows]


def should_generate_strm(name: str, config: Config) -> bool:
    lowered = name.lower()
    if any(fragment in lowered for fragment in config.exclude_name_contains):
        return False
    return Path(name).suffix.lower() in config.include_extensions


def strm_url(remote_path: str, config: Config) -> str:
    media_path = map_remote_to_media_path(remote_path, config)
    encoded_path = encode_remote_path(remote_path)
    return config.strm_url_template.format(
        alist_base_url=config.alist_base_url.rstrip("/") + "/",
        remote_path=encoded_path,
        raw_remote_path=normalize_remote_path(remote_path),
        media_path=media_path,
    )


def map_remote_to_media_path(remote_path: str, config: Config) -> str:
    remote_path = normalize_remote_path(remote_path)
    for source in sorted(config.sources, key=lambda src: len(src.scan_path), reverse=True):
        scan_path = source.scan_path.rstrip("/")
        if remote_path == scan_path:
            rel = ""
        elif remote_path.startswith(scan_path + "/"):
            rel = remote_path[len(scan_path) :].lstrip("/")
        else:
            continue
        if rel:
            return f"{source.output_prefix.rstrip('/')}/{rel}".replace("//", "/")
        return source.output_prefix or "/"
    return remote_path


def write_strm(remote_path: str, config: Config) -> Path:
    media_path = map_remote_to_media_path(remote_path, config)
    rel = safe_rel_path(media_path).with_suffix(".strm")
    target = config.strm_output_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(strm_url(remote_path, config) + "\n", encoding="utf-8")
    return target


def needs_strm(existing: sqlite3.Row | None, is_new: bool) -> bool:
    if is_new or existing is None:
        return True
    if not bool(existing["strm_created"]):
        return True
    strm_path = existing["strm_path"]
    if not strm_path:
        return True
    return not Path(strm_path).exists()


def seed_watch_dirs(state: State, config: Config) -> None:
    for path in config.watch_dirs:
        state.queue_dir(path, "watch_dir", priority=50)


def refresh_one_dir(client: AlistClient, state: State, config: Config, path: str) -> dict[str, int]:
    stats = {"new_files": 0, "new_dirs": 0}
    items = client.list_dir(path)
    state.upsert_entry(path, Path(path).name or "/", True, None, None, None)

    for item in items:
        name = item.get("name")
        if not name:
            continue
        child_path = remote_join(path, name)
        is_dir = bool(item.get("is_dir"))
        size = item.get("size")
        modified = item.get("modified")
        sign = item.get("sign") or item.get("hashinfo") or item.get("thumb")

        is_new = state.upsert_entry(child_path, name, is_dir, size, modified, str(sign) if sign else None)
        if is_dir:
            if is_new:
                stats["new_dirs"] += 1
                state.queue_dir(child_path, "new_dir", priority=60)
            continue

        existing = state.get_entry(child_path)
        if should_generate_strm(name, config) and needs_strm(existing, is_new):
            target = write_strm(child_path, config)
            state.upsert_entry(
                child_path,
                name,
                False,
                size,
                modified,
                str(sign) if sign else None,
                str(target),
                True,
            )
            stats["new_files"] += 1
            state.queue_dir(remote_parent(child_path), "active_parent_new_file", priority=70)

    return stats


def run_once(config: Config) -> dict[str, int]:
    state = State(config.state_db)
    client = AlistClient(config.alist_base_url, config.alist_token)
    seed_watch_dirs(state, config)

    for path in state.active_dirs_due(
        config.active_dir_ttl_days,
        config.recheck_active_after_hours,
        max(1, config.max_dirs_per_run // 2),
    ):
        state.queue_dir(path, "recent_active_dir", priority=90)

    run_id = state.start_run()
    stats = {"dirs_scanned": 0, "new_files": 0, "new_dirs": 0, "errors": 0}
    try:
        for path in state.pop_dirs(config.max_dirs_per_run):
            try:
                result = refresh_one_dir(client, state, config, path)
                stats["dirs_scanned"] += 1
                stats["new_files"] += result["new_files"]
                stats["new_dirs"] += result["new_dirs"]
                sleep_for = config.request_interval_seconds + random.uniform(0, config.jitter_seconds)
                if sleep_for > 0:
                    time.sleep(sleep_for)
            except Exception as exc:  # noqa: BLE001 - CLI should continue with other dirs.
                stats["errors"] += 1
                state.mark_dir_failed(path, str(exc), config.retry_after_minutes)
                print(f"[WARN] {path}: {exc}", file=sys.stderr)
    finally:
        state.finish_run(run_id, stats)
    return stats


def queue_dir(config: Config, remote_path: str, reason: str) -> None:
    state = State(config.state_db)
    state.queue_dir(remote_path, reason, priority=40)
    print(f"queued {normalize_remote_path(remote_path)} ({reason})")


def seconds_until_next_schedule(schedule_times: list[str]) -> int:
    now = datetime.now()
    candidates = []
    for item in schedule_times:
        hour_text, minute_text = item.split(":", 1)
        candidate = now.replace(
            hour=int(hour_text),
            minute=int(minute_text),
            second=0,
            microsecond=0,
        )
        if candidate <= now:
            candidate += timedelta(days=1)
        candidates.append(candidate)
    if not candidates:
        return 0
    return max(1, int((min(candidates) - now).total_seconds()))


def daemon(config: Config, interval_minutes: int, use_schedule: bool) -> None:
    if use_schedule and not config.schedule_times:
        raise RuntimeError("schedule mode requires incremental_refresh.schedule_times in config")

    while True:
        if use_schedule:
            wait_seconds = seconds_until_next_schedule(config.schedule_times)
            next_at = datetime.now() + timedelta(seconds=wait_seconds)
            print(f"[{utc_now()}] waiting until {next_at.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
            time.sleep(wait_seconds)

        started = utc_now()
        print(f"[{started}] incremental refresh started", flush=True)
        stats = run_once(config)
        print(f"[{utc_now()}] incremental refresh finished: {stats}", flush=True)
        if not use_schedule:
            time.sleep(max(60, interval_minutes * 60))


def main() -> int:
    parser = argparse.ArgumentParser(description="Incrementally refresh Alist files into STRM files.")
    parser.add_argument("--config", default="config.incremental-strm.json", help="Path to JSON config.")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("run-once", help="Run one incremental refresh cycle.")

    queue_parser = sub.add_parser("queue-dir", help="Add a directory to the high-priority refresh queue.")
    queue_parser.add_argument("remote_path")
    queue_parser.add_argument("--reason", default="manual")

    daemon_parser = sub.add_parser("daemon", help="Run repeatedly with a fixed interval.")
    daemon_parser.add_argument("--interval-minutes", type=int, default=120)
    daemon_parser.add_argument("--schedule", action="store_true", help="Use incremental_refresh.schedule_times from config.")

    args = parser.parse_args()
    config = Config.load(Path(args.config))

    if args.command == "queue-dir":
        queue_dir(config, args.remote_path, args.reason)
        return 0
    if args.command == "daemon":
        daemon(config, args.interval_minutes, args.schedule)
        return 0

    stats = run_once(config)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
