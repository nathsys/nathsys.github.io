#!/usr/bin/env python3
"""Writes GitHub stats into the page between the github-stats markers.

Run by the Pages workflow before publishing, so the site itself stays free of
JavaScript and third-party requests. If the API can't be reached, the page is
left as it is and the stats committed last time are published instead.

Usage: GITHUB_TOKEN=... python3 scripts/github_stats.py public/index.html
"""
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.request

USER = "nathsys"
SKIP_REPOS = {"nathsys.github.io"}  # this site's own HTML/CSS would skew the languages
TOP_LANGUAGES = 5
START, END = "<!-- github-stats:start -->", "<!-- github-stats:end -->"

CELL, GAP, TOP = 10, 3, 16  # heatmap geometry, in SVG user units
LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2,
          "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}


def api(path, token, body=None):
    req = urllib.request.Request(
        "https://api.github.com/" + path,
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "User-Agent": f"{USER}-site-stats"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def fetch(token):
    repos = [r for r in api(f"users/{USER}/repos?type=owner&per_page=100", token)
             if not r["fork"]]
    languages = {}
    for r in repos:
        if r["name"] in SKIP_REPOS:
            continue
        for lang, size in api(f"repos/{USER}/{r['name']}/languages", token).items():
            languages[lang] = languages.get(lang, 0) + size
    query = """query($login: String!) { user(login: $login) { contributionsCollection {
      contributionCalendar { totalContributions
        weeks { contributionDays { date contributionCount contributionLevel } } } } } }"""
    cal = api("graphql", token, {"query": query, "variables": {"login": USER}})
    cal = cal["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    return {
        "repos": len(repos),
        "stars": sum(r["stargazers_count"] for r in repos),
        "languages": languages,
        "total": cal["totalContributions"],
        "weeks": [w["contributionDays"] for w in cal["weeks"]],
    }


def day_label(iso):
    d = dt.date.fromisoformat(iso)
    return f"{d.day} {d:%b %Y}"


def heatmap(weeks):
    width = len(weeks) * (CELL + GAP) - GAP
    height = TOP + 7 * (CELL + GAP) - GAP
    out = [f'<svg class="heatmap" viewBox="0 0 {width} {height}" role="img" '
           f'aria-label="Contributions per day over the past year">']
    # Label each month above the first week that starts in it, dropping labels
    # that would collide with the next one or run off the right edge.
    starts, prev = [], None
    for col, days in enumerate(weeks):
        month = dt.date.fromisoformat(days[0]["date"]).month
        if month != prev:
            starts.append((col, month))
            prev = month
    if len(starts) > 1 and starts[1][0] - starts[0][0] < 3:
        starts.pop(0)
    for col, month in starts:
        if col <= len(weeks) - 3:
            out.append(f'<text x="{col * (CELL + GAP)}" y="10">{dt.date(2000, month, 1):%b}</text>')
    for col, days in enumerate(weeks):
        x = col * (CELL + GAP)
        for d in days:
            row = dt.date.fromisoformat(d["date"]).isoweekday() % 7  # Sunday first
            n = d["contributionCount"]
            title = f'{n} contribution{"" if n == 1 else "s"} on {day_label(d["date"])}'
            out.append(f'<rect class="l{LEVELS[d["contributionLevel"]]}" x="{x}" '
                       f'y="{TOP + row * (CELL + GAP)}" width="{CELL}" height="{CELL}" rx="2">'
                       f'<title>{title}</title></rect>')
    out.append("</svg>")
    return "".join(out)


def language_rows(languages):
    total = sum(languages.values())
    ranked = sorted(languages.items(), key=lambda kv: -kv[1])
    top, rest = ranked[:TOP_LANGUAGES], sum(v for _, v in ranked[TOP_LANGUAGES:])
    if rest:
        top.append(("Other", rest))
    biggest = top[0][1]
    rows = []
    for name, size in top:
        share = 100 * size / total
        rows.append(
            f'<div class="lang"><span>{html.escape(name)}</span>'
            f'<svg viewBox="0 0 100 6" preserveAspectRatio="none" aria-hidden="true">'
            f'<rect width="{100 * size / biggest:.1f}" height="6"/></svg>'
            f'<span class="dim">{share:.1f}%</span></div>')
    return "\n".join(rows)


def render(s, today):
    return f"""{START}
      <dl class="stats">
        <div><dt>Contributions, past year</dt><dd>{s['total']:,}</dd></div>
        <div><dt>Public repositories</dt><dd>{s['repos']}</dd></div>
        <div><dt>Stars</dt><dd>{s['stars']}</dd></div>
      </dl>
      <div class="heatmap-wrap">
        {heatmap(s['weeks'])}
        <p class="scale" aria-hidden="true">Less <i class="l0"></i><i class="l1"></i><i class="l2"></i><i class="l3"></i><i class="l4"></i> More</p>
      </div>
      <h3 class="langs-title">Languages <span class="dim">by code size, across my repositories</span></h3>
      <div class="langs">
{language_rows(s['languages'])}
      </div>
      <p class="updated">From the GitHub API, updated {day_label(today.isoformat())}.</p>
      {END}"""


def main(page):
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        sys.exit("github_stats: set GITHUB_TOKEN or GH_TOKEN")
    try:
        stats = fetch(token)
    except Exception as e:  # keep the committed snapshot rather than failing the deploy
        print(f"::warning::github_stats: keeping the previous stats ({e})")
        return
    text = open(page, encoding="utf-8").read()
    block = re.compile(re.escape(START) + ".*?" + re.escape(END), re.S)
    if not block.search(text):
        sys.exit(f"github_stats: markers not found in {page}")
    text = block.sub(lambda _: render(stats, dt.date.today()), text)
    open(page, "w", encoding="utf-8").write(text)
    print(f"github_stats: {stats['total']} contributions, {stats['repos']} repos, "
          f"{stats['stars']} stars")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "public/index.html")
