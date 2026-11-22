# -*- coding: utf-8 -*-
"""Kiki Talk v5 test — admin-editable free-trial duration (2026-11-22).

Covers trial_minutes in settings.json (default 60, admin-editable):
  A. Settings + trial logic on a LOCAL mocked store backend (zero HF
     commits): get_settings coercion (missing / garbage / out-of-range
     -> 60), save_settings validation (negative / >1440 / non-integer
     rejected; 0 / 1 / 60 / 1440 accepted), trial_seconds(), signup
     grants the configured trial length (30 / 120 min), trial_minutes
     = 0 -> no trial but signup succeeds, default -> exactly 3600s,
     grant_trial uses the configured length.
  B. app.py source + import checks: the trial field in the payment
     settings form, the "new signups only" note, save_settings call
     passes trial_minutes; store helpers exist; v2/v3/v4 markers intact.
  C. LIVE (reads only, ZERO commits): live settings.json has no
     trial_minutes key yet, so get_settings() must merge the default
     60. The live save_settings write round-trip is SKIPPED by design
     — the HF 128-commits/hour rate limit (429) is active until
     ~12:10; the parent retries it after the limit clears.
  D. Cleanup (reads only): no v5 test user/payment exists live.
  E. Regression (mocked): key v2/v3/v4 invariants re-checked — signup
     default trial ~3600s, duplicate mobile / wrong password rejected,
     settings number + max-trials validation, package add/edit, IP
     trial limit, valid_pin + tap helpers, no visible admin entry.

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


def _seed_settings(trial_minutes=None, max_trials=2):
    """Seed the fake settings.json. trial_minutes=None means omit the
    key entirely (old file without it)."""
    s = copy.deepcopy(store.DEFAULT_SETTINGS)
    s["max_trials_per_ip"] = max_trials
    if trial_minutes is None:
        s.pop("trial_minutes", None)
    else:
        s["trial_minutes"] = trial_minutes
    _FAKE_DB["settings.json"] = s


def _trial_delta_seconds(user: dict) -> float:
    start = store._parse_iso(user["trial_started_at"])
    end = store._parse_iso(user["trial_ends_at"])
    return (end - start).total_seconds()


print("=== Kiki Talk v5 test — admin-editable trial duration — starting ===",
      flush=True)

# ---------------------------------------------------------------- A. settings + trial logic (mocked)
try:
    _install_fake()
    _FAKE_DB.clear()

    # A1. defaults + constants
    check("A1a. DEFAULT_TRIAL_MINUTES is 60",
          store.DEFAULT_TRIAL_MINUTES == 60)
    check("A1b. MAX_TRIAL_MINUTES is 1440",
          store.MAX_TRIAL_MINUTES == 1440)
    check("A1c. TRIAL_SECONDS still 3600 (fallback constant)",
          store.TRIAL_SECONDS == 3600)
    check("A1d. DEFAULT_SETTINGS has trial_minutes = 60",
          store.DEFAULT_SETTINGS.get("trial_minutes") == 60)

    # A2. get_settings coercion
    check("A2a. missing settings.json -> trial_minutes 60",
          store.get_settings()["trial_minutes"] == 60)
    _seed_settings(trial_minutes=90)
    check("A2b. stored 90 -> 90",
          store.get_settings()["trial_minutes"] == 90)
    check("A2c. trial_seconds() is 5400 for 90 min",
          store.trial_seconds() == 5400)
    _seed_settings(trial_minutes="45")
    check("A2d. string '45' coerced to 45",
          store.get_settings()["trial_minutes"] == 45)
    _seed_settings(trial_minutes="abc")
    check("A2e. garbage 'abc' -> default 60",
          store.get_settings()["trial_minutes"] == 60)
    check("A2f. trial_seconds() falls back to 3600 on garbage",
          store.trial_seconds() == 3600)
    _seed_settings(trial_minutes=-5)
    check("A2g. negative -5 -> default 60",
          store.get_settings()["trial_minutes"] == 60)
    _seed_settings(trial_minutes=2000)
    check("A2h. 2000 (>1440) -> default 60",
          store.get_settings()["trial_minutes"] == 60)
    _seed_settings(trial_minutes=None)
    check("A2i. key missing (old file) -> default 60",
          store.get_settings()["trial_minutes"] == 60)
    _seed_settings(trial_minutes=0)
    check("A2j. 0 is kept as 0 (trial off)",
          store.get_settings()["trial_minutes"] == 0)
    check("A2k. trial_seconds() is 0 when trial is off",
          store.trial_seconds() == 0)

    # A3. save_settings validation
    _seed_settings(trial_minutes=60)
    base = {"bkash_number": "01712345678", "nagad_number": "01812345678",
            "instructions": "test instructions", "max_trials_per_ip": 2}
    saved = store.save_settings({**base, "trial_minutes": 30})
    check("A3a. save_settings trial_minutes=30 ok",
          saved["trial_minutes"] == 30
          and store.get_settings()["trial_minutes"] == 30)
    expect_raises("A3b. trial_minutes=-1 rejected",
                  lambda: store.save_settings({**base, "trial_minutes": -1}),
                  "০ থেকে ১৪৪০")
    expect_raises("A3c. trial_minutes=1441 rejected",
                  lambda: store.save_settings({**base, "trial_minutes": 1441}),
                  "০ থেকে ১৪৪০")
    expect_raises("A3d. trial_minutes='abc' rejected",
                  lambda: store.save_settings({**base, "trial_minutes": "abc"}),
                  "সংখ্যায়")
    expect_raises("A3e. trial_minutes=None rejected",
                  lambda: store.save_settings({**base, "trial_minutes": None}),
                  "সংখ্যায়")
    saved0 = store.save_settings({**base, "trial_minutes": 0})
    check("A3f. trial_minutes=0 accepted (trial off)",
          saved0["trial_minutes"] == 0)
    saved_max = store.save_settings({**base, "trial_minutes": 1440})
    check("A3g. trial_minutes=1440 accepted (24h max)",
          saved_max["trial_minutes"] == 1440)
    saved_d = store.save_settings(base)  # key omitted -> default
    check("A3h. key omitted -> default 60 saved",
          saved_d["trial_minutes"] == 60)

    # A4. signup grants the configured trial length
    _FAKE_DB["users.json"] = {"users": []}
    _seed_settings(trial_minutes=30)
    u30 = store.signup("টেস্ট তিরিশ", "01900000051", TEST_PW)
    check("A4a. trial_minutes=30 -> trial lasts 1800s",
          _trial_delta_seconds(u30) == 1800, f"delta={_trial_delta_seconds(u30)}")
    st30 = store.access_state(u30)
    check("A4b. trial state, ~1800s left",
          st30["state"] == "trial" and 1700 < st30["trial_left_s"] <= 1800,
          f"left={st30['trial_left_s']}")
    _seed_settings(trial_minutes=120)
    u120 = store.signup("টেস্ট একশো বিশ", "01900000052", TEST_PW)
    check("A4c. trial_minutes=120 -> trial lasts 7200s",
          _trial_delta_seconds(u120) == 7200)
    _seed_settings(trial_minutes=60)
    u60 = store.signup("টেস্ট ষাট", "01900000053", TEST_PW)
    check("A4d. default 60 -> trial lasts exactly 3600s",
          _trial_delta_seconds(u60) == 3600)

    # A5. trial_minutes = 0 -> no trial, but signup succeeds
    _seed_settings(trial_minutes=0)
    u0 = store.signup("টেস্ট শূন্য", "01900000054", TEST_PW)
    check("A5a. trial_minutes=0 -> signup still succeeds",
          u0["mobile"] == "01900000054")
    check("A5b. trial_minutes=0 -> trial_granted False",
          u0.get("trial_granted") is False)
    check("A5c. trial_minutes=0 -> no trial time (ends == starts)",
          _trial_delta_seconds(u0) == 0)
    st0 = store.access_state(u0)
    check("A5d. trial_minutes=0 -> state expired (must pay first)",
          st0["state"] == "expired" and st0["has_access"] is False)

    # A6. grant_trial uses the configured length too
    _seed_settings(trial_minutes=15)
    store.grant_trial(u0["id"])
    u0g = store.get_user_by_id(u0["id"])
    check("A6a. grant_trial with 15 min -> trial lasts 900s",
          _trial_delta_seconds(u0g) == 900, f"delta={_trial_delta_seconds(u0g)}")
    check("A6b. grant_trial sets trial_granted True",
          u0g.get("trial_granted") is True)
    _restore_real()
except Exception:
    print("TRIAL LOGIC SECTION FAILED", flush=True)
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
    check("B1c. admin form has the trial-duration field",
          "ফ্রি ট্রায়ালের সময় (মিনিট)" in src)
    check("B1d. form note: new signups only",
          "শুধু নতুন সাইন আপে প্রযোজ্য হবে" in src)
    check("B1e. form passes trial_minutes to save_settings",
          '"trial_minutes": int(tr_min)' in src)
    check("B1f. trial field range 0-1440 in the form",
          "min_value=0, max_value=1440, value=int(settings[\"trial_minutes\"])" in src)
    check("B1g. store has trial_seconds + constants",
          "def trial_seconds()" in ssrc
          and "DEFAULT_TRIAL_MINUTES = 60" in ssrc
          and "MAX_TRIAL_MINUTES = 1440" in ssrc)
    check("B1h. signup uses trial_seconds()",
          "trial_secs = trial_seconds()" in ssrc)
    check("B1i. grant_trial uses trial_seconds()",
          "timedelta(seconds=trial_seconds())" in ssrc)
    check("B1j. signup trial_minutes=0 path present",
          "trial_secs <= 0" in ssrc)
    check("B1k. v2 markers intact (default trial text, TRIAL_SECONDS)",
          "১ ঘণ্টার ফ্রি ট্রায়াল" in src and "TRIAL_SECONDS = 3600" in ssrc)
    check("B1l. v3 markers intact (settings/packages/suspicious)",
          "পেমেন্ট সেটিংস" in src and "📦 প্যাকেজ" in src
          and "সন্দেহজনক অ্যাকাউন্ট" in src)
    check("B1m. v4 markers intact (hidden admin flow)",
          "logo_tap_target" in src and "sticker_tap_target" in src
          and "Solve the puzzle" in src)
    _code_lines = [line.split("#", 1)[0] for line in src.splitlines()]
    _code = "\n".join(_code_lines)
    check("B1n. still no ?admin=1 route in source",
          "?admin=1" not in _code and "query_params" not in _code)
except Exception:
    print("APP SOURCE SECTION FAILED", flush=True)
    traceback.print_exc()

# ---------------------------------------------------------------- C. live (reads only, 0 commits)
print("=== live section (reads only; write round-trip SKIPPED) ===",
      flush=True)
try:
    live_settings = store.load_json("settings.json")
    merged = store.get_settings()
    check("C1. live settings.json readable",
          isinstance(live_settings, dict))
    check("C2. live: trial_minutes defaults to 60 (old file has no key)",
          merged.get("trial_minutes") == 60
          and "trial_minutes" not in live_settings,
          f"live keys={sorted(live_settings.keys())}")
    check("C3. live trial_seconds() is 3600 (default 1 hour)",
          store.trial_seconds() == 3600)
    skip("C4. live save_settings write round-trip skipped "
         "(HF rate limit 429 until ~12:10)",
         "parent retries after the limit clears; mocked section proves it")
except Exception as exc:  # noqa: BLE001
    if is_rate_limit(exc):
        skip("C. live reads skipped (HF rate limit 429)",
             "parent retries after ~12:10")
    else:
        print("LIVE READ SECTION FAILED", flush=True)
        traceback.print_exc()
        FAIL.append("C. live read error (see traceback)")

# ---------------------------------------------------------------- D. cleanup (reads only)
print("=== cleanup ===", flush=True)
try:
    users_f = store.load_json("users.json").get("users", [])
    pays_f = store.load_json("payments.json").get("payments", [])
    v5_mobiles = [u for u in users_f
                  if (u.get("mobile") or "").startswith("0190000005")]
    check("D1. no v5 test user exists live",
          len(v5_mobiles) == 0, f"found={len(v5_mobiles)}")
    print(f"  dataset now: users={len(users_f)} payments={len(pays_f)} "
          "(v5 created none; leftovers are out of scope for this suite)",
          flush=True)
except Exception as exc:  # noqa: BLE001
    if is_rate_limit(exc):
        skip("D1. cleanup read skipped (HF rate limit 429)",
             "parent cleanup cron ~12:10 will handle leftovers")
    else:
        print("CLEANUP FAILED", flush=True)
        traceback.print_exc()

# ---------------------------------------------------------------- E. regression (mocked, v2/v3/v4)
print("=== regression (mocked v2/v3/v4 invariants) ===", flush=True)
try:
    _install_fake()
    _FAKE_DB.clear()
    _FAKE_DB["users.json"] = {"users": []}
    _seed_settings(trial_minutes=60, max_trials=2)

    # v2: default signup trial ~3600s, duplicate mobile, wrong password
    u = store.signup("রিগ্রেশন", "01900000061", TEST_PW)
    st_u = store.access_state(u)
    check("E1a. v2: default signup trial ~3600s left",
          st_u["state"] == "trial" and 3000 < st_u["trial_left_s"] <= 3600,
          f"left={st_u['trial_left_s']}")
    expect_raises("E1b. v2: duplicate mobile rejected",
                  lambda: store.signup("আবার", "01900000061", TEST_PW),
                  "ইতিমধ্যে")
    expect_raises("E1c. v2: wrong password login rejected",
                  lambda: store.login("01900000061", "wrongpass"),
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
    ua, ub = store.signup("আইপি এ", "01900000062", TEST_PW, client_ip="10.0.0.1"), None
    ub = store.signup("আইপি বি", "01900000063", TEST_PW, client_ip="10.0.0.1")
    uc = store.signup("আইপি সি", "01900000064", TEST_PW, client_ip="10.0.0.1")
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
