#!/usr/bin/env python3
"""Harvest off-Commons reference photos from Reddit into a tagged folder.

Handles Reddit's anonymous-JSON 403 "Blocked" responses:
  * OAuth (client_credentials) via a free "script" app -> oauth.reddit.com  [definitive]
  * host rotation + retries + 429 backoff when anonymous
  * gzip, a non-generic UA, certifi/SSL fallback
"""
import argparse, base64, gzip, json, os, random, re, ssl, time
import urllib.error, urllib.parse, urllib.request
from urllib.parse import urlparse

UA = "python:harvest:v1.0 (by /u/flowcool)"
HDRS = {"User-Agent": UA,
        "Accept": "application/json,image/*,*/*",
        "Accept-Encoding": "gzip",
        "Accept-Language": "en-US,en;q=0.9"}
BASE = os.path.expanduser("~/Desktop/vulva_offcommons")
MIN_SIDE, MIN_BYTES, MAX_RATIO = 1100, 120_000, 2.6

# sub, scale, view, spread, hair, state, want
SUBS = [
    ("GodPussy",        "tight",  "frontal", "spreadF", "smooth", "none",    20),
    ("Innies",          "tight",  "frontal", "closed",  "smooth", "none",    15),
    ("LabiaGW",         "tight",  "frontal", "spreadF", "smooth", "none",    20),
    ("vulva",           "tight",  "frontal", "spreadF", "smooth", "none",    25),
    ("pussy",           "tight",  "frontal", "spreadF", "smooth", "none",    20),
    ("grool",           "macro",  "frontal", "spreadF", "smooth", "lube",    20),
    ("creampies",       "tight",  "frontal", "spreadP", "smooth", "semen",   15),
    ("Cummypussy",      "tight",  "frontal", "spreadP", "smooth", "semen",   10),
    ("squirting",       "tight",  "frontal", "spreadF", "smooth", "squirt",  12),
    ("gape",            "tight",  "frontal", "open",    "smooth", "none",    12),
    ("clitgonewild",    "macro",  "frontal", "spreadF", "smooth", "arousal", 12),
    ("assholegonewild", "tight",  "rear",    "spreadF", "smooth", "none",    15),
    ("gonwild",         "medium", "frontal", "closed",  "smooth", "none",    12),
    ("pelfie",          "medium", "frontal", "closed",  "smooth", "none",    12),
]

# sub, scale, view, spread, hair, state, want, search query   (view coverage)
SEARCHES = [
    ("vulva", "tight",  "low", "spreadF", "smooth", "none", 10, "from below"),
    ("vulva", "tight",  "low", "spreadF", "smooth", "none", 10, "legs up"),
    ("pussy", "tight",  "low", "spreadF", "smooth", "none", 10, "from below"),
    ("vulva", "medium", "low", "closed",  "smooth", "none",  8, "squatting"),
    ("vulva", "tight",  "top", "spreadF", "smooth", "none", 10, "from above"),
    ("pussy", "tight",  "top", "spreadF", "smooth", "none",  8, "top view"),
]

JOBS = [tuple(list(s) + [""]) for s in SUBS] + [tuple(s) for s in SEARCHES]

CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
TOKEN = {"v": None, "exp": 0.0}
SSL = {"verify": True}


def _ctx():
    if not SSL["verify"]:
        return ssl._create_unverified_context()
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _open(req, timeout=45):
    try:
        return urllib.request.urlopen(req, timeout=timeout, context=_ctx())
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError) and SSL["verify"]:
            SSL["verify"] = False
            print("  (ssl: retrying unverified — fix with "
                  "'/Applications/Python\\ 3.x/Install\\ Certificates.command' or 'pip3 install certifi')")
            return urllib.request.urlopen(req, timeout=timeout, context=_ctx())
        raise


def _read(r):
    raw = r.read()
    if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
        raw = gzip.decompress(raw)
    return raw


def get_bytes(url, timeout=60):
    """Fetch raw (decompressed) bytes with the standard headers."""
    return _read(_open(urllib.request.Request(url, headers=HDRS), timeout))


def token():
    """client_credentials token for a 'script' app. Returns None if unconfigured."""
    if not CLIENT_ID:
        return None
    if TOKEN["v"] and time.time() < TOKEN["exp"]:
        return TOKEN["v"]
    auth = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token", data=body,
        headers={"Authorization": f"Basic {auth}", "User-Agent": UA,
                 "Content-Type": "application/x-www-form-urlencoded"})
    with _open(req) as r:
        j = json.loads(_read(r))
    TOKEN["v"] = j["access_token"]
    TOKEN["exp"] = time.time() + int(j.get("expires_in", 3600)) - 120
    return TOKEN["v"]


def api_get(path, params):
    """GET a reddit json listing. path like '/r/vulva/top'. Rotates hosts on 403."""
    q = urllib.parse.urlencode(params)
    tok = token()
    hosts = ["oauth.reddit.com"] if tok else ["www.reddit.com", "old.reddit.com", "api.reddit.com"]
    last = None
    for attempt in range(6):
        host = hosts[attempt % len(hosts)]
        url = f"https://{host}{path}.json?{q}"
        hdrs = dict(HDRS)
        if tok and host == "oauth.reddit.com":
            hdrs["Authorization"] = f"Bearer {tok}"
        try:
            with _open(urllib.request.Request(url, headers=hdrs)) as r:
                return json.loads(_read(r))
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 401 and host == "oauth.reddit.com":
                TOKEN["exp"] = 0.0
                tok = token()
            time.sleep((3 + attempt * 3) if e.code == 429 else (1.2 + random.random()))
        except Exception as e:
            last = e
            time.sleep(1.5 + attempt)
    print(f"  ! {path}?{q[:44]}: {last}")
    return None


def candidates(d):
    """Return (url, w, h, key) for image content in a post."""
    out, pv = [], (((d.get("preview") or {}).get("images") or [{}])[0]).get("source") or {}
    w, h = pv.get("width"), pv.get("height")
    u = d.get("url_overridden_by_dest") or d.get("url") or ""
    if d.get("is_gallery") and d.get("media_metadata"):
        for mid, m in d["media_metadata"].items():
            if m.get("status") != "valid":
                continue
            s = m.get("s") or {}
            if s.get("u") and s.get("x") and s.get("y"):
                out.append((s["u"], s["x"], s["y"], mid))
    elif d.get("is_video"):
        return out
    elif re.search(r"\.(jpe?g|png)$", urlparse(u).path, re.I):
        if w and h:
            out.append((u, w, h, d.get("id")))
    elif pv.get("url") and w and h:
        out.append((pv["url"], w, h, d.get("id")))
    return out


def good(w, h, minside):
    mn, mx = min(w, h), max(w, h)
    return mn >= minside and mx / mn <= MAX_RATIO


def grab(url, path):
    for i in range(4):
        try:
            data = get_bytes(url)
            if len(data) < MIN_BYTES:
                raise ValueError(f"only {len(data)//1024}KB")
            if not (data[:2] == b"\xff\xd8" or data[:8] == b"\x89PNG\r\n\x1a\n"):
                raise ValueError("not a jpeg/png")
            with open(path, "wb") as f:
                f.write(data)
            return True
        except Exception as e:
            if i == 3:
                print(f"    ! {os.path.basename(path)}: {e}")
                return False
            time.sleep(1.5 * (i + 1))


def main():
    global CLIENT_ID, CLIENT_SECRET, UA
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--min-side", type=int, default=MIN_SIDE)
    ap.add_argument("--only", default="")
    ap.add_argument("--client-id", default="")
    ap.add_argument("--client-secret", default="")
    ap.add_argument("--anon", action="store_true", help="force anonymous mode")
    ap.add_argument("--ua", default="")
    ap.add_argument("--sleep", type=float, default=None, help="seconds between subreddits")
    a = ap.parse_args()

    if a.client_id:
        CLIENT_ID = a.client_id
    if a.client_secret:
        CLIENT_SECRET = a.client_secret
    if a.anon:
        CLIENT_ID = CLIENT_SECRET = ""
    if a.ua:
        UA = a.ua
        HDRS["User-Agent"] = UA
    if CLIENT_ID:
        try:
            token()
            print(f"auth: OAuth ok -> oauth.reddit.com (client {CLIENT_ID[:6]}...)")
        except Exception as e:
            print(f"auth: OAuth failed ({e}) — falling back to anonymous")
            CLIENT_ID = CLIENT_SECRET = ""
    else:
        print("auth: anonymous (export REDDIT_CLIENT_ID/SECRET for reliability)")
    pause = a.sleep if a.sleep is not None else (1.0 if CLIENT_ID else 2.5)

    os.makedirs(BASE, exist_ok=True)
    seen, seen_url, rows, n = set(), set(), [], 0

    for s in JOBS:
        sub, scale, view, spread, hair, state, want, query = s
        if a.only and sub.lower() not in a.only.lower().split(","):
            continue
        if query:
            path = f"/r/{sub}/search"
            params = {"q": query, "restrict_sr": 1, "sort": "top", "t": "all",
                      "limit": 100, "raw_json": 1}
            label = f'r/{sub} "{query}"'
        else:
            path = f"/r/{sub}/top"
            params = {"t": "all", "limit": 100, "raw_json": 1}
            label = f"r/{sub}"
        print(f"[{label}]")

        j = api_get(path, params)
        if not j:
            continue
        got = 0
        for child in (j.get("data") or {}).get("children", []):
            if got >= want:
                break
            d = child.get("data", {})
            if d.get("stickied") or d.get("id") in seen:
                continue
            for u, w, h, key in candidates(d):
                if got >= want:
                    break
                p = urlparse(u).path
                if key in seen or p in seen_url or not good(w, h, a.min_side):
                    continue
                ext = ".png" if p.lower().endswith(".png") else ".jpg"
                name = f"{n+1:03d}_{scale}-{view}-{spread}-{hair}-{state}_{sub}_{key}{ext}"

                if a.dry_run:
                    seen.add(key); seen_url.add(p); n += 1; got += 1
                    print(f"  {name}  {w}x{h}")
                elif grab(u, os.path.join(BASE, name)):
                    seen.add(key); seen_url.add(p); n += 1; got += 1
                    print(f"  {name}  {w}x{h}")
                    rows.append(f"{name}\t{scale}\t{view}\t{spread}\t{hair}\t{state}\t"
                                f"https://reddit.com{d.get('permalink','')}")
        time.sleep(pause)

    if not a.dry_run and rows:
        with open(os.path.join(BASE, "sources.tsv"), "w") as f:
            f.write("file\tscale\tview\tshape\tspread\thair\tstate\tsource\n"
                    .replace("shape\t", ""))
            f.write("\n".join(rows) + "\n")
    print(f"\ndone -> {BASE}  ({n} files)")


if __name__ == "__main__":
    main()