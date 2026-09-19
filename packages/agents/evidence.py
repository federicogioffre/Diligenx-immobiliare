"""Validate source coordinates and amounts against extracted evidence, not model claims."""
from __future__ import annotations

import math
import re


def _text(value: str) -> str:
    return " ".join(value.split()).casefold()


def verified_clause_page(content: str, chunks, page_count: int | None) -> int | None:
    """Cite only a unique extracted page containing the complete quotation."""
    quote = _text(content).removesuffix("…").strip()
    if not quote:
        return None
    matches = {
        chunk.page_number for chunk in chunks
        if type(chunk.page_number) is int and chunk.page_number > 0
        and (page_count is None or chunk.page_number <= page_count)
        and quote in _text(chunk.content)
    }
    return next(iter(matches)) if len(matches) == 1 else None


def grounded_amount(item: dict, text: str) -> tuple[float | None, str, str | None]:
    """Require a verbatim evidence quote containing the reported finite amount.

    Ambiguous units or formats remain unverified rather than being guessed.
    A missing amount is distinct from an amount returned without evidence.
    """
    raw = item.get("amount_eur")
    if raw is None:
        return None, "not_stated", None
    evidence = item.get("amount_evidence")
    try:
        amount = float(raw)
    except (ValueError, TypeError, OverflowError):
        return None, "unverified", None
    if (isinstance(raw, bool) or not math.isfinite(amount) or amount < 0
            or not isinstance(evidence, str) or not _text(evidence)
            or _text(evidence) not in _text(text)):
        return None, "unverified", None
    if (not re.search(r"\b(?:eur|euro)\b|€", evidence, re.I)
            or re.search(r"\b(?:million|millions|milione|milioni|thousand|mila|billion|miliardi)\b", evidence, re.I)):
        return None, "unverified", None
    for token in re.findall(r"(?<!\w)(?:\d{1,3}(?:[\u00a0 ]\d{3})+|\d+)(?:[.,]\d+)*(?!\w)", evidence):
        compact = token.replace(" ", "").replace("\u00a0", "")
        # Accept common Italian/English grouping and decimal conventions.
        forms = {compact}
        if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?", compact):
            if re.search(r"[.,]\d{1,2}$", compact):
                whole, fraction = re.split(r"[.,](?=\d{1,2}$)", compact)
                forms.add(re.sub(r"[.,]", "", whole) + "." + fraction)
            else:
                forms.add(re.sub(r"[.,]", "", compact))
        if re.fullmatch(r"\d+[,]\d{1,2}", compact):
            forms.add(compact.replace(",", "."))
        for value in forms:
            try:
                if float(value) == amount:
                    return amount, "document", evidence
            except ValueError:
                pass
    return None, "unverified", None
