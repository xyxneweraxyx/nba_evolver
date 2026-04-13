"""
data_loader.py — Layer 3: Data Loader
======================================
Loads NBA game JSON files into CDataset structs for C evaluation.

Features:
  - Load training / testing splits from nba_data/
  - Filter by season, by n_games, by game criteria
  - In-memory cache (build CDataset once per session)
  - Optional disk cache (.npy) to skip rebuild on restart
  - Progress reporting
  - Data validation

Usage:
    from data_loader import DataLoader

    loader = DataLoader("./nba_data")
    ds     = loader.get_training()          # full training set
    ds     = loader.get_testing()           # full test set
    ds     = loader.get_season("2021-22")   # one season only
    ds     = loader.get_subset(n=1000)      # first 1000 games (fast filter)
    ds     = loader.get_split("training", seasons=["2021-22","2022-23"])
"""

from __future__ import annotations
import os
import json
import glob
import time
import pickle
import hashlib
from typing import List, Optional, Dict

from nba_engine_binding import (
    CDataset, CGame,
    build_dataset, get_registry,
    MAX_GAMES, MAX_VARS,
)

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

VALID_SPLITS   = ("training", "testing")
CACHE_VERSION  = "v1"   # bump if CDataset layout changes

# ─────────────────────────────────────────────────────────────────────────────
# LOW-LEVEL LOADERS
# ─────────────────────────────────────────────────────────────────────────────

def list_season_dirs(data_dir: str, split: str) -> List[str]:
    """Return sorted list of season directory paths for a given split."""
    base = os.path.join(data_dir, split)
    if not os.path.isdir(base):
        return []
    return sorted(
        os.path.join(base, s) for s in os.listdir(base)
        if os.path.isdir(os.path.join(base, s))
    )

def list_seasons(data_dir: str, split: str) -> List[str]:
    """Return sorted list of season names (e.g. ['2013-14', '2014-15', ...])"""
    return [os.path.basename(d) for d in list_season_dirs(data_dir, split)]

def load_season_games(data_dir: str, split: str, season: str) -> List[dict]:
    """Load all game JSON files for one season."""
    path = os.path.join(data_dir, split, season)
    if not os.path.isdir(path):
        raise FileNotFoundError(f"Season not found: {path}")
    files = sorted(glob.glob(os.path.join(path, "*.json")))
    games = []
    for fp in files:
        with open(fp) as f:
            games.append(json.load(f))
    return games

def load_split_games(data_dir: str, split: str,
                     seasons: Optional[List[str]] = None,
                     verbose: bool = True) -> List[dict]:
    """
    Load all games for a split (training or testing).
    If seasons is specified, load only those seasons.
    """
    avail = list_seasons(data_dir, split)
    if not avail:
        raise FileNotFoundError(f"No seasons found in {data_dir}/{split}/")

    target = seasons if seasons else avail
    missing = [s for s in target if s not in avail]
    if missing:
        raise ValueError(f"Seasons not found: {missing}. Available: {avail}")

    games = []
    for season in target:
        t0 = time.time()
        sg = load_season_games(data_dir, split, season)
        if verbose:
            print(f"    {season}: {len(sg):,} games ({time.time()-t0:.1f}s)")
        games.extend(sg)

    return games

# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def validate_game(game: dict) -> List[str]:
    """
    Validate a single game dict. Returns list of error strings (empty = ok).
    """
    errors = []
    if "result" not in game:
        errors.append("missing 'result'")
        return errors
    if "home" not in game or "away" not in game:
        errors.append("missing 'home' or 'away'")
        return errors

    winner = game["result"].get("winner")
    if winner not in ("home", "away"):
        errors.append(f"invalid winner: {winner!r}")

    for side in ("home", "away"):
        team = game[side]
        if "binary" not in team:
            errors.append(f"{side}: missing 'binary'")
        if "context" not in team:
            errors.append(f"{side}: missing 'context'")

    return errors

def validate_dataset_games(games: List[dict], max_errors: int = 20) -> dict:
    """
    Validate a list of game dicts.
    Returns summary dict with counts and sample errors.
    """
    total     = len(games)
    n_errors  = 0
    samples   = []
    home_wins = 0

    for i, g in enumerate(games):
        errs = validate_game(g)
        if errs:
            n_errors += 1
            if len(samples) < max_errors:
                samples.append({"game_idx": i, "errors": errs})
        else:
            if g["result"]["winner"] == "home":
                home_wins += 1

    valid = total - n_errors
    return {
        "total":          total,
        "valid":          valid,
        "invalid":        n_errors,
        "error_rate":     round(n_errors / total, 4) if total else 0,
        "home_win_pct":   round(home_wins / max(valid, 1), 4),
        "sample_errors":  samples,
    }

def validate_cdataset(ds: CDataset, reg: dict) -> dict:
    """
    Spot-check a CDataset for plausible values.
    Checks a sample of key stat indices.
    """
    issues = []
    checks = {
        "season_stats.off_rtg": (80, 140),
        "season_stats.w_pct":   (0, 1),
        "season_stats.pace":    (85, 115),
        "binary.is_home":       (0, 1),
        "context.rest_days":    (0, 14),
    }

    n_check = min(ds.n_games, 200)
    for name, (lo, hi) in checks.items():
        if name not in reg:
            continue
        idx = reg[name]
        out_of_range = 0
        for i in range(n_check):
            v = ds.games[i].home[idx]
            # Skip 0 (unfilled / None in JSON) — only flag clearly wrong values
            if v != 0.0 and not (lo <= v <= hi):
                out_of_range += 1
        if out_of_range > n_check * 0.30:  # more than 30% out of range
            issues.append(f"{name}[{idx}]: {out_of_range}/{n_check} out of [{lo},{hi}]")

    return {
        "n_games_checked": n_check,
        "issues":          issues,
        "ok":              len(issues) == 0,
    }

# ─────────────────────────────────────────────────────────────────────────────
# DISK CACHE
# ─────────────────────────────────────────────────────────────────────────────

def _cache_key(data_dir: str, split: str,
               seasons: Optional[List[str]]) -> str:
    """Stable cache key based on content."""
    parts = [CACHE_VERSION, data_dir, split]
    if seasons:
        parts.extend(sorted(seasons))
    else:
        parts.extend(list_seasons(data_dir, split))
    return hashlib.md5("|".join(parts).encode()).hexdigest()[:12]

def _cache_path(data_dir: str, split: str,
                seasons: Optional[List[str]]) -> str:
    key = _cache_key(data_dir, split, seasons)
    return os.path.join(data_dir, f".cache_{split}_{key}.pkl")

def save_cache(ds: CDataset, games: List[dict],
               data_dir: str, split: str,
               seasons: Optional[List[str]]):
    """Serialize CDataset + metadata to disk for fast reload."""
    path = _cache_path(data_dir, split, seasons)
    meta = {
        "n_games": ds.n_games,
        "n_vars":  ds.n_vars,
        "split":   split,
        "seasons": seasons,
    }
    # Serialize CDataset as bytes
    import ctypes
    size  = ctypes.sizeof(ds)
    buf   = (ctypes.c_char * size)()
    ctypes.memmove(buf, ctypes.byref(ds), size)
    with open(path, "wb") as f:
        pickle.dump({"meta": meta, "data": bytes(buf)}, f, protocol=4)

def load_cache(data_dir: str, split: str,
               seasons: Optional[List[str]]) -> Optional[CDataset]:
    """Load CDataset from disk cache. Returns None if not found/stale."""
    path = _cache_path(data_dir, split, seasons)
    if not os.path.exists(path):
        return None
    try:
        import ctypes
        with open(path, "rb") as f:
            obj = pickle.load(f)
        ds   = CDataset()
        data = obj["data"]
        size = ctypes.sizeof(ds)
        if len(data) != size:
            return None  # layout changed
        ctypes.memmove(ctypes.byref(ds), data, size)
        ds.n_games = obj["meta"]["n_games"]
        ds.n_vars  = obj["meta"]["n_vars"]
        return ds
    except Exception:
        return None

# ─────────────────────────────────────────────────────────────────────────────
# SUBSET HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def games_to_cdataset(games: List[dict], verbose: bool = False) -> CDataset:
    """
    Convert game dicts to CDataset, with optional progress.
    Thin wrapper around build_dataset().
    """
    n = min(len(games), MAX_GAMES)
    if verbose:
        print(f"  Building CDataset from {n:,} games...", end="", flush=True)
    t0 = time.time()
    ds = build_dataset(games[:n])
    if verbose:
        print(f" {time.time()-t0:.1f}s")
    return ds

def subset_cdataset(ds: CDataset, n: int) -> CDataset:
    """
    Return a view of the first n games without copying 128MB.
    Uses a raw buffer to avoid ctypes zero-initializing the full struct.
    """
    import ctypes
    n = max(1, min(n, ds.n_games))

    # Allocate raw memory without zero-initialization
    buf = ctypes.create_string_buffer(ctypes.sizeof(CDataset))
    # Copy only the n games we need (n * sizeof(CGame) bytes)
    game_size = ctypes.sizeof(CGame)
    ctypes.memmove(buf, ctypes.byref(ds), n * game_size)
    # Cast to CDataset
    sub = ctypes.cast(buf, ctypes.POINTER(CDataset)).contents
    sub.n_games = n
    sub.n_vars  = ds.n_vars
    # Keep buf alive (prevents garbage collection of the memory)
    sub._keep_alive = buf
    return sub

# ─────────────────────────────────────────────────────────────────────────────
# DATA LOADER
# ─────────────────────────────────────────────────────────────────────────────

class DataLoader:
    """
    Main entry point for data loading.
    Caches CDatasets in memory after first build.

    Example:
        loader = DataLoader("./nba_data")
        ds_train = loader.get_training()
        ds_test  = loader.get_testing()
        ds_sub   = loader.get_subset(500)           # quick filter subset
        ds_s     = loader.get_season("2021-22")     # one season
    """

    def __init__(self, data_dir: str,
                 use_disk_cache: bool = True,
                 verbose: bool = True):
        self.data_dir       = os.path.abspath(data_dir)
        self.use_disk_cache = use_disk_cache
        self.verbose        = verbose
        self._reg           = get_registry()

        # In-memory cache: (split, seasons_key) → CDataset
        self._cache: Dict[str, CDataset] = {}
        # Cache available seasons to avoid repeated filesystem I/O
        self._seasons_cache: Dict[str, List[str]] = {}

    # ── public API ────────────────────────────────────────────────────────

    def get_training(self, seasons: Optional[List[str]] = None) -> CDataset:
        """Full training set (or subset of seasons)."""
        return self._load("training", seasons)

    def get_testing(self, seasons: Optional[List[str]] = None) -> CDataset:
        """Full testing set (or subset of seasons)."""
        return self._load("testing", seasons)

    def get_season(self, season: str) -> CDataset:
        """Single season. Auto-detects split."""
        for split in VALID_SPLITS:
            avail = list_seasons(self.data_dir, split)
            if season in avail:
                return self._load(split, [season])
        raise ValueError(f"Season {season!r} not found in any split")

    def get_subset(self, n: int, split: str = "training") -> CDataset:
        """
        Return first n games from the training set.
        Useful for fast exploration (cheap interest filter).
        Doesn't require building the full 128MB CDataset first.
        """
        full = self._load(split, None)
        return subset_cdataset(full, n)

    def get_split(self, split: str,
                  seasons: Optional[List[str]] = None) -> CDataset:
        """Generic split loader."""
        return self._load(split, seasons)

    def available_seasons(self, split: str = "training") -> List[str]:
        """Return list of available season names for a split."""
        if split not in self._seasons_cache:
            self._seasons_cache[split] = list_seasons(self.data_dir, split)
        return self._seasons_cache[split]

    def info(self) -> dict:
        """Return metadata about available data."""
        out = {}
        for split in VALID_SPLITS:
            seasons = self.available_seasons(split)
            total   = 0
            for s in seasons:
                path = os.path.join(self.data_dir, split, s)
                total += len(glob.glob(os.path.join(path, "*.json")))
            out[split] = {"seasons": seasons, "total_games": total}
        return out

    def _cache_key(self, split: str, seasons: Optional[List[str]]) -> str:
        parts = [split] + (seasons or self.available_seasons(split))
        return "|".join(parts)
        """Return metadata about available data."""
        out = {}
        for split in VALID_SPLITS:
            seasons = list_seasons(self.data_dir, split)
            total   = 0
            for s in seasons:
                path = os.path.join(self.data_dir, split, s)
                total += len(glob.glob(os.path.join(path, "*.json")))
            out[split] = {"seasons": seasons, "total_games": total}
        return out

    def validate(self, split: str = "training",
                 seasons: Optional[List[str]] = None) -> dict:
        """
        Validate raw JSON files and the built CDataset.
        Returns a report dict.
        """
        if self.verbose:
            print(f"\nValidating {split}...")

        # Load raw games for JSON validation
        games = load_split_games(self.data_dir, split, seasons,
                                  verbose=self.verbose)
        json_report  = validate_dataset_games(games)

        # Build/get CDataset for value validation
        ds           = self._load(split, seasons)
        cds_report   = validate_cdataset(ds, self._reg)

        return {
            "split":      split,
            "seasons":    seasons or list_seasons(self.data_dir, split),
            "json":       json_report,
            "cdataset":   cds_report,
        }

    def clear_memory_cache(self):
        """Free all in-memory cached CDatasets."""
        self._cache.clear()
        if self.verbose:
            print("Memory cache cleared.")

    def clear_disk_cache(self):
        """Delete all .pkl cache files."""
        for f in glob.glob(os.path.join(self.data_dir, ".cache_*.pkl")):
            os.remove(f)
        if self.verbose:
            print("Disk cache cleared.")

    # ── internals ─────────────────────────────────────────────────────────

    def _load(self, split: str,
              seasons: Optional[List[str]]) -> CDataset:
        key = self._cache_key(split, seasons)

        # 1. Memory cache hit
        if key in self._cache:
            return self._cache[key]

        # 2. Disk cache hit
        if self.use_disk_cache:
            ds = load_cache(self.data_dir, split, seasons)
            if ds is not None:
                if self.verbose:
                    print(f"  [{split}] Loaded from disk cache"
                          f" ({ds.n_games:,} games)")
                self._cache[key] = ds
                return ds

        # 3. Build from JSON files
        if self.verbose:
            label = f"[{split}]" + (f" {seasons}" if seasons else "")
            print(f"\n  {label} Loading JSON files...")

        t0    = time.time()
        games = load_split_games(self.data_dir, split, seasons,
                                  verbose=self.verbose)

        if self.verbose:
            print(f"  Building CDataset ({len(games):,} games)...",
                  end="", flush=True)

        ds = build_dataset(games)

        if self.verbose:
            print(f" {time.time()-t0:.1f}s total")
            print(f"  {ds.n_games:,} games, {ds.n_vars} vars,"
                  f" ~{len(games)*4*MAX_VARS*2//1024//1024}MB in C memory")

        # Save to disk cache
        if self.use_disk_cache:
            try:
                save_cache(ds, games, self.data_dir, split, seasons)
                if self.verbose:
                    print(f"  Disk cache saved.")
            except Exception as e:
                if self.verbose:
                    print(f"  (disk cache save failed: {e})")

        self._cache[key] = ds
        return ds