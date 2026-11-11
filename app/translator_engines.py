# Движки перевода: Google, Argos, NLLB/Opus, Chat-LLM.
# Числа защищены от порчи маркерами <N0> + fallback на сегментный перевод.

from __future__ import annotations

import os
import sys
import time
from typing import Dict, List, Optional, Tuple

from .translator_common import (
    TranslatorError,
    _CACHE, _GOOGLE_LIMITER, _MARKER_RE, _NUMBER_RE, _NUMERIC_ONLY,
    _has_all_numbers, _is_rate_limit_error, _protect_numbers,
    _restore_numbers, split_chunks,
)

# ---------------- Google ----------------
class GoogleFreeBackend:
    name = "Google Translate"

    def __init__(self, source: str = "auto", target: str = "ru", delay_ms: int = 250):
        try:
            from deep_translator import GoogleTranslator
        except ImportError as exc:
            raise TranslatorError(
                "Не установлен deep-translator.\npip install deep-translator"
            ) from exc
        self._cls = GoogleTranslator
        self.source = source or "auto"
        self.target = target or "ru"
        self.delay_ms = max(0, int(delay_ms))
        try:
            self._translator = GoogleTranslator(source=self.source, target=self.target)
        except Exception as exc:
            raise TranslatorError(f"Не удалось создать переводчик:\n{exc}") from exc

    def translate(self, text: str) -> str:
        if not text.strip():
            return text
        parts = [self._translate_chunk(c) for c in split_chunks(text)]
        if self.delay_ms > 0:
            time.sleep(self.delay_ms / 1000.0)
        return " ".join(parts).strip()

    def _translate_chunk(self, chunk: str) -> str:
        last_error: Optional[Exception] = None
        for attempt in range(6):
            _GOOGLE_LIMITER.wait()
            try:
                result = self._translator.translate(chunk)
                if result and result.strip():
                    return result
                last_error = RuntimeError("пустой ответ")
            except Exception as exc:
                last_error = exc
                if _is_rate_limit_error(exc):
                    time.sleep(min(30.0, 2.0 * (attempt + 1) ** 2))
                else:
                    time.sleep(1.0 * (attempt + 1))
        raise TranslatorError(f"Google Translate: {last_error}")

# ---------------- Argos ----------------
class ArgosBackend:
    name = "Argos Translate"

    def __init__(self, source: str = "en", target: str = "ru"):
        if source == "auto":
            raise TranslatorError(
                "Argos не поддерживает автоопределение. Выберите исходный язык."
            )
        try:
            import argostranslate.translate as argos_translate
        except ImportError as exc:
            raise TranslatorError(
                "Не установлен argostranslate.\npip install argostranslate"
            ) from exc
        languages = argos_translate.get_installed_languages()
        src_lang = next((l for l in languages if l.code == source), None)
        tgt_lang = next((l for l in languages if l.code == target), None)
        if not src_lang or not tgt_lang:
            raise TranslatorError(
                f"Не установлена офлайн-модель {source}→{target}."
            )
        translation = src_lang.get_translation(tgt_lang)
        if translation is None:
            raise TranslatorError(f"Модель {source}→{target} не загружена.")
        self._translation = translation
        self.source = source
        self.target = target

    def _plain(self, text: str) -> str:
        return self._translation.translate(text)

    def _plain_multi(self, text: str) -> str:
        if not text.strip():
            return text
        parts = [self._plain(c) for c in split_chunks(text, 2000)]
        return " ".join(parts).strip()

    def _segment_translate(self, text: str) -> str:
        segments: List[Tuple[str, str]] = []
        pos = 0
        for m in _NUMBER_RE.finditer(text):
            if m.start() > pos:
                segments.append(("text", text[pos:m.start()]))
            segments.append(("num", m.group(0)))
            pos = m.end()
        if pos < len(text):
            segments.append(("text", text[pos:]))
        out: List[str] = []
        for kind, seg in segments:
            if kind == "num" or not seg.strip():
                out.append(seg)
                continue
            try:
                translated = self._plain_multi(seg)
                out.append(translated if translated else seg)
            except Exception:
                out.append(seg)
        return "".join(out)

    def translate(self, text: str) -> str:
        if not text.strip():
            return text
        t = text.strip()
        if _NUMERIC_ONLY.match(t):
            return text
        if not _NUMBER_RE.search(t):
            return self._plain_multi(t)
        masked, numbers = _protect_numbers(t)
        try:
            masked_result = self._plain_multi(masked)
        except Exception:
            masked_result = ""
        restored, missing = _restore_numbers(masked_result, numbers)
        if missing == 0 and _has_all_numbers(t, restored):
            return restored
        return self._segment_translate(t)

# ---------------- device helpers ----------------
NLLB_LANG_MAP: Dict[str, str] = {
    "en": "eng_Latn", "ru": "rus_Cyrl", "de": "deu_Latn", "fr": "fra_Latn",
    "es": "spa_Latn", "it": "ita_Latn", "pt": "por_Latn", "nl": "nld_Latn",
    "pl": "pol_Latn", "uk": "ukr_Cyrl", "tr": "tur_Latn",
    "zh-CN": "zho_Hans", "ja": "jpn_Jpan", "ko": "kor_Hang",
}

_LOCAL_MODEL_CACHE: Dict[Tuple[str, str], Tuple[object, object]] = {}

def get_gpu_info() -> str:
    try:
        import torch
    except ImportError:
        return "torch не установлен — GPU недоступен, будет CPU."
    try:
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            mem = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            return f"CUDA OK — {name} ({mem:.1f} ГБ)"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "Apple MPS OK"
    except Exception:
        pass
    return "CUDA/MPS не найдены — будет CPU."

def _resolve_device(requested: str) -> str:
    try:
        import torch
    except ImportError:
        return "cpu"
    cuda_ok = torch.cuda.is_available()
    mps_ok = hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
    if requested == "auto":
        if cuda_ok:
            return "cuda"
        if mps_ok:
            return "mps"
        return "cpu"
    if requested == "cuda" and not cuda_ok:
        raise TranslatorError(
            "CUDA недоступна. Установите torch с CUDA:\n"
            "pip install torch --index-url https://download.pytorch.org/whl/cu121"
        )
    if requested == "mps" and not mps_ok:
        raise TranslatorError("MPS (Apple Metal) не доступен.")
    return requested

def _load_local_model(model_name: str, device: str):
    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
    key = (model_name, device)
    cached = _LOCAL_MODEL_CACHE.get(key)
    if cached is not None:
        return cached
    tok = AutoTokenizer.from_pretrained(model_name)
    mdl = AutoModelForSeq2SeqLM.from_pretrained(model_name)
    mdl.to(device)
    mdl.eval()
    if device == "cuda":
        try:
            mdl.half()
        except Exception:
            pass
    _LOCAL_MODEL_CACHE[key] = (tok, mdl)
    return tok, mdl

# ---------------- NLLB / Opus ----------------
class LocalGpuBackend:
    name = "Локальная модель (NLLB/Opus)"

    def __init__(self, source: str, target: str = "ru",
                 model_kind: str = "nllb", device: str = "auto",
                 batch_size: int = 8):
        try:
            import torch  # noqa: F401
            from transformers import AutoTokenizer, AutoModelForSeq2SeqLM  # noqa: F401
        except ImportError as exc:
            raise TranslatorError(
                "Не установлены torch/transformers.\n"
                "pip install torch transformers sentencepiece accelerate"
            ) from exc
        if source == "auto":
            raise TranslatorError(
                "Локальная модель не поддерживает автоопределение. "
                "Выберите исходный язык."
            )
        if source == target:
            raise TranslatorError("Исходный и целевой языки совпадают.")
        self.device = _resolve_device(device)
        self.source = source
        self.target = target
        self.batch_size = max(1, int(batch_size))
        self._kind = model_kind
        if model_kind == "nllb":
            self._model_name = "facebook/nllb-200-distilled-600M"
        elif model_kind == "opus":
            src = "zh" if source == "zh-CN" else source
            tgt = "zh" if target == "zh-CN" else target
            self._model_name = f"Helsinki-NLP/opus-mt-{src}-{tgt}"
        else:
            raise TranslatorError(f"Неизвестная модель: {model_kind}")
        self._tokenizer, self._model = _load_local_model(self._model_name, self.device)
        if self._kind == "nllb":
            src_code = NLLB_LANG_MAP.get(source)
            tgt_code = NLLB_LANG_MAP.get(target)
            if not src_code or not tgt_code:
                raise TranslatorError(f"{source}→{target} не поддерживается NLLB.")
            self._src_token = self._tokenizer.convert_tokens_to_ids(src_code)
            self._tgt_token = self._tokenizer.convert_tokens_to_ids(tgt_code)
        else:
            self._src_token = None
            self._tgt_token = None

    def _translate_batch(self, texts: List[str]) -> List[str]:
        import torch
        kwargs = {"return_tensors": "pt", "padding": True,
                  "truncation": True, "max_length": 512}
        inputs = self._tokenizer(texts, **kwargs)
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        gen = {"max_length": 512, "num_beams": 4, "no_repeat_ngram_size": 3}
        if self._kind == "nllb" and self._tgt_token is not None:
            gen["forced_bos_token_id"] = self._tgt_token
        with torch.no_grad():
            out = self._model.generate(**inputs, **gen)
        return self._tokenizer.batch_decode(out, skip_special_tokens=True)

    def _raw_translate(self, text: str) -> str:
        if not text.strip():
            return text
        return self._translate_batch([text])[0]

    def _segment_translate(self, text: str) -> str:
        segments: List[Tuple[str, str]] = []
        pos = 0
        for m in _NUMBER_RE.finditer(text):
            if m.start() > pos:
                segments.append(("text", text[pos:m.start()]))
            segments.append(("num", m.group(0)))
            pos = m.end()
        if pos < len(text):
            segments.append(("text", text[pos:]))
        out: List[str] = []
        for kind, seg in segments:
            if kind == "num" or not seg.strip():
                out.append(seg)
                continue
            try:
                translated = self._raw_translate(seg)
                out.append(translated if translated else seg)
            except Exception:
                out.append(seg)
        return "".join(out)

    def translate(self, text: str) -> str:
        if not text.strip():
            return text
        t = text.strip()
        if _NUMERIC_ONLY.match(t):
            return text
        if not _NUMBER_RE.search(t):
            return self._raw_translate(t)
        masked, numbers = _protect_numbers(t)
        try:
            masked_result = self._raw_translate(masked)
        except Exception:
            masked_result = ""
        restored, missing = _restore_numbers(masked_result or "", numbers)
        if missing == 0 and _has_all_numbers(t, restored):
            return restored
        return self._segment_translate(t)

    def translate_many(self, texts: List[str]) -> List[str]:
        results: List[str] = []
        for t in texts:
            try:
                results.append(self.translate(t))
            except Exception:
                results.append("")
        return results

# ---------------- Chat-LLM ----------------
DEFAULT_LLM_PROMPT = (
    "Ты — профессиональный переводчик на русский язык. "
    "Переведи текст на русский, сохраняя смысл, стиль и тон оригинала.\n\n"
    "Правила:\n"
    "1. Если прямое значение слова неизвестно, устарело или это сленг — "
    "используй ближайший по смыслу русский аналог (в том числе сленговое "
    "или разговорное выражение, если это уместно). Никогда не оставляй "
    "слово без перевода и не пиши «[непереводимо]».\n"
    "2. Числа, даты, артикулы, версии, названия моделей оставляй БЕЗ ИЗМЕНЕНИЙ. "
    "Маркеры вида <N0>, <N1> (если они есть во входе) сохрани ровно в том же "
    "виде и в том же месте, где они были — на их место потом подставятся числа.\n"
    "3. Не объясняй, не добавляй комментарии — выводи только готовый перевод.\n"
    "4. Сохраняй разбиение на абзацы и знаки препинания.\n"
    "5. Имена собственные переводи только если есть устоявшийся русский "
    "вариант; иначе оставляй как есть.\n"
)

_LLM_CACHE: Dict[Tuple[str, str], Tuple[object, object]] = {}

def _load_llm(model_path: str, device: str):
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM
    key = (model_path, device)
    cached = _LLM_CACHE.get(key)
    if cached is not None:
        return cached
    dtype = torch.float16 if device in ("cuda", "mps") else torch.float32
    local = os.path.isdir(model_path)
    print(f"[LLM] loading {model_path} (device={device})…", file=sys.stderr)
    tok = AutoTokenizer.from_pretrained(model_path, local_files_only=local)
    if tok.pad_token is None:
        if tok.eos_token is not None:
            tok.pad_token = tok.eos_token
        else:
            tok.add_special_tokens({"pad_token": "<|pad|>"})
    kwargs = {"local_files_only": local, "low_cpu_mem_usage": True}
    try:
        mdl = AutoModelForCausalLM.from_pretrained(model_path, dtype=dtype, **kwargs)
    except TypeError:
        mdl = AutoModelForCausalLM.from_pretrained(
            model_path, torch_dtype=dtype, **kwargs
        )
    if tok.pad_token_id is not None and mdl.get_input_embeddings().num_embeddings < len(tok):
        mdl.resize_token_embeddings(len(tok))
    mdl.to(device)
    mdl.eval()
    _LLM_CACHE[key] = (tok, mdl)
    print(f"[LLM] loaded on {device}", file=sys.stderr)
    return tok, mdl

class ChatLlmBackend:
    name = "Локальная чат-LLM"

    _LANG_RU = {
        "en": "английского", "ru": "русского", "de": "немецкого",
        "fr": "французского", "es": "испанского", "it": "итальянского",
        "pt": "португальского", "nl": "нидерландского", "pl": "польского",
        "uk": "украинского", "tr": "турецкого", "zh-CN": "китайского",
        "ja": "японского", "ko": "корейского",
    }
    _LANG_RU_TO = {
        "ru": "русский", "en": "английский", "de": "немецкий",
        "fr": "французский", "es": "испанский", "it": "итальянский",
        "pt": "португальский", "nl": "нидерландский", "pl": "польский",
        "uk": "украинский", "tr": "турецкий", "zh-CN": "китайский",
        "ja": "японский", "ko": "корейский",
    }

    def __init__(self, source: str, target: str = "ru",
                 model_path: str = "", prompt: str = "",
                 device: str = "auto", max_new_tokens: int = 1024):
        try:
            import torch  # noqa: F401
            from transformers import AutoTokenizer, AutoModelForCausalLM  # noqa: F401
        except ImportError as exc:
            raise TranslatorError(
                "Не установлены torch/transformers.\n"
                "pip install torch transformers accelerate sentencepiece"
            ) from exc
        path = (model_path or "").strip()
        if not path:
            raise TranslatorError(
                "Не выбрана локальная LLM.\n\n"
                "Перевод → Менеджер моделей → скачайте модель → «Использовать выбранную»."
            )
        self.device = _resolve_device(device)
        self.source = source
        self.target = target
        self.prompt = (prompt or DEFAULT_LLM_PROMPT).strip()
        self.max_new_tokens = max(64, int(max_new_tokens))
        try:
            self._tokenizer, self._model = _load_llm(path, self.device)
        except Exception as exc:
            raise TranslatorError(
                f"Не удалось загрузить LLM «{path}».\n"
                f"Причина: {exc or repr(exc)}"
            ) from exc

    def _messages(self, text: str) -> List[dict]:
        src = self._LANG_RU.get(self.source, self.source or "оригинала")
        tgt = self._LANG_RU_TO.get(self.target, "русский")
        user = (
            f"Переведи с {src} на {tgt} следующий текст. "
            f"Верни только перевод. Маркеры <N0>, <N1>… сохрани.\n\n{text}"
        )
        return [
            {"role": "system", "content": self.prompt},
            {"role": "user", "content": user},
        ]

    def _clean(self, text: str) -> str:
        text = text.strip()
        for prefix in ("Перевод:", "Переведённый текст:", "Translation:",
                       "Готовый перевод:", "Текст на русском:"):
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
        for q in ('"', '«', '“'):
            close = {'"': '"', '«': '»', '“': '”'}[q]
            if text.startswith(q) and text.endswith(close) and len(text) > 4:
                text = text[1:-1].strip()
        return text

    def _build_inputs(self, text: str) -> dict:
        messages = self._messages(text)
        try:
            prompt = self._tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
        except Exception:
            parts = []
            for m in messages:
                parts.append(f"{m['role'].upper()}: {m['content']}")
            parts.append("ASSISTANT:")
            prompt = "\n".join(parts) + "\n"
        inputs = self._tokenizer(
            prompt, return_tensors="pt", padding=False, truncation=True,
            max_length=4096,
        )
        return {k: v.to(self.device) for k, v in inputs.items()}

    def _split_for_translation(self, text: str, max_chars: int = 1200) -> List[str]:
        text = text.strip()
        if len(text) <= max_chars:
            return [text]
        chunks: List[str] = []
        current = ""
        for sentence in text.split(". "):
            if not sentence:
                continue
            if len(current) + len(sentence) + 2 <= max_chars:
                current = (current + ". " + sentence).strip(". ") if current else sentence
            else:
                if current:
                    chunks.append(current)
                if len(sentence) > max_chars:
                    for i in range(0, len(sentence), max_chars):
                        chunks.append(sentence[i:i + max_chars])
                    current = ""
                else:
                    current = sentence
        if current:
            chunks.append(current)
        return chunks

    def _generate_once(self, text: str) -> str:
        import torch
        try:
            inputs = self._build_inputs(text)
        except Exception as exc:
            raise TranslatorError(f"Промпт: {exc or repr(exc)}") from exc
        input_len = inputs["input_ids"].shape[-1]
        max_new = max(256, min(self.max_new_tokens, len(text) * 2 + 256))
        try:
            with torch.no_grad():
                out = self._model.generate(
                    **inputs, max_new_tokens=max_new, do_sample=False,
                    pad_token_id=self._tokenizer.pad_token_id,
                    eos_token_id=self._tokenizer.eos_token_id,
                )
        except torch.cuda.OutOfMemoryError as exc:
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass
            raise TranslatorError(
                "Недостаточно VRAM. Уменьшите Max tokens."
            ) from exc
        except Exception as exc:
            raise TranslatorError(
                f"Генерация LLM: {str(exc) or repr(exc) or type(exc).__name__}"
            ) from exc
        try:
            return self._tokenizer.decode(
                out[0][input_len:], skip_special_tokens=True
            )
        except Exception as exc:
            raise TranslatorError(f"Декодирование: {exc or repr(exc)}") from exc

    def _raw_multi(self, text: str) -> str:
        chunks = self._split_for_translation(text)
        results: List[str] = []
        for chunk in chunks:
            raw = self._generate_once(chunk)
            cleaned = self._clean(raw)
            if cleaned.strip() and len(cleaned.strip()) >= max(3, len(chunk) * 0.15):
                results.append(cleaned)
                continue
            try:
                retry = self._clean(self._generate_once(chunk))
            except Exception:
                retry = ""
            results.append(retry or cleaned or "")
        return " ".join(r.strip() for r in results if r.strip()).strip()

    def _segment_translate(self, text: str) -> str:
        segments: List[Tuple[str, str]] = []
        pos = 0
        for m in _NUMBER_RE.finditer(text):
            if m.start() > pos:
                segments.append(("text", text[pos:m.start()]))
            segments.append(("num", m.group(0)))
            pos = m.end()
        if pos < len(text):
            segments.append(("text", text[pos:]))
        out: List[str] = []
        for kind, seg in segments:
            if kind == "num" or not seg.strip():
                out.append(seg)
                continue
            try:
                translated = self._raw_multi(seg)
                out.append(translated if translated else seg)
            except Exception:
                out.append(seg)
        return "".join(out)

    def translate(self, text: str) -> str:
        if not text.strip():
            return text
        t = text.strip()
        if _NUMERIC_ONLY.match(t):
            return text
        if not _NUMBER_RE.search(t):
            return self._raw_multi(t)
        masked, numbers = _protect_numbers(t)
        try:
            masked_result = self._raw_multi(masked)
        except Exception:
            masked_result = ""
        restored, missing = _restore_numbers(masked_result, numbers)
        if missing == 0 and _has_all_numbers(t, restored):
            return restored
        return self._segment_translate(t)

# ---- END OF FILE app/translator_engines.py ----
