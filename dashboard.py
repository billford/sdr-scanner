"""Generates a self-refreshing static HTML dashboard from the incidents database."""
import json
import logging
from collections import defaultdict
import subprocess  # nosec B404 — only used for git plumbing; no user input
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import db
from config import BROADCASTIFY_FEED_URLS, COMMUNITY_NAME

STREAM_STATUS_FILE = Path("stream_status.json")
DASHBOARD_FILE = Path("dashboard.html")

_status_lock = threading.Lock()
_push_lock = threading.Lock()
_LAST_PUSH: float = 0.0
_PUSH_INTERVAL = 300  # push to gh-pages at most once every 5 minutes
_PAGES_POLL_INTERVAL = 15   # seconds between build status checks
_PAGES_POLL_TIMEOUT = 120   # give up waiting after this many seconds

log = logging.getLogger(__name__)


def update_stream_status(url: str, status: str) -> None:
    """Write online/offline status for a feed to the shared status file."""
    with _status_lock:
        data = {}
        if STREAM_STATUS_FILE.exists():
            try:
                data = json.loads(STREAM_STATUS_FILE.read_text(encoding="utf-8"))
            except Exception:  # pylint: disable=broad-exception-caught  # nosec B110 — corrupt file, start fresh
                pass
        data[url] = {"status": status, "since": datetime.now(timezone.utc).isoformat()}
        STREAM_STATUS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_stream_status() -> dict:
    with _status_lock:
        if STREAM_STATUS_FILE.exists():
            try:
                return json.loads(STREAM_STATUS_FILE.read_text(encoding="utf-8"))
            except Exception:  # pylint: disable=broad-exception-caught  # nosec B110 — return empty on any parse error
                pass
    return {}


def _feed_label(url: str) -> str:
    return f"Feed {url.rstrip('/').split('/')[-1]}"


def _fmt_time(iso: str, fmt: str = "%H:%M %b %d") -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime(fmt)
    except Exception:  # pylint: disable=broad-exception-caught  # nosec B110 — return raw string on parse failure
        return iso


def _gh_repo_slug() -> str:
    """Return 'owner/repo' from the origin remote URL."""
    url = subprocess.check_output(  # nosec
        ["git", "remote", "get-url", "origin"], timeout=5
    ).decode().strip()
    # handles https://github.com/owner/repo.git and git@github.com:owner/repo.git
    url = url.removesuffix(".git")
    return url.split("github.com/")[-1].split("github.com:")[-1]


def _notify(title: str, subtitle: str, body: str) -> None:
    subprocess.run(  # nosec — hardcoded osascript, no user input
        ["osascript", "-e",
         f'display notification "{body[:200]}" with title "{title}" subtitle "{subtitle}"'],
        capture_output=True, check=False,
    )


def _watch_pages_build(commit_sha: str) -> None:
    """Poll GitHub Pages build status for commit_sha; notify if it errors."""
    try:
        slug = _gh_repo_slug()
    except Exception:  # pylint: disable=broad-exception-caught
        return
    deadline = time.monotonic() + _PAGES_POLL_TIMEOUT
    time.sleep(_PAGES_POLL_INTERVAL)
    while time.monotonic() < deadline:
        try:
            out = subprocess.check_output(  # nosec
                ["gh", "api", f"repos/{slug}/pages/builds",
                 "--jq", ".[0] | {status, commit: .commit[:8], error: .error.message}"],
                timeout=15,
            )
            build = json.loads(out)
        except Exception:  # pylint: disable=broad-exception-caught
            break
        if build.get("commit") != commit_sha[:8]:
            time.sleep(_PAGES_POLL_INTERVAL)
            continue
        status = build.get("status")
        if status == "built":
            log.info("Pages build succeeded for %s", commit_sha[:8])
            return
        if status == "errored":
            msg = build.get("error") or "unknown error"
            log.warning("Pages build failed for %s: %s", commit_sha[:8], msg)
            _notify("Scanner", "Pages build failed", msg)
            return
        time.sleep(_PAGES_POLL_INTERVAL)
    log.debug("Pages build watch timed out for %s", commit_sha[:8])


_CATEGORY_ORDER = ["Criminal", "Medical", "Fire", "Traffic", "Misc"]

_CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("Medical", [
        "medical", "ems", "overdose", "trauma", "seizure", "cit", "suicide", "suicidal",
        "mental health", "mental", "psych", "welfare check", "wellness", "lift assist",
        "injury", "inhalation", "doa", "death", "exposure", "self-harm", "self-inflicted",
        "mobile crisis", "cardiac", "medic", "drug overdose",
    ]),
    ("Criminal", [
        "assault", "shooting", "shot", "shots", "robbery", "burglary", "theft", "stabbing",
        "homicide", "murder", "sexual", "domestic", "fight", "threat", "blackmail",
        "weapon", "armed", "gun", "gsw", "carjacking", "kidnap", "vandal", "trespass",
        "harass", "narcotic", "drug", "dui", "ovi", "warrant", "felony", "crime",
        "break-in", "b&e", "breaking & e", "fraud", "aggravated", "child abuse",
        "use of force", "disturbance", "pursuit", "gunfire", "gunshot",
        "strangulation", "human trafficking", "missing", "arrest", "shoplifting",
        "shoplifter", "hate crime", "sex offense",
    ]),
    ("Fire", [
        "house fire", "apartment fire", "brush fire", "car fire", "vehicle fire",
        "electrical fire", "vehicle on fire",
        "fire", "arson", "hazmat", "gas leak", "chemical", "electrical", "power line",
        "power outage", "water main", "flood", "smoke", "carbon",
    ]),
    ("Traffic", [
        "accident", "collision", "crash", "mva", "mvc", "mca", "hit and run",
        "hit & run", "hit-and-run", "hit & skip", "hit skip", "rollover",
        "vehicle stop", "traffic stop", "traffic", "motorcycle", "pedestrian struck",
        "car vs", "vehicle vs",
    ]),
]


def _categorize(incident_type: str) -> str:
    t = (incident_type or "").lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(k in t for k in keywords):
            return category
    return "Misc"


_CATEGORY_STYLES: dict[str, tuple[str, str]] = {
    "Criminal": ("#3b0f0f", "#f87171"),
    "Medical":  ("#0d2a4a", "#7dd3fc"),
    "Fire":     ("#3b1f00", "#fb923c"),
    "Traffic":  ("#2a2a00", "#facc15"),
    "Misc":     ("#1f2937", "#9ca3af"),
}


def _push_to_gh_pages() -> None:
    """Push dashboard.html to the gh-pages branch via git plumbing. Rate-limited."""
    global _LAST_PUSH  # pylint: disable=global-statement
    with _push_lock:
        if time.time() - _LAST_PUSH < _PUSH_INTERVAL:
            return
        try:
            html = DASHBOARD_FILE.read_bytes()
            blob = subprocess.check_output(  # nosec — hardcoded git cmd, no user input
                ["git", "hash-object", "-w", "--stdin"], input=html, timeout=10
            ).decode().strip()
            nojekyll_blob = subprocess.check_output(  # nosec — hardcoded git cmd
                ["git", "hash-object", "-w", "--stdin"], input=b"", timeout=10
            ).decode().strip()
            tree = subprocess.check_output(  # nosec — hardcoded git cmd
                ["git", "mktree"],
                input=(
                    f"100644 blob {blob}\tindex.html\n"
                    f"100644 blob {nojekyll_blob}\t.nojekyll\n"
                ).encode(),
                timeout=10,
            ).decode().strip()
            subprocess.run(  # nosec — hardcoded git cmd
                ["git", "fetch", "origin", "gh-pages:refs/remotes/origin/gh-pages"],
                capture_output=True, timeout=30, check=False,
            )
            parent = subprocess.check_output(  # nosec — hardcoded git cmd
                ["git", "rev-parse", "refs/remotes/origin/gh-pages"], timeout=10
            ).decode().strip()
            msg = f"Update dashboard {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
            commit = subprocess.check_output(  # nosec — hardcoded git cmd
                ["git", "commit-tree", tree, "-p", parent, "-m", msg], timeout=10
            ).decode().strip()
            result = subprocess.run(  # nosec — hardcoded git cmd
                ["git", "push", "origin", f"{commit}:refs/heads/gh-pages"],
                capture_output=True, timeout=30, check=False,
            )
            if result.returncode != 0:
                stderr = result.stderr.decode(errors="replace").strip()
                log.warning("gh-pages push failed (exit %d): %s", result.returncode, stderr)
                _notify("Scanner", "gh-pages push failed", stderr)
                return
            _LAST_PUSH = time.time()
            log.info("Dashboard pushed to gh-pages")
            threading.Thread(target=_watch_pages_build, args=(commit,), daemon=True).start()
        except Exception:  # pylint: disable=broad-exception-caught  # nosec B110 — best-effort push
            log.warning("gh-pages push skipped", exc_info=True)


def generate() -> None:
    """Render dashboard.html from current DB state and stream status."""
    now = datetime.now(timezone.utc).astimezone()
    stream_status = _load_stream_status()

    today = db.recent_incidents(minutes=1440)
    week = db.recent_incidents(minutes=10080)
    recent = week[:50]

    by_type: dict[str, int] = {}
    for r in week:
        t = r.get("incident_type") or "Unknown"
        by_type[t] = by_type.get(t, 0) + 1
    by_type_sorted = sorted(by_type.items(), key=lambda x: -x[1])

    last_str = _fmt_time(today[0]["created_at"]) if today else "—"

    # --- Stream status pills ---
    pills_html = ""
    for url in BROADCASTIFY_FEED_URLS:
        info = stream_status.get(url, {})
        status = info.get("status", "unknown")
        since = info.get("since", "")
        since_str = f" since {_fmt_time(since, '%H:%M')}" if since else ""
        icon = {"online": "●", "offline": "○"}.get(status, "◌")
        css = {"online": "pill-online", "offline": "pill-offline"}.get(status, "pill-unknown")
        pills_html += f'<span class="pill {css}">{icon} {_feed_label(url)}{since_str}</span>\n'

    # --- By-type breakdown ---
    type_rows_html = "".join(
        f'<div class="type-row"><span>{t}</span><span class="type-count">{c}</span></div>'
        for t, c in by_type_sorted
    )
    by_type_block = f"""
<div class="by-type">
  <div class="section-title">This week by type</div>
  {type_rows_html}
</div>""" if by_type_sorted else ""

    # --- Incidents table rows grouped by category ---
    by_cat: dict[str, list] = defaultdict(list)
    for r in recent:
        by_cat[_categorize(r.get("incident_type") or "")].append(r)

    rows_html = ""
    for cat in _CATEGORY_ORDER:
        cat_rows = by_cat.get(cat, [])
        if not cat_rows:
            continue
        bg, fg = _CATEGORY_STYLES[cat]
        rows_html += (
            f'<tr class="cat-header">'
            f'<td colspan="5" style="background:{bg};color:{fg}">{cat}</td>'
            f'</tr>'
        )
        for r in cat_rows:
            ts = _fmt_time(r["created_at"])
            itype = r.get("incident_type") or "—"
            loc = r.get("location") or "—"
            summary = r.get("summary", "")
            posted = "✓" if r.get("posted") else "·"
            badge_bg, badge_fg = _CATEGORY_STYLES[cat]
            rows_html += (
                f'<tr>'
                f'<td class="ts">{ts}</td>'
                f'<td><span class="badge" style="background:{badge_bg};color:{badge_fg}">{itype}</span></td>'
                f'<td class="loc">{loc}</td>'
                f'<td class="summary">{summary}</td>'
                f'<td class="posted">{posted}</td>'
                f'</tr>'
            )

    if not rows_html:
        rows_html = '<tr><td colspan="5" class="empty">No incidents in the last 7 days.</td></tr>'

    updated = now.strftime("%H:%M:%S %Z, %b %d %Y")

    # pylint: disable=line-too-long
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>{COMMUNITY_NAME} Scanner</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:system-ui,-apple-system,sans-serif;background:#0f1117;color:#e0e0e0;padding:1.5rem}}
h1{{font-size:1.4rem;font-weight:600;color:#fff}}
.updated{{font-size:.75rem;color:#666;margin-top:.25rem}}
.header{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:1.5rem;flex-wrap:wrap;gap:.5rem}}
.feeds{{display:flex;gap:.5rem;flex-wrap:wrap;align-items:center}}
.pill{{padding:.3rem .75rem;border-radius:999px;font-size:.8rem;font-weight:500}}
.pill-online{{background:#0d3320;color:#4ade80;border:1px solid #166534}}
.pill-offline{{background:#3b0f0f;color:#f87171;border:1px solid #7f1d1d}}
.pill-unknown{{background:#1f2937;color:#9ca3af;border:1px solid #374151}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1rem;margin-bottom:1.5rem}}
.stat-card{{background:#1a1d27;border:1px solid #2d3147;border-radius:8px;padding:1rem}}
.stat-label{{font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;color:#9ca3af;margin-bottom:.25rem}}
.stat-value{{font-size:1.75rem;font-weight:700;color:#fff}}
.stat-sub{{font-size:.75rem;color:#6b7280;margin-top:.25rem}}
.section-title{{font-size:.75rem;text-transform:uppercase;letter-spacing:.06em;color:#6b7280;margin-bottom:.6rem}}
.by-type{{background:#1a1d27;border:1px solid #2d3147;border-radius:8px;padding:1rem;margin-bottom:1.5rem}}
.type-row{{display:flex;justify-content:space-between;padding:.3rem 0;font-size:.85rem;border-bottom:1px solid #1f2333}}
.type-row:last-child{{border-bottom:none}}
.type-count{{color:#9ca3af}}
table{{width:100%;border-collapse:collapse;background:#1a1d27;border:1px solid #2d3147;border-radius:8px;overflow:hidden;font-size:.85rem}}
th{{background:#0f1117;color:#9ca3af;font-weight:500;text-align:left;padding:.6rem .75rem;border-bottom:1px solid #2d3147;font-size:.72rem;text-transform:uppercase;letter-spacing:.04em}}
td{{padding:.6rem .75rem;border-bottom:1px solid #1f2333;vertical-align:top}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:#1f2333}}
.ts{{color:#9ca3af;white-space:nowrap}}
.badge{{background:#1e3a5f;color:#7dd3fc;padding:.15rem .5rem;border-radius:4px;font-size:.75rem;white-space:nowrap}}
.loc{{color:#d1d5db;white-space:nowrap}}
.summary{{color:#e0e0e0;line-height:1.4}}
.posted{{text-align:center;color:#4ade80}}
.empty{{text-align:center;color:#6b7280;padding:2rem}}
.cat-header td{{font-size:.7rem;font-weight:600;text-transform:uppercase;letter-spacing:.08em;padding:.4rem .75rem;border-bottom:1px solid #2d3147}}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>{COMMUNITY_NAME} Scanner</h1>
    <div class="updated">Updated {updated} &middot; refreshes every 60s</div>
  </div>
  <div class="feeds">{pills_html}</div>
</div>

<div class="stats">
  <div class="stat-card">
    <div class="stat-label">Today</div>
    <div class="stat-value">{len(today)}</div>
    <div class="stat-sub">incidents</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">This Week</div>
    <div class="stat-value">{len(week)}</div>
    <div class="stat-sub">incidents</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Last Incident</div>
    <div class="stat-value" style="font-size:1.1rem;padding-top:.4rem">{last_str}</div>
  </div>
</div>

{by_type_block}

<div class="section-title" style="margin-bottom:.6rem">Recent incidents (last 7 days)</div>
<table>
<thead><tr>
  <th>Time</th><th>Type</th><th>Location</th><th>Summary</th><th>Posted</th>
</tr></thead>
<tbody>
{rows_html}
</tbody>
</table>
</body>
</html>"""

    DASHBOARD_FILE.write_text(html, encoding="utf-8")
    _push_to_gh_pages()
