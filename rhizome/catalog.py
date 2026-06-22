"""Corpus catalogue — author/title/year metadata per book.

The connection engine needs author info so it can cross-pollinate (connect
*across* authors, never an author to themselves). This builds catalog.json by
scanning converted/ and filling in what it knows; unknown books get a guessed
title and a blank author you can edit by hand.
"""
import json
import pathlib

from . import config

# Hand-curated metadata for the initial corpus. Keyed by output slug (filename
# without .md). Add entries as you convert more books, or edit catalog.json.
KNOWN = {
    "what-is-called-thinking": {
        "author": "Martin Heidegger", "title": "What Is Called Thinking?", "year": 1968},
    "heidegger-nietzsche-1-and-2": {
        "author": "Martin Heidegger", "title": "Nietzsche, Volumes I & II", "year": 1991},
    "being-and-truth": {
        "author": "Martin Heidegger", "title": "Being and Truth", "year": 2010},
    "metaphysics-of-feeling-angst-and-finitude": {
        "author": "Sharin N. Elkholy",
        "title": "Heidegger and a Metaphysics of Feeling: Angst and the Finitude of Being",
        "year": 2008},
    "heidegger-and-the-destruction-of-aristotle": {
        "author": "Sean D. Kirkland",
        "title": "Heidegger and the Destruction of Aristotle: On How to Read", "year": 2023},
    "heidegger-on-poetic-thinking": {
        "author": "Charles Bambach", "title": "Heidegger on Poetic Thinking", "year": 2024},
    "cambridge-companion-to-heidegger": {
        "author": "various (ed. Charles Guignon)",
        "title": "The Cambridge Companion to Heidegger", "year": 2006},
    "heidegger-dictionary": {
        "author": "Michael Inwood", "title": "The Heidegger Dictionary", "year": 2021},
}


def _guess_title(slug: str) -> str:
    return slug.replace("-", " ").title()


def build_catalog() -> dict:
    """Scan converted/ and produce {book_id: {author, title, year, collection}}."""
    catalog = {}
    for md in sorted(config.CONVERTED_DIR.rglob("*.md")):
        slug = md.stem
        collection = md.parent.name
        meta = dict(KNOWN.get(slug, {"author": "", "title": _guess_title(slug), "year": None}))
        meta["collection"] = collection
        catalog[slug] = meta
    return catalog


def save_catalog(catalog: dict) -> None:
    config.CATALOG_PATH.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n")


def load_catalog() -> dict:
    if config.CATALOG_PATH.exists():
        return json.loads(config.CATALOG_PATH.read_text())
    return build_catalog()
