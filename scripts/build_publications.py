#!/usr/bin/env python3
"""
Generate the research listings from publications.bib.

Quarto renders .bib files into flat reference lists; it has no native way to
group by a custom field or attach status badges. So this script parses the .bib
and emits two markdown partials that index.qmd and research.qmd include:

    _generated/featured.md   -> the "New & Forthcoming" block on the home page
    _generated/research.md   -> the full list, grouped by theme

It runs automatically as a `pre-render` step (see _quarto.yml), so editing
publications.bib and re-rendering is the whole workflow. No dependencies beyond
the standard library.
"""

import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIB = ROOT / "publications.bib"
OUT = ROOT / "_generated"

# Display order and headings for the `theme` field.
THEMES = [
    ("tech-politics", "Technology, Politics and Society"),
    ("migration", "Migration Selection"),
    ("health-ageing", "Health and Ageing"),
    ("education", "Education and Human Capital"),
]

# Working papers sort above published work within a theme.
KIND_RANK = {"unpublished": 0, "article": 1, "incollection": 2}


def parse_bib(text):
    """Minimal BibTeX parser. Returns a list of dicts with 'kind' and 'key'."""
    entries = []
    # Strip whole-line comments so stray '@' in prose can't start a fake entry.
    text = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("%"))

    for m in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text):
        kind, key = m.group(1).lower(), m.group(2)
        # Walk forward counting braces to find the end of this entry.
        i = m.end()
        depth = 1
        while i < len(text) and depth > 0:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        body = text[m.end(): i - 1]

        fields = {"kind": kind, "key": key}
        for fm in re.finditer(r"(\w+)\s*=\s*\{", body):
            name = fm.group(1).lower()
            j = fm.end()
            d = 1
            while j < len(body) and d > 0:
                if body[j] == "{":
                    d += 1
                elif body[j] == "}":
                    d -= 1
                j += 1
            fields[name] = " ".join(body[fm.end(): j - 1].split())
        entries.append(fields)
    return entries


def latex_to_text(s):
    """Undo the handful of LaTeX-isms that appear in a .bib."""
    s = s.replace("--", "–").replace("\\&", "&").replace("~", " ")
    s = re.sub(r"\{\\'([a-z])\}", r"\1", s, flags=re.I)
    return s.strip()


def coauthors(author_field):
    """'Anelli, Massimo and Peri, Giovanni' -> 'with Giovanni Peri'."""
    names = [a.strip() for a in author_field.split(" and ") if a.strip()]
    others = []
    for n in names:
        if n.startswith("Anelli,"):
            continue
        surname, _, given = n.partition(",")
        others.append(f"{given.strip()} {surname.strip()}".strip())
    if not others:
        return ""
    if len(others) == 1:
        return f"with {others[0]}"
    if len(others) == 2:
        return f"with {others[0]} and {others[1]}"
    return "with " + ", ".join(others[:-1]) + f", and {others[-1]}"


def outlet(e):
    """The one-line venue description under a title."""
    if e["kind"] == "article":
        bits = [f"*{latex_to_text(e.get('journal', ''))}*"]
        if e.get("volume"):
            vol = e["volume"]
            if e.get("number"):
                vol += f"({e['number']})"
            bits.append(vol)
        if e.get("pages"):
            bits.append(latex_to_text(e["pages"]))
        if e.get("year"):
            bits.append(e["year"])
        return ", ".join(bits)
    if e["kind"] == "incollection":
        return (
            f"In *{latex_to_text(e.get('booktitle', ''))}*, "
            f"{e.get('publisher', '')}, {e.get('year', '')}"
        )
    return latex_to_text(e.get("note", ""))


def badge(status):
    """Colour-code by how far along the paper is."""
    s = status.lower()
    if s.startswith("accepted"):
        cls = "accepted"
    elif "revise" in s:
        cls = "rr"
    else:
        cls = "submitted"
    return f'<span class="status status-{cls}">{status}</span>'


def render(e, featured=False):
    title = latex_to_text(e.get("title", ""))
    url = e.get("url") or (f"https://doi.org/{e['doi']}" if e.get("doi") else "")
    head = f"[{title}]({url})" if url else title

    lines = [f"### {head}" if not featured else f"**{head}**", ""]

    meta = coauthors(e.get("author", ""))
    if meta:
        lines.append(f"{meta}  ")

    venue = outlet(e)
    if venue:
        lines.append(f"{venue}  ")

    if e.get("status"):
        lines.append(badge(latex_to_text(e["status"])) + "  ")

    if not featured:
        if e.get("award"):
            lines.append(f'<span class="award">{latex_to_text(e["award"])}</span>  ')
        if e.get("media"):
            lines.append(f'<span class="media">Coverage: {latex_to_text(e["media"])}</span>  ')
        if e.get("funding"):
            lines.append(f'<span class="funding">Funded by {latex_to_text(e["funding"])}</span>  ')

    lines.append("")
    return "\n".join(lines)


def sort_key(e):
    try:
        year = int(e.get("year", "0"))
    except ValueError:
        year = 0
    try:
        month = int(e.get("month", "0"))
    except ValueError:
        month = 0
    return (KIND_RANK.get(e["kind"], 9), -year, -month)


def main():
    entries = parse_bib(BIB.read_text(encoding="utf-8"))
    OUT.mkdir(exist_ok=True)

    # --- Home page: "New & Forthcoming" -------------------------------------
    # Ordered by how far along the paper is, not by date: an acceptance at a top
    # journal is the headline even when the working paper itself is years old.
    def news_rank(e):
        s = e.get("status", "").lower()
        if s.startswith("accepted"):
            return 0
        if "revise" in s:
            return 1
        if e["kind"] == "unpublished":
            return 2
        return 3

    feat = [e for e in entries if e.get("featured", "").lower() == "yes"]
    feat.sort(key=lambda e: (news_rank(e), sort_key(e)[1], sort_key(e)[2]))
    body = "\n".join(render(e, featured=True) for e in feat)
    (OUT / "featured.md").write_text(body, encoding="utf-8")

    # --- Research page: everything, grouped by theme ------------------------
    chunks = []
    seen = set()
    for slug, heading in THEMES:
        group = [e for e in entries if e.get("theme") == slug]
        if not group:
            continue
        group.sort(key=sort_key)
        seen.update(e["key"] for e in group)
        chunks.append(f"## {heading}\n")
        chunks.extend(render(e) for e in group)

    # Anything with a missing or unrecognised theme still shows up.
    rest = [e for e in entries if e["key"] not in seen]
    if rest:
        rest.sort(key=sort_key)
        chunks.append("## Other\n")
        chunks.extend(render(e) for e in rest)

    (OUT / "research.md").write_text("\n".join(chunks), encoding="utf-8")
    print(f"[build_publications] {len(entries)} entries -> {len(feat)} featured")


if __name__ == "__main__":
    main()
