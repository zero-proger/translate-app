# Общие константы и утилиты translator'а: числа, кэш, rate-limit, split_chunks.
# Импортируется и переводческими движками, и воркером — так translator.py
# остаётся маленьким и не обрезается при копировании.

from __future__ import annotations

import re
import threading
import time
from typing import Dict, List, Tuple

class TranslatorError(Exception):
    pass

_CACHE: Dict[str, str] = {}
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…;])\s+")

_NUMERIC_ONLY = re.compile(
    r"^[\d\s.,:;\-–—/()\[\]{}«»\"'`+=*№$€£¥%°]+$"
)
_NUMBER_RE = re.compile(r"\d+(?:[.,:/\-–—]\d+)*")
_MARKER_RE = re.compile(r"<\s*[Nn]\s*(\d+)\s*>")

def _protect_numbers(text: str) -> Tuple[str, List[str]]:
    numbers: List[str] = []

    def _sub(m: re.Match) -> str:
        numbers.append(m.group(0))
        return f"<N{len(numbers) - 1}>"

    return _NUMBER_RE.sub(_sub, text), numbers

def _restore_numbers(masked: str, numbers: List[str]) -> Tuple[str, int]:
    if not numbers:
        return masked, 0
    used = set()

    def _sub(m: re.Match) -> str:
        try:
            i = int(m.group(1))
            if 0 <= i < len(numbers):
                used.add(i)
                return numbers[i]
        except ValueError:
            pass
        return m.group(0)

    restored = _MARKER_RE.sub(_sub, masked or "")
    return restored, len(numbers) - len(used)

def _has_all_numbers(original: str, translated: str) -> bool:
    orig_nums = set(_NUMBER_RE.findall(original or ""))
    if not orig_nums:
        return True
    trans = translated or ""
    return all(n in trans for n in orig_nums)

def clear_cache() -> None:
    _CACHE.clear()

def _purge_bad_cache() -> int:
    bad = [k for k, v in _CACHE.items() if not v or not v.strip()]
    for k in bad:
        del _CACHE[k]
    return len(bad)

class _RateLimiter:
    def __init__(self, interval_sec: float):
        self.interval = interval_sec
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delta = now - self._last
            if delta < self.interval:
                time.sleep(self.interval - delta)
            self._last = time.monotonic()

_GOOGLE_LIMITER = _RateLimiter(1.0 / 4.0)

def _is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(t in msg for t in ("too many requests", "429",
                                   "rate limit", "quota"))

def split_chunks(text: str, limit: int = 4500) -> List[str]:
    if len(text) <= limit:
        return [text]
    parts: List[str] = []
    current = ""
    for sentence in _SENTENCE_SPLIT.split(text):
        if not sentence:
            continue
        if len(current) + len(sentence) + 1 <= limit:
            current = (current + " " + sentence).strip()
        else:
            if current:
                parts.append(current)
            if len(sentence) > limit:
                for i in range(0, len(sentence), limit):
                    parts.append(sentence[i:i + limit])
                current = ""
            else:
                current = sentence
    if current:
        parts.append(current)
    return parts

# ---- END OF FILE app/translator_common.py ----
