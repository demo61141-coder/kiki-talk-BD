# -*- coding: utf-8 -*-
"""Kiki Talk v7 test — admin-editable character limits (2026-11-22).

Adds two settings in settings.json (same merge/coerce pattern as
trial_minutes in v5):
  - trial_char_limit (default 0 = no cap): total characters a TRIAL
    user may generate during their trial. Paid users are never
    affected. Tracked as trial_chars_used on the user record.
  - daily_char_limit (default 20000): the daily fair-use limit for
    EVERYONE, replacing the hardcoded DAILY_CHAR_LIMIT constant
    everywhere it is used (charge check, daily-remaining display);
    the constant stays only as the fallback default.

  A. Settings + enforcement on a LOCAL mocked store backend (zero HF
     commits): get_settings coercion (missing / garbage / out-of-range
     -> defaults), save_settings validation (rejections + accepted
     bounds), trial_char_limit() / daily_char_limit() helpers,
     trial-cap enforcement (charges accumulate, cap hit blocks with
     the right Bengali message, paid users unaffected, 0 = no cap),
     custom daily cap enforcement, grant_trial resets the trial
     counter, signup seeds trial_chars_used = 0, daily_remaining and
     trial_chars_remaining with custom limits.
  B. app.py source + import checks: the two new admin-form fields
     with their Bengali labels + notes, save call passes both keys,
     trial caption on the generate page, charge logic + helpers in
     store, v2-v6 markers intact.
  C. LIVE (best effort, max 2 dataset writes): read live settings
     (both new keys must merge to their defaults — the live file was
     written before v7), then a write round-trip (trial 1000, daily
     15000 -> verify -> restore originals -> verify). If the HF
     128-commits/hour rate limit answers 429, the write step is
     SKIPPED (not failed) and the parent re-runs after ~12:10. If
     the first write lands but the restore fails, that is a hard FAIL
     (the live limits would be stuck at the test values) and the
     report must say so explicitly.
  D. Cleanup (reads only): no v7 test user/payment exists live.
  E. Regression (mocked): key v2-v6 invariants re-checked — signup
     default trial ~3600s, duplicate mobile / wrong password rejected,
     settings number + max-trials + trial_minutes validation, package
     add/edit, IP trial limit, valid_pin + tap helpers, NAV_ITEMS
     5 tabs, trial_minutes coercion, DAILY_CHAR_LIMIT fallback 20000.

Uses the REAL private HF dataset demoqqq/kiki-talk-data only for
READS in sections C/D (and at most 2 writes in C). No test
users/payments are created anywhere in this suite. Never prints any
token.
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


def _seed_settings(trial_minutes=60, max_trials=2,
                   trial_char_limit=None, daily_char_limit=None):
    """Seed the fake settings.json. A None limit means omit the key
    entirely (old file without it)."""
    s = copy.deepcopy(store.DEFAULT_SETTINGS)
    s["max_trials_per_ip"] = max_trials
    s["trial_minutes"] = trial_minutes
    if trial_char_limit is None:
        s.pop("trial_char_limit", None)
    else:
        s["trial_char_limit"] = trial_char_limit
    if daily_char_limit is None:
        s.pop("daily_char_limit", None)
    else:
        s["daily_char_limit"] = daily_char_limit
    _FAKE_DB["settings.json"] = s


def _base_settings(**over):
    base = {"bkash_number": "01712345678", "nagad_number": "01812345678",
            "instructions": "test instructions", "max_trials_per_ip": 2,
            "trial_minutes": 60}
    base.update(over)
    return base


def _user_record(user_id):
    for u in _FAKE_DB["users.json"]["users"]:
        if u["id"] == user_id:
            return u
    return None


print("=== Kiki Talk v7 test — admin-editable character limits — starting ===",
      flush=True)

# ---------------------------------------------------------------- A. settings + enforcement (mocked)
try:
    _install_fake()
    _FAKE_DB.clear()

    # A1. defaults + constants
    check("A1a. DEFAULT_TRIAL_CHAR_LIMIT is 0 (no cap)",
          store.DEFAULT_TRIAL_CHAR_LIMIT == 0)
    check("A1b. MAX_TRIAL_CHAR_LIMIT is 100000",
          store.MAX_TRIAL_CHAR_LIMIT == 100000)
    check("A1c. DAILY_CHAR_LIMIT still 20000 (fallback constant)",
          store.DAILY_CHAR_LIMIT == 20000)
    check("A1d. daily bounds are 1000-1000000",
          store.MIN_DAILY_CHAR_LIMIT == 1000
          and store.MAX_DAILY_CHAR_LIMIT == 1000000)
    check("A1e. DEFAULT_SETTINGS has both new keys",
          store.DEFAULT_SETTINGS.get("trial_char_limit") == 0
          and store.DEFAULT_SETTINGS.get("daily_char_limit") == 20000)

    # A2. get_settings coercion
    check("A2a. missing settings.json -> trial 0, daily 20000",
          store.get_settings()["trial_char_limit"] == 0
          and store.get_settings()["daily_char_limit"] == 20000)
    _seed_settings(trial_char_limit=5000, daily_char_limit=15000)
    check("A2b. stored 5000/15000 -> 5000/15000",
          store.get_settings()["trial_char_limit"] == 5000
          and store.get_settings()["daily_char_limit"] == 15000)
    check("A2c. helpers read the stored values",
          store.trial_char_limit() == 5000
          and store.daily_char_limit() == 15000)
    _seed_settings(trial_char_limit="2500", daily_char_limit="12000")
    check("A2d. strings '2500'/'12000' coerced",
          store.get_settings()["trial_char_limit"] == 2500
          and store.get_settings()["daily_char_limit"] == 12000)
    _seed_settings(trial_char_limit="abc", daily_char_limit="xyz")
    check("A2e. garbage -> defaults 0/20000",
          store.get_settings()["trial_char_limit"] == 0
          and store.get_settings()["daily_char_limit"] == 20000)
    check("A2f. helpers fall back to defaults on garbage",
          store.trial_char_limit() == 0
          and store.daily_char_limit() == 20000)
    _seed_settings(trial_char_limit=-5, daily_char_limit=500)
    check("A2g. -5 / 500 (below daily min) -> defaults 0/20000",
          store.get_settings()["trial_char_limit"] == 0
          and store.get_settings()["daily_char_limit"] == 20000)
    _seed_settings(trial_char_limit=100001, daily_char_limit=1000001)
    check("A2h. 100001 / 1000001 (above max) -> defaults 0/20000",
          store.get_settings()["trial_char_limit"] == 0
          and store.get_settings()["daily_char_limit"] == 20000)
    _seed_settings(trial_char_limit=None, daily_char_limit=None)
    check("A2i. keys missing (old file) -> defaults 0/20000",
          store.get_settings()["trial_char_limit"] == 0
          and store.get_settings()["daily_char_limit"] == 20000)
    _seed_settings(trial_char_limit=0, daily_char_limit=1000)
    check("A2j. 0 trial cap kept (no cap); daily min 1000 kept",
          store.get_settings()["trial_char_limit"] == 0
          and store.get_settings()["daily_char_limit"] == 1000)
    _seed_settings(trial_char_limit=100000, daily_char_limit=1000000)
    check("A2k. max bounds 100000/1000000 kept",
          store.get_settings()["trial_char_limit"] == 100000
          and store.get_settings()["daily_char_limit"] == 1000000)

    # A3. save_settings validation
    _seed_settings()
    saved = store.save_settings(_base_settings(trial_char_limit=5000,
                                               daily_char_limit=15000))
    check("A3a. save trial 5000 / daily 15000 ok",
          saved["trial_char_limit"] == 5000
          and saved["daily_char_limit"] == 15000
          and store.get_settings()["trial_char_limit"] == 5000)
    expect_raises("A3b. trial_char_limit=-1 rejected",
                  lambda: store.save_settings(_base_settings(trial_char_limit=-1)),
                  "০ থেকে ১০০০০০")
    expect_raises("A3c. trial_char_limit=100001 rejected",
                  lambda: store.save_settings(_base_settings(trial_char_limit=100001)),
                  "০ থেকে ১০০০০০")
    expect_raises("A3d. trial_char_limit='abc' rejected",
                  lambda: store.save_settings(_base_settings(trial_char_limit="abc")),
                  "সংখ্যায়")
    expect_raises("A3e. daily_char_limit=999 rejected",
                  lambda: store.save_settings(_base_settings(daily_char_limit=999)),
                  "১০০০ থেকে ১০০০০০০")
    expect_raises("A3f. daily_char_limit=1000001 rejected",
                  lambda: store.save_settings(_base_settings(daily_char_limit=1000001)),
                  "১০০০ থেকে ১০০০০০০")
    expect_raises("A3g. daily_char_limit='abc' rejected",
                  lambda: store.save_settings(_base_settings(daily_char_limit="abc")),
                  "সংখ্যায়")
    saved0 = store.save_settings(_base_settings(trial_char_limit=0,
                                                daily_char_limit=1000))
    check("A3h. trial 0 + daily 1000 accepted (bounds)",
          saved0["trial_char_limit"] == 0
          and saved0["daily_char_limit"] == 1000)
    saved_max = store.save_settings(_base_settings(trial_char_limit=100000,
                                                   daily_char_limit=1000000))
    check("A3i. trial 100000 + daily 1000000 accepted (bounds)",
          saved_max["trial_char_limit"] == 100000
          and saved_max["daily_char_limit"] == 1000000)
    saved_d = store.save_settings(_base_settings())  # keys omitted
    check("A3j. keys omitted -> defaults 0/20000 saved",
          saved_d["trial_char_limit"] == 0
          and saved_d["daily_char_limit"] == 20000)

    # A4. trial-cap enforcement (mocked users)
    _FAKE_DB["users.json"] = {"users": []}
    _seed_settings(trial_char_limit=100, daily_char_limit=20000)
    u = store.signup("ট্রায়াল ক্যাপ", "01900000071", TEST_PW)
    check("A4a. signup seeds trial_chars_used = 0",
          u.get("trial_chars_used") == 0)
    check("A4b. trial_chars_remaining starts at 100",
          store.trial_chars_remaining(u) == 100)
    rem = store.check_and_charge_chars(u["id"], 60)
    check("A4c. charge 60 ok; daily remaining 19940",
          rem == 19940, f"rem={rem}")
    check("A4d. trial_chars_used is now 60; 40 left",
          _user_record(u["id"])["trial_chars_used"] == 60
          and store.trial_chars_remaining(store.get_user_by_id(u["id"])) == 40)
    expect_raises("A4e. charge 50 over the cap (60+50>100) blocked",
                  lambda: store.check_and_charge_chars(u["id"], 50),
                  "ট্রায়ালের অক্ষর সীমা")
    check("A4f. blocked charge changed nothing (still 60)",
          _user_record(u["id"])["trial_chars_used"] == 60
          and _user_record(u["id"])["daily_chars_used"] == 60)
    rem2 = store.check_and_charge_chars(u["id"], 40)
    check("A4g. charge 40 reaches the cap exactly (100/100)",
          rem2 == 19900
          and _user_record(u["id"])["trial_chars_used"] == 100)
    expect_raises("A4h. 1 more char over a full cap blocked",
                  lambda: store.check_and_charge_chars(u["id"], 1),
                  "ট্রায়ালের অক্ষর সীমা")

    # A5. trial cap 0 = no cap; daily cap still applies
    _seed_settings(trial_char_limit=0, daily_char_limit=20000)
    u2 = store.signup("ট্রায়াল আনলিমিটেড", "01900000072", TEST_PW)
    check("A5a. trial cap 0 -> trial_chars_remaining is None",
          store.trial_chars_remaining(u2) is None)
    store.check_and_charge_chars(u2["id"], 15000)
    check("A5b. cap 0: 15000 chars charged, trial counter still 0",
          _user_record(u2["id"])["daily_chars_used"] == 15000
          and _user_record(u2["id"])["trial_chars_used"] == 0)
    expect_raises("A5c. cap 0: 6000 more hits the DAILY cap, not trial",
                  lambda: store.check_and_charge_chars(u2["id"], 6000),
                  "আজকের সীমা")

    # A6. custom daily cap enforcement
    _seed_settings(trial_char_limit=0, daily_char_limit=5000)
    u3 = store.signup("ডেইলি ক্যাপ", "01900000073", TEST_PW)
    rem3 = store.check_and_charge_chars(u3["id"], 3000)
    check("A6a. custom daily 5000: charge 3000 -> 2000 left",
          rem3 == 2000, f"rem3={rem3}")
    check("A6b. daily_remaining() honours the custom limit",
          store.daily_remaining(store.get_user_by_id(u3["id"])) == 2000)
    expect_raises("A6c. custom daily: 3000 more blocked, message shows 5,000",
                  lambda: store.check_and_charge_chars(u3["id"], 3000),
                  "5,000")

    # A7. paid (active) users are NOT affected by the trial cap
    _seed_settings(trial_char_limit=100, daily_char_limit=20000)
    u4 = store.signup("পেইড ইউজার", "01900000074", TEST_PW)
    rec = _user_record(u4["id"])
    from datetime import timedelta as _td
    rec["expires_at"] = (store.now() + _td(days=30)).isoformat(timespec="seconds")
    check("A7a. user with future expiry is in active state",
          store.access_state(store.get_user_by_id(u4["id"]))["state"] == "active")
    check("A7b. trial_chars_remaining is None for active users",
          store.trial_chars_remaining(store.get_user_by_id(u4["id"])) is None)
    store.check_and_charge_chars(u4["id"], 150)
    check("A7c. active user charged 150 over the 100 trial cap — ok",
          _user_record(u4["id"])["daily_chars_used"] == 150
          and _user_record(u4["id"])["trial_chars_used"] == 0)

    # A8. grant_trial resets the trial counter
    _seed_settings(trial_char_limit=100, daily_char_limit=20000)
    u5 = store.signup("ট্রায়াল রিসেট", "01900000075", TEST_PW)
    store.check_and_charge_chars(u5["id"], 80)
    check("A8a. trial user used 80 chars",
          _user_record(u5["id"])["trial_chars_used"] == 80)
    store.grant_trial(u5["id"])
    check("A8b. grant_trial resets trial_chars_used to 0",
          _user_record(u5["id"])["trial_chars_used"] == 0)
    _restore_real()
except Exception:
    print("SETTINGS + ENFORCEMENT SECTION FAILED", flush=True)
    traceback.print_exc()
    _restore_real()

# ---------------------------------------------------------------- B. app source checks
try:
    import py_compile
    py_compile.compile("app.py", doraise=True)
    check("B1a. app.py compiles", True)
    py_compile.compile("store.py", doraise=True)
    check("B1b. store.py compiles", True)
    src = open("app.py", encoding="utf-8").read()
    ssrc = open("store.py", encoding="utf-8").read()
    check("B1c. admin form has the trial-cap field",
          "ফ্রি ট্রায়ালের অক্ষর সীমা" in src)
    check("B1d. trial-cap note: 0 = no limit, trial only",
          "০ মানে কোনো সীমা নেই; শুধু ট্রায়াল চলাকালীন প্রযোজ্য" in src)
    check("B1e. admin form has the daily-cap field",
          "দৈনিক অক্ষর সীমা" in src)
    check("B1f. daily-cap note: applies to everyone",
          "সবার জন্য প্রযোজ্য — ট্রায়াল ও প্যাকেজ দুটোতেই" in src)
    check("B1g. form passes both new keys to save_settings",
          '"trial_char_limit": int(tr_chars)' in src
          and '"daily_char_limit": int(day_chars)' in src)
    check("B1h. form ranges: trial 0-100000, daily 1000-1000000",
          "min_value=0, max_value=100000, value=int(settings[\"trial_char_limit\"])" in src
          and "min_value=1000, max_value=1000000, value=int(settings[\"daily_char_limit\"])" in src)
    check("B1i. generate page shows trial-cap remaining",
          "ট্রায়ালের অক্ষর সীমা: আর" in src
          and "trial_chars_remaining(user)" in src)
    check("B1j. store has the new helpers + constants",
          "def trial_char_limit()" in ssrc
          and "def daily_char_limit()" in ssrc
          and "def trial_chars_remaining(" in ssrc
          and "DEFAULT_TRIAL_CHAR_LIMIT = 0" in ssrc
          and "MAX_TRIAL_CHAR_LIMIT = 100000" in ssrc)
    check("B1k. charge enforces the trial cap (trial state only)",
          'access_state(u)["state"] == "trial" and limit_trial > 0' in ssrc
          and "ফ্রি ট্রায়ালের অক্ষর সীমা শেষ" in ssrc
          and "trial_chars_used" in ssrc)
    check("B1l. DAILY_CHAR_LIMIT kept as fallback default only",
          "DAILY_CHAR_LIMIT = 20000" in ssrc
          and "DAILY_CHAR_LIMIT - int(" not in ssrc)
    check("B1m. v5 markers intact (trial_minutes, 60 default)",
          "ফ্রি ট্রায়ালের সময় (মিনিট)" in src
          and "DEFAULT_TRIAL_MINUTES = 60" in ssrc)
    check("B1n. v6 markers intact (bottom nav + top header)",
          "NAV_ITEMS" in src and "render_bottom_nav" in src
          and "render_top_header" in src)
    check("B1o. v4 markers intact (hidden admin flow)",
          "logo_tap_target" in src and "sticker_tap_target" in src
          and "Solve the puzzle" in src)
    _code_lines = [line.split("#", 1)[0] for line in src.splitlines()]
    _code = "\n".join(_code_lines)
    check("B1p. still no ?admin=1 route in source",
          "?admin=1" not in _code and "query_params" not in _code)
    check("B1q. v3 markers intact (settings/packages/suspicious)",
          "পেমেন্ট সেটিংস" in src and "📦 প্যাকেজ" in src
          and "সন্দেহজনক অ্যাকাউন্ট" in src)
except Exception:
    print("APP SOURCE SECTION FAILED", flush=True)
    traceback.print_exc()

# ---------------------------------------------------------------- C. live (read + write round-trip, 429 -> SKIP)
print("=== live section (read + write round-trip; 429 -> SKIP) ===", flush=True)
try:
    live_settings = store.load_json("settings.json")
    merged = store.get_settings()
    check("C1. live settings.json readable",
          isinstance(live_settings, dict))
    check("C2. live: new keys merge to defaults (trial 0, daily 20000)",
          merged.get("trial_char_limit") == 0
          and merged.get("daily_char_limit") == 20000,
          f"live keys={sorted(live_settings.keys())} "
          f"merged trial={merged.get('trial_char_limit')} "
          f"daily={merged.get('daily_char_limit')}")
    check("C3. live helpers return the defaults",
          store.trial_char_limit() == 0
          and store.daily_char_limit() == 20000)
    # Write round-trip (2 commits): trial 1000 / daily 15000 -> verify
    # -> restore originals -> verify. On the HF 429 rate limit this
    # whole step is SKIPPED, not failed — the parent re-runs after
    # ~12:10 to verify it live.
    _live_base = dict(merged)
    _orig_trial = merged.get("trial_char_limit")
    _orig_daily = merged.get("daily_char_limit")
    _wrote_test = False
    try:
        store.save_settings({**_live_base, "trial_char_limit": 1000,
                             "daily_char_limit": 15000})
        _wrote_test = True
    except Exception as exc:  # noqa: BLE001
        if is_rate_limit(exc):
            skip("C4. live save_settings(1000/15000) skipped (HF rate limit 429)",
                 "re-run after ~12:10; mocked section proves it")
        else:
            raise
    if _wrote_test:
        check("C4a. live: trial 1000 / daily 15000 saved + read back",
              store.get_settings()["trial_char_limit"] == 1000
              and store.get_settings()["daily_char_limit"] == 15000)
        try:
            store.save_settings({**_live_base,
                                 "trial_char_limit": _orig_trial,
                                 "daily_char_limit": _orig_daily})
        except Exception as exc:  # noqa: BLE001
            if is_rate_limit(exc):
                print("CRITICAL: live limits left at trial 1000 / daily "
                      "15000 — parent must reset them in settings.json",
                      flush=True)
                FAIL.append("C4b. live restore hit the rate limit; "
                            "limits left at trial 1000 / daily 15000")
            else:
                raise
        else:
            check("C4b. live: limits restored to originals",
                  store.get_settings()["trial_char_limit"] == _orig_trial
                  and store.get_settings()["daily_char_limit"] == _orig_daily)
except Exception as exc:  # noqa: BLE001
    if is_rate_limit(exc):
        skip("C. live section skipped (HF rate limit 429)",
             "parent retries after ~12:10")
    else:
        print("LIVE SECTION FAILED", flush=True)
        traceback.print_exc()
        FAIL.append("C. live section error (see traceback)")

# ---------------------------------------------------------------- D. cleanup (reads only)
print("=== cleanup ===", flush=True)
try:
    users_f = store.load_json("users.json").get("users", [])
    pays_f = store.load_json("payments.json").get("payments", [])
    v7_mobiles = [u for u in users_f
                  if (u.get("mobile") or "").startswith("0190000007")]
    check("D1. no v7 test user exists live",
          len(v7_mobiles) == 0, f"found={len(v7_mobiles)}")
    print(f"  dataset now: users={len(users_f)} payments={len(pays_f)} "
          "(v7 created none; leftovers are out of scope for this suite)",
          flush=True)
except Exception as exc:  # noqa: BLE001
    if is_rate_limit(exc):
        skip("D1. cleanup read skipped (HF rate limit 429)",
             "parent cleanup cron ~12:10 will handle leftovers")
    else:
        print("CLEANUP FAILED", flush=True)
        traceback.print_exc()

# ---------------------------------------------------------------- E. regression (mocked, v2-v6)
print("=== regression (mocked v2-v6 invariants) ===", flush=True)
try:
    _install_fake()
    _FAKE_DB.clear()
    _FAKE_DB["users.json"] = {"users": []}
    _seed_settings(trial_minutes=60, max_trials=2)

    # v2: default signup trial ~3600s, duplicate mobile, wrong password
    u = store.signup("রিগ্রেশন", "01900000081", TEST_PW)
    st_u = store.access_state(u)
    check("E1a. v2: default signup trial ~3600s left",
          st_u["state"] == "trial" and 3000 < st_u["trial_left_s"] <= 3600,
          f"left={st_u['trial_left_s']}")
    expect_raises("E1b. v2: duplicate mobile rejected",
                  lambda: store.signup("আবার", "01900000081", TEST_PW),
                  "ইতিমধ্যে")
    expect_raises("E1c. v2: wrong password login rejected",
                  lambda: store.login("01900000081", "wrongpass"),
                  "পাসওয়ার্ড ভুল")

    # v3: settings number + max-trials validation still works
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

    # v3: package add/edit still works
    _FAKE_DB["packages.json"] = {"packages": copy.deepcopy(store.DEFAULT_PACKAGES)}
    pkg = store.add_package("টেস্ট প্যাকেজ", 3, 10)
    check("E3a. v3: add_package works",
          pkg["name"] == "টেস্ট প্যাকেজ" and pkg["days"] == 3)
    upd = store.update_package(pkg["id"], price=15)
    check("E3b. v3: update_package price works",
          upd["price"] == 15)

    # v3: IP trial limit still works (limit 2 -> 3rd signup no trial)
    ua = store.signup("আইপি এ", "01900000082", TEST_PW, client_ip="10.0.0.1")
    ub = store.signup("আইপি বি", "01900000083", TEST_PW, client_ip="10.0.0.1")
    uc = store.signup("আইপি সি", "01900000084", TEST_PW, client_ip="10.0.0.1")
    check("E4a. v3: 1st + 2nd same-IP signups get trials",
          ua.get("trial_granted") is True and ub.get("trial_granted") is True)
    check("E4b. v3: 3rd same-IP signup allowed but NO trial",
          uc.get("trial_granted") is False)

    # v4: PIN + tap helpers still work
    check("E5a. v4: valid_pin('1234')",
          store.valid_pin("1234") and not store.valid_pin("123"))
    import app as kiki_app
    check("E5b. v4: logo tap 5 -> pin1, sticker tap 5 -> pin2",
          kiki_app.logo_tap_target(False, 5) == "pin1"
          and kiki_app.sticker_tap_target(5) == "pin2")

    # v5: trial_minutes coercion still works
    _seed_settings(trial_minutes="abc")
    check("E6a. v5: garbage trial_minutes -> default 60",
          store.get_settings()["trial_minutes"] == 60)
    _seed_settings(trial_minutes=0)
    check("E6b. v5: trial_minutes 0 kept (trial off)",
          store.get_settings()["trial_minutes"] == 0)
    check("E6c. v5: trial_seconds() 0 when trial is off",
          store.trial_seconds() == 0)

    # v6: bottom nav table still has exactly 5 tabs
    check("E7a. v6: NAV_ITEMS has exactly 5 tabs",
          len(kiki_app.NAV_ITEMS) == 5)

    # v7 fallback: DAILY_CHAR_LIMIT constant still 20000
    check("E8a. v7: DAILY_CHAR_LIMIT fallback still 20000",
          store.DAILY_CHAR_LIMIT == 20000)
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
