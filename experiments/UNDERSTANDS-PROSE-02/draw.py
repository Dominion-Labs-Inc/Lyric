"""Draws the texts of UNDERSTANDS-PROSE-02 from where they are published, by a fixed seed, each cut to its opening
sentences as published (`opening`). Writes texts_raw.json: the sentences alone; the questions were written after, by
hand (questions.py), and joined to them by assemble.py into texts.json.

What it draws from is fetched once into sources/ (as it stood on 2026-10-21, kept there and not pushed), each listing
from LISTINGS and every page after into sources/cache, so drawing again draws the same texts.

    python3 experiments/UNDERSTANDS-PROSE-02/draw.py && python3 experiments/UNDERSTANDS-PROSE-02/assemble.py
"""
import hashlib
import html
import json
import random
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "sources"
SEED = 20261021
SENTENCES = 10
UA = {"User-Agent": "lyric-prose-02/0.1 (research)"}
ABBREVIATIONS = ("e.g.", "i.e.", "etc.", "U.S.", "U.K.", "c.", "ca.", "St.", "Mr.", "Mrs.", "Dr.", "No.", "vs.", "et al.",
                 "approx.", "Jan.", "Feb.", "Aug.", "Sept.", "Oct.", "Nov.", "Dec.", "Inc.", "Ltd.", "Fig.", "Eq.")
#: What the texts are drawn from, as fetched on 2026-10-21.
LISTINGS = {
    "vital3.json": "https://en.wikipedia.org/w/api.php?action=parse&oldid=1380842742&prop=wikitext|revid&format=json&formatversion=2",
    "govuk_guides.json": "https://www.gov.uk/api/search.json?filter_format=guide&count=1000&fields=link,title",
    "py_modindex.html": "https://docs.python.org/3/py-modindex.html",
    "arxiv.xml": "https://export.arxiv.org/api/query?search_query=cat:cs.LG+OR+cat:q-bio.PE+OR+cat:astro-ph.EP+OR+cat:econ.GN&sortBy=submittedDate&sortOrder=descending&max_results=200",
    "openssh_2k.log": "https://raw.githubusercontent.com/logpai/loghub/master/OpenSSH/OpenSSH_2k.log",
    "linux_2k.log": "https://raw.githubusercontent.com/logpai/loghub/master/Linux/Linux_2k.log",
    "wikinews_list.json": "https://en.wikinews.org/w/api.php?action=query&list=categorymembers&cmtitle=Category:Published&cmnamespace=0&cmlimit=500&cmsort=timestamp&cmdir=desc&format=json&formatversion=2",
    "constitution.html": "https://www.archives.gov/founding-docs/constitution-transcript",
    "amendments.html": "https://www.archives.gov/founding-docs/amendments-11-27",
}


def get(url):
    """A page, fetched once and kept in sources/cache."""
    kept = SRC / "cache" / hashlib.sha1(url.encode()).hexdigest()
    if not kept.exists():
        time.sleep(2)
        kept.parent.mkdir(parents=True, exist_ok=True)
        kept.write_text(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read().decode())
    return kept.read_text()


def source(name):
    """A listing in sources/, fetched first where it is not there."""
    if not (SRC / name).exists():
        (SRC / name).write_text(get(LISTINGS[name]))
    return (SRC / name).read_text()


def clean(text):
    """Mechanical only: word joiners, non-breaking spaces, empty parentheses (where a pronunciation was) and runs of
    white space."""
    text = text.replace("\u2060", "").replace("\u00a0", " ").replace("\u200b", "")
    text = re.sub(r"\s*\(\s+\)", "", text)
    return re.sub(r"\s+", " ", text).strip()


def sentences(paragraph):
    """A paragraph's sentences: a split after . ! or ? followed by a space and a capital, a digit or a quote, except
    after an abbreviation or a lone initial."""
    out, start = [], 0
    for m in re.finditer(r"[.!?][\"”')\]]?\s+(?=[A-Z0-9\"“(])", paragraph):
        head = paragraph[start:m.end()].rstrip()
        last = head.split()[-1].lstrip("(\"“")
        if last in ABBREVIATIONS or head.endswith("et al.") or re.fullmatch(r"[A-Z]\.", last):
            continue
        out.append(head)
        start = m.end()
    tail = paragraph[start:].strip()
    if tail:
        out.append(tail)
    return out


def opening(paragraphs, n=SENTENCES):
    """The opening n sentences of the paragraphs, lists left out: the sentence that introduces one (ending ":"), and
    the items after it (each ending ";" or "; and", then the last)."""
    out, in_list = [], False
    for paragraph in paragraphs:
        paragraph = clean(paragraph)
        if in_list:
            in_list = paragraph.endswith((";", "; and", ", and"))
            continue
        said = sentences(paragraph)
        if said and said[-1].endswith(":"):
            said, in_list = said[:-1], True
        for s in said:
            if len(out) < n:
                out.append(s)
    return out


def text_of(fragment):
    return clean(html.unescape(re.sub(r"<[^>]+>", "", fragment)))


texts = []
rng = random.Random(SEED)


def vital_articles():
    """Wikipedia's Vital articles (level 3), by section."""
    sections, section = {}, None
    for line in json.loads(source("vital3.json"))["parse"]["wikitext"].split("\n"):
        heading = re.match(r"^(=+)\s*(.*?)\s*\1\s*$", line)
        if heading and len(heading.group(1)) == 2:
            section = re.sub(r"\(.*?\)", "", heading.group(2)).strip()
            continue
        for link in re.findall(r"\[\[([^\]|#]+)", line):
            if section and not link.startswith(("Wikipedia:", "File:", "Category:")):
                sections.setdefault(section, []).append(link.strip())
    return sections


def wikipedia_leads():
    """Five articles drawn for each of four kinds, those UNDERSTANDS-PROSE-01 is about left out, and each one's lead
    as it stood (by revision)."""
    if not (SRC / "wiki_extracts.json").exists():
        sections, draw = vital_articles(), random.Random(SEED)
        told = {"Whale", "Photosynthesis", "Eiffel Tower", "Python (programming language)", "Prime number"}
        pools = {"encyclopedia": sum((sections[k] for k in ["Geography", "Everyday life", "Arts", "Society and social sciences",
                                                            "People", "Technology", "Health, medicine and disease",
                                                            "Philosophy and religion"]), []),
                 "science": sections["Science"], "history": sections["History"], "mathematics": sections["Mathematics"]}
        kind_of = {title: kind for kind, pool in pools.items() for title in draw.sample(sorted(set(pool) - told), 5)}
        leads, titles = {}, list(kind_of)
        for i in range(0, len(titles), 4):
            q = urllib.parse.urlencode({"action": "query", "prop": "extracts|revisions", "exintro": 1, "explaintext": 1,
                                        "exlimit": 20, "rvprop": "ids|timestamp", "titles": "|".join(titles[i:i + 4]),
                                        "format": "json", "formatversion": 2})
            for page in json.loads(get("https://en.wikipedia.org/w/api.php?" + q))["query"]["pages"]:
                leads[page["title"]] = {"kind": kind_of[page["title"]], "title": page["title"],
                                        "revid": page["revisions"][0]["revid"], "extract": page.get("extract", "")}
        (SRC / "wiki_extracts.json").write_text(json.dumps({t: leads[t] for t in kind_of}, indent=1))
    return json.loads((SRC / "wiki_extracts.json").read_text())


# Encyclopedia, science, history, mathematics: Wikipedia leads drawn from its Vital articles (level 3).
wiki = wikipedia_leads()
for title, page in wiki.items():
    paragraphs = []
    for p in page["extract"].split("\n"):
        if re.search(r"\{\\displaystyle|^\s*$", p):
            continue
        if len(p.strip()) < 40 and not p.strip().endswith("."):
            break
        if paragraphs and not re.search(r"[.!?:;\"”)]\s*$", paragraphs[-1]) and re.match(r"\s*[a-z]", p):
            paragraphs[-1] += " " + p
            continue
        paragraphs.append(p)
    texts.append({"name": title, "kind": page["kind"], "source": f"https://en.wikipedia.org/w/index.php?oldid={page['revid']}",
                  "licence": "CC BY-SA 4.0", "text": opening(paragraphs)})

# Webpage: GOV.UK guides, drawn from the guides its search lists; the page's paragraphs in order, lists left out.
guides = sorted(r["link"] for r in json.loads(source("govuk_guides.json"))["results"])
for link in rng.sample(guides, 5):
    page = json.loads(get("https://www.gov.uk/api/content" + link))
    parts = page["details"].get("parts") or [{"body": page["details"].get("body", "")}]
    body = "".join(part.get("body", "") for part in parts)
    if isinstance(body, list):
        body = "".join(b.get("content", "") for b in body)
    body = re.sub(r"<(ul|ol)\b.*?</\1>", "", body, flags=re.S)
    paragraphs = [text_of(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", body, re.S)]
    texts.append({"name": page["title"].strip(), "kind": "webpage", "source": "https://www.gov.uk" + link,
                  "licence": "Open Government Licence v3.0", "text": opening(paragraphs)})

# Code documentation: the Python documentation of its standard library's modules, drawn from its module index (those
# deprecated or removed, and private ones, left out); the module page's paragraphs in order, source and availability
# notes left out.
index = source("py_modindex.html")
modules = re.findall(r'<a href="library/([a-z0-9_.]+)\.html#module-([a-z0-9_]+)"><code class="xref">([a-z0-9_]+)</code></a>', index)
gone = set(re.findall(r'<code class="xref">([a-z0-9_]+)</code></a>.{0,200}?(?:Deprecated|Removed)', index, re.S))
modules = sorted({(page, name) for page, name, shown in modules if name == shown and not name.startswith("_") and name not in gone})
def module_text(page, name):
    body = get(f"https://docs.python.org/3/library/{page}.html")
    body = body[body.index("<h1>"):]
    body = re.sub(r"<(ul|ol|table)\b.*?</\1>", "", body, flags=re.S)
    body = re.sub(r'<div class="admonition seealso">.*?</div>', "", body, flags=re.S)
    paragraphs = [text_of(p) for p in re.findall(r"<p>(.*?)</p>", body, re.S)]
    paragraphs = [p for p in paragraphs if p and not p.startswith(("Source code:", "Availability", "Added in version",
                                                                   "Changed in version", "Deprecated since"))]
    return {"name": name, "kind": "code documentation", "source": f"https://docs.python.org/3/library/{page}.html",
            "licence": "PSF Documentation Licence", "text": opening(paragraphs)}


# A module documented in fewer than three sentences of prose (its page a list or a table) is replaced by one drawn by a
# second seed, so the draws of the other kinds stay as they are.
again = random.Random(SEED + 1)
for page, name in rng.sample(modules, 5):
    text = module_text(page, name)
    while len(text["text"]) < 3:
        text = module_text(*again.choice(modules))
    texts.append(text)

# Paper abstract: arXiv abstracts, drawn from the 200 newest in four fields.
feed = source("arxiv.xml")
entries = re.findall(r"<entry>(.*?)</entry>", feed, re.S)
for entry in rng.sample(entries, 5):
    title = clean(re.search(r"<title>(.*?)</title>", entry, re.S).group(1))
    link = re.search(r"<id>(.*?)</id>", entry).group(1)
    summary = clean(html.unescape(re.search(r"<summary>(.*?)</summary>", entry, re.S).group(1)))
    texts.append({"name": title, "kind": "paper abstract", "source": link, "licence": "arXiv metadata (CC0)",
                  "text": opening([summary])})

# Security log: ten lines running from a drawn line, three times from an OpenSSH log and twice from a Linux one
# (Loghub).
for log in ("openssh_2k.log", "openssh_2k.log", "openssh_2k.log", "linux_2k.log", "linux_2k.log"):
    lines = source(log).splitlines()
    at = rng.randrange(len(lines) - SENTENCES)
    texts.append({"name": f"{log} lines {at + 1}-{at + SENTENCES}", "kind": "security log",
                  "source": f"https://github.com/logpai/loghub/blob/master/{'OpenSSH/OpenSSH' if 'ssh' in log else 'Linux/Linux'}_2k.log",
                  "licence": "Loghub (research use)", "text": [clean(line) for line in lines[at:at + SENTENCES]]})

# News: Wikinews articles, drawn from its 500 newest published; the dateline left out.
published = sorted(m["title"] for m in json.loads(source("wikinews_list.json"))["query"]["categorymembers"])
for title in rng.sample(published, 5):
    q = urllib.parse.urlencode({"action": "query", "prop": "extracts|revisions", "explaintext": 1, "rvprop": "ids",
                                "titles": title, "format": "json", "formatversion": 2})
    page = json.loads(get("https://en.wikinews.org/w/api.php?" + q))["query"]["pages"][0]
    body = page["extract"].split("\n== ")[0]
    paragraphs = [p for p in body.split("\n") if p.strip() and not p.startswith(("File:", "Image:"))]
    if paragraphs and re.match(r"^\w+day, \w+ \d+, \d{4}$", paragraphs[0].strip()):
        paragraphs = paragraphs[1:]
    texts.append({"name": title, "kind": "news",
                  "source": f"https://en.wikinews.org/w/index.php?oldid={page['revisions'][0]['revid']}",
                  "licence": "CC BY 2.5", "text": opening(paragraphs)})

# Premises and a rule: rules of the United States Constitution as the National Archives transcribes them, chosen (not
# drawn) as rules a question can apply: who may hold an office, who may vote, how long a term runs.
def published(*files):
    out = []
    for f in files:
        page = html.unescape(re.sub(r"<[^>]+>", "\n", source(f)))
        out += [clean(p) for p in re.split(r"\n\s*\n", page) if p.strip()]
    return out


clauses = published("constitution.html", "amendments.html")
RULES = {
    "The House of Representatives": ["The House of Representatives shall be composed", "No Person shall be a Representative",
                                     "When vacancies happen in the Representation", "The House of Representatives shall chuse"],
    "The Senate": ["The Senate of the United States shall be composed", "No Person shall be a Senator",
                   "The Vice President of the United States shall be President of the Senate"],
    "The President": ["The executive Power shall be vested", "No Person except a natural born Citizen",
                      "In case of the removal of the President from office"],
    "The right to vote": ["The right of citizens of the United States to vote shall not be denied or abridged by the United States or by any State on account of race",
                          "The right of citizens of the United States to vote shall not be denied or abridged by the United States or by any State on account of sex",
                          "The right of citizens of the United States, who are eighteen"],
    "Terms of office": ["No person shall be elected to the office of the President more than twice",
                        "The terms of the President and Vice President shall end"],
}
for name, starts in RULES.items():
    found = []
    for start in starts:
        clause = next(c for c in clauses if c.startswith(start))
        found.append(sentences(clause)[0].rstrip("-") if start.startswith(("The executive", "The right of citizens of the United States to vote shall not be denied or abridged by the United States or by any State on account of race", "No person shall be elected")) else clause)
    texts.append({"name": name, "kind": "premises and a rule",
                  "source": "https://www.archives.gov/founding-docs/constitution-transcript, https://www.archives.gov/founding-docs/amendments-11-27",
                  "licence": "public domain", "text": found})

(HERE / "texts_raw.json").write_text(json.dumps(texts, indent=1, ensure_ascii=False))
for t in texts:
    print(f"{t['kind']:20} {len(t['text']):2d}  {t['name'][:70]}")
print(sum(len(t["text"]) for t in texts), "sentences in", len(texts), "texts")
