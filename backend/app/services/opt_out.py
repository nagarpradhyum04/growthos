"""Deterministic opt-out detection — runs on every reply BEFORE (and independent of) the LLM.

Deliberately conservative: a false positive costs one lead; a false negative means emailing someone
who asked us to stop. The Reply Analysis Agent provides a second, smarter layer on top.
"""
import re
from enum import StrEnum


class OptOutType(StrEnum):
    FORGET = "forget"
    UNSUBSCRIBE = "unsubscribe"


_FORGET_RE = re.compile(
    r"forget me|right to (be forgotten|erasure)|(delete|erase|remove|purge) (all )?(of )?my (personal )?"
    r"(data|information|info|details|record)|gdpr (request|erasure|deletion)",
    re.I,
)
_UNSUBSCRIBE_RE = re.compile(
    r"unsubscribe|remove me|take me off|opt(-| )?out|stop (emailing|contacting|sending|messaging|writing)|"
    r"(do not|don'?t|never) (contact|email|e-mail|message|write to) me|no more emails|leave me alone",
    re.I,
)


def detect_opt_out(text: str) -> OptOutType | None:
    if _FORGET_RE.search(text):
        return OptOutType.FORGET
    if _UNSUBSCRIBE_RE.search(text):
        return OptOutType.UNSUBSCRIBE
    return None
