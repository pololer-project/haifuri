#!/usr/bin/env python3
"""
MuxTools Automation Script for High School Fleet.

Automates the process of muxing anime episodes using MuxTools.
Optimized for efficiency, readability, and correct resource resolution.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

try:
    from muxtools import (
        AudioFile,
        Chapters,
        GlobSearch,
        Premux,
        Setup,
        SubFile,
        TmdbConfig,
        log,
        mux,
    )
except ImportError as e:
    sys.exit(f"Error: {e}. Run 'uv sync' to install dependencies.")

__all__ = ["RunMode", "ShowConfig", "mux_episode", "main"]


class RunMode(Enum):
    NORMAL = "normal"
    DRYRUN = "dryrun"


@dataclass(frozen=True, slots=True)
class ShowConfig:
    """Immutable configuration for the anime show."""

    name: str
    premux_dir: Path
    audio_dir: Path
    sub_dir: Path
    tmdb_id: int = 0
    titles: tuple[str, ...] = ()

    @classmethod
    def from_defaults(cls) -> ShowConfig:
        """Create configuration relative to the script location."""
        # Resolution relative to script location (root)
        base = Path(__file__).resolve().parent

        return cls(
            name="High School Fleet",
            premux_dir=base / "premux",
            audio_dir=base / "audio",
            sub_dir=base / "subtitle",
            tmdb_id=66105,
            titles=None,
        )


CONFIG = ShowConfig.from_defaults()


@dataclass(slots=True)
class MuxResult:
    episode: str | int
    success: bool
    error: str | None = None


def _get_episode_str(episode: str | int) -> str:
    """Convert episode identifier to standard string format."""
    if isinstance(episode, int):
        return f"{episode:02d}"
    return str(episode)


def _find_video(ep_str: str, config: ShowConfig) -> Path:
    """Find the video file for the given episode string."""
    search = GlobSearch(
        "*.mkv", allow_multiple=True, recursive=True, dir=str(config.premux_dir)
    )

    for p in search.paths:
        name = Path(p).name

        # Standard episode match: " - 01 " or "E01)"
        if f" - {ep_str} " in name or f"E{ep_str})" in name:
            return Path(p)

        # OVA match: "OVA" and " - 01 "
        if ep_str.startswith("OVA") and "OVA" in name:
            ova_num = ep_str.replace("OVA", "")
            if f" - {ova_num:0>2} " in name:
                return Path(p)

        # NC match
        if ep_str.startswith("NC") and ep_str in name:
            return Path(p)

    raise FileNotFoundError(f"Video file not found for episode {ep_str}")


def _find_audio(ep_str: str, config: ShowConfig) -> AudioFile:
    """Find audio files for the given episode string."""
    search = GlobSearch(
        "*.flac", allow_multiple=True, recursive=True, dir=str(config.audio_dir)
    )

    # Filter for exact episode match
    candidates = [p for p in search.paths if f" - {ep_str} " in Path(p).name]

    if not candidates:
        raise FileNotFoundError(f"Audio files not found for episode {ep_str}")

    # Apply -1000ms delay only for NCOP/NCED
    delay = -1000 if ep_str.startswith("NC") else 0
    return AudioFile(candidates, container_delay=delay)


def _find_subtitle(ep_str: str, config: ShowConfig) -> SubFile:
    """Find and prepare the subtitle file."""
    # Special handling for NCOP/NCED
    if ep_str.startswith("NCOP"):
        sub_path = config.sub_dir.parent / "songs" / "OP.ass"
    elif ep_str.startswith("NCED"):
        sub_path = config.sub_dir.parent / "songs" / "ED.ass"
    else:
        # Standard search
        sub_path = config.sub_dir / f"{ep_str}.ass"
        if not sub_path.exists():
            # Fallback to glob search
            search = GlobSearch(f"*{ep_str}*.ass", dir=str(config.sub_dir))
            if not search.paths:
                raise FileNotFoundError(f"Subtitle file not found for episode {ep_str}")
            sub_path = Path(search.paths[0])

    if not sub_path.exists():
        raise FileNotFoundError(f"Subtitle file not found at {sub_path}")

    # Apply -1000ms delay only for NCOP/NCED
    delay = -1000 if ep_str.startswith("NC") else 0
    sub = SubFile(str(sub_path), container_delay=delay)
    # Apply cleaning
    sub.merge(r"common/warning.ass").clean_styles().clean_garbage()
    return sub


def mux_episode(
    episode: str | int,
    out_dir: Path,
    version: int = 1,
    flag: str = "testing",
    mode: RunMode = RunMode.NORMAL,
    config: ShowConfig | None = None,
) -> MuxResult:
    config = config or CONFIG
    ep_str = _get_episode_str(episode)
    version_str = "" if version == 1 else f"v{version}"

    # Title handling
    title = ""
    if (
        isinstance(episode, int)
        and config.titles
        and 1 <= episode <= len(config.titles)
    ):
        title = f" | {config.titles[episode - 1]}"

    setup = Setup(
        ep_str,
        None,
        show_name=config.name,
        out_name=f"[{flag}] $show$ - $ep${version_str} (BDRip 1920x1080 HEVC FLAC) [$crc32$]",
        mkv_title_naming=f"$show$ - $ep${version_str}{title}",
        out_dir=str(out_dir),
        clean_work_dirs=False,
    )

    if mode == RunMode.DRYRUN:
        log.info(f"[Dry Run] Would mux episode {ep_str} to {out_dir}")
        return MuxResult(episode, True)

    try:
        # Locating Resources
        video_file = _find_video(ep_str, config)
        setup.set_default_sub_timesource(video_file)

        audio_files = _find_audio(ep_str, config)
        sub_file = _find_subtitle(ep_str, config)

        # Chapters & Fonts
        if ep_str.startswith("NC"):
            chapters = []
        else:
            chapters = Chapters.from_mkv(video_file)

        font_paths = [
            config.sub_dir / "fonts",
            config.sub_dir.parent / "songs" / "fonts",
        ]
        valid_font_paths = [p for p in font_paths if p.exists()]
        fonts = sub_file.collect_fonts(
            use_system_fonts=False, additional_fonts=valid_font_paths
        )

        # Muxing
        premux = Premux(
            video_file,
            audio=None,
            subtitles=None,
            keep_attachments=False,
            mkvmerge_args=["--no-global-tags", "--no-chapters"],
        )

        mux_args = [
            premux,
            audio_files.to_track("Japanese", "ja", default=True),
            sub_file.to_track(flag, "id", default=True),
            *fonts,
        ]

        if chapters:
            mux_args.append(chapters)

        outfile = mux(
            *mux_args,
            tmdb=TmdbConfig(config.tmdb_id, write_cover=True),
        )
        log.info(f"Muxed: {outfile.name}")
        return MuxResult(episode, True)

    except Exception as e:
        log.error(f"Failed to mux {ep_str}: {e}")
        return MuxResult(episode, False, str(e))


def parse_episodes(arg: str) -> list[str | int]:
    """Parse episode argument into a list of episode identifiers."""
    if arg.lower() == "all":
        # Integer episodes
        eps = {
            int(p.stem[:2])
            for p in CONFIG.sub_dir.glob("*.ass")
            if p.stem[:2].isdigit()
        }
        # String episodes (OVA, NC)
        extras = {
            p.stem for p in CONFIG.sub_dir.glob("*.ass") if not p.stem[:2].isdigit()
        }
        return sorted(list(eps) + list(extras), key=lambda x: str(x))

    eps = []
    for part in arg.split(","):
        part = part.strip()
        if "-" in part and part.replace("-", "").isdigit():
            start, end = map(int, part.split("-"))
            eps.extend(range(start, end + 1))
        elif part.isdigit():
            eps.append(int(part))
        else:
            eps.append(part)

    # Deduplicate while preserving order
    return list(dict.fromkeys(eps))


def main() -> int:
    parser = argparse.ArgumentParser(description="Optimized Mux System")
    parser.add_argument(
        "episodes", help="Episodes to mux (e.g., 1, 1-5, all, OVA1, NCOP)"
    )
    parser.add_argument(
        "outdir",
        nargs="?",
        default="muxed",
        help="Output directory",
    )
    parser.add_argument("-f", "--flag", default="pololer", help="Release group/flag")
    parser.add_argument("-d", "--dry-run", action="store_true", help="Dry run")
    parser.add_argument("-v", "--version", type=int, default=1, help="Version number")

    args = parser.parse_args()

    try:
        episodes = parse_episodes(args.episodes)
    except ValueError:
        log.error("Invalid episode specification")
        return 1

    if not episodes:
        log.error("No episodes found")
        return 1

    out_dir = Path(args.outdir).resolve()
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    results = [
        mux_episode(
            ep,
            out_dir,
            flag=args.flag,
            mode=RunMode.DRYRUN if args.dry_run else RunMode.NORMAL,
            version=args.version,
        )
        for ep in episodes
    ]

    success_count = sum(1 for r in results if r.success)
    log.info(f"Processed {success_count}/{len(results)} episodes successfully.")

    return 0 if success_count == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
