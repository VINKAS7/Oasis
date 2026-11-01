"""Words as people type them ("the nearest pizzas", "tshirt", "Trattoria Basilco"), in one form
for every search (BM25 in bm25.py, the directory, show_items and the shops' own search):

- words are folded (case, accents: "Zürich" = "zurich") and joined ("t-shirt" = "tshirt");
- plurals are trimmed ("pizzas" = "pizza", "dishes" = "dish");
- a few everyday synonyms share one form ("tee" = "tshirt", "barber" = "haircut");
- filler and "where" words are dropped ("the nearest ... near me").
Prefixes and typos ("marg", "basilco") are resolved against the vocabulary in bm25.Index.expand."""

import difflib
import re
import unicodedata
from typing import Any

STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "for", "to", "in", "on", "at", "by", "with", "about", "is", "are", "be", "what", "whats",
    "which", "who", "where", "how", "me", "my", "i", "im", "you", "your", "it", "its", "this", "that", "any", "some", "find", "show",
    "tell", "list", "give", "see", "please", "can", "could", "would", "should", "want", "need", "looking", "look", "get", "buy", "order",
    "near", "nearest", "nearby", "closest", "close", "around", "here", "there", "local", "best", "good", "great", "cheap", "place",
    "places", "spot", "store", "stores", "shop", "shops", "something", "anything", "from", "sell", "sells", "selling", "offer",
    "offers", "have", "has", "do", "does", "go", "one", "ones", "all", "some", "nice", "now", "today",
}

# Words people use interchangeably, in their trimmed form; each group matches as its first word.
_SAME = [
    ("tshirt", "tee"),
    ("haircut", "hair", "hairdresser", "barber", "hairstylist", "hairstyle", "salon"),
    ("pizza", "pizzeria"),
    ("cafe", "coffee", "espresso", "cappuccino"),
    ("bike", "bicycle", "cycling", "cycle", "velo"),
    ("clothing", "clothe", "apparel", "fashion", "garment"),
    ("sweater", "jumper", "pullover", "knitwear"),
    ("trouser", "pant", "chino"),
    ("fitness", "gym", "workout", "training", "trainer", "coach", "coaching"),
    ("nail", "manicure", "pedicure"),
    ("restaurant", "food", "eat", "dinner", "lunch", "meal", "dining"),
    ("hotel", "accommodation", "lodging"),
]
_CANON = {w: group[0] for group in _SAME for w in group}
_WORD = re.compile(r"\w+(?:[-'’]\w+)*")


def fold(text: str) -> str:
    """Lower case without accents."""
    text = unicodedata.normalize("NFKD", str(text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("ches", "shes", "sses", "xes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def tokens(text: str) -> list[str]:
    """Every word of a text in its matching form (stopwords kept: they are harmless in a corpus)."""
    out = []
    for raw in _WORD.findall(fold(text)):
        w = re.sub(r"['’]s$", "", raw)
        w = re.sub(r"[-'’]", "", w)
        if w:
            w = stem(w)
            out.append(_CANON.get(w, w))
    return out


def terms(query: str) -> list[str]:
    """The words of a query worth matching, in order, without repeats."""
    out: list[str] = []
    for raw in _WORD.findall(fold(query)):
        if re.sub(r"['’]s$", "", raw) in STOPWORDS:
            continue
        for t in tokens(raw):
            if len(t) > 1 and t not in STOPWORDS and t not in out:
                out.append(t)
    return out


def filter_items(items: list[dict[str, Any]], query: str) -> tuple[list[dict[str, Any]], str]:
    """The items matching a query, best first, by BM25 and the shared rules (bm25.select_items):
    "all" when they say every word, "some" for the closest ones, "none" (every item) otherwise."""
    words = terms(query)
    if not words:
        return items, "all"
    from . import bm25, search_index

    lex = search_index.lexical()
    shown, matched = bm25.select_items(items, words, lex.items, lex.options)
    if matched:
        return shown, "all"
    return (items, "none") if shown is items else (shown, "some")


def name_similarity(query: str, name: str) -> float:
    """0..1: how much a query looks like a business name ("rhein thread" ~ "Rhein Threads")."""
    a, b = " ".join(tokens(query)), " ".join(tokens(name))
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    q = set(a.split())
    overlap = len(q & set(b.split())) / len(q)
    return max(ratio, overlap * 0.95 if len(q) > 1 or len(a) > 3 else 0.0)
