"""Words as people type them ("the nearest pizzas", "tshirt", "Trattoria Basilco"), in one form
for every search (BM25 in bm25.py, the directory, show_items and the shops' own search):

- words are folded (case, accents, ß: "Zürich" = "zurich", "Straße" = "strasse") and joined ("t-shirt" = "tshirt");
- plurals are trimmed ("pizzas" = "pizza", "dishes" = "dish");
- everyday synonyms share one form, across English, German, French and Italian ("tee" = "tshirt",
  "Haarschnitt" = "coupe" = "taglio" = "haircut", "Hemd" = "chemise" = "camicia" = "shirt");
- filler and "where" words are dropped in all four languages ("the nearest ... near me",
  "in der Nähe", "près d'ici", "qui vicino").
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
    "offers", "have", "has", "do", "does", "go", "one", "ones", "all", "some", "nice", "now", "today", "size", "eat",
    # German
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem", "einer", "und", "oder", "im", "am", "auf", "mit",
    "fur", "von", "zu", "zum", "zur", "bei", "nahe", "nah", "umgebung", "wo", "wie", "was", "welche", "welcher", "welches", "gibt",
    "es", "ich", "mich", "mir", "mein", "meine", "suche", "suchen", "finde", "finden", "zeig", "zeige", "zeigen", "bitte", "kann",
    "konnen", "mochte", "moechte", "will", "brauche", "habe", "haben", "hat", "heute", "jetzt", "hier", "nachste", "nachsten",
    "nachstgelegene", "laden", "geschaft", "essen", "kaufen", "bestellen", "grosse", "groesse", "lassen", "kann", "man", "ist",
    # French
    "le", "la", "les", "un", "une", "du", "de", "au", "aux", "et", "ou", "en", "dans", "sur", "avec", "pour", "chez", "pres",
    "proche", "ici", "quel", "quelle", "quels", "quelles", "est", "sont", "je", "moi", "mon", "ma", "mes", "cherche", "chercher",
    "trouve", "trouver", "montre", "montrer", "voudrais", "veux", "besoin", "puis", "peux", "manger", "acheter", "commander",
    "maintenant", "aujourd", "hui", "plus", "magasin", "boutique", "taille", "faire", "couper", "il", "ya", "ce",
    # Italian
    "il", "lo", "gli", "uno", "una", "di", "da", "del", "della", "dei", "delle", "nel", "nella", "con", "per", "su", "vicino",
    "qui", "dove", "come", "cosa", "quale", "quali", "sono", "io", "mi", "mio", "mia", "cerco", "cercare", "trova", "trovare",
    "mostra", "mostrami", "voglio", "vorrei", "posso", "mangiare", "comprare", "ordinare", "ora", "oggi", "negozio", "taglia",
    "fare", "un", "che",
}

# Words people use interchangeably, in their trimmed form; each group matches as its first word.
_SAME = [
    ("tshirt", "tee", "teeshirt", "maglietta", "magliette"),
    ("haircut", "hair", "hairdresser", "barber", "barbershop", "hairstylist", "hairstyle", "salon", "haarschnitt", "haar", "haare",
     "friseur", "frisor", "coiffeur", "coiffeuse", "coiffure", "coupe", "cheveux", "capelli", "taglio", "parrucchiere", "barbiere"),
    ("pizza", "pizzeria", "pizze", "pizzen"),
    ("cafe", "coffee", "espresso", "cappuccino", "kaffee", "kaffi", "caffe", "caffetteria"),
    ("gelato", "gelati", "gelateria", "glace", "glacier", "eis", "icecream"),
    ("bike", "bicycle", "cycling", "cycle", "velo", "fahrrad", "fahrrader", "fahrraeder", "rad", "bici", "bicicletta"),
    ("rental", "rent", "hire", "mieten", "miete", "vermietung", "verleih", "louer", "noleggio", "affitto"),
    ("clothing", "clothe", "apparel", "fashion", "garment", "kleidung", "kleider", "mode", "vetement", "abbigliamento", "vestiti", "moda"),
    ("shirt", "hemd", "hemden", "chemise", "camicia", "camicie", "bluse", "blouse"),
    ("hoodie", "hoody", "kapuzenpullover", "kapuzenpulli", "felpa", "cappuccio", "capuche"),
    ("sweater", "jumper", "pullover", "knitwear", "pull", "pulli", "maglione", "strickpullover"),
    ("trouser", "pant", "chino", "hose", "hosen", "pantalon", "pantaloni"),
    ("wool", "wolle", "laine", "lana"),
    ("beanie", "bonnet", "mutze", "muetze", "strickmutze", "berretto", "cuffia", "toque"),
    ("cap", "kappe", "basecap", "casquette", "cappellino"),
    ("jacket", "jacke", "veste", "blouson", "giacca", "giubbotto"),
    ("vest", "weste", "gilet", "smanicato"),
    ("sock", "socke", "socken", "chaussette", "calzino", "calzini", "calza", "calze"),
    ("scarf", "schal", "echarpe", "sciarpa"),
    ("glove", "handschuh", "handschuhe", "gant", "guanto", "guanti"),
    ("shoe", "schuh", "schuhe", "chaussure", "scarpa", "scarpe"),
    ("dress", "kleid", "robe", "vestito"),
    ("bag", "tasche", "sac", "borsa"),
    ("ribbed", "gerippt", "cotele", "coste"),
    ("vegan", "vegane", "veganes", "veganer", "vegano", "vegana", "vegetalien"),
    ("vegetarian", "vegetarisch", "vegetarische", "vegetarien", "vegetariano", "vegetariana", "veggie"),
    ("bowl", "schussel", "schale", "bol", "ciotola"),
    ("linen", "leinen", "lin", "lino"),
    ("black", "schwarz", "schwarze", "schwarzen", "schwarzer", "noir", "noire", "nero", "nera"),
    ("white", "weiss", "weisse", "weissen", "weisser", "blanc", "blanche", "bianco", "bianca"),
    ("red", "rot", "rote", "roten", "roter", "rouge", "rosso", "rossa"),
    ("grey", "gray", "grau", "graue", "grauen", "gris", "grise", "grigio", "grigia"),
    ("blue", "blau", "blaue", "blauen", "bleu", "bleue", "blu"),
    ("green", "grun", "grune", "grunen", "vert", "verte", "verde"),
    ("bakery", "backerei", "baeckerei", "boulangerie", "panetteria", "forno"),
    ("bread", "brot", "pain", "pane"),
    ("cake", "kuchen", "gateau", "torta", "torte"),
    ("fitness", "gym", "workout", "training", "trainer", "coach", "coaching", "allenamento", "entrainement"),
    ("nail", "manicure", "pedicure", "nagel", "ongle", "unghie"),
    ("restaurant", "food", "dinner", "lunch", "meal", "dining", "ristorante", "mittagessen", "abendessen", "dejeuner", "diner",
     "pranzo", "cena"),
    ("hotel", "accommodation", "lodging", "albergo", "unterkunft", "hebergement"),
]
_CANON = {w: group[0] for group in _SAME for w in group}
_WORD = re.compile(r"\w+(?:[-'’]\w+)*")


_LIGATURES = str.maketrans({"ß": "ss", "æ": "ae", "œ": "oe", "ø": "o", "ð": "d", "þ": "th", "ł": "l"})


def fold(text: str) -> str:
    """Lower case without accents; ß, æ, œ written out ("Straße" = "strasse")."""
    text = unicodedata.normalize("NFKD", str(text or "").lower().translate(_LIGATURES))
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
