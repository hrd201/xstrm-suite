"""STRM file generator."""
from pathlib import Path
from typing import Optional


def normalize_output_path(output_root: str, media_path: str) -> Path:
    """Normalize output .strm file path from media path.

    Args:
        output_root: Root directory for .strm files (e.g., /emby-strm)
        media_path: Media file logical path (e.g., /115/电影/avatar.mkv)

    Returns:
        Path to .strm file
    """
    relative = media_path.lstrip('/')
    return Path(output_root) / Path(relative).with_suffix('.strm')


def resolve_strm_target(config: dict, media_path: str, full_path: str) -> str:
    """Resolve the target path to write into .strm file.

    In AList directory scan mode, the .strm content is the logical path itself.

    Args:
        config: Configuration dict
        media_path: Logical media path
        full_path: Full AList path

    Returns:
        Target path to write into .strm
    """
    return media_path


def generate_one(output_root: str, media_path: str, target_path: str) -> Path:
    """Generate a single .strm file.

    Args:
        output_root: Root directory for .strm files
        media_path: Logical media path (for output path calculation)
        target_path: Content to write into .strm file

    Returns:
        Path to generated .strm file
    """
    out = normalize_output_path(output_root, media_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(target_path, encoding='utf-8')
    print(f'已生成: {out}')
    return out


def map_scan_to_media(scan_path: str, output_prefix: str, full_path: str) -> str:
    """Map AList full path to media path based on scan_path and output_prefix.

    Args:
        scan_path: Original scan path (e.g., /mnt/115/电影)
        output_prefix: Output prefix (e.g., /115/电影)
        full_path: Full AList path (e.g., /mnt/115/电影/avatar.mkv)

    Returns:
        Mapped media path (e.g., /115/电影/avatar.mkv)
    """
    prefix = scan_path.rstrip('/')
    rel = full_path[len(prefix):].lstrip('/') if full_path.startswith(prefix + '/') else Path(full_path).name
    return f"{output_prefix.rstrip('/')}/{rel}".replace('//', '/')
