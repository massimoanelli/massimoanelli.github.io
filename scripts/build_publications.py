#!/usr/bin/env python3
"""
Generate the research listings from publications.bib.

Quarto renders .bib files into flat reference lists; it has no native way to
group by a custom field or attach status badges. So this script parses the .bib
and emits two markdown partials that index.qmd and research.qmd include:

    _generated/featured.md   -> home page: publications and working papers, two columns
    _generated/research.md   -> full list, one column per research area

It runs automatically as a `pre-render` step (see _quarto.yml), so editing
publications.bib and re-rendering is the whole workflow. No dependencies beyond
the standard library.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIB = ROOT / "publications.bib"
OUT = ROOT / "_generated"

# Display order and headings for the `theme` field.
THEMES = [
    ("tech-politics", "Technology, Politics and Society"),
    ("migration", "Migration Selection"),
    ("education", "Education and Human Capital"),
    ("health-ageing", "Health and Ageing"),
]

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
    """'Anelli, Massimo and Peri, Giovanni' -> 'with G. Peri' (first initial only)."""
    names = [a.strip() for a in author_field.split(" and ") if a.strip()]
    others = []
    for n in names:
        if n.startswith("Anelli,"):
            continue
        surname, _, given = n.partition(",")
        given = given.strip()
        initial = f"{given[0]}. " if given else ""
        others.append(f"{initial}{surname.strip()}")
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
        elif e.get("number"):
            bits.append(f"no. {e['number']}")
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
    if "accepted" in s or "forthcoming" in s:
        cls = "accepted"
    elif "revise" in s:
        cls = "rr"
    else:
        cls = "submitted"
    return f'<span class="status status-{cls}">{status}</span>'


def render(e, extras=True):
    """A single entry as one paragraph with hard line breaks (trailing two
    spaces), so the title, authors, venue and badge stay visually together."""
    title = latex_to_text(e.get("title", ""))
    url = e.get("url") or (f"https://doi.org/{e['doi']}" if e.get("doi") else "")
    head = f"[{title}]({url})" if url else title

    lines = [f"[{head}]{{.pub-title}}  "]

    meta = coauthors(e.get("author", ""))
    if meta:
        lines.append(f'<span class="pub-authors">{meta}</span>  ')

    venue = outlet(e)
    if venue:
        lines.append(f'<span class="pub-venue">{venue}</span>  ')

    if e.get("status"):
        lines.append(badge(latex_to_text(e["status"])) + "  ")

    # Awards are shown everywhere, including the compact homepage entries.
    if e.get("award"):
        lines.append(f'<span class="status status-award">🏆 {latex_to_text(e["award"])}</span>  ')

    if extras:
        if e.get("media"):
            lines.append(f'<span class="media">Coverage: {latex_to_text(e["media"])}</span>  ')

    # Drop the hard break on the last line so no empty line trails the entry.
    lines[-1] = lines[-1].rstrip()
    return "\n".join(lines) + "\n"


def date_key(e):
    try:
        year = int(e.get("year", "0"))
    except ValueError:
        year = 0
    try:
        month = int(e.get("month", "0"))
    except ValueError:
        month = 0
    return (-year, -month)


def stage(e):
    """How far along a paper is. Status beats kind: an accepted working paper
    is a forthcoming publication, whatever its BibTeX entry type says."""
    s = e.get("status", "").lower()
    if "accepted" in s or "forthcoming" in s:
        return 0
    if "revise" in s:
        return 1
    if e["kind"] == "unpublished":
        return 2
    if e.get("category") == "italian":
        return 5
    return 3 if e["kind"] == "article" else 4


def sort_key(e):
    return (stage(e),) + date_key(e)


def entry_div(e, compact=False):
    """One entry wrapped in a Pandoc div, so it can sit inside a grid column."""
    return "::: {.pub}\n" + render(e, extras=not compact) + "\n:::\n"


def column(heading, blocks):
    return "::: {.pub-col}\n\n" + f"## {heading}\n\n" + "\n".join(blocks) + "\n:::\n"


def main():
    entries = parse_bib(BIB.read_text(encoding="utf-8"))
    OUT.mkdir(exist_ok=True)

    # --- Home page: two columns ---------------------------------------------
    # Left: forthcoming papers, then the most recent international articles.
    # Right: working papers, R&Rs first, then submitted or featured drafts.
    # Italian-journal articles stay on the Research page only.
    forthcoming = sorted((e for e in entries if stage(e) == 0 and e.get("category") != "italian"),
                         key=date_key)
    recent_articles = sorted((e for e in entries if stage(e) == 3), key=date_key)[:3]
    pubs = forthcoming + recent_articles

    wps = [e for e in entries if stage(e) == 1
           or (stage(e) == 2 and not e.get("status", "").lower().startswith("draft")
               and (e.get("status") or e.get("featured", "").lower() == "yes"))]
    wps.sort(key=sort_key)

    home = ("::: {.pub-grid .pub-grid-2}\n\n"
            + column("Forthcoming & Recent Publications", [entry_div(e, compact=True) for e in pubs])
            + "\n"
            + column("Working Papers", [entry_div(e, compact=True) for e in wps])
            + "\n:::\n")
    (OUT / "featured.md").write_text(home, encoding="utf-8")

    # --- Research page: one column per area ---------------------------------
    # Inside each area: forthcoming and R&R, then working papers, then publications.
    # Italian-journal articles are pulled out of the areas into their own section,
    # stacked under the last area (Health and Ageing) in the same column.
    groups = [("Forthcoming & Revise and Resubmit", {0, 1}),
              ("Working Papers", {2}),
              ("Publications", {3, 4})]
    italian = sorted((e for e in entries if e.get("category") == "italian"), key=date_key)
    rest = [e for e in entries if e.get("category") != "italian"]
    cols = []
    seen = {e["key"] for e in italian}
    themes = THEMES + [("__other__", "Other")]
    for slug, heading in themes:
        if slug == "__other__":
            members = [e for e in rest if e["key"] not in seen]
        else:
            members = [e for e in rest if e.get("theme") == slug]
        if not members:
            continue
        seen.update(e["key"] for e in members)
        blocks = []
        for label, stages in groups:
            sub = sorted((e for e in members if stage(e) in stages), key=sort_key)
            if sub:
                blocks.append(f"### {label}\n")
                blocks.extend(entry_div(e) for e in sub)
        if slug == THEMES[-1][0] and italian:
            blocks.append("::: {.pub-subsection}\n\n## Publications in Italian Journals\n\n"
                          + "\n".join(entry_div(e) for e in italian) + "\n:::\n")
        cols.append(column(heading, blocks))

    research = "::: {.pub-grid .pub-grid-4}\n\n" + "\n".join(cols) + "\n:::\n"
    (OUT / "research.md").write_text(research, encoding="utf-8")
    print(f"[build_publications] {len(entries)} entries -> home: {len(pubs)} publications, "
          f"{len(wps)} working papers")


if __name__ == "__main__":
    main()
