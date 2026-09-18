"""Market data layer.

Two providers behind one interface:

* `FredProvider` — REAL market data from FRED (St. Louis Fed), keyless:
  S&P 500, Nasdaq Composite, VIX and the Treasury curve. Official data,
  no API key, with a disk cache to stay polite.
* `SyntheticProvider` — seeded, regime-switching synthetic markets so the
  whole stack is reproducible offline and in tests.

Swap in your own provider (broker feeds, yfinance, vendor APIs) by
implementing `DataProvider`.
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import random
import urllib.request
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from typing import Optional

from aletheia.core.types import Bar, MarketSnapshot

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# FRED series id -> symbol the framework trades
FRED_MAP = {
    "SP500": "SPX",        # S&P 500 index, daily close (last 10y)
    "NASDAQCOM": "NDX",    # Nasdaq Composite
    "DJIA": "DJIA",        # Dow Jones Industrial Average (last 10y)
    "NIKKEI225": "NIKKEI", # Nikkei 225 (daily, back to 1949)
    "VIXCLS": "VIX",       # CBOE volatility index
    "DGS10": "UST10Y",     # 10y Treasury yield
    "DGS2": "UST2Y",       # 2y Treasury yield
}


def _http_get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


class DataProvider(ABC):
    """One method to rule the data layer — implement this to plug in a feed."""

    @abstractmethod
    def get_snapshot(self, symbols: list[str], as_of: date, lookback: int = 260) -> MarketSnapshot:
        ...


# --------------------------------------------------------------------------
# Real data: FRED
# --------------------------------------------------------------------------
class FredProvider(DataProvider):
    """Official, keyless daily market data from the St. Louis Fed (FRED).

    Symbols understood: SPX, NDX, VIX, UST10Y, UST2Y. Responses are cached
    on disk (one file per series per day) so repeated runs are polite and
    fast. FRED's SP500 series covers the most recent 10 years, which is
    exactly what the walk-forward engine wants.
    """

    BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv"

    def __init__(self, cache_dir: str = ".cache/fred") -> None:
        self.cache_dir = cache_dir
        self._memory: dict[str, list[Bar]] = {}

    # -- cache helpers ------------------------------------------------
    def _cache_path(self, series: str, fetched_on: date) -> str:
        """One cache file per series per fetch day."""
        return os.path.join(self.cache_dir, f"{series}_{fetched_on.isoformat()}.csv")

    def _read_stale_cache(self, series: str) -> Optional[list[Bar]]:
        """Newest cached CSV for this series, regardless of fetch day."""
        if not os.path.isdir(self.cache_dir):
            return None
        names = sorted(n for n in os.listdir(self.cache_dir)
                       if n.startswith(f"{series}_") and n.endswith(".csv"))
        for name in reversed(names):
            try:
                with open(os.path.join(self.cache_dir, name), encoding="utf-8") as f:
                    return self._parse_csv(FRED_MAP[series], f.read())
            except (OSError, ValueError):
                continue
        return None

    def _load_series(self, series: str) -> list[Bar]:
        """Load a series from cache or FRED, failing fast when unavailable.

        Order: in-memory cache → any disk cache for the series (newest
        first) → fresh fetch (cached on success). If every route fails,
        raise with an actionable message: a missing series must never
        silently degrade the committee's data to empty bars.
        """
        sym = FRED_MAP[series]
        if series in self._memory:
            return self._memory[series]
        cached = self._read_stale_cache(series)
        if cached is not None:
            self._memory[series] = cached
            return self._memory[series]
        try:
            url = f"{self.BASE}?id={series}"
            raw = _http_get(url).decode("utf-8", errors="replace")
            bars = self._parse_csv(sym, raw)
        except Exception as exc:
            raise RuntimeError(
                f"cannot load FRED series '{series}': {exc}. No cache found "
                f"under '{self.cache_dir}'. Check network access to "
                "fred.stlouisfed.org or pre-populate the cache (README: "
                "'Offline & cold-start')."
            ) from exc
        if not bars:
            raise RuntimeError(
                f"FRED returned no usable rows for series '{series}'; the "
                "series id may have changed — update FRED_MAP."
            )
        os.makedirs(self.cache_dir, exist_ok=True)
        with open(self._cache_path(series, date.today()), "w", encoding="utf-8") as f:
            f.write(raw)
        self._memory[series] = bars
        return bars

    @staticmethod
    def _parse_csv(symbol: str, text: str) -> list[Bar]:
        bars: list[Bar] = []
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            d_raw = (row.get("observation_date") or "").strip()
            if not d_raw:
                continue
            val = (list(row.values())[1] or "").strip()
            if not val or val == ".":
                continue  # missing observation
            try:
                d = datetime.strptime(d_raw, "%Y-%m-%d").date()
                close = float(val)
            except ValueError:
                continue
            bars.append(Bar(symbol=symbol, date=d, open=close, high=close,
                            low=close, close=close, volume=0.0))
        bars.sort(key=lambda b: b.date)
        return bars

    # -- DataProvider --------------------------------------------------
    def get_snapshot(self, symbols: list[str], as_of: date, lookback: int = 260) -> MarketSnapshot:
        bars: dict[str, list[Bar]] = {}
        macro: dict[str, float] = {}
        for series, sym in FRED_MAP.items():
            if sym not in symbols and series not in ("VIXCLS", "DGS10", "DGS2"):
                continue
            series_bars = [b for b in self._load_series(series) if b.date <= as_of]
            if series in ("VIXCLS", "DGS10", "DGS2"):
                if series_bars:
                    macro[sym] = series_bars[-1].close
                continue
            if sym in symbols:
                bars[sym] = series_bars[-lookback:]
        missing = [s for s in symbols if not bars.get(s)]
        if missing:
            raise RuntimeError(
                f"no data for symbol(s) {missing} as of {as_of}; check the "
                "requested date range against series availability."
            )
        return MarketSnapshot(as_of=as_of, bars=bars, macro=macro)


# --------------------------------------------------------------------------
# Synthetic markets (for reproducible tests and offline demos)
# --------------------------------------------------------------------------
class SyntheticProvider(DataProvider):
    """Seeded regime-switching GBM markets. Deterministic given the seed.

    All paths are generated ONCE at construction; every snapshot call slices
    the same cached history, so the engine's view of the world is coherent
    across time (and repeatable across runs).
    """

    def __init__(self, seed: int = 7, n_days: int = 1500,
                 start: date = date(2019, 1, 2), start_px: float = 100.0) -> None:
        self.rng = random.Random(seed)
        self.n_days = n_days
        self.start = start
        self.start_px = start_px
        self._vix: dict[date, float] = {}
        self._cache: dict[str, list[Bar]] = {}
        self._built = False

    def _ensure_built(self) -> None:
        if self._built:
            return
        bars = self._gen_bars("SYN")
        self._cache["SYN"] = bars
        # deterministic per-day VIX from the same stream (no state on read)
        for i, b in enumerate(bars):
            base = 12.0 + 10.0 * abs(math.sin(i / 23.0))
            self._vix[b.date] = round(base + self.rng.gauss(0, 1.5), 2)
        self._built = True

    def _gen_bars(self, symbol: str, drift_scale: float = 1.0) -> list[Bar]:
        px = self.start_px * (0.6 + 0.8 * self.rng.random())
        bars: list[Bar] = []
        regime_drift = 0.0
        regime_vol = 0.012
        d = self.start
        for i in range(self.n_days):
            if self.rng.random() < 0.02:  # regime switch ~ every 50 days
                regime_drift = self.rng.uniform(-0.0006, 0.0009) * drift_scale
                regime_vol = self.rng.uniform(0.008, 0.028)
            shock = self.rng.gauss(regime_drift, regime_vol)
            if self.rng.random() < 0.01:
                shock -= self.rng.uniform(0.02, 0.05)  # crash day
            o = px
            px = max(1.0, px * math.exp(shock))
            hi = max(o, px) * (1 + abs(self.rng.gauss(0, 0.004)))
            lo = min(o, px) * (1 - abs(self.rng.gauss(0, 0.004)))
            bars.append(Bar(symbol=symbol, date=d, open=o, high=hi,
                            low=lo, close=px, volume=float(self.rng.randint(1_000, 9_999))))
            d += timedelta(days=1)
            while d.weekday() >= 5:
                d += timedelta(days=1)
        return bars

    def get_snapshot(self, symbols: list[str], as_of: date, lookback: int = 260) -> MarketSnapshot:
        self._ensure_built()
        bars: dict[str, list[Bar]] = {}
        all_bars = [b for b in self._cache.get("SYN", []) if b.date <= as_of]
        for s in symbols:
            bars[s] = all_bars[-lookback:]
        vix = self._vix.get(as_of, 15.0)
        return MarketSnapshot(
            as_of=as_of, bars=bars,
            macro={"VIX": vix, "UST10Y": 2.5, "UST2Y": 1.5},
        )
