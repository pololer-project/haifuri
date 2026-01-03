#!/usr/bin/env python3
"""
MuxTools Automation Script for Anime Muxing.

Automates the process of muxing anime episodes using MuxTools.
 Optimized for efficiency and relative path resolution.
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
        # Resolution relative to d:\haifuri\ (root)
        base = Path(__file__).resolve().parent

        return cls(
            name="High School Fleet",
            premux_dir=base / "premux",
            audio_dir=base / "audio",
            sub_dir=base / "subtitle",
            tmdb_id=66105,  # Haifuri TMDB ID
            titles=None,
        )


CONFIG = ShowConfig.from_defaults()


@dataclass(slots=True)
class MuxResult:
    episode: int
    success: bool
    error: str | None = None


def _get_episode_str(episode: int) -> str:
    return f"{episode:02d}"


def mux_episode(
    episode: int,
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
    if config.titles and 1 <= episode <= len(config.titles):
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

    # 1. Video
    video_search = GlobSearch(f"*{ep_str}*.mkv", dir=str(config.premux_dir))
    if not video_search.paths:
        return MuxResult(episode, False, "Video file not found")
    video_file = video_search.paths[0]
    setup.set_default_sub_timesource(video_file)

    # 2. Audio
    audio_search = GlobSearch(
        f"*{ep_str}*.flac", allow_multiple=True, dir=str(config.audio_dir)
    )
    if not audio_search.paths:
        return MuxResult(episode, False, "Audio files not found")
    audio_files = AudioFile(audio_search.paths)

    # 3. Subtitles
    # Try looking for "01.ass" or "*01*.ass" in current dir
    sub_path = config.sub_dir / f"{ep_str}.ass"
    if not sub_path.exists():
        # Fallback search if exact match fails
        sub_search = GlobSearch(f"*{ep_str}*.ass", dir=str(config.sub_dir))
        if not sub_search.paths:
            return MuxResult(episode, False, "Subtitle file not found")
        sub_path = Path(sub_search.paths[0])

    sub_file = SubFile(str(sub_path))
    sub_file.merge(r"common/warning.ass").clean_styles().clean_garbage()

    # 4. Chapters & Fonts
    chapters = Chapters.from_mkv(video_file)

    # Collect fonts from 'fonts' folder and songs folder (relative from subtitle dir)
    font_paths = [config.sub_dir / "fonts", config.sub_dir.parent / "songs" / "fonts"]
    valid_font_paths = [p for p in font_paths if p.exists()]
    fonts = sub_file.collect_fonts(
        use_system_fonts=False, additional_fonts=valid_font_paths
    )

    # 5. Mux
    try:
        premux = Premux(
            video_file,
            audio=None,
            subtitles=None,
            keep_attachments=False,
            mkvmerge_args=["--no-global-tags", "--no-chapters"],
        )

        outfile = mux(
            premux,
            audio_files.to_track("Japanese", "ja", default=True),
            sub_file.to_track(flag, "id", default=True),
            *fonts,
            chapters,
            tmdb=TmdbConfig(config.tmdb_id, write_cover=True),
        )
        log.info(f"Muxed: {outfile.name}")
        return MuxResult(episode, True)
    except Exception as e:
        log.error(f"Failed to mux {ep_str}: {e}")
        return MuxResult(episode, False, str(e))


def parse_episodes(arg: str) -> list[int]:
    if arg.lower() == "all":
        # Auto-discovery
        return sorted(
            {
                int(p.stem[:2])
                for p in CONFIG.sub_dir.glob("*.ass")
                if p.stem[:2].isdigit()
            }
        )

    eps = set()
    for part in arg.split(","):
        if "-" in part:
            start, end = map(int, part.split("-"))
            eps.update(range(start, end + 1))
        else:
            eps.add(int(part))
    return sorted(eps)


def main() -> int:
    parser = argparse.ArgumentParser(description="Optimized Mux System")
    parser.add_argument("episodes", help="Episodes to mux (e.g., 1, 1-5, all)")
    parser.add_argument("outdir", nargs="?", default="muxed", help="Output directory")
    parser.add_argument(
        "-f", "--flag", default="BestRelease", help="Release group/flag"
    )
    parser.add_argument("-d", "--dry-run", action="store_true", help="Dry run")
    parser.add_argument("-v", "--version", type=int, default=1, help="Version number")

    args = parser.parse_args()

    try:
        episodes = parse_episodes(args.episodes)
    except ValueError:
        log.error("Invalid episode specifcation")
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
