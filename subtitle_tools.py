# -*- coding: utf-8 -*-
"""কিকি টক সাবটাইটেল টুলস — Streamlit ছাড়া চলে, তাই আলাদা করে পরীক্ষা করা যায়।

তিনটি পথে একই জিনিস বানায়: স্ক্রিপ্টের লেখা (১০০% সঠিক) + অডিওর সময়।
ASR (শুনে লেখা বের করা) কোথাও ব্যবহার করা হয় না — লেখা সবসময় স্ক্রিপ্টেরটাই।

পথ A — স্ক্রিপ্ট থেকে অডিও বানানো: প্রতিটা বাক্য আলাদা করে বেছে নেওয়া কণ্ঠে
       বানানো হয়, প্রতিটার আসল সময় মাপা হয়। সবচেয়ে নির্ভুল।
পথ B — অডিও + স্ক্রিপ্ট: আপলোড করা অডিওতে নীরবতা (silence) ধরে বাক্যের
       সীমানা খোঁজা হয়, তারপর স্ক্রিপ্টের বাক্যগুলো ক্রমানুসারে বসানো হয়।
পথ C — স্ক্রিপ্ট + মোট সময়: অডিও না থাকলে মোট সময় বাক্যের দৈর্ঘ্য
       অনুযায়ী ভাগ করে দেওয়া হয় (আনুমানিক — সতর্কবার্তা দেখানো হয়)।
"""
import io
import json
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

MIN_SILENCE_S = 0.40     # এর চেয়ে লম্বা নীরবতাকেই বাক্যের ফাঁক ধরা হয় (মাপা: বাক্যের
                       # ভেতরের বিরতি সর্বোচ্চ ০.২৫ সেকেন্ড, আর জোড়ার ফাঁক
                       # কমপক্ষে ০.৫০ সেকেন্ড — তাই ০.৪০ নিরাপদ সীমা)
MIN_SPEECH_S = 0.50      # এর চেয়ে ছোট টুকরো বাক্য হতে পারে না
FRAME_S = 0.02           # RMS মাপার জানালা (০.০৫ থেকে ছোট করা — সীমানা আরও নিখুঁত হয়)


def split_sentences(text: str) -> list[str]:
    """দাঁড়িতে ভাগ — প্রতিটা বাক্য একটা সাবটাইটেল কার্ড হবে।"""
    text = " ".join(text.split())
    sentences, buf = [], ""
    for ch in text:
        buf += ch
        if ch == "।":
            sentences.append(buf.strip())
            buf = ""
    if buf.strip():
        sentences.append(buf.strip())
    return [s for s in sentences if s]


def srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(segments) -> str:
    out = []
    for i, seg in enumerate(segments, 1):
        out.append(f"{i}\n{srt_time(seg['start'])} --> {srt_time(seg['end'])}\n{seg['text']}\n")
    return "\n".join(out)


def to_json(filename: str, duration: float, segments, method: str,
            voice: str = "Kiki Talk (কিকি টক)") -> str:
    data = {
        "file": filename,
        "language": "bn",
        "voice": voice,
        "method": method,
        "duration_seconds": round(duration, 2),
        "full_text": " ".join(s["text"] for s in segments),
        "segments": [
            {"id": i, "start": round(s["start"], 2), "end": round(s["end"], 2),
             "text": s["text"]}
            for i, s in enumerate(segments, 1)
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def read_wav_bytes(data: bytes) -> tuple[np.ndarray, int]:
    """WAV বাইট → (float32 mono samples, sample_rate)।"""
    with wave.open(io.BytesIO(data), "rb") as w:
        nch, sw, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if sw == 2:
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sw == 4:
        audio = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError("শুধু 16-bit বা 32-bit WAV চলবে।")
    if nch > 1:
        audio = audio.reshape(-1, nch).mean(axis=1)
    return audio, rate


def decode_audio(data: bytes, ext: str) -> tuple[np.ndarray, int]:
    """যেকোনো অডিও (mp3/m4a/...) → WAV-এ নামিয়ে (ffmpeg) float32 samples।"""
    ext = ext.lower().lstrip(".")
    if ext == "wav":
        return read_wav_bytes(data)
    with tempfile.NamedTemporaryFile(suffix="." + ext, delete=False) as f:
        f.write(data)
        src = f.name
    out = src + ".wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src,
                    "-map", "0:a:0", "-ar", "16000", "-ac", "1", out],
                   check=True)
    return read_wav_bytes(Path(out).read_bytes())


def silence_segments(audio: np.ndarray, rate: int) -> list[tuple[float, float]]:
    """নীরবতা ধরে কথা বলার টুকরোগুলোর (start, end) সেকেন্ডে বের করে।"""
    frame = max(1, int(FRAME_S * rate))
    n_frames = len(audio) // frame
    if n_frames == 0:
        return []
    frames = audio[: n_frames * frame].reshape(n_frames, frame)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    peak = rms.max()
    if peak <= 0:
        return []
    # থ্রেশহোল্ড: সর্বোচ্চ শব্দের ৩% — কিকি বিগ রিরেকর্ডের ০.৫ সেকেন্ডের জোড়া নীরবতা
    # পুরো শূন্য, তাই এই সীমায় ধরা পড়বেই।
    silent = rms < max(peak * 0.01, 1e-4)
    min_sil_frames = max(1, int(MIN_SILENCE_S / FRAME_S))
    # লম্বা নীরবতার মাঝখানটা বের করো
    bounds: list[tuple[float, float]] = []
    start = 0.0
    i = 0
    while i < n_frames:
        if silent[i]:
            j = i
            while j < n_frames and silent[j]:
                j += 1
            if j - i >= min_sil_frames and i > 0:
                bounds.append((start, i * FRAME_S))
                start = j * FRAME_S
            i = j
        else:
            i += 1
    bounds.append((start, len(audio) / rate))
    # খুব ছোট টুকরো পাশেরটার সঙ্গে জুড়ে দাও
    merged: list[tuple[float, float]] = []
    for s, e in bounds:
        if e - s < MIN_SPEECH_S and merged:
            ps, _ = merged[-1]
            merged[-1] = (ps, e)
        else:
            merged.append((s, e))
    return [(round(s, 2), round(e, 2)) for s, e in merged if e - s >= MIN_SPEECH_S]


def proportional_segments(sentences: list[str], total_s: float) -> list[dict]:
    """মোট সময় বাক্যের দৈর্ঘ্য অনুযায়ী ভাগ করে (আনুমানিক)।"""
    total_chars = sum(len(s) for s in sentences) or 1
    out, offset = [], 0.0
    for sent in sentences:
        dur = total_s * len(sent) / total_chars
        out.append({"start": round(offset, 2), "end": round(offset + dur, 2),
                    "text": sent})
        offset += dur
    return out


def align_audio_script(audio: np.ndarray, rate: int, sentences: list[str]):
    """পথ B: অডিওর নীরবতা-টুকরো ↔ স্ক্রিপ্টের বাক্য (ক্রমানুসারে)।

    ফেরত: (segments, exact: bool, note) — সংখ্যা না মিললে আনুমানিক ভাগে
    ফিরে যায় আর সেটা note-এ জানিয়ে দেয়।
    """
    total = len(audio) / rate
    spans = silence_segments(audio, rate)
    if len(spans) == len(sentences):
        segs = [{"start": s, "end": e, "text": t}
                for (s, e), t in zip(spans, sentences)]
        return segs, True, f"অডিওতে {len(spans)}টি বাক্যের ফাঁক পাওয়া গেছে — সময় নির্ভুল।"
    segs = proportional_segments(sentences, total)
    return segs, False, (
        f"অডিওতে {len(spans)}টি টুকরো পাওয়া গেছে, কিন্তু স্ক্রিপ্টে বাক্য "
        f"{len(sentences)}টি — তাই মোট সময় বাক্যের দৈর্ঘ্য অনুযায়ী ভাগ করে "
        f"দেওয়া হয়েছে (আনুমানিক)। বাক্যের ফাঁকে ০.৫ সেকেন্ড নীরবতা থাকলে "
        f"নির্ভুল হয় — কিকি বিগ রিরেকর্ড ডেমো থেকে বানানো অডিওতে সেটা থাকে।"
    )


def synthesize_aligned(text: str, model_key: str = "akib", speed: float = 1.0):
    """পথ A: প্রতি বাক্য আলাদা করে বেছে নেওয়া কণ্ঠে বানিয়ে সময়সহ সাবটাইটেল দেয়.

    ফেরত: (samples, segments, info) — segments-এ প্রতিটা বাক্যের
    আসল শুরু/শেষ সময় (সেকেন্ডে) থাকে। tts_engine এখানে দেরিতে import
    করা হয়, যাতে এই মডিউল Streamlit/sherpa ছাড়াও পরীক্ষা করা যায়।
    """
    import tts_engine

    sentences = split_sentences(text)
    if not sentences:
        raise ValueError("খালি স্ক্রিপ্ট।")
    # এই মডেল কিকি বানানরীতি ব্যবহার করে (য়→য+় ইত্যাদি): অডিও বানানোর
    # লেখাটা normalize করতে হয়, কিন্তু সাবটাইটেলে মূল স্ক্রিপ্টের লেখাই থাকে।
    normalize = getattr(tts_engine, "normalize_text", lambda t: t)
    tts = tts_engine._load_tts(model_key)
    join = np.zeros(int(tts_engine.JOIN_SILENCE_S * tts_engine.SAMPLE_RATE),
                    dtype=np.float32)
    samples = np.zeros(0, dtype=np.float32)
    segments = []
    offset = 0.0
    for sent in sentences:
        audio = tts.generate(normalize(sent), sid=0, speed=speed)
        s = np.asarray(audio.samples, dtype=np.float32)
        dur = len(s) / tts_engine.SAMPLE_RATE
        segments.append({"start": round(offset, 2), "end": round(offset + dur, 2),
                         "text": sent})
        samples = np.concatenate([samples, s, join])
        offset += dur + tts_engine.JOIN_SILENCE_S
    if len(sentences) > 1:
        samples = samples[: len(samples) - len(join)]
    duration = len(samples) / tts_engine.SAMPLE_RATE
    return samples, segments, {"sentences": len(sentences),
                                "duration_s": round(duration, 2)}


def format_duration(total_s: float) -> str:
    """সেকেন্ড → '১ মিনিট ২৩ সেকেন্ড' / '৪৮.৬ সেকেন্ড'।"""
    total_s = round(total_s, 1)
    m, s = divmod(total_s, 60)
    if m >= 1:
        return f"{int(m)} মিনিট {s:.0f} সেকেন্ড"
    return f"{total_s} সেকেন্ড"
