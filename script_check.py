# -*- coding: utf-8 -*-
"""Script check for Kiki Talk: auto-fix a Bengali script BEFORE generation,
so the voice does not garble.

Rules (from the approved subscription plan, p.5):
  - digits -> Bengali words (২০২৪ -> "দুই হাজার চব্বিশ", ৫০ -> "পঞ্চাশ")
  - colon : -> comma (colon is NOT in the model vocab)
  - ellipsis … / "..." -> removed (not in vocab)
  - triple danda ।।। -> single দাঁড়ি (extra dandas add no pause)
  - orthography: য়→য+়, ড়→ড+়, ঢ়→ঢ+় (training orthography)
  - collapse extra whitespace

Warnings (shown, not auto-fixed):
  - "?" — only for real questions (longest pause but question intonation)
  - "!" — only for real surprise
  - Latin letters — prefer Bengali words
  - very long sentences (>700 chars) — split them
  - a chunk with no danda at the end
"""

import re

from tts_engine import normalize_text

_BN_DIGITS = "০১২৩৪৫৬৭৮৯"
_EN_DIGITS = "0123456789"
_EN_TO_BN = str.maketrans(_EN_DIGITS, _BN_DIGITS)

_ONES = ["শূন্য", "এক", "দুই", "তিন", "চার", "পাঁচ", "ছয়", "সাত", "আট", "নয়"]
_TEENS = ["দশ", "এগারো", "বারো", "তেরো", "চৌদ্দ", "পনেরো", "ষোলো",
          "সতেরো", "আঠারো", "উনিশ"]
_TENS = ["", "", "বিশ", "ত্রিশ", "চল্লিশ", "পঞ্চাশ", "ষাট", "সত্তর",
         "আশি", "নব্বই"]
_TENS_ONES = {
    21: "একুশ", 22: "বাইশ", 23: "তেইশ", 24: "চব্বিশ", 25: "পঁচিশ",
    26: "ছাব্বিশ", 27: "সাতাশ", 28: "আটাশ", 29: "ঊনত্রিশ",
    31: "একত্রিশ", 32: "বত্রিশ", 33: "তেত্রিশ", 34: "চৌত্রিশ",
    35: "পঁয়ত্রিশ", 36: "ছত্রিশ", 37: "সাঁইত্রিশ", 38: "আটত্রিশ",
    39: "ঊনচল্লিশ", 41: "একচল্লিশ", 42: "বিয়াল্লিশ", 43: "তেতাল্লিশ",
    44: "চুয়াল্লিশ", 45: "পঁয়তাল্লিশ", 46: "ছেচল্লিশ", 47: "সাতচল্লিশ",
    48: "আটচল্লিশ", 49: "ঊনপঞ্চাশ", 51: "একান্ন", 52: "বায়ান্ন",
    53: "তিপ্পান্ন", 54: "চুয়ান্ন", 55: "পঞ্চান্ন", 56: "ছাপ্পান্ন",
    57: "সাতান্ন", 58: "আটান্ন", 59: "ঊনষাট", 61: "একষট্টি",
    62: "বাষট্টি", 63: "তেষট্টি", 64: "চৌষট্টি", 65: "পঁয়ষট্টি",
    66: "ছেষট্টি", 67: "সাতষট্টি", 68: "আটষট্টি", 69: "ঊনসত্তর",
    71: "একাত্তর", 72: "বাহাত্তর", 73: "তিয়াত্তর", 74: "চুয়াত্তর",
    75: "পঁচাত্তর", 76: "ছিয়াত্তর", 77: "সাতাত্তর", 78: "আটাত্তর",
    79: "ঊনআশি", 81: "একাশি", 82: "বিরাশি", 83: "তিরাশি",
    84: "চুরাশি", 85: "পঁচাশি", 86: "ছিয়াশি", 87: "সাতাশি",
    88: "আটাশি", 89: "ঊননব্বই", 91: "একানব্বই", 92: "বিরানব্বই",
    93: "তিরানব্বই", 94: "চুরানব্বই", 95: "পঁচানব্বই", 96: "ছিয়ানব্বই",
    97: "সাতানব্বই", 98: "আটানব্বই", 99: "নিরানব্বই",
}


def _under_100(n: int) -> str:
    if n < 10:
        return _ONES[n]
    if n < 20:
        return _TEENS[n - 10]
    if n % 10 == 0:
        return _TENS[n // 10]
    return _TENS_ONES[n]


def _under_1000(n: int) -> str:
    if n < 100:
        return _under_100(n)
    hundreds, rest = divmod(n, 100)
    if rest == 0:
        return f"{_ONES[hundreds]} শত"
    return f"{_ONES[hundreds]} শত {_under_100(rest)}"


def number_to_bengali_words(n: int) -> str:
    """Integer (0 .. 999,999,999) -> Bengali words. Uses হাজার / লক্ষ / কোটি."""
    if n < 0:
        return "ঋণাত্মক " + number_to_bengali_words(-n)
    if n < 1000:
        return _under_1000(n)
    crore, rest = divmod(n, 10_000_000)
    lakh, rest = divmod(rest, 100_000)
    thousand, rest = divmod(rest, 1000)
    parts = []
    if crore:
        parts.append(f"{_under_1000(crore)} কোটি")
    if lakh:
        parts.append(f"{_under_100(lakh)} লক্ষ")
    if thousand:
        parts.append(f"{_under_100(thousand)} হাজার")
    if rest:
        parts.append(_under_1000(rest))
    return " ".join(parts)


def _digits_to_words_token(token: str) -> str:
    """One digit-run token (may contain , or . separators) -> Bengali words."""
    ascii_token = token.translate(str.maketrans(_BN_DIGITS, _EN_DIGITS))
    if "." in ascii_token:
        whole, frac = ascii_token.split(".", 1)
        whole_w = number_to_bengali_words(int(whole)) if whole else "শূন্য"
        frac_w = " ".join(_ONES[int(d)] for d in frac if d.isdigit())
        return f"{whole_w} দশমিক {frac_w}" if frac_w else whole_w
    n = int(ascii_token.replace(",", ""))
    if len(ascii_token.replace(",", "")) > 9:
        # Very long runs (phone numbers etc.) — read digit by digit.
        return " ".join(_ONES[int(d)] for d in ascii_token if d.isdigit())
    return number_to_bengali_words(n)


_NUM_RE = re.compile(r"[০-৯0-9]+(?:[,.][০-৯0-9]+)+|[০-৯0-9]+")


def digits_to_words(text: str) -> str:
    """Replace every digit run in text with Bengali words."""
    return _NUM_RE.sub(lambda m: _digits_to_words_token(m.group(0)), text)


def check_script(text: str) -> dict:
    """Auto-fix a script and report what changed.

    Returns {"fixed": str, "fixes": [str], "warnings": [str]}.
    The returned ``fixed`` text is what generation must use.
    """
    fixes: list[str] = []
    warnings: list[str] = []
    original = text or ""
    fixed = original

    # 1. Orthography (য়→য+় etc.)
    norm = normalize_text(fixed)
    if norm != fixed:
        fixes.append("বানানরীতি ঠিক করা হয়েছে (য়/ড়/ঢ় → য+়/ড+়/ঢ+়)।")
        fixed = norm

    # 2. Digits -> Bengali words
    if _NUM_RE.search(fixed):
        fixed = digits_to_words(fixed)
        fixes.append("সব সংখ্যা বাংলা কথায় বদলে দেওয়া হয়েছে (যেমন ২০২৪ → দুই হাজার চব্বিশ)।")

    # 3. Colon -> comma (colon is not in the model vocab)
    if ":" in fixed:
        fixed = fixed.replace(":", ",")
        fixes.append("কোলন (:) বাদ দিয়ে কমা দেওয়া হয়েছে — কোলন মডেল পড়তে পারে না।")

    # 4. Ellipsis -> removed (not in vocab)
    if "…" in fixed or "..." in fixed:
        fixed = fixed.replace("…", "").replace("...", "")
        fixes.append("তিন ডট (…) বাদ দেওয়া হয়েছে — এটা মডেল পড়তে পারে না।")

    # 5. Triple danda -> single danda
    if "।।" in fixed:
        fixed = re.sub(r"।{2,}", "।", fixed)
        fixes.append("বাড়তি দাঁড়ি (।।।) কমিয়ে একটা দাঁড়ি করা হয়েছে — বাড়তি দাঁড়িতে বাড়তি বিরতি হয় না।")

    # 6. Whitespace
    cleaned = " ".join(fixed.split())
    if cleaned != fixed:
        fixed = cleaned
        fixes.append("বাড়তি ফাঁকা জায়গা পরিষ্কার করা হয়েছে।")

    # ---- warnings (shown, not auto-fixed) ----
    if "?" in fixed:
        warnings.append("প্রশ্নবোধক (?) আছে — শুধু আসল প্রশ্নের বাক্যেই রাখবেন; খবরে শুধু থামার জন্য ব্যবহার করবেন না (সুর প্রশ্নের মতো হয়ে যায়)।")
    if "!" in fixed:
        warnings.append("বিস্ময়সূচক (!) আছে — শুধু আসল বিস্ময় বা জোরের জায়গায় রাখবেন, প্রতিটি বাক্যে নয়।")
    if re.search(r"[A-Za-z]", fixed):
        warnings.append("ইংরেজি অক্ষর আছে — যতটা পারা যায় বাংলা শব্দ ব্যবহার করুন, নইলে মডেল এলোমেলো পড়তে পারে।")
    if re.search(r"[×÷+%]", fixed):
        warnings.append("× ÷ + % চিহ্ন আছে — এগুলো পড়া নাও হতে পারে; কথায় লিখুন (যেমন ‘শতকরা’ )।")

    # Long sentences / missing danda
    sentences = [s for s in fixed.split("।") if s.strip()]
    for s in sentences:
        if len(s.strip()) > 700:
            warnings.append("একটা বাক্য অনেক লম্বা (৭০০ অক্ষরের বেশি) — ভেঙে দুটি বাক্য করুন, তাতে থামা ঠিক থাকবে।")
            break
    if fixed and not fixed.rstrip().endswith(("।", "?", "!")):
        warnings.append("শেষ বাক্যটা দাঁড়ি দিয়ে শেষ হয়নি — দাঁড়ি দিয়ে শেষ করুন।")

    return {"fixed": fixed, "fixes": fixes, "warnings": warnings}


# ---------------------------------------------------------------------------
# Rules page content (from the approved plan, p.5) + the ready-made prompt.
# ---------------------------------------------------------------------------

RULES_TABLE = [
    ("দাঁড়ি ।", "প্রতিটি বাক্য দাঁড়ি দিয়ে শেষ করুন। এটিই মূল থামা। প্রতিটি বাক্য আলাদা করে তৈরি হলে বাক্যের মাঝে সঠিক লম্বা বিরতি পাওয়া যায়।"),
    ("কমা ,", "বাক্যের ভেতরে ছোট থামার জায়গায় কমা দিন। কমা মানে খুব ছোট বিরতি — লম্বা থামা চাইলে বাক্যটাই শেষ করে দাঁড়ি দিন।"),
    ("প্রশ্নবোধক ?", "শুধু আসল প্রশ্ন হলেই ব্যবহার করুন। এতে বিরতি সবচেয়ে লম্বা হয়, কিন্তু সুরটাও প্রশ্নের মতো হয়ে যায় — খবরে শুধু থামার জন্য এটি ব্যবহার করবেন না।"),
    ("বিস্ময়সূচক !", "আসল বিস্ময় বা জোরের জায়গাতেই ব্যবহার করুন, প্রতিটি বাক্যে নয়।"),
    ("তিন দাঁড়ি ।।।", "ব্যবহার করে লাভ নেই — বাড়তি দাঁড়ি বাড়তি বিরতি দেয় না, একটি দাঁড়ির সমানই থামে।"),
    ("কোলন : ও তিন ডট …", "একদম ব্যবহার করবেন না। এই দুটি চিহ্ন মডেলের শব্দভান্ডারে নেই — মডেল এগুলো বাদ দিয়ে পড়ে, ফলে থামাও পাওয়া যায় না, লেখার অর্থও বদলে যেতে পারে। কোলনের বদলে কমা বা দাঁড়ি দিন।"),
    ("সংখ্যা", "সব সংখ্যা বাংলা কথায় লিখুন, অঙ্কে নয়। যেমন: ২০২৪ লিখবেন না, লিখুন “দুই হাজার চব্বিশ”; ৫০ টাকা নয়, “পঞ্চাশ টাকা”। অঙ্কে লিখলে মডেল ভুল বা এলোমেলো পড়তে পারে।"),
    ("ইংরেজি শব্দ", "যতটা পারা যায় বাংলা শব্দ ব্যবহার করুন। খুব পরিচিত ইংরেজি শব্দ ছাড়া বিদেশি শব্দ, সংক্ষিপ্ত রূপ ও লিঙ্ক স্ক্রিপ্টে রাখবেন না।"),
    ("বাক্যের দৈর্ঘ্য", "একেকটি বাক্য ছোট ও পরিষ্কার রাখুন। খুব লম্বা বাক্য ভেঙে দুটি বাক্য করুন — তাতে থামা ঠিক থাকে, শুনতেও ভালো লাগে।"),
]

READY_PROMPT = """তুমি বাংলা ভয়েসওভারের জন্য স্ক্রিপ্ট সাজিয়ে দাও। নিচের লেখাটি হুবহু অর্থ ঠিক রেখে, কোনো তথ্য যোগ বা বাদ না দিয়ে, এই নিয়মে সাজিয়ে দাও:

১. সব সংখ্যা বাংলা কথায় লিখবে। যেমন ২০২৪ হবে "দুই হাজার চব্বিশ", ৫০ হবে "পঞ্চাশ"। লেখায় কোনো অঙ্ক থাকবে না।
২. কোলন (:) ও তিন ডট (…) একদম ব্যবহার করবে না। কোলনের বদলে কমা বা দাঁড়ি দেবে।
৩. প্রতিটি বাক্য দাঁড়ি (।) দিয়ে শেষ করবে। তিন দাঁড়ি (।।।) ব্যবহার করবে না।
৪. প্রশ্নবোধক (?) শুধু আসল প্রশ্নের বাক্যেই রাখবে, বিস্ময়সূচক (!) শুধু আসল বিস্ময়ের জায়গায়।
৫. খুব লম্বা বাক্য ভেঙে ছোট ছোট বাক্য করবে, যাতে পড়তে ও শুনতে সুবিধা হয়।
৬. ইংরেজি শব্দ ও সংক্ষিপ্ত রূপ যতটা পারা যায় সহজ বাংলায় বদলে দেবে।
৭. কোনো শিরোনাম, নম্বর, তালিকা বা ব্যাখ্যা যোগ করবে না — শুধু সাজানো স্ক্রিপ্টটাই দেবে, একটানা অনুচ্ছেদে।

স্ক্রিপ্ট: [এখানে নিজের স্ক্রিপ্ট বসান]"""
