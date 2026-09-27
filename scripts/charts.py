#!/usr/bin/env python3
"""Draw the README's activity grid and its hover page, then push them.

One square per day for the last year, shaded by AI tokens. Each day also carries
GitHub contributions and WakaTime coding time:

  assets/activity.svg   the grid, as an image in the README (GitHub allows no hover there)
  docs/index.html       the same grid on GitHub Pages, with a tooltip per day
  assets/activity.json  every day's tokens and seconds ever seen -- the local logs get pruned

Sources: ccusage (this Mac's agent logs), `gh api graphql` (contributions), and the
WakaTime API with the key its editor plugin writes to ~/.wakatime.cfg (skipped until then).
Commits as the github-actions bot, so the daily commit is not one of Zeke's contributions.
Run twice a day by ~/Library/LaunchAgents/com.zekevoigt.readme-tokens.plist.
"""
import base64
import configparser
import datetime as dt
import html
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG = REPO / "assets" / "activity.json"
SVG = REPO / "assets" / "activity.svg"
PAGE = REPO / "docs" / "index.html"
PAGE_URL = "https://zekevoigt.github.io/ZekeVoigt/"
BOT = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"

CELL, PITCH, LEFT, TOP = 10, 13, 32, 44
LIGHT = ["#eff2f5", "#aceebb", "#4ac26b", "#2da44e", "#116329"]
DARK = ["#151b23", "#033a16", "#196c2e", "#2ea043", "#56d364"]

os.environ["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:" + os.environ.get("PATH", "")


def run(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True, cwd="/tmp").stdout


def tokens():
    data = json.loads(run("npx", "-y", "ccusage@latest", "daily", "--json"))
    return {row["period"]: row["totalTokens"] for row in data["daily"]}


def contributions():
    q = ("query { viewer { contributionsCollection { contributionCalendar {"
         " weeks { contributionDays { date contributionCount } } } } } }")
    cal = json.loads(run("gh", "api", "graphql", "-f", f"query={q}"))
    weeks = cal["data"]["viewer"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    return {d["date"]: d["contributionCount"] for w in weeks for d in w["contributionDays"]}


def coding_seconds(start, end):
    cfg = configparser.ConfigParser()
    cfg.read(Path.home() / ".wakatime.cfg")
    key = cfg.get("settings", "api_key", fallback="")
    if not key:
        return {}
    req = urllib.request.Request(
        f"https://wakatime.com/api/v1/users/current/summaries?start={start}&end={end}",
        headers={"Authorization": "Basic " + base64.b64encode(key.encode()).decode()},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)["data"]
    except Exception as e:  # WakaTime down or key revoked: keep what the log has
        print(f"wakatime: {e}", file=sys.stderr)
        return {}
    return {d["range"]["date"]: int(d["grand_total"]["total_seconds"]) for d in data}


def merge(log, field, fresh):
    for day, v in fresh.items():
        row = log.setdefault(day, {})
        row[field] = max(row.get(field, 0), v)


def short(n):
    for div, unit in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if n >= div:
            return f"{n / div:.1f}".rstrip("0").rstrip(".") + unit
    return str(int(n))


def duration(s):
    h, m = divmod(round(s / 60), 60)
    return f"{h}h {m}m" if h else f"{m}m"


def levels(values):
    """GitHub-style: 0 for none, then 1-4 by quartile of the days that have any."""
    nz = sorted(v for v in values if v)
    if not nz:
        return lambda v: 0
    cuts = [nz[min(len(nz) - 1, len(nz) * q // 4)] for q in (1, 2, 3)]
    return lambda v: 0 if not v else 1 + sum(v > c for c in cuts)


def grid(log, contrib, today):
    """The days as (week column, weekday row, date, tokens, contributions, seconds)."""
    start = today - dt.timedelta(days=(today.weekday() + 1) % 7 + 52 * 7)  # a Sunday
    days = []
    d = start
    while d <= today:
        row = log.get(d.isoformat(), {})
        days.append(((d - start).days // 7, (d.weekday() + 1) % 7, d,
                     row.get("tokens", 0), contrib.get(d.isoformat(), 0), row.get("seconds", 0)))
        d += dt.timedelta(days=1)
    return days


def ordinal(d):
    n = d.day
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{d:%B} {n}{suf}"


def draw(days, total, interactive):
    level = levels([t for *_, t, _, _ in days])
    weeks = days[-1][0] + 1
    W = LEFT + weeks * PITCH + 12
    H = TOP + 7 * PITCH + 34

    out = []
    last = -9
    for col, row, d, *_ in days:
        if row == 0 and (d.day <= 7 and col - last >= 3 or col == 0 and d.day <= 21):
            out.append(f'<text class="lbl" x="{LEFT + col * PITCH}" y="{TOP - 8}">{d:%b}</text>')
            last = col
    for row, name in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        out.append(f'<text class="lbl" x="{LEFT - 6}" y="{TOP + row * PITCH + 9}" text-anchor="end">{name}</text>')

    for col, row, d, tok, con, sec in days:
        attrs = ""
        if interactive:
            attrs = (f' tabindex="0" data-date="{html.escape(ordinal(d))}" data-t="{tok}"'
                     f' data-c="{con}" data-s="{sec}"')
        out.append(f'<rect class="c l{level(tok)}" x="{LEFT + col * PITCH}" y="{TOP + row * PITCH}"'
                   f' width="{CELL}" height="{CELL}" rx="2"{attrs}/>')

    ly = TOP + 7 * PITCH + 14
    lx = W - 12 - 5 * PITCH - 34
    out.append(f'<text class="lbl" x="{lx - 6}" y="{ly + 9}" text-anchor="end">Less</text>')
    for i in range(5):
        out.append(f'<rect class="c l{i}" x="{lx + i * PITCH}" y="{ly}" width="{CELL}" height="{CELL}" rx="2"/>')
    out.append(f'<text class="lbl" x="{lx + 5 * PITCH - 3 + 6}" y="{ly + 9}">More</text>')
    if not interactive:
        out.append(f'<text class="lbl" x="{LEFT}" y="{ly + 9}">Click for daily details</text>')

    swatch = "\n".join(f"  .l{i} {{ fill: {c}; }}" for i, c in enumerate(LIGHT))
    swatch_dark = "\n".join(f"    .l{i} {{ fill: {c}; }}" for i, c in enumerate(DARK))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="{short(total)} AI tokens in the last year, one square per day">
<style>
  text {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif; }}
  .title {{ fill: #1f2328; font-size: 16px; }}
  .lbl {{ fill: #59636e; font-size: 12px; }}
  .c {{ stroke: rgba(31, 35, 40, 0.05); stroke-width: 1; }}
{swatch}
  @media (prefers-color-scheme: dark) {{
    .title {{ fill: #f0f6fc; }}
    .lbl {{ fill: #9198a1; }}
    .c {{ stroke: rgba(240, 246, 252, 0.05); }}
{swatch_dark}
  }}
</style>
<text class="title" x="{LEFT}" y="18">{short(total)} AI tokens in the last year</text>
{chr(10).join(out)}
</svg>
"""


def page(svg):
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Zeke's activity</title>
<style>
  :root {{ color-scheme: light dark; --bg: #ffffff; --tip: #25292e; --tip-fg: #ffffff; --muted: #9198a1; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg: #0d1117; --tip: #3d444d; }} }}
  html, body {{ margin: 0; background: var(--bg); }}
  body {{ min-height: 100vh; display: grid; place-items: center; padding: 16px; box-sizing: border-box; }}
  .wrap {{ max-width: 100%; overflow-x: auto; }}
  svg {{ display: block; }}
  rect[tabindex] {{ cursor: pointer; outline: none; }}
  rect[tabindex]:hover, rect[tabindex]:focus-visible {{ stroke: var(--muted); stroke-width: 1.5; }}
  #tip {{ position: fixed; pointer-events: none; opacity: 0; transform: translate(-50%, calc(-100% - 10px));
         background: var(--tip); color: var(--tip-fg); border-radius: 6px; padding: 7px 10px;
         font: 12px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif;
         white-space: nowrap; transition: opacity .08s; }}
  #tip::after {{ content: ""; position: absolute; left: 50%; top: 100%; margin-left: -5px;
                border: 5px solid transparent; border-top-color: var(--tip); }}
  #tip b {{ font-weight: 600; }}
  #tip .dim {{ color: #b7bdc8; }}
</style>
</head>
<body>
<div class="wrap">
{svg}
</div>
<div id="tip" role="tooltip"></div>
<script>
const tip = document.getElementById("tip");
const short = n => {{
  for (const [d, u] of [[1e9, "B"], [1e6, "M"], [1e3, "K"]])
    if (n >= d) return (n / d).toFixed(1).replace(/\\.0$/, "") + u;
  return String(n);
}};
const dur = s => {{
  const m = Math.round(s / 60), h = Math.floor(m / 60);
  return h ? `${{h}}h ${{m % 60}}m` : `${{m}}m`;
}};
const line = (v, text, none) => v ? `<div>${{text}}</div>` : `<div class="dim">${{none}}</div>`;
function show(el) {{
  const t = +el.dataset.t, c = +el.dataset.c, s = +el.dataset.s;
  tip.innerHTML = `<b>${{el.dataset.date}}</b>`
    + line(t, `${{short(t)}} AI tokens`, "No AI tokens")
    + line(c, `${{c}} contribution${{c === 1 ? "" : "s"}}`, "No contributions")
    + line(s, `${{dur(s)}} coding`, "No coding time");
  const r = el.getBoundingClientRect();
  const half = tip.offsetWidth / 2 + 8;
  tip.style.left = Math.min(Math.max(r.left + r.width / 2, half), innerWidth - half) + "px";
  tip.style.top = r.top + "px";
  tip.style.opacity = 1;
}}
const hide = () => tip.style.opacity = 0;
for (const el of document.querySelectorAll("rect[tabindex]")) {{
  el.addEventListener("pointerenter", () => show(el));
  el.addEventListener("pointerleave", hide);
  el.addEventListener("focus", () => show(el));
  el.addEventListener("blur", hide);
}}
addEventListener("scroll", hide, true);
</script>
</body>
</html>
"""


def git(*args):
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=True).stdout


def main():
    today = dt.date.today()
    log = json.loads(LOG.read_text()) if LOG.exists() else {}
    merge(log, "tokens", tokens())
    merge(log, "seconds", coding_seconds(today - dt.timedelta(days=13), today))
    LOG.write_text(json.dumps(dict(sorted(log.items())), indent=1) + "\n")

    days = grid(log, contributions(), today)
    total = sum(t for *_, t, _, _ in days)
    SVG.write_text(draw(days, total, interactive=False))
    PAGE.parent.mkdir(exist_ok=True)
    PAGE.write_text(page(draw(days, total, interactive=True)))
    if "--no-push" in sys.argv:
        return
    git("pull", "--rebase", "--autostash", "-q")
    git("add", "assets", "docs")
    if not git("status", "--porcelain", "assets", "docs").strip():
        return
    subprocess.run(
        ["git", "-C", str(REPO), "-c", f"user.name={BOT}", "-c", f"user.email={BOT_EMAIL}",
         "commit", "-q", "-m", "Update activity grid"],
        check=True,
    )
    git("push", "-q")


if __name__ == "__main__":
    main()
