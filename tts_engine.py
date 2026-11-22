# -*- coding: utf-8 -*-
"""Dual-model TTS engine for Kiki Talk (কিকি টক).

Two Bengali VITS voices, both trained fresh from the EMTIAZZ base with the
same 92-token vocab and the same orthography rules:

  akib — Akib's voice (2,381 clips / 152.1 min, 64 of 65 epochs,
         checkpoint_17500). HF repo demoqqq/banglatts-akib.
  kiki — Kiki Big Rerecord voice (1,641 clips / 220.0 min, ~80 of 90
         epochs, checkpoint_15500). HF repo
         demoqqq/banglatts-kiki-big-rerecord.

Importable without Streamlit: ``python -c "import tts_engine"`` must work
in a plain venv that only has sherpa-onnx installed.

Model source: public Hugging Face repos. Each 114 MB ONNX exceeds
GitHub's 100 MB per-file limit, so models are never committed — they are
downloaded at runtime and verified by exact byte size AND MD5 before use.

Proven synthesis settings (same as the Android app / VM tests):
noise_scale 0.667, noise_scale_w 0.8, length_scale 1.0,
max_num_sentences 1, silence_scale 0.2, sample rate 22050 Hz.

ORTHOGRAPHY NORMALIZATION: both vocabs (92 tokens, byte-identical
tokens files) use ONLY the decomposed forms (য+় / ড+় / ঢ+়), like the
old training transcripts — typed Bengali MUST be normalized before
generation (য়→য+়, ড়→ড+়, ঢ়→ঢ+়), otherwise those characters are
out-of-vocab. See normalize_text() below.
"""

import hashlib
import io
import os
import time
import urllib.request
import wave
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Model registry. MODEL_SIZE / MODEL_MD5 verified from the ONNX exports
# (Akib 2026-11-21, Kiki Big Rerecord 2026-11-22). TOKENS verified:
# both sherpa token files are 605 B, MD5 366751e1... (same 92-token vocab).
# ---------------------------------------------------------------------------
MODELS = {
    "akib": {
        "label": "মডেল ১ — আকিব",
        "voice_name": "Akib (আকিব)",
        "hf_repo": "demoqqq/banglatts-akib",
        "model_url": "https://huggingface.co/demoqqq/banglatts-akib/resolve/main/model.onnx",
        "model_size": 114192738,
        "model_md5": "d82a9bb0a4afd0e8a02c569bff3d8e93",
        "tokens_url": "https://huggingface.co/demoqqq/banglatts-akib/resolve/main/tokens_sherpa.txt",
        "tokens_size": 605,
        "tokens_md5": "366751e11c26877a07828e4cbd3e7d7d",
        "cache_subdir": "model_cache_akib",
        "env_dir": "BANGALTTS_AKIB_MODEL_DIR",
    },
    "kiki": {
        "label": "মডেল ২ — কিকি বিগ রিরেকর্ড",
        "voice_name": "Kiki Big Rerecord (কিকি বিগ রিরেকর্ড)",
        "hf_repo": "demoqqq/banglatts-kiki-big-rerecord",
        "model_url": "https://huggingface.co/demoqqq/banglatts-kiki-big-rerecord/resolve/main/model.onnx",
        "model_size": 114192751,
        "model_md5": "88d36f7e19ba187e4952e0c76a9c8108",
        "tokens_url": "https://huggingface.co/demoqqq/banglatts-kiki-big-rerecord/resolve/main/tokens_sherpa.txt",
        "tokens_size": 605,
        "tokens_md5": "366751e11c26877a07828e4cbd3e7d7d",
        "cache_subdir": "model_cache_kiki",
        "env_dir": "BANGALTTS_KIKI_MODEL_DIR",
    },
}

MODEL_KEYS = list(MODELS)

SAMPLE_RATE = 22050
MAX_PART_CHARS = 700          # never generate more than this in one call
JOIN_SILENCE_S = 0.5          # silence between parts
NUM_THREADS = int(os.environ.get("BANGALTTS_THREADS", "2"))


def _md5_of(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path, expected_size: int, expected_md5: str) -> Path:
    """Download a file, verifying exact size AND MD5. Loud failure on mismatch."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    req = urllib.request.Request(url, headers={"User-Agent": "kiki-talk-streamlit/1.0"})
    with urllib.request.urlopen(req, timeout=300) as resp, open(tmp, "wb") as out:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    size = tmp.stat().st_size
    if size != expected_size:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"download size mismatch for {dest.name}: got {size}, "
            f"expected {expected_size}"
        )
    md5 = _md5_of(tmp)
    if md5 != expected_md5:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"download MD5 mismatch for {dest.name}: got {md5}, "
            f"expected {expected_md5}"
        )
    tmp.replace(dest)
    return dest


def default_cache_dir(model_key: str) -> Path:
    spec = MODELS[model_key]
    override = os.environ.get(spec["env_dir"])
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / spec["cache_subdir"]


# Both vocabs use ONLY decomposed forms.
_PRECOMPOSED_TO_DECOMPOSED = {
    "\u09df": "\u09af\u09bc",  # য় -> য + ়
    "\u09dc": "\u09a1\u09bc",  # ড় -> ড + ়
    "\u09dd": "\u09a2\u09bc",  # ঢ় -> ঢ + ়
}


def normalize_text(text: str) -> str:
    """Normalize typed Bengali to the training orthography."""
    for pre, dec in _PRECOMPOSED_TO_DECOMPOSED.items():
        text = text.replace(pre, dec)
    return text


def ensure_model(model_key: str, cache_dir: Path | None = None) -> tuple[Path, Path]:
    """Return (model_path, tokens_path) for one voice, downloading if needed."""
    spec = MODELS[model_key]
    cache_dir = Path(cache_dir) if cache_dir else default_cache_dir(model_key)
    model_path = cache_dir / "model.onnx"
    tokens_path = cache_dir / "tokens_sherpa.txt"
    if not (model_path.exists() and model_path.stat().st_size == spec["model_size"]
            and _md5_of(model_path) == spec["model_md5"]):
        _download(spec["model_url"], model_path, spec["model_size"], spec["model_md5"])
    if not (tokens_path.exists() and tokens_path.stat().st_size == spec["tokens_size"]
            and _md5_of(tokens_path) == spec["tokens_md5"]):
        _download(spec["tokens_url"], tokens_path, spec["tokens_size"], spec["tokens_md5"])
    return model_path, tokens_path


# ---------------------------------------------------------------------------
# Chunking: split ONLY at sentence boundaries, never mid-word / mid-phrase.
# Primary boundary is the danda (।). A part is at most 700 chars.
# ---------------------------------------------------------------------------
_DANDA = "।"
_FALLBACK_BOUNDARIES = ("?", "!", ",", "…")


def split_into_parts(text: str, max_chars: int = MAX_PART_CHARS) -> list[str]:
    """Split text into parts of <= max_chars, cutting only at punctuation."""
    text = " ".join(text.split())
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    sentences: list[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if ch == _DANDA:
            sentences.append(buf.strip())
            buf = ""
    if buf.strip():
        sentences.append(buf.strip())

    parts: list[str] = []
    for sent in sentences:
        if len(sent) <= max_chars:
            if parts and len(parts[-1]) + 1 + len(sent) <= max_chars:
                parts[-1] = parts[-1] + " " + sent
            else:
                parts.append(sent)
        else:
            parts.extend(_split_long_sentence(sent, max_chars))
    final: list[str] = []
    for p in parts:
        if len(p) <= max_chars:
            final.append(p)
        else:
            final.extend(_split_long_sentence(p, max_chars))
    return [p for p in final if p]


def _split_long_sentence(sent: str, max_chars: int) -> list[str]:
    """Split one over-long sentence at fallback punctuation, then spaces."""
    pieces: list[str] = []
    buf = ""
    for ch in sent:
        buf += ch
        if ch in _FALLBACK_BOUNDARIES:
            pieces.append(buf.strip())
            buf = ""
    if buf.strip():
        pieces.append(buf.strip())
    out: list[str] = []
    for piece in pieces:
        if len(piece) <= max_chars:
            out.append(piece)
        else:
            words = piece.split(" ")
            cur = ""
            for w in words:
                if len(cur) + len(w) + 1 <= max_chars:
                    cur = (cur + " " + w).strip()
                else:
                    if cur:
                        out.append(cur)
                    cur = w
            if cur:
                out.append(cur)
    packed: list[str] = []
    for p in out:
        if packed and len(packed[-1]) + 1 + len(p) <= max_chars:
            packed[-1] = packed[-1] + " " + p
        else:
            packed.append(p)
    return packed


# ---------------------------------------------------------------------------
# Synthesis (one loaded TTS object per voice, cached in-process)
# ---------------------------------------------------------------------------
_tts_by_model: dict[str, object] = {}


def _load_tts(model_key: str):
    if model_key in _tts_by_model:
        return _tts_by_model[model_key]
    import sherpa_onnx

    model_path, tokens_path = ensure_model(model_key)
    tts = sherpa_onnx.OfflineTts(
        sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=str(model_path),
                    tokens=str(tokens_path),
                    noise_scale=0.667,
                    noise_scale_w=0.8,
                    length_scale=1.0,
                ),
                num_threads=NUM_THREADS,
            ),
            rule_fsts="",
            max_num_sentences=1,
            silence_scale=0.2,
        )
    )
    _tts_by_model[model_key] = tts
    return tts


def synthesize(text: str, model_key: str, speed: float = 1.0) -> tuple[np.ndarray, dict]:
    """Synthesize Bengali text -> (float32 mono samples @22050, info dict).

    Chunks by danda (<=700 chars/part) and joins parts with 0.5 s silence.
    """
    text = normalize_text(text)
    parts = split_into_parts(text)
    if not parts:
        raise ValueError("খালি লেখা — কিছু লিখে তারপর বানান।")
    tts = _load_tts(model_key)
    samples = np.zeros(0, dtype=np.float32)
    join = np.zeros(int(JOIN_SILENCE_S * SAMPLE_RATE), dtype=np.float32)
    t0 = time.time()
    for part in parts:
        audio = tts.generate(part, sid=0, speed=speed)
        s = np.asarray(audio.samples, dtype=np.float32)
        samples = np.concatenate([samples, s, join])
    if len(parts) > 1:
        samples = samples[: len(samples) - len(join)]
    wall = time.time() - t0
    duration = len(samples) / SAMPLE_RATE
    info = {
        "model": model_key,
        "parts": len(parts),
        "part_chars": [len(p) for p in parts],
        "duration_s": round(duration, 2),
        "synth_time_s": round(wall, 1),
        "rtf": round(wall / duration, 2) if duration > 0 else None,
        "peak": round(float(np.abs(samples).max()), 3) if len(samples) else 0.0,
        "rms": round(float(np.sqrt((samples ** 2).mean())), 4) if len(samples) else 0.0,
    }
    return samples, info


def samples_to_wav_bytes(samples: np.ndarray) -> bytes:
    """Float32 mono @22050 -> 16-bit PCM WAV bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()


def write_wav(path: Path, samples: np.ndarray) -> Path:
    path = Path(path)
    path.write_bytes(samples_to_wav_bytes(samples))
    return path
