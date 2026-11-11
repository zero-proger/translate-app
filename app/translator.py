# Публичный API translator'а: create_backend, install_argos_package,
# TranslateWorker + реэкспорт для settings_dialog.
#
# Все движки и утилиты вынесены в translator_common.py и translator_engines.py,
# чтобы этот файл был маленьким (≈250 строк) и не обрезался при копировании.

from __future__ import annotations

import sys
import time
import traceback
from typing import Iterable, List, Optional, Tuple

from PySide6.QtCore import QThread, Signal

# Реэкспорт для остального кода (settings_dialog.py и др.)
from .translator_common import (  # noqa: F401
    TranslatorError,
    clear_cache,
    split_chunks,
    _CACHE,
    _NUMBER_RE,
    _purge_bad_cache,
    _protect_numbers,
    _restore_numbers,
    _has_all_numbers,
)
from .translator_engines import (  # noqa: F401
    DEFAULT_LLM_PROMPT,
    GoogleFreeBackend,
    ArgosBackend,
    LocalGpuBackend,
    ChatLlmBackend,
    get_gpu_info,
    NLLB_LANG_MAP,
)

# ---------------- factory ----------------
def create_backend(kind: str, source: str, target: str, delay_ms: int = 250,
                   local_model: str = "nllb", local_device: str = "auto",
                   local_batch: int = 8,
                   llm_model_path: str = "", llm_prompt: str = "",
                   llm_device: str = "auto", llm_max_new_tokens: int = 1024):
    if kind == "argos":
        return ArgosBackend(source, target)
    if kind == "local":
        return LocalGpuBackend(source, target, model_kind=local_model,
                               device=local_device, batch_size=local_batch)
    if kind == "local_llm":
        return ChatLlmBackend(source, target, model_path=llm_model_path,
                              prompt=llm_prompt, device=llm_device,
                              max_new_tokens=llm_max_new_tokens)
    return GoogleFreeBackend(source, target, delay_ms=delay_ms)

def install_argos_package(source: str, target: str) -> None:
    if source == "auto":
        raise TranslatorError("Выберите исходный язык (не «Авто»).")
    try:
        import argostranslate.package as argos_package
    except ImportError as exc:
        raise TranslatorError(
            "Не установлен argostranslate.\npip install argostranslate"
        ) from exc
    argos_package.update_package_index()
    available = argos_package.get_available_packages()
    match = next(
        (p for p in available if p.from_code == source and p.to_code == target),
        None,
    )
    if match is None:
        raise TranslatorError(f"Модель {source}→{target} не найдена в Argos.")
    argos_package.install_from_path(match.download())

# ---------------- worker ----------------
Unit = Tuple[str, object, Optional[object]]

def _should_retranslate(original: str, translated: str) -> bool:
    if not translated or not translated.strip():
        return True
    o = original.rstrip()
    t = translated.rstrip()
    if not o:
        return False
    if len(t) < len(o) * 0.4:
        return True
    orig_nums = set(_NUMBER_RE.findall(o))
    if orig_nums:
        if not all(n in t for n in orig_nums):
            return True
    if o and t and o[-1] in ".!?…" and t[-1] not in ".!?…\"')»":
        return True
    return False

def _iter_units(pages, only_empty: bool = True) -> Iterable[Unit]:
    for page in pages:
        for block in page.blocks:
            if block.use_block_layout:
                if not block.original_text.strip():
                    continue
                if only_empty and block.translated_text.strip():
                    if not _should_retranslate(block.original_text,
                                               block.translated_text):
                        continue
                yield ("block", block, None)
            elif block.lines:
                for line in block.lines:
                    if not line.original.strip():
                        continue
                    if only_empty and line.translated.strip():
                        if not _should_retranslate(line.original, line.translated):
                            continue
                    yield ("line", block, line)
            else:
                if not block.original_text.strip():
                    continue
                if only_empty and block.translated_text.strip():
                    if not _should_retranslate(block.original_text,
                                               block.translated_text):
                        continue
                yield ("block", block, None)

def _get_original(unit: Unit) -> str:
    kind, block, line = unit
    if kind == "line" and line is not None:
        return line.original  # type: ignore[attr-defined]
    return block.original_text  # type: ignore[attr-defined]

def _set_translated(unit: Unit, text: str) -> None:
    kind, block, line = unit
    if kind == "line" and line is not None:
        line.translated = text  # type: ignore[attr-defined]
    else:
        block.translated_text = text  # type: ignore[attr-defined]

def _cache_get(key: str, original: str) -> Optional[str]:
    value = _CACHE.get(key)
    if not value or not value.strip():
        return None
    if _should_retranslate(original, value):
        return None
    return value

class TranslateWorker(QThread):
    progress = Signal(int, int, int, int)  # done, total, words, elapsed_ms
    finished_ok = Signal(int)
    cancelled = Signal(int)
    failed = Signal(str)

    def __init__(self, pages, backend, only_empty: bool = True,
                 use_batch: bool = False, parent=None):
        super().__init__(parent)
        self.pages = pages
        self.backend = backend
        self.only_empty = only_empty
        self.use_batch = use_batch
        self._abort = False
        self.total_words_done = 0
        self.elapsed_ms = 0
        self._start_time = 0.0

    def cancel(self) -> None:
        self._abort = True

    @staticmethod
    def _count_words(text: str) -> int:
        if not text:
            return 0
        return sum(1 for w in text.split() if w)

    def _snapshot(self) -> int:
        if self._start_time <= 0:
            self.elapsed_ms = 0
            return 0
        self.elapsed_ms = int((time.monotonic() - self._start_time) * 1000)
        return self.elapsed_ms

    def run(self) -> None:  # noqa: D401
        try:
            self._start_time = time.monotonic()
            purged = _purge_bad_cache()
            if purged:
                print(f"[worker] purged {purged} bad cache entries",
                      file=sys.stderr)

            target = getattr(self.backend, "target", "ru")
            jobs: List[Unit] = []
            done = 0
            for unit in _iter_units(self.pages, only_empty=self.only_empty):
                original = _get_original(unit)
                key = f"{target}|{original}"
                cached = _cache_get(key, original)
                if cached is not None:
                    _set_translated(unit, cached)
                    done += 1
                    self.total_words_done += self._count_words(cached)
                else:
                    jobs.append(unit)

            total = done + len(jobs)
            self.progress.emit(done, total, self.total_words_done,
                               self._snapshot())
            print(f"[worker] jobs={len(jobs)} total={total}", file=sys.stderr)

            use_batch = self.use_batch and hasattr(self.backend, "translate_many")
            if use_batch and jobs:
                batch_size = 20
                for i in range(0, len(jobs), batch_size):
                    if self._abort:
                        break
                    chunk = jobs[i:i + batch_size]
                    texts = [_get_original(u) for u in chunk]
                    try:
                        outs = self.backend.translate_many(texts)
                    except Exception as exc:
                        print(f"[worker] batch failed: {exc or repr(exc)}",
                              file=sys.stderr)
                        outs = []
                        for t in texts:
                            try:
                                outs.append(self.backend.translate(t))
                            except Exception as exc2:
                                print(f"[worker] single failed: "
                                      f"{exc2 or repr(exc2)}", file=sys.stderr)
                                outs.append("")
                    for unit, out in zip(chunk, outs):
                        if out and out.strip():
                            _set_translated(unit, out)
                            _CACHE[f"{target}|{_get_original(unit)}"] = out
                            self.total_words_done += self._count_words(out)
                        done += 1
                    self.progress.emit(done, total, self.total_words_done,
                                       self._snapshot())
            else:
                for unit in jobs:
                    if self._abort:
                        break
                    original = _get_original(unit)
                    try:
                        out = self.backend.translate(original) or ""
                    except Exception as exc:
                        print(f"[worker] translate failed: "
                              f"{exc or repr(exc)}", file=sys.stderr)
                        traceback.print_exc()
                        out = ""
                    if out and out.strip():
                        _set_translated(unit, out)
                        _CACHE[f"{target}|{original}"] = out
                        self.total_words_done += self._count_words(out)
                    done += 1
                    self.progress.emit(done, total, self.total_words_done,
                                       self._snapshot())

            self._snapshot()
            if self._abort:
                self.cancelled.emit(done)
            else:
                self.finished_ok.emit(done)
        except Exception as exc:
            traceback.print_exc()
            msg = str(exc) or repr(exc) or type(exc).__name__
            if not msg.strip():
                msg = f"{type(exc).__name__} (без сообщения)"
            self.failed.emit(msg)

# ---- END OF FILE app/translator.py ----
