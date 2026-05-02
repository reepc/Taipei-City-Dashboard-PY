"""Geocode Taipei 集會遊行 ral_address1/ral_address2 to road + lon/lat.

Usage:
    python geocode_ral_addresses.py input.json [--out result.json] [--provider photon|mapbox]
                                               [--token MAPBOX_TOKEN] [--field ral_address1]
                                               [--limit N] [--sleep 0.5]

Input: JSON list of records with `ral_address1` (and optional `ral_address2`).
Output: JSON list, each record annotated with `geo` field:
    {"query": "...", "road": "...", "house": "...", "district": "...",
     "lon": 121.x, "lat": 25.x, "provider": "photon"|"mapbox", "raw": {...}}
or `geo: null` on miss.
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request

import httpx

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False


class _FallbackBar:
    def __init__(self, total, desc="geocode"):
        self.total = total
        self.desc = desc
        self.n = 0
        self.start = time.time()
        self.postfix = ""
        self._render()

    def _render(self):
        width = 30
        frac = self.n / self.total if self.total else 1.0
        filled = int(width * frac)
        bar = "█" * filled + "░" * (width - filled)
        elapsed = time.time() - self.start
        rate = self.n / elapsed if elapsed > 0 else 0
        eta = (self.total - self.n) / rate if rate > 0 else 0
        sys.stderr.write(
            f"\r{self.desc} |{bar}| {self.n}/{self.total} "
            f"[{elapsed:5.1f}s<{eta:5.1f}s, {rate:4.1f}it/s] {self.postfix}"
        )
        sys.stderr.flush()

    def update(self, n=1):
        self.n += n
        self._render()

    def set_postfix_str(self, s):
        self.postfix = s
        self._render()

    def write(self, msg):
        sys.stderr.write("\r" + " " * 100 + "\r" + msg + "\n")
        self._render()

    def close(self):
        sys.stderr.write("\n")
        sys.stderr.flush()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def make_bar(total, desc="geocode", disable=False):
    if disable:
        class _Null:
            def update(self, n=1): pass
            def set_postfix_str(self, s): pass
            def write(self, m): print(m, file=sys.stderr)
            def close(self): pass
            def __enter__(self): return self
            def __exit__(self, *a): pass
        return _Null()
    if HAS_TQDM:
        return tqdm(total=total, desc=desc, unit="addr", file=sys.stderr,
                    bar_format="{desc} |{bar}| {n_fmt}/{total_fmt} "
                               "[{elapsed}<{remaining}, {rate_fmt}] {postfix}")
    return _FallbackBar(total, desc)

DISTRICTS = [
    "大安區", "松山區", "中山區", "萬華區", "大同區", "北投區", "信義區",
    "中正區", "內湖區", "南港區", "士林區", "文山區",
]
CITY_PREFIXES = ["臺北市", "台北市"]


def normalize_fullwidth(s: str) -> str:
    out = []
    for ch in s:
        cp = ord(ch)
        if 0xFF10 <= cp <= 0xFF19 or 0xFF21 <= cp <= 0xFF5A:
            out.append(chr(cp - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def clean_address(addr: str) -> str:
    if not addr:
        return ""
    s = normalize_fullwidth(addr)
    s = s.replace("自門牌號至門牌號", "").strip()
    for cp in CITY_PREFIXES:
        if s.startswith(cp):
            s = s[len(cp):]
            break
    s = re.split(r"[,，、]", s)[0].strip()
    s = re.sub(r"(\d+號)至\d+號", r"\1", s)
    s = re.sub(r"(\d+)至(\d+)號", r"\1號", s)
    for d in DISTRICTS:
        if s.startswith(d):
            s = d + " " + s[len(d):]
            break
    s = re.sub(r"([^\d\s])(\d+號)", r"\1 \2", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# Taipei proximity + Taiwan bbox for landmark search
TPE_LAT, TPE_LON = 25.04, 121.55
TW_BBOX = "119.5,21.5,122.5,25.5"

PHOTON_URL = "https://photon.komoot.io/api/"
MAPBOX_URL_TPL = "https://api.mapbox.com/geocoding/v5/mapbox.places/{q}.json"

# Photon's hosted instance returns 403 when the request looks like a bot
# (default httpx UA). A plain UA string is enough to satisfy it.
_GEOCODE_HEADERS = {
    "User-Agent": "taipei-city-dashboard-py/1.0 (geocode tool)",
    "Accept": "application/json",
}


def _photon_params(query: str, mode: str) -> dict:
    params = {"q": query, "limit": "1", "lang": "default"}
    if mode == "landmark":
        params.update({"lat": str(TPE_LAT), "lon": str(TPE_LON), "bbox": TW_BBOX})
    return params


def _parse_photon(data: dict) -> dict | None:
    feats = data.get("features", [])
    if not feats:
        return None
    f = feats[0]
    p = f["properties"]
    c = f["geometry"]["coordinates"]
    return {
        "name": p.get("name"),
        "road": p.get("street"),
        "house": p.get("housenumber"),
        "district": p.get("district"),
        "city": p.get("city"),
        "kind": f"{p.get('osm_key','')}/{p.get('osm_value','')}",
        "lon": c[0],
        "lat": c[1],
        "provider": "photon",
        "raw": p,
    }


def _mapbox_params(token: str, mode: str) -> dict:
    params = {
        "language": "zh-TW",
        "country": "tw",
        "limit": "1",
        "access_token": token,
    }
    if mode == "landmark":
        params["proximity"] = f"{TPE_LON},{TPE_LAT}"
        params["types"] = "poi,address,place,locality,neighborhood"
    return params


def _parse_mapbox(data: dict) -> dict | None:
    feats = data.get("features", [])
    if not feats:
        return None
    f = feats[0]
    ctx = {c["id"].split(".")[0]: c.get("text") for c in f.get("context", [])}
    lon, lat = f["center"]
    return {
        "name": f.get("text"),
        "road": ctx.get("street") or f.get("text"),
        "house": f.get("address"),
        "district": ctx.get("locality") or ctx.get("district"),
        "city": ctx.get("place") or ctx.get("region"),
        "kind": ",".join(f.get("place_type", [])),
        "lon": lon,
        "lat": lat,
        "provider": "mapbox",
        "raw": {"place_name": f.get("place_name"), "place_type": f.get("place_type")},
    }


def geocode_photon(query: str, mode: str = "address", timeout: int = 10):
    url = PHOTON_URL + "?" + urllib.parse.urlencode(_photon_params(query, mode))
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return _parse_photon(json.load(r))


def geocode_mapbox(query: str, token: str, mode: str = "address", timeout: int = 10):
    url = MAPBOX_URL_TPL.format(q=urllib.parse.quote(query)) + "?" + \
          urllib.parse.urlencode(_mapbox_params(token, mode))
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return _parse_mapbox(json.load(r))


def geocode(query: str, provider: str, token: str | None, mode: str = "address"):
    if provider == "mapbox":
        if not token:
            raise SystemExit("mapbox requires --token")
        return geocode_mapbox(query, token, mode=mode)
    return geocode_photon(query, mode=mode)


async def async_geocode_photon(
    query: str, mode: str = "address", timeout: float = 10.0
) -> dict | None:
    async with httpx.AsyncClient(timeout=timeout, headers=_GEOCODE_HEADERS) as client:
        r = await client.get(PHOTON_URL, params=_photon_params(query, mode))
        r.raise_for_status()
        return _parse_photon(r.json())


async def async_geocode_mapbox(
    query: str, token: str, mode: str = "address", timeout: float = 10.0
) -> dict | None:
    url = MAPBOX_URL_TPL.format(q=urllib.parse.quote(query))
    async with httpx.AsyncClient(timeout=timeout, headers=_GEOCODE_HEADERS) as client:
        r = await client.get(url, params=_mapbox_params(token, mode))
        r.raise_for_status()
        return _parse_mapbox(r.json())


async def async_geocode(
    query: str,
    provider: str = "photon",
    token: str | None = None,
    mode: str = "address",
) -> dict | None:
    if provider == "mapbox":
        if not token:
            raise ValueError("mapbox provider requires a token")
        return await async_geocode_mapbox(query, token, mode=mode)
    return await async_geocode_photon(query, mode=mode)


# Taiwan rough bbox: lon 119.5–122.5, lat 21.5–25.5. Anything outside is
# almost certainly a wrong-country hit from the unbiased "address" mode.
_TW_LON_MIN, _TW_LAT_MIN, _TW_LON_MAX, _TW_LAT_MAX = 119.5, 21.5, 122.5, 25.5


def _in_taiwan(result: dict) -> bool:
    return (
        _TW_LON_MIN <= result["lon"] <= _TW_LON_MAX
        and _TW_LAT_MIN <= result["lat"] <= _TW_LAT_MAX
    )


async def async_resolve_place(
    query: str,
    provider: str = "photon",
    token: str | None = None,
) -> dict | None:
    """Resolve a free-form Taipei place name to coordinates.

    Tries cleaned address geocoding first, then the landmark/POI search on
    the raw query. Hits outside Taiwan's bbox are discarded — the unbiased
    address mode otherwise resolves Chinese-language queries to mainland
    China locations. Returns None if every attempt misses or fails.
    """
    raw = (query or "").strip()
    if not raw:
        return None
    cleaned = clean_address(raw)
    attempts: list[tuple[str, str]] = []
    if cleaned:
        attempts.append((cleaned, "address"))
    if (raw, "landmark") not in attempts:
        attempts.append((raw, "landmark"))
    last_err: Exception | None = None
    saw_clean_miss = False
    for q, mode in attempts:
        try:
            result = await async_geocode(q, provider=provider, token=token, mode=mode)
        except Exception as e:
            last_err = e
            continue
        if result and _in_taiwan(result):
            return {"query": q, "mode": mode, **result}
        saw_clean_miss = True
    if last_err is not None and not saw_clean_miss:
        raise last_err
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="JSON file (list of records)")
    ap.add_argument("--out", default="-", help="output JSON path or - for stdout")
    ap.add_argument("--provider", choices=["photon", "mapbox"], default="photon")
    ap.add_argument("--token", help="Mapbox access token (provider=mapbox)")
    ap.add_argument("--field", default="ral_address1", help="address field name")
    ap.add_argument("--fallback-field", default="ral_address2",
                    help="fallback address field if primary misses")
    ap.add_argument("--limit", type=int, default=0, help="0=all")
    ap.add_argument("--sleep", type=float, default=0.5, help="delay between requests")
    ap.add_argument("--verbose", action="store_true", help="print per-row OK/MISS log")
    ap.add_argument("--no-progress", action="store_true", help="disable progress bar")
    ap.add_argument("--mode", choices=["address", "landmark", "auto"], default="address",
                    help="address=clean+geocode (default); landmark=raw POI search; "
                         "auto=address first, fallback landmark")
    ap.add_argument("--query", help="single landmark/address query (skip --input)")
    args = ap.parse_args()

    # Single-query mode: --query "信義威秀"
    if args.query:
        mode = args.mode if args.mode != "auto" else "landmark"
        q = args.query if mode == "landmark" else clean_address(args.query)
        result = geocode(q, args.provider, args.token, mode=mode)
        if result:
            print(json.dumps({"query": q, "mode": mode, **result},
                             ensure_ascii=False, indent=2))
        else:
            print("MISS", file=sys.stderr)
            sys.exit(1)
        return

    with open(args.input, encoding="utf-8") as f:
        records = json.load(f)
    if args.limit:
        records = records[:args.limit]

    hits = misses = 0
    bar = make_bar(len(records), desc=f"geocode[{args.provider}]",
                   disable=args.no_progress)
    with bar:
        for i, rec in enumerate(records, 1):
            primary = rec.get(args.field) or ""
            q = primary.strip() if args.mode == "landmark" else clean_address(primary)
            result = None
            used_q = q
            used_mode = "landmark" if args.mode == "landmark" else "address"
            if q:
                try:
                    result = geocode(q, args.provider, args.token, mode=used_mode)
                except Exception as e:
                    bar.write(f"[{i}] err {e!r} on {q!r}")

            # auto mode: fall back to landmark search on raw primary
            if not result and args.mode == "auto" and primary.strip():
                try:
                    result = geocode(primary.strip(), args.provider, args.token,
                                     mode="landmark")
                    used_q = primary.strip()
                    used_mode = "landmark"
                except Exception as e:
                    bar.write(f"[{i}] err landmark {e!r} on {primary!r}")

            if not result and args.fallback_field:
                fb = rec.get(args.fallback_field) or ""
                q2 = fb.strip() if args.mode == "landmark" else clean_address(fb)
                if q2 and q2 != q:
                    try:
                        result = geocode(q2, args.provider, args.token, mode=used_mode)
                        used_q = q2
                    except Exception as e:
                        bar.write(f"[{i}] err {e!r} on {q2!r}")

            if result:
                hits += 1
                rec["geo"] = {"query": used_q, "mode": used_mode, **result}
                if args.verbose:
                    label = result.get("name") or result.get("road") or "?"
                    bar.write(f"[{i}] OK[{used_mode}] {used_q!r} -> {label} "
                              f"({result['lon']:.5f},{result['lat']:.5f})")
            else:
                misses += 1
                rec["geo"] = None
                if args.verbose:
                    bar.write(f"[{i}] MISS {used_q!r}")

            bar.set_postfix_str(f"hit={hits} miss={misses}")
            bar.update(1)
            time.sleep(args.sleep)

    print(f"hits={hits} misses={misses} total={len(records)}", file=sys.stderr)

    out = json.dumps(records, ensure_ascii=False, indent=2)
    if args.out == "-":
        sys.stdout.write(out)
    else:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()