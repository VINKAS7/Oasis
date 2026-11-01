"""BM25F: relevance by words, for the directory and the shops' own search.

Each document (an item, or a business) has fields with weights: a word in a product's name says
more than the same word in its description. Rare words count more than common ones (inverse
document frequency over every live item or business, so a single shop's handful of items doesn't
skew it). Words go through matching.tokens(): "T-shirts" and "tees" are the same word.

select_items() then decides where a list stops, which BM25 alone can't do: colour and size words
filter, items that say every word come first, and meaning (embeddings) is only a fallback."""

import difflib
import math
from collections import Counter
from typing import Any, Iterable

from . import matching

K1, B = 1.2, 0.75

ITEM_FIELDS = {"name": 3.0, "section": 2.5, "options": 2.0, "attributes": 1.5, "description": 1.0}
ITEM_STRONG = ("name", "section", "options", "attributes")
BUSINESS_FIELDS = {"name": 3.0, "kind": 2.5, "items": 2.0, "description": 1.5, "web": 1.0}
BUSINESS_STRONG = ("name", "kind", "items", "description")

# When nothing says every word, meaning leads: items close in meaning to the query (cosine at least
# MEANING_MIN and near the best item), or with a fused score (words weigh less here) at least
# FALLBACK_MIN and near the best. A stray word in a description ("sweet potato" for "something
# sweet") is then not enough on its own.
MEANING_MIN, MEANING_MARGIN = 0.38, 0.06
FALLBACK_MIN, FALLBACK_MARGIN = 0.45, 0.15
W_WORDS_FALLBACK = 0.35


def _flat(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for v in value.values():
            yield from _flat(v)
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            yield from _flat(v)
    elif value not in (None, ""):
        yield str(value)


def toks(value: Any) -> list[str]:
    return matching.tokens(" ".join(_flat(value)))


def item_fields(item: dict[str, Any]) -> dict[str, list[str]]:
    return {
        "name": toks(item.get("name", "")),
        "section": toks(item.get("section") or item.get("category") or ""),
        "options": toks(item.get("options") or {}),
        "attributes": toks(item.get("attributes") or {}),
        "description": toks(item.get("description", "")),
    }


class Index:
    """Collection statistics for one kind of document: how many contain each word, and how long
    each field usually is."""

    def __init__(self, docs: list[dict[str, list[str]]], weights: dict[str, float], strong: tuple[str, ...]):
        self.weights, self.strong = weights, strong
        self.n = max(1, len(docs))
        self.df: Counter[str] = Counter()
        totals: Counter[str] = Counter()
        for d in docs:
            self.df.update({t for f in weights for t in d.get(f, [])})
            for f in weights:
                totals[f] += len(d.get(f, []))
        self.avg = {f: max(1.0, totals[f] / self.n) for f in weights}
        self.vocab = set(self.df)
        self._expansions: dict[str, list[tuple[str, float]]] = {}

    def idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def expand(self, term: str) -> list[tuple[str, float]]:
        """The vocabulary words a query word stands for: itself, else its completions ("marg" ->
        "margherita"), else its closest spelling ("basilco" -> "basilico"), with a lower weight."""
        if term in self._expansions:
            return self._expansions[term]
        if term in self.vocab:
            out = [(term, 1.0)]
        else:
            out = []
            if len(term) >= 4:
                out = [(v, 0.7) for v in sorted(self.vocab) if v.startswith(term)][:5]
            if not out and len(term) >= 5:
                out = [(v, 0.6) for v in difflib.get_close_matches(term, self.vocab, n=2, cutoff=0.8)]
        self._expansions[term] = out
        return out

    def score(self, doc: dict[str, list[str]], terms: list[str]) -> float:
        counts = {f: Counter(doc.get(f, [])) for f in self.weights}
        lengths = {f: len(doc.get(f, [])) for f in self.weights}
        total = 0.0
        for term in terms:
            for word, factor in self.expand(term):
                tf = sum(w * counts[f][word] / (1 - B + B * lengths[f] / self.avg[f]) for f, w in self.weights.items() if counts[f][word])
                if tf:
                    total += factor * self.idf(word) * tf * (K1 + 1) / (tf + K1)
        return total

    def says(self, doc: dict[str, list[str]], term: str, fields: tuple[str, ...] | None = None) -> bool:
        """Whether a strong field (or the given ones) contains the word or what it stands for."""
        words = {w for w, _ in self.expand(term)} or {term}
        return any(words & set(doc.get(f, [])) for f in (fields or self.strong))


# ---- colours, sizes and other options --------------------------------------------------------

def option_vocab(items: Iterable[dict[str, Any]]) -> dict[str, set[str]]:
    """Single-word option values across the catalogue ("black" -> {"colour"}, "xl" -> {"size"})."""
    vocab: dict[str, set[str]] = {}
    for i in items:
        for axis, values in (i.get("options") or {}).items():
            for v in values or []:
                t = matching.tokens(v)
                if len(t) == 1:
                    vocab.setdefault(t[0], set()).add(axis)
    return vocab


def option_hints(item: dict[str, Any], terms: list[str]) -> dict[str, str]:
    """The item's own option values the query names: "black tee" -> {"colour": "Black"}."""
    out: dict[str, str] = {}
    wanted = set(terms)
    for axis, values in (item.get("options") or {}).items():
        for v in values or []:
            t = matching.tokens(v)
            if t and set(t) <= wanted:
                out[axis] = v
                break
    return out


def _lacks_option(item: dict[str, Any], fields: dict[str, list[str]], term: str, axes: set[str]) -> bool:
    """True when the item comes in that kind of option but not in this value, and doesn't
    otherwise say the word ("navy" for a tee only made in white and black)."""
    opts = item.get("options") or {}
    mine = [a for a in axes if a in opts]
    if not mine:
        return False  # no colours at all (a pizza): colour words don't filter it
    if any(term in matching.tokens(v) for a in mine for v in opts[a]):
        return False
    return not any(term in fields[f] for f in ("name", "section", "attributes"))


def select_items(items: list[dict[str, Any]], terms: list[str], index: Index, vocab: dict[str, set[str]],
                 sims: dict[str, float] | None = None, sem=None, key=None, context_terms: set[str] | None = None,
                 ) -> tuple[list[dict[str, Any]], bool]:
    """The items to show for a query, best first, and whether they match it exactly.

    1. Colour/size words filter: an item made in other colours is dropped.
    2. If some items say every remaining word in a strong field, only those.
    3. Otherwise items close in meaning (or, without embeddings, by words), with matched=False.
    Each returned item is a copy with `preselect` when the query names one of its options.
    context_terms: words already explained by the business itself (its name or kind)."""
    if not terms or not items:
        return items, True
    words = [t for t in terms if t not in (context_terms or set())] or terms
    fields = [item_fields(i) for i in items]
    opt = [t for t in words if t in vocab]
    keep = [n for n in range(len(items)) if not any(_lacks_option(items[n], fields[n], t, vocab[t]) for t in opt)]
    pool = keep or list(range(len(items)))
    bm = {n: index.score(fields[n], words) for n in pool}
    best = max(bm.values(), default=0.0) or 1.0
    sim = {n: (sims.get(key(items[n])) if sims and key else None) for n in pool}

    def fused(n: int) -> float:
        b = bm[n] / best
        return 0.5 * b + 0.5 * sem(sim[n]) if sims and sem else b

    exact = [n for n in keep if all(index.says(fields[n], t) for t in words)]
    if exact:
        chosen, matched = sorted(exact, key=lambda n: (-fused(n), n)), True
    else:
        if sims and sem:
            scores = {n: W_WORDS_FALLBACK * bm[n] / best + (1 - W_WORDS_FALLBACK) * sem(sim[n]) for n in pool}
            top_sim = max((x for x in sim.values() if x is not None), default=0.0)
            near = {n for n in pool if sim[n] is not None and sim[n] >= MEANING_MIN and sim[n] >= top_sim - MEANING_MARGIN}
            floor = FALLBACK_MIN
        else:
            scores, near, floor = {n: bm[n] / best for n in pool}, set(), 0.5
        top = max(scores.values(), default=0.0)
        chosen = sorted((n for n in pool if n in near or (scores[n] >= floor and scores[n] >= top - FALLBACK_MARGIN)),
                        key=lambda n: (-(sim[n] or 0) if near else -scores[n], n))
        matched = False
        if not chosen:
            return items, False
    out = []
    for n in chosen:
        hint = option_hints(items[n], terms)
        out.append({**items[n], "preselect": hint} if hint else items[n])
    return out, matched
