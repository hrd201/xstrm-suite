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
import shutil
import sqlite3
import sys
import time
from dataclasses import dataclass, field
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

SUBTITLE_EXTENSIONS = {
    ".ass",
    ".idx",
    ".pgs",
    ".smi",
    ".srt",
    ".ssa",
    ".sub",
    ".sup",
    ".vtt",
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
        if part in {".", ".."}:
            raise ValueError(f"unsafe remote path component: {part}")
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
    max_retry_attempts: int
    cold_dir_recheck_days: int
    cold_dirs_per_run: int
    remote_delete_policy: str
    remote_delete_grace_days: int
    schedule_times: list[str]
    include_extensions: set[str]
    exclude_name_contains: list[str]
    subtitle_sync: bool = True
    subtitle_extensions: set[str] = field(default_factory=lambda: set(SUBTITLE_EXTENSIONS))
    target_max_dirs_per_run: int = 50

    @classmethod
    def load(cls, path: Path) -> "Config":
        with path.open("r", encoding="utf-8") as fh:
            if path.name.lower().endswith((".yaml", ".yml", ".yaml.example", ".yml.example")):
                import yaml

                raw = yaml.safe_load(fh) or {}
            else:
                raw = json.load(fh)

        inc = raw.get("incremental_refresh", {})
        alist = raw.get("alist", {}) or {}
        scan = raw.get("scan", {}) or {}
        extensions = raw.get("include_extensions") or scan.get("include_ext") or sorted(VIDEO_EXTENSIONS)
        subtitle_extensions = scan.get("subtitle_exts") or sorted(SUBTITLE_EXTENSIONS)
        sources = []
        for source in raw.get("sources", []):
            scan_path = source.get("scan_path") or source.get("path")
            output_prefix = source.get("output_prefix") or scan_path
            if scan_path and output_prefix:
                sources.append(SourceMapping(normalize_remote_path(scan_path), normalize_remote_path(output_prefix)))

        watch_dirs = [normalize_remote_path(p) for p in (raw.get("watch_dirs") or inc.get("watch_dirs") or [])]
        if not watch_dirs and sources:
            watch_dirs = [source.scan_path for source in sources]

        config = cls(
            alist_base_url=(raw.get("alist_base_url") or alist.get("base_url") or "").rstrip("/") + "/",
            alist_token=raw.get("alist_token") or alist.get("token", ""),
            strm_output_dir=Path(raw.get("strm_output_dir") or raw.get("output_root", "/emby-strm")).expanduser(),
            state_db=Path(raw.get("state_db") or inc.get("state_db", "incremental_strm_state.sqlite3")).expanduser(),
            watch_dirs=watch_dirs,
            sources=sources,
            strm_url_template=raw.get("strm_url_template") or inc.get("strm_url_template", "{media_path}"),
            max_dirs_per_run=int(inc.get("max_dirs_per_run", 20)),
            request_interval_seconds=float(inc.get("request_interval_seconds", 3)),
            jitter_seconds=float(inc.get("jitter_seconds", 10)),
            active_dir_ttl_days=int(inc.get("active_dir_ttl_days", 14)),
            recheck_active_after_hours=int(inc.get("recheck_active_after_hours", 6)),
            retry_after_minutes=int(inc.get("retry_after_minutes", 30)),
            max_retry_attempts=int(inc.get("max_retry_attempts", 3)),
            cold_dir_recheck_days=int(inc.get("cold_dir_recheck_days", 7)),
            cold_dirs_per_run=int(inc.get("cold_dirs_per_run", 4)),
            remote_delete_policy=str(inc.get("remote_delete_policy", "keep")),
            remote_delete_grace_days=int(inc.get("remote_delete_grace_days", 7)),
            schedule_times=list(inc.get("schedule_times", [])),
            include_extensions={ext.lower() for ext in extensions},
            exclude_name_contains=[s.lower() for s in (raw.get("exclude_name_contains") or inc.get("exclude_name_contains", []))],
            subtitle_sync=bool(scan.get("subtitle_sync", True)),
            subtitle_extensions={str(ext).lower() if str(ext).startswith(".") else f".{str(ext).lower()}" for ext in subtitle_extensions},
            target_max_dirs_per_run=int(inc.get("target_max_dirs_per_run", 50)),
        )
        if not config.alist_base_url.strip("/"):
            raise ValueError("AList base URL is required")
        if not config.sources:
            raise ValueError("at least one source mapping is required")
        if config.max_dirs_per_run < 1:
            raise ValueError("max_dirs_per_run must be at least 1")
        if config.target_max_dirs_per_run < 1:
            raise ValueError("target_max_dirs_per_run must be at least 1")
        if config.remote_delete_policy not in {"keep", "quarantine", "delete"}:
            raise ValueError("remote_delete_policy must be keep, quarantine, or delete")
        if config.max_retry_attempts < 1:
            raise ValueError("max_retry_attempts must be at least 1")
        return config


class AlistClient:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url
        self.token = token

    def list_dir(self, path: str, refresh: bool = True) -> list[dict[str, Any]]:
        payload = json.dumps(
            {
                "path": normalize_remote_path(path),
                "password": "",
                "page": 1,
                "per_page": 0,
                # Candidate directories are already rate-limited and budgeted.
                # Refreshing only these directories avoids stale AList listings
                # without recursively refreshing the whole drive.
                "refresh": bool(refresh),
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

        last_error: Exception | None = None
        for attempt in range(2):
            try:
                with urlopen(request, timeout=60) as response:
                    body = response.read().decode("utf-8")
                parsed = json.loads(body)
                if parsed.get("code") in (200, "200"):
                    return parsed.get("data", {}).get("content") or []
                message = str(parsed.get("message") or parsed.get("msg") or parsed)
                error = RuntimeError(f"Alist API error: {message}")
                if not self._is_transient_error(message):
                    raise error
                last_error = error
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                error = RuntimeError(f"Alist HTTP {exc.code}: {detail}")
                if exc.code < 500 or not self._is_transient_error(detail):
                    raise error from exc
                last_error = error
            except (URLError, TimeoutError, OSError) as exc:
                last_error = RuntimeError(f"Alist request failed: {exc}")

            if attempt == 0:
                delay = 5 + random.uniform(0, 3)
                print(f"[WARN] AList 临时连接异常，{delay:.1f} 秒后重试: {path}", file=sys.stderr, flush=True)
                time.sleep(delay)

        raise last_error or RuntimeError("Alist request failed")

    @staticmethod
    def _is_transient_error(message: str) -> bool:
        lowered = message.lower()
        return any(token in lowered for token in (
            "timeout", "timed out", "handshake", "connection reset",
            "connection refused", "temporary", "unexpected eof", "try again",
        ))

    def download_file(self, remote_path: str, target: Path) -> None:
        info_payload = json.dumps({
            "path": normalize_remote_path(remote_path),
            "password": "",
        }).encode("utf-8")
        info_request = Request(
            urljoin(self.base_url, "api/fs/get"),
            data=info_payload,
            headers={"Content-Type": "application/json", "Authorization": self.token},
            method="POST",
        )
        with urlopen(info_request, timeout=60) as response:
            info = json.loads(response.read().decode("utf-8"))
        if info.get("code") not in (200, "200"):
            raise RuntimeError(f"Alist file info error: {info.get('message') or info.get('msg') or info.get('code')}")

        sign = ((info.get("data") or {}).get("sign") or "").strip()
        encoded_path = "/".join(quote(part) for part in normalize_remote_path(remote_path).split("/"))
        download_url = urljoin(self.base_url, "d" + encoded_path)
        params = []
        if sign:
            params.append("sign=" + quote(sign, safe=""))
        if self.token:
            params.append("token=" + quote(self.token, safe=""))
        if params:
            download_url += "?" + "&".join(params)
        download_request = Request(download_url, headers={"Authorization": self.token})
        with urlopen(download_request, timeout=120) as response:
            content_type = response.headers.get("Content-Type", "")
            content = response.read()
        if "application/json" in content_type:
            raise RuntimeError("Alist returned JSON instead of subtitle content")

        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(target)


class State:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        db_path.chmod(0o600)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("pragma journal_mode = wal")
        self.conn.execute("pragma busy_timeout = 5000")
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
                recursive integer not null default 0,
                updated_at text not null
            );

            create table if not exists dead_letter (
                remote_path text primary key,
                reason text not null,
                attempts integer not null,
                failed_at text not null
            );

            create table if not exists ignored_paths (
                remote_path text primary key,
                reason text not null,
                created_at text not null
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
        self._add_column("entries", "last_scanned_at", "text")
        self._add_column("entries", "missing_remote_since", "text")
        self._add_column("dir_queue", "recursive", "integer not null default 0")
        self._add_column("runs", "restored_files", "integer not null default 0")
        self._add_column("runs", "remote_missing", "integer not null default 0")
        self._add_column("runs", "subtitle_downloaded", "integer not null default 0")
        self._add_column("runs", "subtitle_failed", "integer not null default 0")
        self.conn.commit()

    def _add_column(self, table: str, column: str, declaration: str) -> None:
        columns = {row[1] for row in self.conn.execute(f"pragma table_info({table})")}
        if column not in columns:
            self.conn.execute(f"alter table {table} add column {column} {declaration}")

    def start_run(self) -> int:
        cur = self.conn.execute("insert into runs (started_at) values (?)", (utc_now(),))
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, stats: dict[str, int]) -> None:
        self.conn.execute(
            """
            update runs
            set finished_at = ?, dirs_scanned = ?, new_files = ?, new_dirs = ?, errors = ?,
                restored_files = ?, remote_missing = ?, subtitle_downloaded = ?, subtitle_failed = ?
            where id = ?
            """,
            (
                utc_now(),
                stats["dirs_scanned"],
                stats["new_files"],
                stats["new_dirs"],
                stats["errors"],
                stats["restored_files"],
                stats["remote_missing"],
                stats["subtitle_downloaded"],
                stats["subtitle_failed"],
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
        recursive: bool = False,
        revive_dead: bool = False,
    ) -> bool:
        path = normalize_remote_path(remote_path)
        if revive_dead:
            self.conn.execute("delete from dead_letter where remote_path = ?", (path,))
        elif self.conn.execute("select 1 from dead_letter where remote_path = ?", (path,)).fetchone():
            return False
        when = not_before or utc_now()
        self.conn.execute(
            """
            insert into dir_queue (remote_path, reason, priority, not_before, attempts, recursive, updated_at)
            values (?, ?, ?, ?, 0, ?, ?)
            on conflict(remote_path) do update set
                reason = excluded.reason,
                priority = min(dir_queue.priority, excluded.priority),
                not_before = min(dir_queue.not_before, excluded.not_before),
                recursive = max(dir_queue.recursive, excluded.recursive),
                updated_at = excluded.updated_at
            """,
            (path, reason, priority, when, 1 if recursive else 0, utc_now()),
        )
        self.conn.commit()
        return True

    def pop_dirs(self, limit: int) -> list[sqlite3.Row]:
        rows = self.conn.execute(
            """
            select remote_path, reason, attempts, recursive
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
        return rows

    def pop_dirs_under(self, root_path: str, limit: int) -> list[sqlite3.Row]:
        root = normalize_remote_path(root_path)
        prefix = root.rstrip('/') + '/'
        rows = self.conn.execute(
            """
            select remote_path, reason, attempts, recursive
            from dir_queue
            where not_before <= ?
              and (remote_path = ? or substr(remote_path, 1, length(?)) = ?)
            order by priority asc, updated_at asc
            limit ?
            """,
            (utc_now(), root, prefix, prefix, limit),
        ).fetchall()
        paths = [row["remote_path"] for row in rows]
        self.conn.executemany("delete from dir_queue where remote_path = ?", [(p,) for p in paths])
        self.conn.commit()
        return rows

    def mark_dir_failed(
        self,
        path: str,
        reason: str,
        retry_after_minutes: int,
        attempts: int,
        max_attempts: int,
        recursive: bool = False,
    ) -> bool:
        not_before = (datetime.utcnow() + timedelta(minutes=retry_after_minutes)).replace(microsecond=0).isoformat() + "Z"
        attempts += 1
        if attempts >= max_attempts:
            self.conn.execute(
                "insert or replace into dead_letter (remote_path, reason, attempts, failed_at) values (?, ?, ?, ?)",
                (normalize_remote_path(path), reason[:1000], attempts, utc_now()),
            )
            self.conn.commit()
            return True
        priority = min(500, 100 + attempts * 25)
        self.conn.execute(
            """
            insert into dir_queue (remote_path, reason, priority, not_before, attempts, recursive, updated_at)
            values (?, ?, ?, ?, ?, ?, ?)
            on conflict(remote_path) do update set
                reason = excluded.reason,
                priority = excluded.priority,
                not_before = excluded.not_before,
                attempts = excluded.attempts,
                updated_at = excluded.updated_at
            """,
            (normalize_remote_path(path), reason, priority, not_before, attempts, 1 if recursive else 0, utc_now()),
        )
        self.conn.commit()
        return False

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
                size = coalesce(excluded.size, entries.size),
                modified = coalesce(excluded.modified, entries.modified),
                sign = coalesce(excluded.sign, entries.sign),
                strm_path = coalesce(excluded.strm_path, entries.strm_path),
                strm_created = max(entries.strm_created, excluded.strm_created),
                missing_remote_since = null,
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

    def cold_dirs_due(self, recheck_days: int, limit: int) -> list[str]:
        if limit <= 0:
            return []
        due_before = (datetime.utcnow() - timedelta(days=recheck_days)).replace(microsecond=0).isoformat() + "Z"
        rows = self.conn.execute(
            """
            select remote_path from entries
            where is_dir = 1 and (last_scanned_at is null or last_scanned_at <= ?)
            order by coalesce(last_scanned_at, first_seen_at) asc
            limit ?
            """,
            (due_before, limit),
        ).fetchall()
        return [row["remote_path"] for row in rows]

    def mark_dir_scanned(self, path: str) -> None:
        self.conn.execute(
            "update entries set last_scanned_at = ?, last_seen_at = ? where remote_path = ?",
            (utc_now(), utc_now(), normalize_remote_path(path)),
        )
        self.conn.commit()

    def mark_remote_missing(self, parent_path: str, seen_paths: set[str]) -> list[sqlite3.Row]:
        rows = self.conn.execute(
            "select * from entries where parent_path = ? and is_dir = 0",
            (normalize_remote_path(parent_path),),
        ).fetchall()
        missing = [row for row in rows if row["remote_path"] not in seen_paths]
        self.conn.executemany(
            "update entries set missing_remote_since = coalesce(missing_remote_since, ?) where remote_path = ?",
            [(utc_now(), row["remote_path"]) for row in missing],
        )
        self.conn.commit()
        return missing

    def is_ignored(self, path: str) -> bool:
        normalized = normalize_remote_path(path)
        return bool(
            self.conn.execute(
                "select 1 from ignored_paths where ? = remote_path or ? like remote_path || '/%' limit 1",
                (normalized, normalized),
            ).fetchone()
        )

    def set_ignored(self, path: str, reason: str) -> None:
        self.conn.execute(
            "insert or replace into ignored_paths (remote_path, reason, created_at) values (?, ?, ?)",
            (normalize_remote_path(path), reason, utc_now()),
        )
        self.conn.commit()

    def clear_ignored(self, path: str) -> None:
        self.conn.execute("delete from ignored_paths where remote_path = ?", (normalize_remote_path(path),))
        self.conn.commit()

    def strm_paths_under(self, path: str) -> list[str]:
        normalized = normalize_remote_path(path)
        rows = self.conn.execute(
            "select strm_path from entries where strm_path is not null and (remote_path = ? or remote_path like ?)",
            (normalized, normalized.rstrip("/") + "/%"),
        ).fetchall()
        return [row["strm_path"] for row in rows if row["strm_path"]]

    def summary(self) -> dict[str, Any]:
        return {
            "entries": self.conn.execute("select count(*) from entries").fetchone()[0],
            "queued": self.conn.execute("select count(*) from dir_queue").fetchone()[0],
            "dead": self.conn.execute("select count(*) from dead_letter").fetchone()[0],
            "ignored": self.conn.execute("select count(*) from ignored_paths").fetchone()[0],
            "remote_missing": self.conn.execute(
                "select count(*) from entries where missing_remote_since is not null"
            ).fetchone()[0],
        }


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
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(strm_url(remote_path, config) + "\n", encoding="utf-8")
    temporary.replace(target)
    return target


def subtitle_target(remote_path: str, config: Config) -> Path:
    return config.strm_output_dir / safe_rel_path(map_remote_to_media_path(remote_path, config))


def should_sync_subtitle(name: str, config: Config) -> bool:
    return config.subtitle_sync and Path(name).suffix.lower() in config.subtitle_extensions


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
        state.queue_dir(path, "watch_dir", priority=50, recursive=False)


def item_changed(existing: sqlite3.Row | None, size: int | None, modified: str | None, sign: str | None) -> bool:
    if existing is None:
        return True
    return any(
        existing[key] != value
        for key, value in (("size", size), ("modified", modified), ("sign", sign))
        if value is not None
    )


def apply_remote_delete_policy(row: sqlite3.Row, config: Config) -> None:
    if config.remote_delete_policy == "keep" or not row["strm_path"]:
        return
    missing_since = row["missing_remote_since"]
    if not missing_since:
        return
    missing_at = datetime.fromisoformat(missing_since.rstrip("Z"))
    if datetime.utcnow() - missing_at < timedelta(days=config.remote_delete_grace_days):
        return
    target = Path(row["strm_path"])
    if not target.exists():
        return
    if config.remote_delete_policy == "delete":
        target.unlink()
    elif config.remote_delete_policy == "quarantine":
        try:
            relative = target.relative_to(config.strm_output_dir)
        except ValueError:
            relative = safe_rel_path(row["remote_path"]).with_suffix(".strm")
        trash = config.strm_output_dir / ".xstrm-trash" / relative
        trash.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target), str(trash))


def refresh_one_dir(
    client: AlistClient, state: State, config: Config, path: str, recursive: bool = False
) -> dict[str, int]:
    stats = {
        "new_files": 0,
        "restored_files": 0,
        "new_dirs": 0,
        "remote_missing": 0,
        "subtitle_downloaded": 0,
        "subtitle_skipped": 0,
        "subtitle_failed": 0,
    }
    items = client.list_dir(path)
    state.upsert_entry(path, Path(path).name or "/", True, None, None, None)
    seen_paths: set[str] = set()

    for item in items:
        name = item.get("name")
        if not name:
            continue
        child_path = remote_join(path, name)
        seen_paths.add(child_path)
        is_dir = bool(item.get("is_dir"))
        size = item.get("size")
        modified = item.get("modified")
        sign = item.get("sign") or item.get("hashinfo") or item.get("thumb")

        previous = state.get_entry(child_path)
        normalized_sign = str(sign) if sign else None
        changed = item_changed(previous, size, modified, normalized_sign)
        is_new = state.upsert_entry(child_path, name, is_dir, size, modified, normalized_sign)
        if is_dir:
            if is_new:
                stats["new_dirs"] += 1
            never_scanned = previous is None or previous["last_scanned_at"] is None
            if is_new or changed or never_scanned:
                if is_new or never_scanned:
                    priority, reason = 5, "new_unscanned_child"
                elif changed:
                    priority, reason = 15, "changed_child"
                state.queue_dir(
                    child_path,
                    reason,
                    priority=priority,
                    recursive=recursive or is_new,
                )
            continue

        existing = state.get_entry(child_path)
        if state.is_ignored(child_path):
            continue
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
            if is_new:
                stats["new_files"] += 1
            else:
                stats["restored_files"] += 1
        elif should_sync_subtitle(name, config):
            target = subtitle_target(child_path, config)
            if target.exists():
                stats["subtitle_skipped"] += 1
            else:
                try:
                    client.download_file(child_path, target)
                    stats["subtitle_downloaded"] += 1
                    time.sleep(random.uniform(0.5, 1.5))
                except Exception as exc:  # Keep scanning sibling media files.
                    stats["subtitle_failed"] += 1
                    print(f"[WARN] 字幕下载失败 {child_path}: {exc}", file=sys.stderr, flush=True)

    state.mark_dir_scanned(path)
    missing_rows = state.mark_remote_missing(path, seen_paths)
    stats["remote_missing"] = len(missing_rows)
    for row in missing_rows:
        refreshed = state.get_entry(row["remote_path"])
        if refreshed is not None:
            apply_remote_delete_policy(refreshed, config)

    return stats


def run_once(config: Config, target_root: str | None = None) -> dict[str, int]:
    state = State(config.state_db)
    client = AlistClient(config.alist_base_url, config.alist_token)
    target_root = normalize_remote_path(target_root) if target_root else None
    if target_root:
        state.queue_dir(target_root, "web_manual", priority=1, recursive=True, revive_dead=True)
    else:
        seed_watch_dirs(state, config)

        for path in state.active_dirs_due(
            config.active_dir_ttl_days,
            config.recheck_active_after_hours,
            max(1, config.max_dirs_per_run // 2),
        ):
            state.queue_dir(path, "recent_active_dir", priority=45)

        for path in state.cold_dirs_due(config.cold_dir_recheck_days, config.cold_dirs_per_run):
            state.queue_dir(path, "cold_integrity_check", priority=120)

    run_id = state.start_run()
    stats = {
        "dirs_scanned": 0,
        "new_files": 0,
        "restored_files": 0,
        "new_dirs": 0,
        "remote_missing": 0,
        "subtitle_downloaded": 0,
        "subtitle_skipped": 0,
        "subtitle_failed": 0,
        "errors": 0,
    }
    directory_budget = config.target_max_dirs_per_run if target_root else config.max_dirs_per_run
    try:
        while stats["dirs_scanned"] < directory_budget:
            queued = state.pop_dirs_under(target_root, 1) if target_root else state.pop_dirs(1)
            if not queued:
                break
            item = queued[0]
            path = item["remote_path"]
            stats["dirs_scanned"] += 1
            print(
                f'[{stats["dirs_scanned"]}/{directory_budget}] 正在刷新 {path}',
                flush=True,
            )
            try:
                result = refresh_one_dir(client, state, config, path, recursive=bool(item["recursive"]))
                for key in (
                    "new_files", "restored_files", "new_dirs", "remote_missing",
                    "subtitle_downloaded", "subtitle_skipped", "subtitle_failed",
                ):
                    stats[key] += result[key]
                print(
                    f'[{stats["dirs_scanned"]}/{directory_budget}] 完成 {path}: '
                    f'新增 {result["new_files"]}, 补回 {result["restored_files"]}, '
                    f'子目录 {result["new_dirs"]}, 字幕下载 {result["subtitle_downloaded"]}, '
                    f'字幕失败 {result["subtitle_failed"]}',
                    flush=True,
                )
                sleep_for = config.request_interval_seconds + random.uniform(0, config.jitter_seconds)
                if sleep_for > 0:
                    time.sleep(sleep_for)
            except Exception as exc:  # noqa: BLE001 - CLI should continue with other dirs.
                stats["errors"] += 1
                dead = state.mark_dir_failed(
                    path,
                    str(exc),
                    config.retry_after_minutes,
                    int(item["attempts"]),
                    config.max_retry_attempts,
                    bool(item["recursive"]),
                )
                suffix = "; moved to dead letter" if dead else ""
                print(f"[WARN] {path}: {exc}{suffix}", file=sys.stderr)
    finally:
        state.finish_run(run_id, stats)
    return stats


def queue_dir(config: Config, remote_path: str, reason: str) -> None:
    state = State(config.state_db)
    state.queue_dir(remote_path, reason, priority=30, recursive=True, revive_dead=True)
    print(f"queued {normalize_remote_path(remote_path)} ({reason})")


def ignore_path(config: Config, remote_path: str, reason: str) -> None:
    state = State(config.state_db)
    path = normalize_remote_path(remote_path)
    state.set_ignored(path, reason)
    removed = 0
    for strm_path in state.strm_paths_under(path):
        target = Path(strm_path)
        if target.exists():
            target.unlink()
            removed += 1
    print(f"ignored {path} ({reason}); removed {removed} STRM files")


def unignore_path(config: Config, remote_path: str) -> None:
    state = State(config.state_db)
    path = normalize_remote_path(remote_path)
    state.clear_ignored(path)
    state.queue_dir(remote_parent(path), "unignore_parent", priority=25, recursive=False, revive_dead=True)
    print(f"unignored {path}; parent queued")


def show_status(config: Config) -> None:
    print(json.dumps(State(config.state_db).summary(), ensure_ascii=False, indent=2))


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
    parser.add_argument("--config", default="config/strm-sync.yaml", help="Path to YAML or JSON config.")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("run-once", help="Run one incremental refresh cycle.")

    run_path_parser = sub.add_parser("run-path", help="Refresh only one directory tree.")
    run_path_parser.add_argument("remote_path")

    queue_parser = sub.add_parser("queue-dir", help="Add a directory to the high-priority refresh queue.")
    queue_parser.add_argument("remote_path")
    queue_parser.add_argument("--reason", default="manual")

    ignore_parser = sub.add_parser("ignore-path", help="Ignore a remote file or directory and remove its STRM.")
    ignore_parser.add_argument("remote_path")
    ignore_parser.add_argument("--reason", default="manual")

    unignore_parser = sub.add_parser("unignore-path", help="Remove an ignore rule and queue its parent.")
    unignore_parser.add_argument("remote_path")

    sub.add_parser("status", help="Show queue, dead-letter, ignore and remote-missing counts.")

    daemon_parser = sub.add_parser("daemon", help="Run repeatedly with a fixed interval.")
    daemon_parser.add_argument("--interval-minutes", type=int, default=120)
    daemon_parser.add_argument("--schedule", action="store_true", help="Use incremental_refresh.schedule_times from config.")

    args = parser.parse_args()
    config = Config.load(Path(args.config))

    if args.command == "queue-dir":
        queue_dir(config, args.remote_path, args.reason)
        return 0
    if args.command == "ignore-path":
        ignore_path(config, args.remote_path, args.reason)
        return 0
    if args.command == "unignore-path":
        unignore_path(config, args.remote_path)
        return 0
    if args.command == "status":
        show_status(config)
        return 0
    if args.command == "daemon":
        daemon(config, args.interval_minutes, args.schedule)
        return 0

    stats = run_once(config, target_root=args.remote_path if args.command == "run-path" else None)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 2 if stats["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
