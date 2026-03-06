"""Simple language detection for Italian vs English text.

Uses character-frequency heuristics on common short words to avoid
heavy NLP dependencies. Returns 'it' or 'en'.
"""

# High-frequency Italian function words
_IT_WORDS = frozenset({
    "il", "lo", "la", "le", "li", "gli", "un", "una", "uno",
    "di", "del", "della", "dei", "delle", "dello", "degli",
    "da", "dal", "dalla", "dai", "dalle", "dallo",
    "in", "nel", "nella", "nei", "nelle", "nello",
    "con", "su", "per", "tra", "fra",
    "che", "non", "è", "sono", "ha", "hanno",
    "questo", "questa", "quello", "quella",
    "anche", "più", "così", "dove", "come", "quando",
    "essere", "avere", "fare", "dire", "andare",
    "al", "alla", "ai", "alle", "allo",
})

# High-frequency English function words
_EN_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were",
    "of", "in", "to", "for", "with", "on", "at", "by",
    "and", "or", "but", "not", "this", "that", "it",
    "from", "as", "be", "have", "has", "had", "do",
    "will", "would", "can", "could", "should",
    "which", "who", "what", "where", "when", "how",
    "all", "each", "every", "both", "more", "some",
    "than", "been", "being", "does", "did",
})


def detect_language(text: str) -> str:
    """Detect whether *text* is Italian or English.

    Returns ``'it'`` or ``'en'``.  Falls back to ``'en'`` when
    the signal is too weak.
    """
    words = text.lower().split()
    if not words:
        return "en"

    # Sample first 500 words for speed on large documents
    sample = words[:500]

    it_hits = sum(1 for w in sample if w in _IT_WORDS)
    en_hits = sum(1 for w in sample if w in _EN_WORDS)

    if it_hits > en_hits:
        return "it"
    return "en"
