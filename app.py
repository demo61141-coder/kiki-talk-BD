# -*- coding: utf-8 -*-
"""কিকি টক (Kiki Talk) — বাংলা TTS সাবস্ক্রিপশন অ্যাপ।

দুটি ভয়েস (মডেল ১ আকিব / মডেল ২ কিকি বিগ রিরেকর্ড) এক লগইনে।
সাইন আপ করলেই ১ ঘণ্টার ফ্রি ট্রায়াল, তারপর ম্যানুয়াল বিকাশ/নগদ
পেমেন্টে প্যাকেজ অনুযায়ী (১ সপ্তাহ / ১ মাস / ২ মাস) আনলিমিটেড।
অ্যাডমিন প্যানেল অ্যাপের ভেতরেই — লুকানো প্রবেশপথ (কোনো বাটন বা লিংক
নেই); ৪ সংখ্যার পিন দিয়ে খোলে। পেমেন্ট যাচাই করে এক ক্লিকে অ্যাকাউন্ট
চালু করা যায়; পেমেন্টের নম্বর/নির্দেশনা ও প্যাকেজও অ্যাডমিন নিজেই
বদলাতে পারেন; এক IP থেকে একাধিক অ্যাকাউন্ট ধরার ব্যবস্থা আছে।

ডেটা থাকে প্রাইভেট Hugging Face ডেটাসেটে (store.py দেখুন) — Streamlit
Cloud রিস্টার্ট হলেও মুছে যায় না, কোনো সার্ভার লাগে না।
"""

import time
from pathlib import Path

import streamlit as st

import script_check
import store
import subtitle_tools as tools
import tts_engine

# ---------------------------------------------------------------------------
# পেমেন্টের নম্বর — মালিকের আসল নম্বর পেলেই এখানে বসাতে হবে।
# TODO: replace with owner's real bKash/Nagad number
# ---------------------------------------------------------------------------
BKASH_NUMBER = "01XXXXXXXXX"  # TODO: replace with owner's real bKash number
NAGAD_NUMBER = "01XXXXXXXXX"  # TODO: replace with owner's real Nagad number

APP_DIR = Path(__file__).resolve().parent
DEMO_AKIB = APP_DIR / "assets" / "demo_akib.wav"
DEMO_KIKI = APP_DIR / "assets" / "demo_kiki.wav"

# Demo voices: the GitHub push route is UTF-8 text-only, so the wav
# binaries live on the PUBLIC HF model repos instead. The app uses the
# local assets when present, otherwise downloads them from HF (verified
# by exact size + MD5) on first use.
DEMO_URLS = {
    "akib": "https://huggingface.co/demoqqq/banglatts-akib/resolve/main/demo_akib.wav",
    "kiki": "https://huggingface.co/demoqqq/banglatts-kiki-big-rerecord/resolve/main/demo_kiki.wav",
}
DEMO_MD5 = {"akib": "1bc6794a822f198f4a76c1b21c1875ef",
            "kiki": "34a960a8c67468c7d03423336b11a7b3"}
DEMO_SIZE = {"akib": 133164, "kiki": 143404}
DEMO_LOCAL = {"akib": DEMO_AKIB, "kiki": DEMO_KIKI}


def ensure_demo_wav(model_key: str, dest: Path | None = None) -> Path | None:
    """Local demo wav if present, else download it from HF (verified).

    Returns the wav path, or None if it cannot be obtained.
    """
    import hashlib
    import urllib.request

    dest = Path(dest) if dest is not None else DEMO_LOCAL[model_key]
    try:
        if dest.exists() and dest.stat().st_size == DEMO_SIZE[model_key]:
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(DEMO_URLS[model_key],
                                     headers={"User-Agent": "kiki-talk/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        dest.write_bytes(data)
        if (dest.stat().st_size != DEMO_SIZE[model_key]
                or hashlib.md5(data).hexdigest() != DEMO_MD5[model_key]):
            dest.unlink(missing_ok=True)
            return None
        return dest
    except Exception:
        return None

SAMPLE_SCRIPT = (
    "পররাষ্ট্র প্রতিমন্ত্রী শামা ওবায়েদ ইসলাম বলেছেন, নাগরিক হলেই পাসপোর্ট "
    "পাওয়া যাবে, এমন কোনো নিশ্চয়তা নেই। "
    "দণ্ডপ্রাপ্ত অপরাধী হলে সরকার পাসপোর্ট দিতে বাধ্য নয়। "
    "তিনি জানান, দুই হাজার চব্বিশ সালের জুলাই-আগস্টের ঘটনায় মানবতাবিরোধী "
    "অপরাধের দায়ে শেখ হাসিনা দোষী সাব্যস্ত হয়েছেন এবং তাকে মৃত্যুদণ্ড দেওয়া হয়েছে।"
)

AUDIO_EXTS = ["mp3", "wav", "m4a", "flac", "ogg", "aac"]

_BN = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


def bn(value) -> str:
    """ASCII digits -> Bengali digits for display."""
    return str(value).translate(_BN)


def fmt_mins(seconds: int) -> str:
    m, s = divmod(max(0, int(seconds)), 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{bn(h)} ঘণ্টা {bn(m)} মিনিট"
    if m > 0:
        return f"{bn(m)} মিনিট {bn(s)} সেকেন্ড"
    return f"{bn(s)} সেকেন্ড"


def client_info() -> tuple[str, str]:
    """Client IP + User-Agent from the request headers (best effort).

    Streamlit Cloud sits behind a proxy, so the real IP is the first
    entry of X-Forwarded-For. Outside a running app (tests, imports)
    this safely returns ("unknown", "").
    """
    ip, ua = "unknown", ""
    try:
        raw = dict(st.context.headers)
        low = {str(k).lower(): v for k, v in raw.items()}
        fwd = low.get("x-forwarded-for", "") or ""
        ip = (fwd.split(",")[0].strip() if fwd else "") or "unknown"
        ua = low.get("user-agent", "") or ""
    except Exception:
        pass
    return ip, ua


# ---------------------------------------------------------------------------
# Hidden admin access: logo taps -> PIN -> decoy sticker -> PIN -> panel.
# There is NO visible admin button and NO ?admin=1 route anywhere in
# the app. The logo/title ("🎙️ কিকি টক") is the tap target on every
# page; it renders as plain title text (tertiary button), not a button.
# ---------------------------------------------------------------------------

LOGO_TAPS_NEEDED = 5
STICKER_TAPS_NEEDED = 5
_PIN_KEYS = ("pin_input_pin1", "pin_input_pin2", "pin_setup_1",
             "pin_setup_2", "puzzle_answer")


def logo_tap_target(needs_setup: bool, taps: int) -> str | None:
    """Pure logic: after a logo tap, which admin stage opens once the
    5-tap threshold is reached (None = keep tapping)."""
    if taps >= LOGO_TAPS_NEEDED:
        return "pin_setup" if needs_setup else "pin1"
    return None


def sticker_tap_target(taps: int) -> str | None:
    """Pure logic: after a sticker tap, which stage opens at 5 taps."""
    if taps >= STICKER_TAPS_NEEDED:
        return "pin2"
    return None


def _reset_admin_flow(msg: str | None = None):
    """Leave the admin flow: clear counters, stage, auth flag and any
    typed PIN / puzzle text. `msg` is shown once on the normal screen."""
    st.session_state["logo_taps"] = 0
    st.session_state["sticker_taps"] = 0
    st.session_state["admin_stage"] = None
    st.session_state["admin_ok"] = False
    for key in _PIN_KEYS:
        st.session_state.pop(key, None)
    if msg:
        st.session_state["admin_msg"] = msg


def logo_tap_button():
    """The app title, tappable. 5 taps opens the hidden admin flow."""
    if st.button("🎙️ কিকি টক", key="logo_tap", type="tertiary"):
        taps = int(st.session_state.get("logo_taps", 0)) + 1
        st.session_state["logo_taps"] = taps
        target = logo_tap_target(store.admin_needs_pin_setup(), taps)
        if target:
            st.session_state["logo_taps"] = 0
            st.session_state["admin_stage"] = target
            st.rerun()


# ---------------------------------------------------------------------------
# Bottom navigation (mobile tab bar) + compact top header.
# The sidebar is gone as the navigation home: the 5 menu items live in
# a fixed bottom bar (icons + short Bengali labels, active tab orange),
# and the user name / mobile / trial pill live in a top header.
# The logo tap target (hidden admin entry) sits in the top header title
# on every logged-in page, and in the login hero on the auth page.
# ---------------------------------------------------------------------------

NAV_ITEMS = [
    ("nav_voice", "🎙️ ভয়েস", "🎙️ ভয়েস বানান"),
    ("nav_payment", "💳 পেমেন্ট", "💳 পেমেন্ট / রিনিউ"),
    ("nav_rules", "📏 নিয়ম", "📏 স্ক্রিপ্টের নিয়ম"),
    ("nav_password", "🔐 পাসওয়ার্ড", "🔐 পাসওয়ার্ড বদলান"),
    ("nav_logout", "🚪 লগ আউট", "🚪 লগ আউট"),
]
NAV_PAGES = [page for _, _, page in NAV_ITEMS]


def status_pill_html(state: dict) -> str:
    """The status pill HTML for the top header (trial/active/blocked/expired)."""
    if state["state"] == "trial":
        return (f'<span class="kt-pill">⏳ ট্রায়াল — আর '
                f'{fmt_mins(state["trial_left_s"])}</span>')
    if state["state"] == "active":
        return (f'<span class="kt-pill">✅ চালু — আর '
                f'{bn(state["sub_left_days"])} দিন</span>')
    if state["state"] == "blocked":
        return '<span class="kt-pill">🚫 অ্যাকাউন্ট বন্ধ আছে</span>'
    return '<span class="kt-pill">⌛ মেয়াদ শেষ — রিনিউ করুন</span>'


def render_top_header(user: dict, state: dict):
    """Compact top header: logo (hidden admin tap target) + user info."""
    logo_tap_button()
    st.markdown(
        f'<div class="kt-topbar">👋 <b>{user["name"]}</b> &nbsp; 📱 '
        f'{user["mobile"]} &nbsp; {status_pill_html(state)}</div>',
        unsafe_allow_html=True,
    )


def render_bottom_nav():
    """Fixed bottom tab bar. A tap sets menu_page (and reruns)."""
    current = st.session_state.get("menu_page", "🎙️ ভয়েস বানান")
    cols = st.columns(len(NAV_ITEMS), gap="small")
    for col, (key, label, page) in zip(cols, NAV_ITEMS):
        with col:
            btn_type = "primary" if current == page else "tertiary"
            if st.button(label, key=key, type=btn_type,
                         use_container_width=True):
                st.session_state["menu_page"] = page
                st.rerun()


# ---------------------------------------------------------------------------
# Design: warm orange/cream palette, Hind Siliguri, gradient buttons,
# cards, fade/slide-in animations. Mobile-first.
# ---------------------------------------------------------------------------
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Hind+Siliguri:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Hind Siliguri', sans-serif; }
.stApp { background: linear-gradient(180deg, #fff8ef 0%, #fff3e0 55%, #ffeedd 100%); }

/* --- gradient buttons (real designed buttons, not default grey) --- */
.stButton > button, .stDownloadButton > button {
    background: linear-gradient(135deg, #ff7a18 0%, #ff9a3d 60%, #ffb347 100%) !important;
    color: #fff !important;
    border: none !important;
    border-radius: 999px !important;
    padding: 0.65rem 1.4rem !important;
    font-weight: 700 !important;
    font-size: 1.02rem !important;
    box-shadow: 0 6px 18px rgba(255, 122, 24, 0.35) !important;
    transition: transform 0.15s ease, box-shadow 0.15s ease, filter 0.15s ease !important;
}
.stButton > button:hover, .stDownloadButton > button:hover {
    transform: translateY(-2px) scale(1.02);
    box-shadow: 0 10px 24px rgba(255, 122, 24, 0.45) !important;
    filter: brightness(1.05);
}
.stButton > button:active, .stDownloadButton > button:active { transform: scale(0.97); }
.stButton > button[kind="secondary"], .stDownloadButton > button[kind="secondary"] {
    background: #fff !important; color: #e56b00 !important;
    border: 2px solid #ffb347 !important;
    box-shadow: 0 4px 12px rgba(255, 154, 61, 0.18) !important;
}
/* secondary (outline) buttons */
div[data-testid="stButton"] > button[kind="secondary"] {
    background: #ffffff !important; color: #e56b00 !important;
    border: 2px solid #ffb347 !important;
}
/* logo tap target: a tertiary button that looks like plain title text,
   not a button — the hidden admin entry point (5 taps). */
.stButton > button[kind="tertiary"] {
    background: transparent !important; border: none !important;
    box-shadow: none !important; color: #7a3c00 !important;
    font-size: 1.5rem !important; font-weight: 700 !important;
    padding: 0.1rem 0.3rem !important; border-radius: 10px !important;
}
.stButton > button[kind="tertiary"]:hover {
    background: rgba(255, 122, 24, 0.10) !important;
    box-shadow: none !important; transform: none !important; filter: none !important;
}
.stButton > button[kind="tertiary"]:active { transform: scale(0.98) !important; }

/* --- cards --- */
.kt-card {
    background: #ffffff; border-radius: 18px; padding: 18px 20px;
    box-shadow: 0 8px 24px rgba(120, 60, 0, 0.10);
    border: 1px solid #ffe3c2; margin: 10px 0;
    animation: ktFadeUp 0.5s ease both;
}
.kt-hero {
    background: linear-gradient(135deg, #ff7a18, #ff9a3d 55%, #ffc46b);
    color: #fff; border-radius: 22px; padding: 26px 22px; text-align: center;
    box-shadow: 0 12px 30px rgba(255, 122, 24, 0.35); margin-bottom: 14px;
    animation: ktFadeUp 0.5s ease both;
}
.kt-hero h1 { color: #fff !important; margin: 0 0 6px 0; font-size: 2.1rem; }
.kt-hero p { color: #fff7ec !important; margin: 0; font-size: 1.05rem; }
.kt-price { font-size: 2.4rem; font-weight: 700; color: #e56b00; line-height: 1.1; }
.kt-price small { font-size: 1rem; color: #8a5a2b; font-weight: 500; }
.kt-pill {
    display: inline-block; background: #fff1de; color: #b25e00;
    border-radius: 999px; padding: 4px 14px; font-weight: 600; font-size: 0.9rem;
    border: 1px solid #ffd9a8;
}
.kt-demo { border: 1px solid #ffe3c2; border-radius: 16px; padding: 12px 14px; background: #fff; margin: 8px 0; animation: ktFadeUp 0.55s ease both; }
@keyframes ktFadeUp { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: translateY(0); } }
@keyframes ktPop { 0% { transform: scale(0.96); } 60% { transform: scale(1.02); } 100% { transform: scale(1); } }
.kt-pop { animation: ktPop 0.4s ease both; }

/* inputs */
.stTextInput input, .stTextArea textarea {
    border-radius: 14px !important; border: 1.5px solid #ffd9a8 !important;
    background: #fff !important;
}
.stTextInput input:focus, .stTextArea textarea:focus {
    border-color: #ff7a18 !important; box-shadow: 0 0 0 3px rgba(255, 122, 24, 0.15) !important;
}
/* radio cards look */
div[role="radiogroup"] label { font-weight: 600; }
h1, h2, h3 { color: #7a3c00 !important; }
hr { border-color: #ffe3c2; }

/* --- sidebar: removed as the navigation home (bottom bar replaces it) --- */
section[data-testid="stSidebar"] { display: none !important; }
div[data-testid="collapsedControl"] { display: none !important; }

/* --- compact top header (user + trial pill) --- */
.kt-topbar {
    display: flex; flex-wrap: wrap; align-items: center; gap: 4px 10px;
    background: #fff; border: 1px solid #ffe3c2; border-radius: 14px;
    padding: 8px 12px; margin: 2px 0 10px 0; font-size: 0.95rem;
    box-shadow: 0 4px 12px rgba(120, 60, 0, 0.07);
}

/* --- bottom navigation (mobile tab bar, fixed) --- */
/* The nav is the only horizontal block holding tertiary buttons, so
   :has() pins the fixed bar to exactly that block. Older browsers
   without :has() simply show the bar in-flow at the page bottom. */
div[data-testid="stHorizontalBlock"]:has(button[kind="tertiary"]) {
    position: fixed !important;
    bottom: 0; left: 0; right: 0;
    z-index: 1000000;
    background: #fffdf8;
    border-top: 1px solid #ffe3c2;
    box-shadow: 0 -6px 18px rgba(120, 60, 0, 0.12);
    padding: 6px 4px calc(6px + env(safe-area-inset-bottom, 0px)) !important;
    margin: 0 !important;
}
div[data-testid="stHorizontalBlock"]:has(button[kind="tertiary"]) div[data-testid="column"] {
    padding: 0 1px !important;
}
div[data-testid="stHorizontalBlock"]:has(button[kind="tertiary"]) button[kind="tertiary"] {
    background: transparent !important; border: none !important;
    box-shadow: none !important; color: #8a5a2b !important;
    font-size: 0.75rem !important; font-weight: 600 !important;
    padding: 6px 1px !important; border-radius: 12px !important;
    width: 100% !important; white-space: nowrap !important;
}
div[data-testid="stHorizontalBlock"]:has(button[kind="tertiary"]) button[kind="primary"] {
    font-size: 0.75rem !important; font-weight: 700 !important;
    padding: 6px 1px !important; border-radius: 12px !important;
    width: 100% !important; white-space: nowrap !important;
    box-shadow: 0 3px 10px rgba(255, 122, 24, 0.30) !important;
}
/* content must clear the fixed bar */
div[data-testid="stMainBlockContainer"] { padding-bottom: 120px !important; }
</style>
"""

# Decoy sticker screen CSS — injected ONLY while the sticker screen is
# shown, so primary buttons on other pages keep their normal look. The
# sticker is a primary button restyled as a bright, slightly rotated
# sticker card; the textbox submit / back buttons there are secondary.
STICKER_CSS = """
<style>
div[data-testid="stButton"] > button[kind="primary"] {
    transform: rotate(-2deg) !important;
    border-radius: 20px !important;
    border: 3px dashed #fff !important;
    background: linear-gradient(135deg, #ffe066 0%, #ff9f43 100%) !important;
    color: #7a3c00 !important;
    font-size: 1.4rem !important; font-weight: 700 !important;
    padding: 1.1rem 1.2rem !important;
    box-shadow: 0 8px 20px rgba(0,0,0,0.18) !important;
}
div[data-testid="stButton"] > button[kind="primary"]:hover {
    transform: rotate(-2deg) scale(1.02) !important;
    filter: brightness(1.03);
}
</style>
"""


def show_demo_voices():
    """Two tap-to-play demos, one per model (same samples as the plan)."""
    st.markdown("### 🎧 ভয়েস শুনে দেখুন")
    st.write("অ্যাকাউন্ট খোলার আগেই দুটি ভয়েসের নমুনা শুনতে পারেন — ট্যাপ করলেই বাজবে।")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown('<div class="kt-demo"><b>🎙️ মডেল ১ — আকিব</b></div>',
                    unsafe_allow_html=True)
        demo = ensure_demo_wav("akib")
        if demo is not None:
            st.audio(demo.read_bytes(), format="audio/wav")
        else:
            st.info("ডেমো শীঘ্রই আসছে।")
    with col2:
        st.markdown('<div class="kt-demo"><b>🎙️ মডেল ২ — কিকি বিগ রিরেকর্ড</b></div>',
                    unsafe_allow_html=True)
        demo = ensure_demo_wav("kiki")
        if demo is not None:
            st.audio(demo.read_bytes(), format="audio/wav")
        else:
            st.info("ডেমো শীঘ্রই আসছে।")


def pricing_card():
    lines = None
    try:
        pkgs = store.get_active_packages()
        if pkgs:
            lines = "<br>".join(
                f"📦 {p['name']} — ৳{bn(p['price'])} • {bn(p['days'])} দিন"
                for p in pkgs)
    except Exception:
        lines = None
    if lines is None:
        lines = "📦 ১ মাস — ৳৫০ • ৩০ দিন"
    st.markdown(
        '<div class="kt-card" style="text-align:center;">'
        '<div class="kt-price">৳৫০ <small>/ মাস</small></div>'
        f'<p style="margin:6px 0 0 0;">দুটি ভয়েসই আনলিমিটেড • সাবটাইটেলসহ (SRT / TXT / JSON)<br>{lines}<br>'
        'প্রথমে <b>১ ঘণ্টা ফ্রি ট্রায়াল</b> — আউটপুট শুনে তারপর পেমেন্ট।</p>'
        '</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Auth pages
# ---------------------------------------------------------------------------

def page_auth():
    logo_tap_button()
    st.markdown(
        '<div class="kt-hero">'
        '<p>বাংলা ভয়েসে আপনার কনটেন্ট — দুটি ভালো ভয়েস, এক লগইনে।</p></div>',
        unsafe_allow_html=True,
    )
    pricing_card()
    show_demo_voices()

    tab_login, tab_signup = st.tabs(["🔑 লগইন", "✍️ সাইন আপ (ফ্রি ট্রায়াল)"])
    with tab_login:
        mobile = st.text_input("মোবাইল নম্বর", placeholder="01XXXXXXXXX", key="login_mobile")
        password = st.text_input("পাসওয়ার্ড", type="password", key="login_pw")
        if st.button("🔓 লগইন করুন", type="primary", use_container_width=True):
            try:
                ip, ua = client_info()
                user = store.login(mobile, password, client_ip=ip, user_agent=ua)
                st.session_state["user_id"] = user["id"]
                st.session_state["menu_page"] = "🎙️ ভয়েস বানান"
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        st.caption("পাসওয়ার্ড ভুলে গেলে মালিকের সাথে যোগাযোগ করুন — অ্যাডমিন আপনার পাসওয়ার্ড বদলে দিতে পারবেন।")
    with tab_signup:
        name = st.text_input("আপনার নাম", placeholder="যেমন: রহিম উদ্দিন", key="su_name")
        mobile = st.text_input("মোবাইল নম্বর", placeholder="01XXXXXXXXX", key="su_mobile")
        password = st.text_input("পাসওয়ার্ড (কমপক্ষে ৬ অক্ষর)", type="password", key="su_pw")
        st.info("সাইন আপ করলেই **১ ঘণ্টার ফ্রি ট্রায়াল** চালু হবে — দুটি ভয়েসই ব্যবহার করে আউটপুটের মান দেখুন, তারপর পেমেন্টের সিদ্ধান্ত নিন।")
        if st.button("🎉 অ্যাকাউন্ট খুলুন — ফ্রি ট্রায়াল শুরু", type="primary", use_container_width=True):
            try:
                ip, ua = client_info()
                user = store.signup(name, mobile, password, client_ip=ip, user_agent=ua)
                st.session_state["user_id"] = user["id"]
                st.session_state["menu_page"] = "🎙️ ভয়েস বানান"
                if user.get("trial_granted", True):
                    st.success("অ্যাকাউন্ট খোলা হয়েছে! আপনার ১ ঘণ্টার ফ্রি ট্রায়াল চালু।")
                else:
                    st.warning("অ্যাকাউন্ট খোলা হয়েছে! তবে এই ডিভাইস/নেটওয়ার্ক থেকে "
                               "আগেই ফ্রি ট্রায়াল নেওয়া হয়েছে, তাই এই অ্যাকাউন্টে "
                               "ট্রায়াল নেই — পেমেন্ট করে প্যাকেজ নিলেই ব্যবহার করতে পারবেন।")
                time.sleep(1)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


# ---------------------------------------------------------------------------
# Generation page (3 options, model switch, script check first)
# ---------------------------------------------------------------------------

def show_segments(segments):
    for seg in segments:
        st.write(f"**{tools.srt_time(seg['start'])} → {tools.srt_time(seg['end'])}**  {seg['text']}")


def download_row(base: str, segments, duration: float, method: str, voice: str,
                 wav_bytes: bytes | None = None):
    srt_text = tools.to_srt(segments)
    json_text = tools.to_json(f"{base}.wav", duration, segments, method, voice=voice)
    cols = st.columns(4 if wav_bytes else 3)
    with cols[0]:
        st.download_button("⬇️ SRT ডাউনলোড", srt_text, file_name=f"{base}.srt",
                           mime="text/plain", use_container_width=True)
    with cols[1]:
        st.download_button("⬇️ JSON ডাউনলোড", json_text, file_name=f"{base}.json",
                           mime="application/json", use_container_width=True)
    with cols[2]:
        st.download_button("⬇️ শুধু লেখা (.txt)", " ".join(s["text"] for s in segments),
                           file_name=f"{base}.txt", mime="text/plain",
                           use_container_width=True)
    if wav_bytes:
        with cols[3]:
            st.download_button("⬇️ অডিও (.wav)", wav_bytes, file_name=f"{base}.wav",
                               mime="audio/wav", use_container_width=True)


def page_generate(user: dict):
    state = store.access_state(user)
    # ---- status card ----
    if state["state"] == "trial":
        st.markdown(
            f'<div class="kt-card">⏳ <b>ফ্রি ট্রায়াল চলছে</b> — আর '
            f'<b>{fmt_mins(state["trial_left_s"])}</b> বাকি। '
            f'ট্রায়াল শেষ হলে পেমেন্ট করে প্যাকেজ নিন।</div>',
            unsafe_allow_html=True,
        )
    elif state["state"] == "active":
        left = state["sub_left_days"]
        left_txt = f"{bn(left)} দিন" if left > 0 else f"{bn(state['sub_left_hours'])} ঘণ্টা"
        st.markdown(
            f'<div class="kt-card">✅ <b>প্যাকেজ চালু আছে</b> — আর '
            f'<b>{left_txt}</b> বাকি। মেয়াদ শেষের আগে রিনিউ করতে পারবেন।</div>',
            unsafe_allow_html=True,
        )
    remaining = store.daily_remaining(user)
    st.caption(f"আজকের ফেয়ার-ইউজ সীমা: আর {bn(f'{remaining:,}')} অক্ষর বাকি।")

    st.subheader("🎙️ ভয়েস বানান")
    model_key = st.radio(
        "ভয়েস বেছে নিন",
        options=["akib", "kiki"],
        format_func=lambda k: tts_engine.MODELS[k]["label"],
        horizontal=True,
    )
    voice_name = tts_engine.MODELS[model_key]["voice_name"]

    option = st.radio(
        "কীভাবে বানাবেন?",
        ["শুধু অডিও", "অডিও + সাবটাইটেল (SRT)", "অডিও + স্ক্রিপ্ট → সাবটাইটেল"],
        index=1,
    )

    # ---- option 3: audio + script -> subtitle ----
    if option.startswith("অডিও + স্ক্রিপ্ট"):
        uploaded = st.file_uploader("আগে বানানো অডিও ফাইল দিন", type=AUDIO_EXTS)
        text = st.text_area("স্ক্রিপ্ট (অডিওতে যা বলা হয়েছে, হুবহু তাই লিখুন)",
                            height=150, key="script_b",
                            help="দাঁড়ি (।) দিয়ে প্রতিটা বাক্য শেষ করুন।")
        if uploaded is not None:
            st.audio(uploaded)
        if st.button("📝 সাবটাইটেল বানাও", type="primary", use_container_width=True):
            if uploaded is None:
                st.warning("আগে অডিও ফাইল দিন।")
            elif not (text or "").strip():
                st.warning("আগে স্ক্রিপ্ট লিখুন।")
            else:
                checked = script_check.check_script(text)
                for f in checked["fixes"]:
                    st.info(f"✔️ {f}")
                for w in checked["warnings"]:
                    st.warning(f"⚠️ {w}")
                try:
                    with st.spinner("অডিও পড়া হচ্ছে…"):
                        ext = uploaded.name.rsplit(".", 1)[-1].lower()
                        audio, rate = tools.decode_audio(uploaded.getbuffer().tobytes(), ext)
                    sentences = tools.split_sentences(checked["fixed"])
                    segments, exact, note = tools.align_audio_script(audio, rate, sentences)
                    duration = len(audio) / rate
                    if exact:
                        st.success(f"শেষ! {bn(len(segments))}টি বাক্য • মোট সময় "
                                   f"{tools.format_duration(duration)} • {note}")
                    else:
                        st.warning(note)
                    st.subheader("সাবটাইটেল")
                    show_segments(segments)
                    base = uploaded.name.rsplit(".", 1)[0]
                    download_row(base, segments, duration, "audio+script", voice_name)
                except Exception as exc:  # noqa: BLE001
                    st.error(f"বানানো যায়নি: {exc}")
        return

    # ---- options 1 & 2: script -> audio (+ subtitle) ----
    if st.button("📰 নমুনা স্ক্রিপ্ট", use_container_width=False):
        st.session_state["script_main"] = SAMPLE_SCRIPT
    text = st.text_area("স্ক্রিপ্ট (বাংলায়, দাঁড়ি দিয়ে বাক্য শেষ করুন)",
                        value=st.session_state.get("script_main", SAMPLE_SCRIPT),
                        height=160, key="script_main")
    speed = st.selectbox("গতি", options=[0.75, 1.0, 1.25, 1.5], index=1,
                         format_func=lambda v: f"{v}x")

    col_check, col_gen = st.columns(2)
    with col_check:
        check_clicked = st.button("🔍 স্ক্রিপ্ট যাচাই করুন", use_container_width=True)
    with col_gen:
        gen_clicked = st.button("🎙️ ভয়েস বানাও", type="primary", use_container_width=True)

    if check_clicked:
        checked = script_check.check_script(text)
        st.session_state["checked_script"] = checked["fixed"]
        if checked["fixes"]:
            for f in checked["fixes"]:
                st.success(f"✔️ {f}")
        else:
            st.success("✔️ স্ক্রিপ্ট ঠিক আছে — কোনো বদল লাগেনি।")
        for w in checked["warnings"]:
            st.warning(f"⚠️ {w}")
        with st.expander("📝 যাচাই করা স্ক্রিপ্ট দেখুন"):
            st.write(checked["fixed"])

    if gen_clicked:
        raw = (text or "").strip()
        if not raw:
            st.warning("আগে স্ক্রিপ্ট লিখুন।")
            return
        checked = script_check.check_script(raw)
        st.session_state["checked_script"] = checked["fixed"]
        for f in checked["fixes"]:
            st.info(f"✔️ {f}")
        for w in checked["warnings"]:
            st.warning(f"⚠️ {w}")
        fixed = checked["fixed"]
        try:
            remaining_now = store.check_and_charge_chars(user["id"], len(fixed))
        except Exception as exc:
            st.error(str(exc))
            return
        try:
            with st.spinner("মডেল লোড হচ্ছে / অডিও বানানো হচ্ছে… (প্রথমবার মডেল নামতে একটু সময় লাগবে)"):
                t0 = time.time()
                tts_engine.ensure_model(model_key)
                if option.startswith("শুধু অডিও"):
                    samples, info = tts_engine.synthesize(fixed, model_key, speed=speed)
                    segments = None
                else:
                    samples, segments, info = tools.synthesize_aligned(fixed, model_key, speed=speed)
                total = time.time() - t0
            wav = tts_engine.samples_to_wav_bytes(samples)
            st.audio(wav, format="audio/wav", sample_rate=tts_engine.SAMPLE_RATE)
            st.success(f"শেষ! মোট সময় {tools.format_duration(info['duration_s'])} • "
                       f"বানাতে লেগেছে {total:.0f} সেকেন্ড • "
                       f"আজ আর {bn(f'{remaining_now:,}')} অক্ষর বাকি")
            if segments is not None:
                st.subheader("সাবটাইটেল")
                show_segments(segments)
                download_row("kiki_talk_audio", segments, info["duration_s"],
                             "script-to-audio", voice_name, wav_bytes=wav)
            else:
                st.download_button("⬇️ অডিও ডাউনলোড (.wav)", wav,
                                   file_name="kiki_talk_audio.wav",
                                   mime="audio/wav", use_container_width=True)
        except Exception as exc:  # noqa: BLE001
            st.error(f"বানানো যায়নি: {exc}")


# ---------------------------------------------------------------------------
# Payment / renew page
# ---------------------------------------------------------------------------

def page_payment(user: dict):
    state = store.access_state(user)
    st.subheader("💳 পেমেন্ট — প্যাকেজ নিন")
    pricing_card()
    if state["state"] == "active":
        st.success(f"আপনার প্যাকেজ চালু আছে — আর {bn(state['sub_left_days'])} দিন বাকি। "
                   "মেয়াদ শেষের আগেই রিনিউ করতে পারেন।")
    elif state["state"] == "trial":
        st.info(f"আপনার ফ্রি ট্রায়াল চলছে — আর {fmt_mins(state['trial_left_s'])} বাকি। "
                "ট্রায়াল শেষ হলে এখান থেকে পেমেন্ট করে প্যাকেজ নিন।")

    settings = store.get_settings()
    pkgs = store.get_active_packages()
    if not pkgs:
        st.error("এখন কোনো প্যাকেজ চালু নেই — মালিকের সাথে যোগাযোগ করুন।")
        return
    pkg_by_id = {p["id"]: p for p in pkgs}
    default_idx = 0
    for i, p in enumerate(pkgs):
        if p["days"] == 30:
            default_idx = i
            break

    st.markdown("### 📦 প্যাকেজ বেছে নিন")
    chosen_id = st.radio(
        "কোন প্যাকেজটি নিতে চান?",
        options=[p["id"] for p in pkgs],
        format_func=lambda pid: (
            f"{pkg_by_id[pid]['name']} — ৳{bn(pkg_by_id[pid]['price'])} • "
            f"{bn(pkg_by_id[pid]['days'])} দিন"),
        index=default_idx,
        key="pay_pkg",
    )
    chosen = pkg_by_id[chosen_id]

    st.markdown("### 📱 যেভাবে টাকা পাঠাবেন")
    for line in settings["instructions"].splitlines():
        if line.strip():
            st.write(line)
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**বিকাশ (Send Money)**")
        st.code(settings["bkash_number"])
    with col2:
        st.markdown("**নগদ (Send Money)**")
        st.code(settings["nagad_number"])
    if (settings["bkash_number"] in ("", store.PLACEHOLDER_NUMBER)
            and settings["nagad_number"] in ("", store.PLACEHOLDER_NUMBER)):
        st.caption("মালিক এখনো পেমেন্টের নম্বর বসাননি — নম্বর দেখা গেলে তারপর টাকা পাঠাবেন।")

    st.markdown("### 🧾 পেমেন্ট জমা দিন")
    txn_id = st.text_input("ট্রানজাকশন আইডি", placeholder="যেমন: 9HX7K2PQR1", key="pay_txn")
    amount = st.number_input("অ্যামাউন্ট (টাকা)", min_value=1, value=int(chosen["price"]), step=1)
    shot = st.file_uploader("পেমেন্টের স্ক্রিনশট (যদি থাকে)", type=["png", "jpg", "jpeg"])
    if st.button("📤 পেমেন্ট জমা দিন", type="primary", use_container_width=True):
        try:
            shot_bytes = shot.getbuffer().tobytes() if shot is not None else None
            ext = "png"
            if shot is not None:
                ext = shot.name.rsplit(".", 1)[-1].lower()
                if ext not in ("png", "jpg", "jpeg"):
                    ext = "png"
            pay = store.submit_payment(user, txn_id, int(amount), shot_bytes, ext,
                                       package_id=chosen["id"])
            st.success(f"পেমেন্ট জমা হয়েছে! মালিক যাচাই করে {chosen['name']} প্যাকেজটি "
                       f"({bn(chosen['days'])} দিন) চালু করে দেবেন। "
                       "লগইন করলেই মেয়াদ দেখতে পাবেন।")
            st.info(f"আপনার জমা নম্বর: {pay['id']}")
        except Exception as exc:
            st.error(str(exc))

    st.markdown("### 📋 আমার পেমেন্টগুলো")
    mine = store.list_user_payments(user["id"])
    if not mine:
        st.write("এখনো কোনো পেমেন্ট জমা দেননি।")
    for p in mine:
        status_bn = {"pending": "⏳ যাচাই চলছে", "approved": "✅ চালু হয়েছে",
                     "rejected": "❌ বাতিল হয়েছে"}.get(p["status"], p["status"])
        pkg_txt = f" • {p.get('package_name')}" if p.get("package_name") else ""
        st.write(f"**{p['submitted_at'][:16]}** • {bn(p['amount'])} টাকা{pkg_txt} • "
                 f"Txn: {p['txn_id'] or '—'} • {status_bn}")


# ---------------------------------------------------------------------------
# Rules page
# ---------------------------------------------------------------------------

def page_rules():
    st.subheader("📏 স্ক্রিপ্ট লেখার নিয়ম")
    st.write("মডেল কথা পড়ে ঠিক যেভাবে লেখা থাকে। নিয়ম মানলেই ভয়েস পরিষ্কার থাকবে — "
             "আর অ্যাপ নিজেই জেনারেটের আগে স্ক্রিপ্ট যাচাই করে ঠিক করে দেয়।")
    for title, rule in script_check.RULES_TABLE:
        st.markdown(f"**{title}** — {rule}")
    st.markdown("### 🤖 তৈরি প্রম্পট — স্ক্রিপ্ট আগে সাজিয়ে নিন")
    st.write("যেকোনো স্ক্রিপ্ট প্রথমে এই প্রম্পটের সঙ্গে ChatGPT বা Gemini-তে দিন, "
             "সাজানো লেখাটি ফিরে এলে সেটি কপি করে অ্যাপে বসান।")
    st.code(script_check.READY_PROMPT, language=None)


# ---------------------------------------------------------------------------
# Change password page
# ---------------------------------------------------------------------------

def page_change_password(user: dict):
    st.subheader("🔐 পাসওয়ার্ড বদলান")
    old = st.text_input("পুরনো পাসওয়ার্ড", type="password", key="cp_old")
    new = st.text_input("নতুন পাসওয়ার্ড (কমপক্ষে ৬ অক্ষর)", type="password", key="cp_new")
    new2 = st.text_input("নতুন পাসওয়ার্ড আবার", type="password", key="cp_new2")
    if st.button("💾 পাসওয়ার্ড বদলান", type="primary", use_container_width=True):
        if new != new2:
            st.error("নতুন পাসওয়ার্ড দুবার এক হয়নি।")
        else:
            try:
                store.change_password(user["id"], old, new)
                st.success("পাসওয়ার্ড বদলে গেছে।")
            except Exception as exc:
                st.error(str(exc))


# ---------------------------------------------------------------------------
# Admin panel (inside the app; password set on first visit, never hard-coded)
# ---------------------------------------------------------------------------

def page_admin():
    st.markdown(
        '<div class="kt-hero"><h1>🛡️ অ্যাডমিন প্যানেল</h1>'
        '<p>শুধু মালিকের জন্য — পেমেন্ট যাচাই ও অ্যাকাউন্ট নিয়ন্ত্রণ।</p></div>',
        unsafe_allow_html=True,
    )
    if st.button("← অ্যাপে ফিরে যান"):
        _reset_admin_flow()
        st.rerun()

    # ---- logged in as admin ----
    # (PIN setup / verification happens in page_admin_gate before this
    # function is called, so no password form lives here anymore.)
    users = store.list_users()
    pending = store.list_payments(status="pending")
    n_trial = sum(1 for u in users if store.access_state(u)["state"] == "trial")
    n_active = sum(1 for u in users if store.access_state(u)["state"] == "active")
    n_expired = sum(1 for u in users if store.access_state(u)["state"] == "expired")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("মোট ইউজার", bn(len(users)))
    c2.metric("ট্রায়ালে", bn(n_trial))
    c3.metric("পেইড চালু", bn(n_active))
    c4.metric("মেয়াদ শেষ", bn(n_expired))

    st.markdown("### 🧾 পেমেন্ট সাবমিশন (যাচাই বাকি)")
    if not pending:
        st.write("যাচাই করার মতো কোনো পেমেন্ট নেই।")
    for p in pending:
        pkg_days = int(p.get("package_days") or store.SUBSCRIPTION_DAYS)
        pkg_txt = f"প্যাকেজ: <b>{p.get('package_name') or 'মাসিক প্যাকেজ'}</b> • " if p.get("package_name") else ""
        with st.container():
            st.markdown(
                f'<div class="kt-card"><b>{p["name"]}</b> ({p["mobile"]})<br>'
                f'{pkg_txt}'
                f'ট্রানজাকশন আইডি: <b>{p["txn_id"] or "—"}</b> • '
                f'অ্যামাউন্ট: <b>{bn(p["amount"])} টাকা</b><br>'
                f'জমা: {p["submitted_at"]}</div>',
                unsafe_allow_html=True,
            )
            if p.get("screenshot_path"):
                try:
                    img = store.download_screenshot(p["screenshot_path"])
                    st.image(img, caption="পেমেন্টের স্ক্রিনশট", use_container_width=True)
                except Exception as exc:
                    st.warning(f"স্ক্রিনশট খোলা যায়নি: {exc}")
            b1, b2 = st.columns(2)
            with b1:
                if st.button(f"✅ অ্যাপ্রুভ — {bn(pkg_days)} দিন চালু করুন",
                             key=f"ap_{p['id']}", type="primary", use_container_width=True):
                    try:
                        store.decide_payment(p["id"], approve=True)
                        st.success(f"{p['name']}-এর অ্যাকাউন্ট {bn(pkg_days)} দিনের জন্য চালু হয়েছে।")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
            with b2:
                if st.button("❌ রিজেক্ট", key=f"rj_{p['id']}", use_container_width=True):
                    try:
                        store.decide_payment(p["id"], approve=False)
                        st.warning("পেমেন্টটি বাতিল করা হয়েছে।")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

    st.markdown("### 💳 পেমেন্ট সেটিংস")
    st.write("এখানে বদলালেই পেমেন্ট পেজে নতুন নম্বর ও নির্দেশনা দেখাবে — কোড বদলাতে হয় না।")
    settings = store.get_settings()
    with st.form("payment_settings"):
        bk = st.text_input("বিকাশ নম্বর (Send Money)", value=settings["bkash_number"])
        ng = st.text_input("নগদ নম্বর (Send Money)", value=settings["nagad_number"])
        ins = st.text_area("টাকা পাঠানোর নির্দেশনা (ইউজারকে দেখাবে)",
                           value=settings["instructions"], height=170)
        max_tr = st.number_input(
            "এক IP থেকে সর্বোচ্চ ফ্রি ট্রায়াল (টি অ্যাকাউন্ট)",
            min_value=0, max_value=10, value=int(settings["max_trials_per_ip"]),
            help="এই সংখ্যক ট্রায়ালের পর একই IP থেকে নতুন অ্যাকাউন্টে আর ফ্রি ট্রায়াল থাকবে না — অ্যাকাউন্ট খুলবে, তবে পেমেন্ট করে ব্যবহার করতে হবে।")
        tr_min = st.number_input(
            "ফ্রি ট্রায়ালের সময় (মিনিট)",
            min_value=0, max_value=1440, value=int(settings["trial_minutes"]),
            help="নতুন সাইন আপে এই সময়ের ফ্রি ট্রায়াল মিলবে। ০ লিখলে আর ফ্রি ট্রায়াল থাকবে না — নতুন অ্যাকাউন্টে সরাসরি পেমেন্ট লাগবে।")
        st.caption("⚠️ ট্রায়ালের সময় বদলালে শুধু নতুন সাইন আপে প্রযোজ্য হবে — "
                   "যারা ইতিমধ্যে ট্রায়ালে আছে, তাদের সময় বদলাবে না।")
        saved = st.form_submit_button("💾 সেটিংস সংরক্ষণ করুন", type="primary")
    if saved:
        try:
            store.save_settings({"bkash_number": bk.strip(),
                                 "nagad_number": ng.strip(),
                                 "instructions": ins,
                                 "max_trials_per_ip": int(max_tr),
                                 "trial_minutes": int(tr_min)})
            st.success("পেমেন্ট সেটিংস সংরক্ষণ হয়েছে।")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    st.markdown("### 📦 প্যাকেজ")
    st.write("নতুন প্যাকেজ যোগ করুন, দাম/মেয়াদ বদলান, বা বন্ধ করুন। বন্ধ করা প্যাকেজ "
             "আর কেনা যাবে না, তবে আগের পেমেন্টের হিসাব ঠিক থাকবে (মুছে ফেলা হয় না)।")
    for p in store.get_packages():
        is_on = p.get("active", True)
        with st.expander(f"{p['name']} — ৳{bn(p['price'])} • {bn(p['days'])} দিন "
                         f"{'(চালু)' if is_on else '(বন্ধ)'}"):
            new_name = st.text_input("নাম", value=p["name"], key=f"pk_name_{p['id']}")
            new_days = st.number_input("মেয়াদ (দিন)", min_value=1, max_value=365,
                                       value=int(p["days"]), key=f"pk_days_{p['id']}")
            new_price = st.number_input("দাম (টাকা)", min_value=1,
                                        value=int(p["price"]), key=f"pk_price_{p['id']}")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("💾 বদলান", key=f"pk_save_{p['id']}", use_container_width=True):
                    try:
                        store.update_package(p["id"], name=new_name,
                                             days=int(new_days), price=int(new_price))
                        st.success("প্যাকেজ বদলে গেছে।")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
            with c2:
                label = "⏸️ বন্ধ করুন" if is_on else "▶️ চালু করুন"
                if st.button(label, key=f"pk_tgl_{p['id']}", use_container_width=True):
                    store.set_package_active(p["id"], not is_on)
                    st.rerun()
    with st.form("add_package"):
        st.write("**নতুন প্যাকেজ যোগ করুন**")
        an = st.text_input("নাম (যেমন: ৩ দিন)")
        ad = st.number_input("মেয়াদ (দিন)", min_value=1, max_value=365, value=3)
        ap = st.number_input("দাম (টাকা)", min_value=1, value=10)
        if st.form_submit_button("➕ প্যাকেজ যোগ করুন", type="primary"):
            try:
                store.add_package(an, int(ad), int(ap))
                st.success("নতুন প্যাকেজ যোগ হয়েছে।")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    st.markdown("### 🔍 সন্দেহজনক অ্যাকাউন্ট (এক IP থেকে একাধিক অ্যাকাউন্ট)")
    st.caption("একই IP থেকে ২টির বেশি অ্যাকাউন্ট খোলা হলে এখানে দেখাবে — ট্রায়ালের "
               "অপব্যবহার ধরার জন্য। তবে শেয়ার করা ওয়াই-ফাইতেও এমন হতে পারে, তাই "
               "যাচাই না করে বন্ধ করবেন না। একই IP-র সব অ্যাকাউন্ট একসাথে দেখে সিদ্ধান্ত নিন।")
    groups = store.same_ip_groups()
    if not groups:
        st.write("সন্দেহজনক কোনো গ্রুপ নেই।")
    for g in groups:
        with st.expander(f"🌐 IP {g['ip']} — {bn(len(g['users']))}টি অ্যাকাউন্ট"):
            for u in g["users"]:
                stt = store.access_state(u)
                state_bn = {"trial": f"⏳ ট্রায়াল — আর {fmt_mins(stt['trial_left_s'])}",
                            "active": f"✅ চালু — আর {bn(stt['sub_left_days'])} দিন",
                            "expired": "⌛ মেয়াদ শেষ",
                            "blocked": "🚫 বন্ধ আছে"}.get(stt["state"], stt["state"])
                st.write(f"**{u['name']}** • {u['mobile']} • "
                         f"সাইন আপ: {u.get('created_at', '')[:16]} • {state_bn} • "
                         f"ট্রায়াল: {'হ্যাঁ' if u.get('trial_granted', True) else 'না'}")
                sc1, sc2 = st.columns(2)
                with sc1:
                    label = "🚫 বন্ধ করুন" if u.get("active", True) else "✅ চালু করুন"
                    if st.button(label, key=f"sus_blk_{u['id']}", use_container_width=True):
                        store.set_user_active(u["id"], not u.get("active", True))
                        st.rerun()
                with sc2:
                    if st.button("🎁 ট্রায়াল দিন (১ ঘণ্টা)", key=f"sus_tr_{u['id']}",
                                 use_container_width=True):
                        store.grant_trial(u["id"])
                        st.success(f"{u['name']}-কে ১ ঘণ্টার ট্রায়াল দেওয়া হয়েছে।")
                        st.rerun()
            gb1, gb2 = st.columns(2)
            with gb1:
                if st.button("🚫 পুরো গ্রুপ বন্ধ করুন", key=f"grp_blk_{g['ip']}",
                             use_container_width=True):
                    for u in g["users"]:
                        store.set_user_active(u["id"], False)
                    st.rerun()
            with gb2:
                if st.button("✅ পুরো গ্রুপ চালু করুন", key=f"grp_un_{g['ip']}",
                             use_container_width=True):
                    for u in g["users"]:
                        store.set_user_active(u["id"], True)
                    st.rerun()

    st.markdown("### 👥 ব্যবহারকারী ও মেয়াদ")
    for u in users:
        stt = store.access_state(u)
        state_bn = {"trial": f"⏳ ট্রায়াল — আর {fmt_mins(stt['trial_left_s'])}",
                    "active": f"✅ চালু — আর {bn(stt['sub_left_days'])} দিন",
                    "expired": "⌛ মেয়াদ শেষ",
                    "blocked": "🚫 বন্ধ আছে"}.get(stt["state"], stt["state"])
        with st.expander(f"{u['name']} • {u['mobile']} • {state_bn}"):
            st.write(f"সাইন আপ: {u.get('created_at', '')[:16]}")
            st.write(f"ট্রায়াল শেষ: {u.get('trial_ends_at', '')[:16]}")
            st.write(f"মেয়াদ শেষ: {(u.get('expires_at') or '—')[:16]}")
            used_chars = bn(f"{int(u.get('daily_chars_used', 0)):,}")
            st.write(f"আজকের ব্যবহার: {used_chars} অক্ষর")
            new_pw = st.text_input("নতুন পাসওয়ার্ড দিন (ভুলে গেলে)", type="password",
                                   key=f"rpw_{u['id']}")
            cb1, cb2 = st.columns(2)
            with cb1:
                if st.button("🔑 পাসওয়ার্ড বদলে দিন", key=f"rpw_btn_{u['id']}",
                             use_container_width=True):
                    try:
                        store.admin_set_user_password(u["id"], new_pw)
                        st.success(f"পাসওয়ার্ড বদলে গেছে — ইউজারকে জানিয়ে দিন: {new_pw}")
                    except Exception as exc:
                        st.error(str(exc))
            with cb2:
                label = "🚫 অ্যাকাউন্ট বন্ধ করুন" if u.get("active", True) else "✅ অ্যাকাউন্ট চালু করুন"
                if st.button(label, key=f"blk_{u['id']}", use_container_width=True):
                    store.set_user_active(u["id"], not u.get("active", True))
                    st.rerun()


# ---------------------------------------------------------------------------
# Hidden admin gate: pin_setup -> pin1 -> sticker -> pin2 -> open.
# The admin panel itself (page_admin) only renders at stage "open".
# ---------------------------------------------------------------------------

def _pin_setup_screen():
    """First-run (or legacy-credential) PIN setup: choose a 4-digit PIN."""
    st.markdown(
        '<div class="kt-card"><h3>🔐 অ্যাডমিন পিন সেট করুন</h3>'
        '<p>প্রথমবার ৪ সংখ্যার একটি পিন বেছে নিন — এই পিন দিয়েই পরে '
        'অ্যাডমিন প্যানেল খুলবে। পিনটি মনে রাখবেন, কাউকে জানাবেন না।</p></div>',
        unsafe_allow_html=True,
    )
    pin1 = st.text_input("৪ সংখ্যার পিন", type="password", max_chars=4,
                         key="pin_setup_1")
    pin2 = st.text_input("পিনটি আবার লিখুন", type="password", max_chars=4,
                         key="pin_setup_2")
    if st.button("🔒 পিন সেট করুন", type="primary", use_container_width=True):
        if not store.valid_pin(pin1) or not store.valid_pin(pin2):
            st.error("পিন ঠিক ৪ সংখ্যার হতে হবে (শুধু সংখ্যা)।")
        elif store.normalize_pin(pin1) != store.normalize_pin(pin2):
            st.error("দুবার এক হয়নি — আবার লিখুন।")
        else:
            try:
                store.admin_set_pin(pin1)
                st.session_state["admin_stage"] = "open"
                st.session_state["admin_ok"] = True
                for key in ("pin_setup_1", "pin_setup_2"):
                    st.session_state.pop(key, None)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    if st.button("← ফিরে যান", use_container_width=True):
        _reset_admin_flow()
        st.rerun()


def _pin_screen(stage: str):
    """PIN entry (stage 'pin1' or 'pin2'). Correct PIN moves forward;
    a wrong PIN clears everything and returns to the normal app."""
    st.markdown(
        '<div class="kt-card"><h3>🔢 পিন দিন</h3>'
        '<p>অ্যাডমিন পিনটি লিখুন।</p></div>',
        unsafe_allow_html=True,
    )
    pin = st.text_input("৪ সংখ্যার পিন", type="password", max_chars=4,
                        key=f"pin_input_{stage}")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔓 যাচাই করুন", type="primary",
                     key=f"pin_go_{stage}", use_container_width=True):
            if store.admin_check_pin(pin):
                st.session_state.pop(f"pin_input_{stage}", None)
                if stage == "pin1":
                    st.session_state["admin_stage"] = "sticker"
                    st.session_state["sticker_taps"] = 0
                else:  # pin2
                    st.session_state["admin_stage"] = "open"
                    st.session_state["admin_ok"] = True
                st.rerun()
            else:
                _reset_admin_flow("❌ পিন ভুল হয়েছে।")
                st.rerun()
    with col2:
        if st.button("← ফিরে যান", key=f"pin_back_{stage}",
                     use_container_width=True):
            _reset_admin_flow()
            st.rerun()


def _sticker_screen():
    """Decoy: a sticker that never opens from the textbox. Any answer
    submitted in the textbox fails and stays here — no hint is shown
    about tapping. Tapping the sticker itself 5 times opens the second
    PIN pad."""
    st.markdown(STICKER_CSS, unsafe_allow_html=True)
    if st.button("🧩 Solve the puzzle", key="sticker_tap", type="primary",
                 use_container_width=True):
        taps = int(st.session_state.get("sticker_taps", 0)) + 1
        st.session_state["sticker_taps"] = taps
        if sticker_tap_target(taps) == "pin2":
            st.session_state["sticker_taps"] = 0
            st.session_state.pop("puzzle_answer", None)
            st.session_state["admin_stage"] = "pin2"
            st.rerun()
    st.write("নিচের বাক্সে উত্তর লিখুন — সঠিক উত্তর দিলেই খুলবে।")
    st.text_input("উত্তর", key="puzzle_answer", placeholder="উত্তর লিখুন")
    if st.button("✅ জমা দিন", key="puzzle_submit", use_container_width=True):
        ans = st.session_state.get("puzzle_answer", "")
        if not (ans or "").strip():
            st.warning("আগে উত্তর লিখুন।")
        else:
            st.error("❌ ভুল উত্তর! আবার চেষ্টা করুন।")
    if st.button("← ফিরে যান", key="sticker_back", use_container_width=True):
        _reset_admin_flow()
        st.rerun()


def page_admin_gate():
    """Hidden admin flow state machine."""
    stage = st.session_state.get("admin_stage")
    if stage == "open":
        page_admin()
    elif stage == "pin_setup":
        _pin_setup_screen()
    elif stage == "pin1":
        _pin_screen("pin1")
    elif stage == "sticker":
        _sticker_screen()
    elif stage == "pin2":
        _pin_screen("pin2")
    else:
        _reset_admin_flow()
        st.rerun()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    st.set_page_config(page_title="কিকি টক — বাংলা ভয়েস", page_icon="🎙️",
                       layout="centered", initial_sidebar_state="collapsed")
    st.markdown(CSS, unsafe_allow_html=True)

    # Hidden admin flow (logo taps -> PIN -> sticker -> PIN). There is no
    # visible admin button and no ?admin=1 route anywhere in the app.
    if st.session_state.get("admin_stage") in (
            "pin_setup", "pin1", "sticker", "pin2", "open"):
        page_admin_gate()
        return

    # One-shot message from the admin flow (e.g. wrong PIN), shown once
    # on the normal screen, then cleared.
    _msg = st.session_state.pop("admin_msg", None)
    if _msg:
        st.error(_msg)

    user_id = st.session_state.get("user_id")
    user = None
    if user_id:
        try:
            user = store.get_user_by_id(user_id)
        except Exception as exc:
            st.error(f"ডেটা খোলা যায়নি: {exc}")
            st.stop()
        if user is None:
            st.session_state.pop("user_id", None)

    if user is None:
        page_auth()
        return

    # ---- logged-in shell: top header + page + fixed bottom nav ----
    state = store.access_state(user)
    render_top_header(user, state)

    if not state["has_access"]:
        st.warning("আপনার ট্রায়াল / প্যাকেজের মেয়াদ শেষ হয়েছে — ভয়েস বানাতে "
                   "হলে পেমেন্ট করে প্যাকেজ নিন।")
        page_payment(user)
        return

    page = st.session_state.get("menu_page", "🎙️ ভয়েস বানান")
    if page == "🚪 লগ আউট":
        st.session_state.pop("user_id", None)
        st.session_state.pop("menu_page", None)
        st.rerun()

    if page == "🎙️ ভয়েস বানান":
        page_generate(user)
    elif page == "💳 পেমেন্ট / রিনিউ":
        page_payment(user)
    elif page == "📏 স্ক্রিপ্টের নিয়ম":
        page_rules()
    elif page == "🔐 পাসওয়ার্ড বদলান":
        page_change_password(user)

    render_bottom_nav()


if __name__ == "__main__":
    main()
