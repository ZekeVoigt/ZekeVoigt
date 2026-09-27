#!/usr/bin/env python3
"""Draw tokens-per-day from this Mac's Claude Code / Codex logs (via ccusage) and push it.

Writes assets/tokens.svg in this repo, commits it as the github-actions bot (so the
daily commit does not count as one of Zeke's contributions), and pushes.
Run by ~/Library/LaunchAgents/com.zekevoigt.readme-tokens.plist once a day.
"""
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "assets" / "tokens.svg"
LOG = REPO / "assets" / "tokens.json"  # every day seen, kept: local logs get pruned
DAYS = 90
BOT = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"

os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:" + os.environ.get("PATH", "")


def usage():
    out = subprocess.run(
        ["npx", "-y", "ccusage@latest", "daily", "--json"],
        capture_output=True, text=True, check=True, cwd="/tmp",
    ).stdout
    data = json.loads(out)
    seen = json.loads(LOG.read_text()) if LOG.exists() else {}
    for row in data["daily"]:
        seen[row["period"]] = max(seen.get(row["period"], 0), row["totalTokens"])
    LOG.write_text(json.dumps(dict(sorted(seen.items())), indent=1) + "\n")
    return seen, sum(seen.values())


def short(n):
    for div, unit in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if n >= div:
            v = n / div
            return f"{v:.1f}".rstrip("0").rstrip(".") + unit
    return str(int(n))


def nice_max(v):
    if v <= 0:
        return 1
    mag = 10 ** (len(str(int(v))) - 1)
    for step in (1, 2, 2.5, 5, 10):
        if step * mag >= v:
            return step * mag


def bar(x, y, w, base, r=4):
    h = base - y
    r = min(r, h, w / 2)
    if h <= 0:
        return ""
    return (f"M{x:.1f},{base} V{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
            f"H{x + w - r:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} V{base} Z")


def svg(by_day, all_time, today):
    days = [today - dt.timedelta(days=i) for i in range(DAYS - 1, -1, -1)]
    vals = [by_day.get(d.isoformat(), 0) for d in days]
    top = nice_max(max(vals))

    W, H = 800, 230
    left, right, plot_top, base = 48, 16, 64, 196
    plot_w = W - left - right
    slot = plot_w / DAYS
    gap = 1.5
    bw = slot - gap

    parts = []
    for frac in (0.5, 1.0):
        y = base - (base - plot_top) * frac
        parts.append(f'<line class="grid" x1="{left}" x2="{W - right}" y1="{y:.1f}" y2="{y:.1f}"/>')
        parts.append(f'<text class="axis" x="{left - 8}" y="{y + 4:.1f}" text-anchor="end">{short(top * frac)}</text>')
    parts.append(f'<line class="base" x1="{left}" x2="{W - right}" y1="{base}" y2="{base}"/>')

    for i, (d, v) in enumerate(zip(days, vals)):
        x = left + i * slot + gap / 2
        y = base - (base - plot_top) * v / top
        p = bar(x, y, bw, base)
        if p:
            parts.append(f'<path class="bar" d="{p}"><title>{d:%b %-d}: {v:,} tokens</title></path>')

    for i in (0, DAYS // 3, 2 * DAYS // 3, DAYS - 1):
        x = left + i * slot + slot / 2
        parts.append(f'<text class="axis" x="{x:.1f}" y="{base + 18}" text-anchor="middle">{days[i]:%b %-d}</text>')

    month = sum(vals)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="AI tokens per day, last {DAYS} days: {short(month)} total; {short(all_time)} all time">
<style>
  text {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }}
  .bg {{ fill: #ffffff; stroke: #d1d9e0; }}
  .title {{ fill: #1f2328; font-size: 15px; font-weight: 600; }}
  .sub, .axis {{ fill: #59636e; font-size: 12px; }}
  .num {{ fill: #1f2328; font-size: 20px; font-weight: 600; }}
  .grid {{ stroke: #eaeef2; stroke-width: 1; }}
  .base {{ stroke: #d1d9e0; stroke-width: 1; }}
  .bar {{ fill: #2da44e; }}
  @media (prefers-color-scheme: dark) {{
    .bg {{ fill: #0d1117; stroke: #3d444d; }}
    .title, .num {{ fill: #f0f6fc; }}
    .sub, .axis {{ fill: #9198a1; }}
    .grid {{ stroke: #21262d; }}
    .base {{ stroke: #3d444d; }}
    .bar {{ fill: #3fb950; }}
  }}
</style>
<rect class="bg" x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="6"/>
<text class="title" x="20" y="30">AI tokens per day</text>
<text class="sub" x="20" y="48">AI coding agents · last {DAYS} days · updated {today:%b %-d}</text>
<text class="num" x="{W - 20}" y="32" text-anchor="end">{short(month)}</text>
<text class="sub" x="{W - 20}" y="48" text-anchor="end">last {DAYS} days · {short(all_time)} all time</text>
{chr(10).join(parts)}
</svg>
"""


def git(*args):
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=True).stdout


def main():
    by_day, all_time = usage()
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(svg(by_day, all_time, dt.date.today()))
    if "--no-push" in sys.argv:
        print(OUT)
        return
    git("pull", "--rebase", "--autostash", "-q")
    git("add", str(OUT), str(LOG))
    if not git("status", "--porcelain", str(OUT), str(LOG)).strip():
        return
    subprocess.run(
        ["git", "-C", str(REPO), "-c", f"user.name={BOT}", "-c", f"user.email={BOT_EMAIL}",
         "commit", "-q", "-m", "Update token chart"],
        check=True,
    )
    git("push", "-q")


if __name__ == "__main__":
    main()
