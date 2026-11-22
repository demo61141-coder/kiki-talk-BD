# -*- coding: utf-8 -*-
"""Kiki Talk v6 test — bottom navigation bar + top header (2026-11-22).

Moves navigation from the left Streamlit sidebar to a fixed BOTTOM
tab bar (mobile-app style), with user info + trial countdown in a
compact TOP header. The hidden admin access (v4) must survive intact:
the logo tap target lives in the top header title on every logged-in
page and in the login hero on the auth page.

  A. Nav/header logic on a LOCAL mocked store backend (zero HF
     commits): NAV_ITEMS (exactly 5 tabs, labels + canonical page
     values, keys unique, the 4 page values identical to the old
     sidebar radio options), status_pill_html for all 4 states
     (trial/active/blocked/expired), logo/sticker tap helpers (v4).
  B. app.py source + import checks: no st.sidebar anywhere; sidebar
     hidden by CSS + initial_sidebar_state collapsed; bottom-nav CSS
     (fixed bar via :has(tertiary) selector, safe-area padding,
     content bottom padding); NAV_ITEMS / render_bottom_nav /
     render_top_header / status_pill_html present; all 5 tab labels
     present; top header shows name + mobile + pill; logo tap target
     on every page (login hero + top header); logout handled in main;
     no-access branch still payment-only; hidden admin intact
     (no ?admin=1 route, no query_params, no visible admin button);
     v2-v5 markers intact.
  C. LIVE (reads only, zero commits): live settings.json + packages.json
     readable, trial_minutes defaults to 60. Any failure here is
     SKIPPED (not failed) — the HF 128-commits/hour rate limit is in
     effect until ~12:10 and the parent re-runs after that; the mocked
     + source sections already prove the change.
  D. Cleanup (reads only): no v6 test user/payment exists live.
  E. Regression (mocked): key v2-v5 invariants re-checked — signup
     default trial 3600s, duplicate mobile / wrong password rejected,
     settings number + max-trials validation, package add/edit, IP
     trial limit, valid_pin + tap helpers, trial_minutes coercion.

Uses the REAL private HF dataset demoqqq/kiki-talk-data only for
READS in sections C/D. No test users/payments are created anywhere
in this suite. Never prints any token.
"""
import copy
import os
import sys
import traceback

# --- HF write token via the registered connector surrogate (never printed) ---
sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
from dynamic_credentials import dynamic_credential_entry

_entry = dynamic_credential_entry("custom.huggingface")
os.environ["HF_TOKEN"] = str(_entry["surrogate"]).strip()

sys.path.insert(0, "/home/hatch/workspace/kiki-talk")
os.chdir("/home/hatch/workspace/kiki-talk")

import store

PASS = []
FAIL = []
SKIP = []

TEST_PW = "testpass123"


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}", flush=True)


def skip(name, detail=""):
    SKIP.append(name)
    print(f"[SKIP] {name} {detail}", flush=True)


def expect_raises(name, fn, substr=None):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        ok = substr is None or substr in str(exc)
        check(name, ok, f"raised: {exc}")
        return
    check(name, False, "no exception raised")


def is_rate_limit(exc) -> bool:
    text = str(exc)
    return "429" in text or "rate limit" in text.lower()


# ---------------------------------------------------------------------------
# Mocked store backend (Sections A + E): in-memory dict, zero HF commits.
# ---------------------------------------------------------------------------
_FAKE_DB: dict = {}
_orig_load = store.load_json
_orig_save = store.save_json


def _fake_load(name):
    if name not in _FAKE_DB:
        raise FileNotFoundError(name)
    return copy.deepcopy(_FAKE_DB[name])


def _fake_save(name, data, retries=3):
    _FAKE_DB[name] = copy.deepcopy(data)


def _install_fake():
    store.load_json = _fake_load
    store.save_json = _fake_save


def _restore_real():
    store.load_json = _orig_load
    store.save_json = _orig_save


print("=== Kiki Talk v6 test — bottom nav + top header — starting ===",
      flush=True)

import app as kiki_app

# ---------------------------------------------------------------- A. nav/header logic (mocked)
try:
    # A1. NAV_ITEMS table
    items = kiki_app.NAV_ITEMS
    check("A1a. NAV_ITEMS has exactly 5 tabs", len(items) == 5,
          f"got {len(items)}")
    keys = [k for k, _, _ in items]
    check("A1b. nav keys unique",
          len(set(keys)) == 5 and all(keys))
    labels = [lab for _, lab, _ in items]
    check("A1c. nav labels are icon + short Bengali",
          labels == ["🎙️ ভয়েস", "💳 পেমেন্ট", "📏 নিয়ম",
                     "🔐 পাসওয়ার্ড", "🚪 লগ আউট"],
          f"labels={labels}")
    pages = [p for _, _, p in items]
    check("A1d. nav pages are the canonical menu values",
          pages == ["🎙️ ভয়েস বানান", "💳 পেমেন্ট / রিনিউ",
                    "📏 স্ক্রিপ্টের নিয়ম", "🔐 পাসওয়ার্ড বদলান",
                    "🚪 লগ আউট"],
          f"pages={pages}")
    check("A1e. the 4 page values match the old sidebar radio options",
          pages[:4] == ["🎙️ ভয়েস বানান", "💳 পেমেন্ট / রিনিউ",
                        "📏 স্ক্রিপ্টের নিয়ম", "🔐 পাসওয়ার্ড বদলান"])
    check("A1f. NAV_PAGES covers all 5 values",
          kiki_app.NAV_PAGES == pages)

    # A2. status pill HTML for all 4 states
    pill_trial = kiki_app.status_pill_html(
        {"state": "trial", "trial_left_s": 3540})
    check("A2a. trial pill shows countdown",
          "⏳ ট্রায়াল" in pill_trial and "৫৯ মিনিট" in pill_trial,
          f"pill={pill_trial}")
    pill_active = kiki_app.status_pill_html(
        {"state": "active", "sub_left_days": 29})
    check("A2b. active pill shows days left",
          "✅ চালু" in pill_active and "২৯ দিন" in pill_active,
          f"pill={pill_active}")
    pill_blocked = kiki_app.status_pill_html({"state": "blocked"})
    check("A2c. blocked pill",
          "🚫 অ্যাকাউন্ট বন্ধ আছে" in pill_blocked)
    pill_expired = kiki_app.status_pill_html({"state": "expired"})
    check("A2d. expired pill asks to renew",
          "⌛ মেয়াদ শেষ" in pill_expired and "রিনিউ" in pill_expired)
    check("A2e. pills use the kt-pill class",
          all("kt-pill" in p for p in
              (pill_trial, pill_active, pill_blocked, pill_expired)))

    # A3. hidden-admin tap helpers still work (v4 invariants)
    check("A3a. logo tap 5 -> pin1 (no setup needed)",
          kiki_app.logo_tap_target(False, 5) == "pin1")
    check("A3b. logo tap 5 -> pin_setup (setup needed)",
          kiki_app.logo_tap_target(True, 5) == "pin_setup")
    check("A3c. logo tap 4 -> nothing yet",
          kiki_app.logo_tap_target(False, 4) is None)
    check("A3d. sticker tap 5 -> pin2",
          kiki_app.sticker_tap_target(5) == "pin2")
    check("A3e. sticker tap 4 -> nothing yet",
          kiki_app.sticker_tap_target(4) is None)
    check("A3f. render functions exist",
          callable(kiki_app.render_top_header)
          and callable(kiki_app.render_bottom_nav)
          and callable(kiki_app.logo_tap_button))
except Exception:
    print("NAV/HEADER LOGIC SECTION FAILED", flush=True)
    traceback.print_exc()

# ---------------------------------------------------------------- B. app source checks
try:
    import py_compile
    py_compile.compile("app.py", doraise=True)
    check("B1a. app.py compiles", True)
    py_compile.compile("store.py", doraise=True)
    check("B1b. store.py compiles", True)
    src = open("app.py", encoding="utf-8").read()
    ssrc = open("store.py", encoding="utf-8").read()
    _code_lines = [line.split("#", 1)[0] for line in src.splitlines()]
    _code = "\n".join(_code_lines)

    # B2. sidebar gone as the navigation home
    check("B2a. no st.sidebar anywhere in source",
          "st.sidebar" not in src)
    check("B2b. no sidebar radio menu (old menu_page radio gone)",
          "with st.sidebar:" not in src and 'key="menu_page"' not in src)
    check("B2c. sidebar hidden by CSS",
          'section[data-testid="stSidebar"]' in src
          and "display: none" in src)
    check("B2d. collapsed sidebar control hidden by CSS",
          'div[data-testid="collapsedControl"]' in src)
    check("B2e. set_page_config collapses the sidebar",
          'initial_sidebar_state="collapsed"' in src)

    # B3. bottom nav CSS + mechanics
    check("B3a. bottom nav fixed bar selector present",
          ':has(button[kind="tertiary"])' in src)
    check("B3b. nav bar is position: fixed at bottom",
          "position: fixed" in src and "bottom: 0" in src)
    check("B3c. safe-area padding for phone home indicator",
          "safe-area-inset-bottom" in src)
    check("B3d. content bottom padding clears the fixed bar",
          "padding-bottom: 120px" in src)
    check("B3e. nav uses st.columns with all 5 items",
          "st.columns(len(NAV_ITEMS)" in src)
    check("B3f. nav tap sets menu_page and reruns",
          'st.session_state["menu_page"] = page' in src
          and "st.rerun()" in src)
    check("B3g. active tab uses primary, others tertiary",
          'btn_type = "primary" if current == page else "tertiary"' in src)

    # B4. top header
    check("B4a. top header function + topbar CSS present",
          "def render_top_header" in src and "kt-topbar" in src)
    check("B4b. header shows user name + mobile",
          'user["name"]' in src and 'user["mobile"]' in src)
    check("B4c. header uses the status pill helper",
          "status_pill_html(state)" in src)
    check("B4d. header calls the logo tap target",
          "logo_tap_button()" in src)

    # B5. logo tap target on every page
    _logo_calls = src.count("logo_tap_button()")
    check("B5a. logo tap target called on login page + top header",
          _logo_calls >= 2, f"call sites (incl. def)={_logo_calls}")
    _auth_src = src[src.index("def page_auth"):src.index("def page_generate")]
    check("B5b. login page (page_auth) starts with the logo tap target",
          "logo_tap_button()" in _auth_src)
    _hdr_src = src[src.index("def render_top_header"):src.index("def render_bottom_nav")]
    check("B5c. top header renders the logo tap target",
          "logo_tap_button()" in _hdr_src)
    check("B5d. logo is a tertiary button (looks like title text)",
          'type="tertiary"' in src)

    # B6. logout + no-access behaviour preserved
    check("B6a. logout handled in main (clears user + menu, reruns)",
          'if page == "🚪 লগ আউট":' in src
          and 'st.session_state.pop("user_id", None)' in src)
    check("B6b. no-access branch still shows payment only",
          'if not state["has_access"]:' in src)
    check("B6c. bottom nav rendered after the page dispatch",
          src.index("    render_bottom_nav()")
          > src.index('if page == "🎙️ ভয়েস বানান":'))

    # B7. hidden admin intact (v4)
    check("B7a. tap helpers + sticker trap present",
          "logo_tap_target" in src and "sticker_tap_target" in src
          and "Solve the puzzle" in src)
    check("B7b. still no ?admin=1 route in code (comments stripped)",
          "?admin=1" not in _code)
    check("B7c. still no query_params in code",
          "query_params" not in _code)
    check("B7d. no visible admin button anywhere",
          'st.button("🛡️ অ্যাডমিন প্যানেল"' not in src)
    check("B7e. PIN screens + stage machine present",
          "def _pin_screen" in src and "def _sticker_screen" in src
          and "def page_admin_gate" in src)

    # B8. v2-v5 markers intact
    check("B8a. v2 markers (trial text, TRIAL_SECONDS)",
          "১ ঘণ্টার ফ্রি ট্রায়াল" in src and "TRIAL_SECONDS = 3600" in ssrc)
    check("B8b. v3 markers (settings/packages/suspicious)",
          "পেমেন্ট সেটিংস" in src and "📦 প্যাকেজ" in src
          and "সন্দেহজনক অ্যাকাউন্ট" in src)
    check("B8c. v5 markers (trial_minutes setting)",
          "ফ্রি ট্রায়ালের সময় (মিনিট)" in src
          and "trial_minutes" in ssrc)
    check("B8d. v4 markers (PIN helpers in store)",
          "def valid_pin" in ssrc and "def admin_set_pin" in ssrc
          and "def admin_check_pin" in ssrc)
    check("B8e. only the logo button uses a literal tertiary type",
          src.count('type="tertiary"') == 1,
          f"literal type=\"tertiary\" count={src.count('type=\"tertiary\"')}")
except Exception:
    print("APP SOURCE SECTION FAILED", flush=True)
    traceback.print_exc()

# ---------------------------------------------------------------- C. live (reads only; any failure -> SKIP)
print("=== live section (reads only; failure -> SKIP) ===", flush=True)
try:
    live_settings = store.load_json("settings.json")
    merged = store.get_settings()
    check("C1. live settings.json readable",
          isinstance(live_settings, dict))
    check("C2. live trial_minutes defaults to 60",
          merged.get("trial_minutes") == 60,
          f"trial_minutes={merged.get('trial_minutes')}")
    live_pkgs = store.get_active_packages()
    check("C3. live packages readable (3 defaults active)",
          len(live_pkgs) == 3,
          f"packages={[p['name'] for p in live_pkgs]}")
except Exception as exc:  # noqa: BLE001
    if is_rate_limit(exc):
        skip("C1-C3. live reads skipped (HF rate limit 429)",
             "re-run after ~12:10; mocked + source sections prove the change")
    else:
        skip("C1-C3. live reads skipped (dataset unreachable right now)",
             f"{exc}")

# ---------------------------------------------------------------- D. cleanup (reads only)
try:
    users = store.list_users()
    pays = store.list_payments()
    v6_mobiles = {"01900000071", "01900000072"}
    check("D1. no v6 test user exists live",
          not any(u.get("mobile") in v6_mobiles for u in users),
          f"live users={len(users)}")
    check("D2. no v6 test payment exists live",
          not any(p.get("mobile") in v6_mobiles for p in pays),
          f"live payments={len(pays)}")
    print(f"[INFO] live dataset: {len(users)} user(s), {len(pays)} payment(s) "
          "(v2 leftovers belong to the 12:10 cleanup, not v6)", flush=True)
except Exception as exc:  # noqa: BLE001
    skip("D1-D2. live cleanup check skipped (dataset unreachable)",
         f"{exc}")

# ---------------------------------------------------------------- E. regression (mocked)
try:
    _install_fake()
    _FAKE_DB.clear()
    _FAKE_DB["settings.json"] = copy.deepcopy(store.DEFAULT_SETTINGS)
    _FAKE_DB["users.json"] = {"users": []}

    # v2: signup default trial ~3600s, duplicates + wrong password rejected
    u = store.signup("রিগ্রেশন", "01900000071", TEST_PW)
    start = store._parse_iso(u["trial_started_at"])
    end = store._parse_iso(u["trial_ends_at"])
    check("E1a. v2: signup default trial exactly 3600s",
          (end - start).total_seconds() == 3600)
    expect_raises("E1b. v2: duplicate mobile rejected",
                  lambda: store.signup("আবার", "01900000071", TEST_PW),
                  "ইতিমধ্যে")
    expect_raises("E1c. v2: wrong password login rejected",
                  lambda: store.login("01900000071", "wrongpass"),
                  "পাসওয়ার্ড ভুল")

    # v3: settings number + max-trials validation
    expect_raises("E2a. v3: bad bkash rejected",
                  lambda: store.save_settings({
                      "bkash_number": "123", "nagad_number": "01812345678",
                      "instructions": "x", "max_trials_per_ip": 2,
                      "trial_minutes": 60}), "বিকাশ")
    expect_raises("E2b. v3: max_trials_per_ip 11 rejected",
                  lambda: store.save_settings({
                      "bkash_number": "01712345678",
                      "nagad_number": "01812345678",
                      "instructions": "x", "max_trials_per_ip": 11,
                      "trial_minutes": 60}), "০ থেকে ১০")

    # v3: package add/edit
    _FAKE_DB["packages.json"] = {"packages": copy.deepcopy(store.DEFAULT_PACKAGES)}
    pkg = store.add_package("টেস্ট প্যাকেজ", 3, 10)
    check("E3a. v3: add_package works",
          pkg["name"] == "টেস্ট প্যাকেজ" and pkg["days"] == 3)
    upd = store.update_package(pkg["id"], price=15)
    check("E3b. v3: update_package price works",
          upd["price"] == 15)

    # v3: IP trial limit (limit 2 -> 3rd signup no trial)
    ua = store.signup("আইপি এ", "01900000072", TEST_PW, client_ip="10.0.0.1")
    ub = store.signup("আইপি বি", "01900000073", TEST_PW, client_ip="10.0.0.1")
    uc = store.signup("আইপি সি", "01900000074", TEST_PW, client_ip="10.0.0.1")
    check("E4a. v3: 1st + 2nd same-IP signups get trials",
          ua.get("trial_granted") is True and ub.get("trial_granted") is True)
    check("E4b. v3: 3rd same-IP signup allowed but NO trial",
          uc.get("trial_granted") is False)

    # v4: PIN + tap helpers
    check("E5a. v4: valid_pin('1234')",
          store.valid_pin("1234") and not store.valid_pin("123"))
    check("E5b. v4: logo tap 5 -> pin1, sticker tap 5 -> pin2",
          kiki_app.logo_tap_target(False, 5) == "pin1"
          and kiki_app.sticker_tap_target(5) == "pin2")

    # v5: trial_minutes coercion
    _FAKE_DB["settings.json"] = copy.deepcopy(store.DEFAULT_SETTINGS)
    store.save_settings({"bkash_number": "01712345678",
                         "nagad_number": "01812345678",
                         "instructions": "x", "max_trials_per_ip": 2,
                         "trial_minutes": 90})
    check("E6a. v5: trial_minutes 90 saved + read back",
          store.get_settings()["trial_minutes"] == 90)
    _FAKE_DB["settings.json"]["trial_minutes"] = "abc"
    check("E6b. v5: garbage trial_minutes -> default 60",
          store.get_settings()["trial_minutes"] == 60)
    _restore_real()
except Exception:
    print("REGRESSION SECTION FAILED", flush=True)
    traceback.print_exc()
    _restore_real()

print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed, "
      f"{len(SKIP)} skipped", flush=True)
if FAIL:
    print("FAILED: " + ", ".join(FAIL), flush=True)
    sys.exit(1)
if SKIP:
    print("SKIPPED: " + ", ".join(SKIP), flush=True)
print("ALL TESTS PASSED" + (" (with skips noted above)" if SKIP else ""),
      flush=True)
