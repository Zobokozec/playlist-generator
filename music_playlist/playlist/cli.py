"""
CLI rozhraní pro music-playlist generátor.

Použití:
    python -m music_playlist.cli generate --params params.json
    python -m music_playlist.cli generate --params params.json --output ids
    python -m music_playlist.cli generate --params params.json --dry-run
    python -m music_playlist.cli history  --last 5
    python -m music_playlist.cli presets  --list
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _load_params(path: str) -> dict:
    """Načte a validuje params soubor (JSON nebo YAML)."""
    p = Path(path)
    if not p.exists():
        print(f"[ERROR] Soubor nenalezen: {path}", file=sys.stderr)
        sys.exit(1)
    with open(p, encoding="utf-8") as f:
        if p.suffix in (".yaml", ".yml"):
            import yaml
            data = yaml.safe_load(f)
        else:
            data = json.load(f)
    if "duration_sec" not in data:
        print("[ERROR] params chybí povinný klíč: duration_sec", file=sys.stderr)
        sys.exit(1)
    return data


class _StubDB:
    """Stub DB klient – vrací prázdné výsledky (pro nepřipojené DB)."""
    def dotaz_dict(self, *_, **__): return []
    def execute(self, *_, **__): pass
    def commit(self): pass


class _SQLiteClient:
    """Jednoduchý SQLite klient s rozhraním dotaz_dict/execute/commit."""

    def __init__(self, path: str):
        import sqlite3
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row

    def dotaz_dict(self, sql: str, params=None) -> list[dict]:
        cur = self._conn.execute(sql, params or [])
        return [dict(r) for r in cur.fetchall()]

    def execute(self, sql: str, params=None) -> int:
        cur = self._conn.execute(sql, params or [])
        return cur.rowcount

    def commit(self) -> None:
        self._conn.commit()


class _TWRsqlAdapter:
    """Adaptér TWRsql → rozhraní dotaz_dict/execute/commit očekávané pipeline.

    Převádí pojmenované parametry ve stylu :name (SQLite/SQLAlchemy)
    na %(name)s (PyMySQL), který TWRsql/PyMySQL vyžaduje.
    """

    def __init__(self, db):
        self._db = db

    @staticmethod
    def _convert_params(sql: str, params) -> tuple:
        """Převede :name → %(name)s pokud params je dict, jinak vrátí beze změny."""
        import re
        if isinstance(params, dict):
            sql = re.sub(r":(\w+)", r"%(\1)s", sql)
        return sql, params

    def dotaz_dict(self, sql: str, params=None) -> list[dict]:
        sql, params = self._convert_params(sql, params)
        return self._db.query(sql, params, as_dict=True)

    def execute(self, sql: str, params=None) -> int:
        sql, params = self._convert_params(sql, params)
        return self._db.execute(sql, params)

    def commit(self) -> None:
        self._db.cnx.commit()


def _build_context_from_config():
    """Sestaví PlaylistContext z konfigurace."""
    from twrsql import TWRsql
    from music_playlist.config.config import PlaylistConfig
    from music_playlist.playlist.context import PlaylistContext

    cfg = PlaylistConfig.from_toml()

    twar = _TWRsqlAdapter(TWRsql())
    musicdb = _SQLiteClient(cfg.MUSIC_DB)

    # --- Stub klient pro playlistdb (zatím bez skutečné DB) ---
    class _StubDB:
        def dotaz_dict(self, _sql, _params=None):
            return []
        def execute(self, _sql, _params=None):
            pass
        def commit(self):
            pass

    playlistdb = _StubDB()

    return PlaylistContext(twar, musicdb, playlistdb, cfg)


def cmd_generate(args: argparse.Namespace) -> None:
    """Generuje playlist dle params.json."""
    params = _load_params(args.params)
    output_fmt = args.output or params.get("options", {}).get("output", "full")
    dry_run = args.dry_run or params.get("options", {}).get("dry_run", False)

    raw_start = args.start or params.get("scheduled_start") or datetime.now().isoformat()
    scheduled_start = datetime.fromisoformat(raw_start)
    duration_sec = int(params["duration_sec"])

    # Normalizace kvót (string klíče → int)
    raw_quotas = params.get("quotas", {})
    quotas = {int(k): {int(ck): v for ck, v in cv.items()} for k, cv in raw_quotas.items()}

    # Normalizace soft_filter
    raw_sf = params.get("soft_filter", {})
    sf_chars = {int(k): v for k, v in raw_sf.get("chars", {}).items()}
    soft_params = {
        "chars":    sf_chars,
        "duration": raw_sf.get("duration", {}),
        "year":     raw_sf.get("year", {}),
    }

    from music_playlist.config.config import PlaylistConfig
    from music_playlist.playlist.context import PlaylistContext
    from music_playlist.playlist.hard_filter import run_hard_filter
    from music_playlist.playlist.enrich import enrich_tracks
    from music_playlist.playlist.soft_filter import soft_filter
    from music_playlist.playlist.cooldown import apply_cooldown
    from music_playlist.playlist.selector import select_tracks
    from music_playlist.playlist.validator import validate_selected
    from music_playlist.playlist.exporter import GeneratorResult, export_playlist
    from music_playlist.playlist.db import init_db, create_playlist, add_tracks

    cfg = PlaylistConfig.from_toml()
    context = _build_context_from_config()

    if not dry_run:
        conn = init_db(cfg.PLAYLIST_DB)

    # Pipeline
    logger.info("=== INIT ===")
    logger.info("Scheduled: %s, Duration: %ds", scheduled_start, duration_sec)

    logger.info("=== HARD FILTER ===")
    candidates = run_hard_filter(context.twar)
    logger.info("Hard filter: %d kandidátů", len(candidates))

    logger.info("=== ENRICH ===")
    enriched = enrich_tracks(candidates, context)

    logger.info("=== SOFT FILTER ===")
    eligible, soft_excluded = soft_filter(enriched, soft_params)

    logger.info("=== COOLDOWN ===")
    after_cooldown, cd_excluded = apply_cooldown(eligible, scheduled_start, context)

    logger.info("=== SELECTOR ===")
    selected = select_tracks(after_cooldown, quotas, float(duration_sec), cfg.MAX_SELECTOR_ITERATIONS)

    logger.info("=== VALIDACE ===")
    selected_ids = {t["music_id"] for t in selected}
    validated = validate_selected(selected, after_cooldown, selected_ids)

    # Sestavení excluded dict
    excluded: dict[str, list[int]] = {}
    for item in soft_excluded + cd_excluded:
        excluded.setdefault(item["reason"], []).append(item["id"])

    stats = {
        "total_candidates":  len(candidates),
        "after_hard_filter": len(candidates),
        "after_soft_filter": len(eligible),
        "after_cooldown":    len(after_cooldown),
        "selected":          len(validated),
        "total_duration":    sum(
            t.get("net_duration") or t.get("duration", 0) for t in validated
        ),
    }

    playlist_id = 0
    if not dry_run:
        config_json = json.dumps(params.get("quotas", {}), ensure_ascii=False)
        playlist_id = create_playlist(
            conn,
            name=params.get("preset", "default"),
            scheduled_start=scheduled_start.isoformat(),
            duration=duration_sec,
            preset_name=params.get("preset", "default"),
            config_json=config_json,
        )
        add_tracks(conn, playlist_id, [t["music_id"] for t in validated])

    result = GeneratorResult(
        playlist_id=playlist_id,
        selected=validated,
        excluded=excluded,
        stats=stats,
    )

    output = export_playlist(result, context, params, output_fmt, dry_run=dry_run)
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))


def cmd_history(args: argparse.Namespace) -> None:
    """Zobrazí historii posledních N playlistů."""
    from music_playlist.config.config import PlaylistConfig
    from music_playlist.playlist.db import init_db

    cfg = PlaylistConfig.from_toml()
    conn = init_db(cfg.PLAYLIST_DB)
    last = args.last or 5
    rows = conn.execute(
        "SELECT id, name, scheduled_start, total_tracks, actual_duration, status "
        "FROM playlists ORDER BY id DESC LIMIT ?",
        (last,),
    ).fetchall()
    if not rows:
        print("Žádné playlisty v historii.")
        return
    for row in rows:
        print(
            f"#{row['id']:4d}  {row['scheduled_start']}  "
            f"tracks={row['total_tracks']}  dur={row['actual_duration']}s  "
            f"[{row['status']}]  {row['name']}"
        )


def cmd_presets(args: argparse.Namespace) -> None:
    """Zobrazí seznam dostupných presetů."""
    from music_playlist.config.config import PlaylistConfig
    import tomllib

    cfg = PlaylistConfig.from_toml()
    preset_dir = Path(cfg.PRESETS_DIR)
    if not preset_dir.exists():
        print(f"Adresář s presety neexistuje: {preset_dir}")
        return
    presets = sorted(preset_dir.glob("*.yaml")) + sorted(preset_dir.glob("*.toml"))
    if not presets:
        print("Žádné presety nalezeny.")
        return
    for p in presets:
        print(f"  {p.stem}  ({p.suffix})")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m music_playlist.cli",
        description="Music Playlist Generator CLI",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Podrobný výstup")
    sub = parser.add_subparsers(dest="command")

    # generate
    gen = sub.add_parser("generate", help="Vygeneruj playlist")
    gen.add_argument("--params",   required=True, help="Cesta k params souboru (JSON nebo YAML)")
    gen.add_argument("--start",    default=None,  help="Čas vysílání ISO 8601 (výchozí: now)")
    gen.add_argument("--output",   choices=["ids", "full", "debug"], help="Výstupní formát")
    gen.add_argument("--dry-run",  action="store_true", help="Neukládej do DB")

    # history
    hist = sub.add_parser("history", help="Historie playlistů")
    hist.add_argument("--last", type=int, default=5, help="Počet posledních playlistů")

    # presets
    prs = sub.add_parser("presets", help="Správa presetů")
    prs.add_argument("--list", action="store_true", help="Vypíše dostupné presety")

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    if args.command == "generate":
        cmd_generate(args)
    elif args.command == "history":
        cmd_history(args)
    elif args.command == "presets":
        cmd_presets(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
