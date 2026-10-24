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


def api(path, token):
    req = urllib.request.Request(
        "https://api.github.com/" + path,
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
    return {"repos": len(repos), "languages": languages}


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
        <div><dt>Public repositories</dt><dd>{s['repos']}</dd></div>
      </dl>
      <h3 class="langs-title">Languages <span class="dim">by code size, across my repositories</span></h3>
      <div class="langs">
{language_rows(s['languages'])}
      </div>
      <p class="updated">From the GitHub API, updated {today.day} {today:%b %Y}.</p>
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
    print(f"github_stats: {stats['repos']} repos, {len(stats['languages'])} languages")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "public/index.html")
