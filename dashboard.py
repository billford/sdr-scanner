"""Generates a self-refreshing static HTML dashboard from the incidents database."""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import db
from config import BROADCASTIFY_FEED_URLS, COMMUNITY_NAME

STREAM_STATUS_FILE = Path("stream_status.json")
DASHBOARD_FILE = Path("dashboard.html")

_status_lock = threading.Lock()


def update_stream_status(url: str, status: str) -> None:
    """Write online/offline status for a feed to the shared status file."""
    with _status_lock:
        data = {}
        if STREAM_STATUS_FILE.exists():
            try:
                data = json.loads(STREAM_STATUS_FILE.read_text(encoding="utf-8"))
            except Exception:  # pylint: disable=broad-exception-caught
                pass
        data[url] = {"status": status, "since": datetime.now(timezone.utc).isoformat()}
        STREAM_STATUS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_stream_status() -> dict:
    with _status_lock:
        if STREAM_STATUS_FILE.exists():
            try:
                return json.loads(STREAM_STATUS_FILE.read_text(encoding="utf-8"))
            except Exception:  # pylint: disable=broad-exception-caught
                pass
    return {}


def _feed_label(url: str) -> str:
    return f"Feed {url.rstrip('/').split('/')[-1]}"


def _fmt_time(iso: str, fmt: str = "%H:%M %b %d") -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime(fmt)
    except Exception:  # pylint: disable=broad-exception-caught
        return iso


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

    # --- Incidents table rows ---
    rows_html = ""
    for r in recent:
        ts = _fmt_time(r["created_at"])
        itype = r.get("incident_type") or "—"
        loc = r.get("location") or "—"
        summary = r.get("summary", "")
        posted = "✓" if r.get("posted") else "·"
        rows_html += f"""<tr>
  <td class="ts">{ts}</td>
  <td><span class="badge">{itype}</span></td>
  <td class="loc">{loc}</td>
  <td class="summary">{summary}</td>
  <td class="posted">{posted}</td>
</tr>"""

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
