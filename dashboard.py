"""Generates a self-refreshing static HTML dashboard from the incidents database."""
import json
import logging
import math
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


def _pie_svg(category_totals: list[tuple[str, int]], size: int = 220) -> str:
    """Return a bare SVG donut element for the given category totals."""
    total = sum(c for _, c in category_totals if c)
    if not total:
        return ""
    cx = cy = size // 2
    r_outer = int(size * 0.42)
    r_inner = int(size * 0.24)
    bg = "#0f1424"
    paths: list[str] = []
    angle = -math.pi / 2
    for cat, count in category_totals:
        if not count:
            continue
        _, fg = _CATEGORY_STYLES[cat]
        sweep = 2 * math.pi * count / total
        if abs(sweep - 2 * math.pi) < 1e-9:
            paths.append(
                f'<circle cx="{cx}" cy="{cy}" r="{r_outer}" fill="{fg}"/>'
                f'<circle cx="{cx}" cy="{cy}" r="{r_inner}" fill="{bg}"/>'
            )
            angle += sweep
            continue
        x1 = cx + r_outer * math.cos(angle)
        y1 = cy + r_outer * math.sin(angle)
        xi1 = cx + r_inner * math.cos(angle)
        yi1 = cy + r_inner * math.sin(angle)
        angle += sweep
        x2 = cx + r_outer * math.cos(angle)
        y2 = cy + r_outer * math.sin(angle)
        xi2 = cx + r_inner * math.cos(angle)
        yi2 = cy + r_inner * math.sin(angle)
        large = 1 if sweep > math.pi else 0
        paths.append(
            f'<path d="M {x1:.1f} {y1:.1f} A {r_outer} {r_outer} 0 {large} 1 {x2:.1f} {y2:.1f} '
            f'L {xi2:.1f} {yi2:.1f} A {r_inner} {r_inner} 0 {large} 0 {xi1:.1f} {yi1:.1f} Z" '
            f'fill="{fg}" stroke="{bg}" stroke-width="2"/>'
        )
    return f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">{"".join(paths)}</svg>'


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

    # --- By-type cards (top 8 per category + bar charts) ---
    _BAR_LIMIT = 8
    by_type_cat: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for t, c in by_type_sorted:
        by_type_cat[_categorize(t)].append((t, c))

    cat_cards_html = ""
    for cat in _CATEGORY_ORDER:
        rows = by_type_cat.get(cat, [])
        if not rows:
            continue
        _, fg = _CATEGORY_STYLES[cat]
        cat_total = sum(c for _, c in rows)
        max_count = rows[0][1] if rows else 1
        visible = rows[:_BAR_LIMIT]
        remainder = len(rows) - len(visible)
        bar_rows = ""
        for t, c in visible:
            pct = int(c / max_count * 100)
            bar_rows += (
                f'<div class="bar-row">'
                f'<span class="bar-label">{t}</span>'
                f'<div class="bar-right">'
                f'<div class="bar-track"><div class="bar-fill" style="width:{pct}%;background:{fg}"></div></div>'
                f'<span class="bar-count">{c:,}</span>'
                f'</div></div>'
            )
        more_html = f'<div class="bar-more">+{remainder} more types</div>' if remainder else ""
        cat_cards_html += (
            f'<div class="cat-card">'
            f'<div class="cat-card-hdr" style="color:{fg};border-bottom-color:rgba({{}},{{}},{{}},0.15)">'
            f'<span>{cat}</span><span class="cat-card-total">{cat_total:,}</span></div>'
            f'<div class="cat-card-body">{bar_rows}{more_html}</div>'
            f'</div>'
        ).replace("{},{},{}", "255,255,255")

    # --- Pie chart card ---
    cat_totals = [
        (cat, sum(c for _, c in by_type_cat.get(cat, [])))
        for cat in _CATEGORY_ORDER
    ]
    total_incidents = sum(c for _, c in cat_totals)
    pie_svg = _pie_svg(cat_totals, size=200)
    legend_rows = "".join(
        f'<div class="leg-row">'
        f'<span class="leg-dot" style="background:{_CATEGORY_STYLES[cat][1]}"></span>'
        f'<span class="leg-name">{cat}</span>'
        f'<span class="leg-val">{count:,} &thinsp; {count/total_incidents*100:.0f}%</span>'
        f'</div>'
        for cat, count in cat_totals if count
    ) if total_incidents else ""
    pie_card = (
        f'<div class="pie-card">'
        f'<div class="pie-title">This week by category</div>'
        f'<div class="pie-body">{pie_svg}'
        f'<div class="pie-legend">{legend_rows}</div>'
        f'</div></div>'
    ) if pie_svg else ""

    # --- Incidents table rows grouped by category ---
    by_cat: dict[str, list] = defaultdict(list)
    for r in recent:
        by_cat[_categorize(r.get("incident_type") or "")].append(r)

    rows_html = ""
    for cat in _CATEGORY_ORDER:
        cat_rows = by_cat.get(cat, [])
        if not cat_rows:
            continue
        _, fg = _CATEGORY_STYLES[cat]
        rows_html += (
            f'<tr class="cat-hdr"><td colspan="5" style="color:{fg};border-left:3px solid {fg}">'
            f'{cat}</td></tr>'
        )
        for r in cat_rows:
            ts = _fmt_time(r["created_at"])
            itype = r.get("incident_type") or "—"
            loc = r.get("location") or "—"
            summary = r.get("summary", "")
            posted = '<span class="chk">✓</span>' if r.get("posted") else '<span class="dot">·</span>'
            rows_html += (
                f'<tr>'
                f'<td class="ts">{ts}</td>'
                f'<td><span class="badge" style="color:{fg}">{itype}</span></td>'
                f'<td class="loc">{loc}</td>'
                f'<td class="summ">{summary}</td>'
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
:root{{--bg:#090d1a;--surf:#0f1424;--surf2:#141929;--bdr:rgba(255,255,255,0.07);--text:#e2e8f0;--muted:#64748b;--dim:#374151}}
body{{font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);padding:1.25rem 1.5rem;max-width:1400px;margin:0 auto}}
/* Header */
header{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:1.5rem;gap:1rem;flex-wrap:wrap}}
.title-row{{display:flex;align-items:center;gap:.6rem}}
h1{{font-size:1.5rem;font-weight:700;color:#fff;letter-spacing:-.02em}}
.live{{width:8px;height:8px;border-radius:50%;background:#4ade80;box-shadow:0 0 0 0 rgba(74,222,128,.5);animation:pulse 2s ease-in-out infinite;flex-shrink:0}}
@keyframes pulse{{0%,100%{{box-shadow:0 0 0 0 rgba(74,222,128,.4)}}50%{{box-shadow:0 0 0 7px rgba(74,222,128,0)}}}}
.updated{{font-size:.73rem;color:var(--muted);margin-top:.25rem}}
.feeds{{display:flex;gap:.5rem;flex-wrap:wrap;align-items:center}}
.pill{{padding:.25rem .7rem;border-radius:999px;font-size:.78rem;font-weight:500;border:1px solid}}
.pill-online{{background:rgba(74,222,128,.08);color:#4ade80;border-color:rgba(74,222,128,.2)}}
.pill-offline{{background:rgba(248,113,113,.08);color:#f87171;border-color:rgba(248,113,113,.2)}}
.pill-unknown{{background:rgba(156,163,175,.08);color:#94a3b8;border-color:rgba(156,163,175,.15)}}
/* Top row: stats + pie */
.top-row{{display:grid;grid-template-columns:1fr auto;gap:1rem;margin-bottom:1.25rem;align-items:start}}
.stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:1rem}}
.stat-card{{background:var(--surf);border:1px solid var(--bdr);border-radius:12px;padding:1.1rem 1.25rem;border-top:3px solid}}
.stat-label{{font-size:.67rem;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);margin-bottom:.5rem}}
.stat-value{{font-size:2.1rem;font-weight:800;color:#fff;line-height:1;font-variant-numeric:tabular-nums}}
.stat-sub{{font-size:.7rem;color:var(--dim);margin-top:.4rem}}
/* Pie card */
.pie-card{{background:var(--surf);border:1px solid var(--bdr);border-radius:12px;padding:1.1rem 1.25rem}}
.pie-title{{font-size:.67rem;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);margin-bottom:.85rem}}
.pie-body{{display:flex;align-items:center;gap:1.5rem}}
.pie-legend{{display:flex;flex-direction:column;gap:.55rem}}
.leg-row{{display:flex;align-items:center;gap:.55rem}}
.leg-dot{{width:9px;height:9px;border-radius:50%;flex-shrink:0}}
.leg-name{{font-size:.82rem;color:var(--text);flex:1;min-width:70px}}
.leg-val{{font-size:.8rem;color:var(--muted);font-variant-numeric:tabular-nums;white-space:nowrap}}
/* By-type grid */
.section-lbl{{font-size:.67rem;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);margin-bottom:.75rem}}
.by-type-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:1rem;margin-bottom:1.25rem}}
.cat-card{{background:var(--surf);border:1px solid var(--bdr);border-radius:12px;overflow:hidden}}
.cat-card-hdr{{display:flex;justify-content:space-between;align-items:center;padding:.6rem 1rem;font-size:.7rem;font-weight:700;text-transform:uppercase;letter-spacing:.09em;border-bottom:1px solid var(--bdr)}}
.cat-card-total{{font-variant-numeric:tabular-nums;font-size:.85rem}}
.cat-card-body{{padding:.6rem .9rem}}
.bar-row{{display:grid;grid-template-columns:1fr auto;gap:.75rem;align-items:center;padding:.28rem 0;border-bottom:1px solid rgba(255,255,255,.04)}}
.bar-row:last-of-type{{border-bottom:none}}
.bar-label{{font-size:.79rem;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.bar-right{{display:flex;align-items:center;gap:.5rem}}
.bar-track{{width:64px;height:5px;background:rgba(255,255,255,.08);border-radius:3px;flex-shrink:0}}
.bar-fill{{height:5px;border-radius:3px;min-width:2px}}
.bar-count{{font-size:.74rem;color:var(--muted);font-variant-numeric:tabular-nums;min-width:26px;text-align:right}}
.bar-more{{font-size:.72rem;color:var(--dim);padding:.4rem 0 .05rem}}
/* Incidents table */
table{{width:100%;border-collapse:collapse;background:var(--surf);border:1px solid var(--bdr);border-radius:12px;overflow:hidden;font-size:.84rem}}
thead th{{background:var(--surf2);color:var(--muted);font-weight:600;text-align:left;padding:.65rem 1rem;font-size:.68rem;text-transform:uppercase;letter-spacing:.07em;border-bottom:1px solid var(--bdr);position:sticky;top:0;z-index:1}}
td{{padding:.65rem 1rem;border-bottom:1px solid rgba(255,255,255,.04);vertical-align:top}}
tbody tr:not(.cat-hdr):hover td{{background:rgba(255,255,255,.025)}}
.cat-hdr td{{font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.1em;padding:.45rem 1rem;background:rgba(255,255,255,.03);border-bottom:1px solid var(--bdr)}}
.ts{{color:var(--muted);white-space:nowrap;font-size:.78rem}}
.badge{{display:inline-block;padding:.18rem .55rem;border-radius:5px;font-size:.72rem;font-weight:600;white-space:nowrap;background:rgba(255,255,255,.06)}}
.loc{{color:#cbd5e1;font-size:.82rem;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.summ{{color:var(--text);line-height:1.45}}
.posted{{text-align:center;width:44px}}
.chk{{color:#4ade80;font-size:.9rem}}
.dot{{color:var(--dim)}}
.empty{{text-align:center;color:var(--muted);padding:2.5rem}}
@media(max-width:900px){{.top-row{{grid-template-columns:1fr}}}}
@media(max-width:600px){{.stats{{grid-template-columns:1fr 1fr}}.loc{{max-width:100px}}}}
</style>
</head>
<body>
<header>
  <div>
    <div class="title-row"><div class="live"></div><h1>{COMMUNITY_NAME} Scanner</h1></div>
    <div class="updated">Updated {updated} &middot; refreshes every 60s</div>
  </div>
  <div class="feeds">{pills_html}</div>
</header>

<div class="top-row">
  <div class="stats">
    <div class="stat-card" style="border-top-color:#f87171">
      <div class="stat-label">Today</div>
      <div class="stat-value">{len(today):,}</div>
      <div class="stat-sub">incidents logged</div>
    </div>
    <div class="stat-card" style="border-top-color:#60a5fa">
      <div class="stat-label">This Week</div>
      <div class="stat-value">{len(week):,}</div>
      <div class="stat-sub">incidents logged</div>
    </div>
    <div class="stat-card" style="border-top-color:#4ade80">
      <div class="stat-label">Last Incident</div>
      <div class="stat-value" style="font-size:1.2rem;margin-top:.15rem">{last_str}</div>
    </div>
  </div>
  {pie_card}
</div>

<div class="section-lbl">This week by type</div>
<div class="by-type-grid">{cat_cards_html}</div>

<div class="section-lbl" style="margin-bottom:.75rem">Recent incidents &mdash; last 7 days</div>
<table>
<thead><tr>
  <th>Time</th><th>Type</th><th>Location</th><th>Summary</th><th></th>
</tr></thead>
<tbody>
{rows_html}
</tbody>
</table>
</body>
</html>"""

    DASHBOARD_FILE.write_text(html, encoding="utf-8")
    _push_to_gh_pages()
