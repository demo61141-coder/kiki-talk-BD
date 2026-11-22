# -*- coding: utf-8 -*-
"""Kiki Talk v4 test — hidden admin access (2026-11-22).

Covers the hidden admin flow (logo 5 taps -> 4-digit PIN -> decoy
sticker -> PIN -> panel):
  A. PIN logic on a LOCAL mocked store backend (zero HF commits):
     valid_pin / normalize_pin, needs_setup matrix (missing / empty /
     legacy non-PIN hash / PIN), set_pin validation + verify + double-set
     rejection, legacy migration (old password hash forces fresh setup
     and never verifies), reset_pin, pure tap-target helpers.
  B. app.py source + import checks: no visible admin button, no
     ?admin=1 route, no show_admin; logo/sticker tap targets, sticker
     decoy text, PIN screens and stage machine all present.
  C. LIVE (best effort, max 3 dataset writes): reset -> set PIN ->
     verify on a fresh read -> reset. If the HF 128-commits/hour rate
     limit answers 429, this section is SKIPPED (not failed) and the
     parent retries after ~12:10 — the mocked section already proves
     the logic. If a write succeeds but the final reset fails, that is
     a hard FAIL (a test PIN would be left live) and the report must
     say so explicitly.

Uses the REAL private HF dataset demoqqq/kiki-talk-data only in
section C. No test users/payments are created anywhere in this suite.
Never prints any token.
"""
import copy
import os
import sys
import time
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
LIVE_PIN = "2468"  # test PIN used ONLY in the live section; reset after


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
# Mocked store backend (Section A): in-memory dict, zero HF commits.
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


print("=== Kiki Talk v4 test — hidden admin access — starting ===",
      flush=True)

# ---------------------------------------------------------------- A. PIN logic (mocked)
try:
    _install_fake()
    _FAKE_DB.clear()

    # A1. valid_pin / normalize_pin
    check("A1a. valid_pin('1234')", store.valid_pin("1234"))
    check("A1b. valid_pin rejects 3 digits", not store.valid_pin("123"))
    check("A1c. valid_pin rejects 5 digits", not store.valid_pin("12345"))
    check("A1d. valid_pin rejects letters", not store.valid_pin("12a4"))
    check("A1e. valid_pin rejects empty", not store.valid_pin(""))
    check("A1f. valid_pin rejects None", not store.valid_pin(None))
    check("A1g. Bengali digits accepted ('১২৩৪')",
          store.valid_pin("১২৩৪") and store.normalize_pin("১২৩৪") == "1234")
    check("A1h. spaces stripped", store.valid_pin(" 1234 "))

    # A2. needs_setup matrix
    check("A2a. missing admin.json -> needs setup",
          store.admin_needs_pin_setup())
    _FAKE_DB["admin.json"] = {}
    check("A2b. empty admin.json -> needs setup",
          store.admin_needs_pin_setup())
    _FAKE_DB["admin.json"] = {"salt": None, "password_hash": None}
    check("A2c. null hash -> needs setup", store.admin_needs_pin_setup())
    check("A2d. null hash -> check_pin False",
          store.admin_check_pin("1234") is False)

    # A3. set_pin validation + verify + double-set
    expect_raises("A3a. set_pin('123') rejected",
                  lambda: store.admin_set_pin("123"), "৪ সংখ্যার")
    expect_raises("A3b. set_pin('12a4') rejected",
                  lambda: store.admin_set_pin("12a4"), "৪ সংখ্যার")
    expect_raises("A3c. set_pin('12345') rejected",
                  lambda: store.admin_set_pin("12345"), "৪ সংখ্যার")
    expect_raises("A3d. set_pin('') rejected",
                  lambda: store.admin_set_pin(""), "৪ সংখ্যার")
    store.admin_set_pin("1234")
    check("A3e. set_pin('1234') ok, no longer needs setup",
          store.admin_needs_pin_setup() is False)
    check("A3f. stored record is kind='pin' with a hash",
          _FAKE_DB["admin.json"].get("kind") == "pin"
          and bool(_FAKE_DB["admin.json"].get("password_hash"))
          and _FAKE_DB["admin.json"]["password_hash"] != "1234",
          "plaintext never stored")
    check("A3g. check_pin('1234') True", store.admin_check_pin("1234"))
    check("A3h. check_pin('4321') False",
          store.admin_check_pin("4321") is False)
    check("A3i. check_pin('123') False (not 4 digits)",
          store.admin_check_pin("123") is False)
    check("A3j. check_pin('১২৩৪') True (Bengali digits)",
          store.admin_check_pin("১২৩৪"))
    expect_raises("A3k. set_pin again rejected (already set)",
                  lambda: store.admin_set_pin("5678"), "আগেই")

    # A4. legacy migration: old free-form password hash (no kind)
    salt, pw_hash = store.hash_password("legacytest999")
    _FAKE_DB["admin.json"] = {"salt": salt, "password_hash": pw_hash}
    check("A4a. legacy hash (no kind) -> needs setup",
          store.admin_needs_pin_setup())
    check("A4b. legacy password never verifies as a PIN",
          store.admin_check_pin("legacytest999") is False)
    check("A4c. admin_is_set_up still True for legacy (v2 compat)",
          store.admin_is_set_up())
    store.admin_set_pin("5678")
    check("A4d. fresh PIN setup overwrites legacy credential",
          store.admin_needs_pin_setup() is False
          and store.admin_check_pin("5678")
          and not store.admin_check_pin("legacytest999"))

    # A5. reset
    store.admin_reset_pin()
    check("A5a. reset_pin -> needs setup again",
          store.admin_needs_pin_setup())
    check("A5b. reset_pin -> check_pin False",
          store.admin_check_pin("5678") is False)
    _restore_real()
except Exception:
    print("PIN LOGIC SECTION FAILED", flush=True)
    traceback.print_exc()
    _restore_real()

# ---------------------------------------------------------------- A6. pure tap helpers
try:
    import app as kiki_app

    check("A6a. logo taps 0-4 -> no stage",
          kiki_app.logo_tap_target(False, 0) is None
          and kiki_app.logo_tap_target(False, 4) is None)
    check("A6b. logo tap 5 (PIN set) -> pin1",
          kiki_app.logo_tap_target(False, 5) == "pin1")
    check("A6c. logo tap 5 (needs setup) -> pin_setup",
          kiki_app.logo_tap_target(True, 5) == "pin_setup")
    check("A6d. logo taps >5 still open pin1",
          kiki_app.logo_tap_target(False, 7) == "pin1")
    check("A6e. sticker taps 0-4 -> no stage",
          kiki_app.sticker_tap_target(0) is None
          and kiki_app.sticker_tap_target(4) is None)
    check("A6f. sticker tap 5 -> pin2",
          kiki_app.sticker_tap_target(5) == "pin2")
    check("A6g. sticker taps >5 still pin2",
          kiki_app.sticker_tap_target(9) == "pin2")
    check("A6h. thresholds are 5 and 5",
          kiki_app.LOGO_TAPS_NEEDED == 5
          and kiki_app.STICKER_TAPS_NEEDED == 5)
except Exception:
    print("TAP HELPERS SECTION FAILED", flush=True)
    traceback.print_exc()

# ---------------------------------------------------------------- B. app source checks
try:
    import py_compile
    py_compile.compile("app.py", doraise=True)
    check("B1a. app.py compiles", True)
    src = open("app.py", encoding="utf-8").read()
    check("B1b. no visible admin button in source",
          'st.button("🛡️ অ্যাডমিন প্যানেল"' not in src)
    # "?admin=1" also appears in one explanatory comment — check code
    # lines only (comments stripped) for a real route.
    _code_lines = [line.split("#", 1)[0] for line in src.splitlines()]
    _code = "\n".join(_code_lines)
    check("B1c. no ?admin=1 route in source",
          "?admin=1" not in _code and "query_params" not in _code)
    check("B1d. no show_admin flag left in source",
          "show_admin" not in src)
    check("B1e. logo tap target present",
          'key="logo_tap"' in src and 'type="tertiary"' in src)
    check("B1f. sticker tap target present",
          'key="sticker_tap"' in src and "Solve the puzzle" in src)
    check("B1g. sticker decoy wrong-answer text present",
          "❌ ভুল উত্তর! আবার চেষ্টা করুন।" in src)
    check("B1h. all gate stages present",
          all(s in src for s in ('"pin_setup"', '"pin1"', '"sticker"',
                                 '"pin2"', '"open"', '"admin_stage"')))
    check("B1i. PIN screens use store PIN functions",
          "store.admin_set_pin(" in src
          and "store.admin_check_pin(" in src
          and "store.admin_needs_pin_setup()" in src)
    check("B1j. sticker CSS only on sticker screen",
          "STICKER_CSS" in src and "st.markdown(STICKER_CSS" in src)
    check("B1k. wrong PIN resets the flow (message + reset)",
          '_reset_admin_flow("❌ পিন ভুল হয়েছে।")' in src)
    check("B1l. v3 source markers intact (settings/packages/suspicious)",
          "পেমেন্ট সেটিংস" in src and "📦 প্যাকেজ" in src
          and "সন্দেহজনক অ্যাকাউন্ট" in src
          and "store.get_settings()" in src
          and "package_id=chosen" in src)
    check("B1m. store PIN functions exist",
          all(hasattr(store, f) for f in (
              "valid_pin", "normalize_pin", "admin_needs_pin_setup",
              "admin_set_pin", "admin_check_pin", "admin_reset_pin")))
    check("B1n. old admin password functions kept (v2 compat)",
          all(hasattr(store, f) for f in (
              "admin_set_password", "admin_check_password",
              "admin_is_set_up")))
except Exception:
    print("APP SOURCE SECTION FAILED", flush=True)
    traceback.print_exc()

# ---------------------------------------------------------------- C. live (best effort)
print("=== live section (max 3 writes; 429 -> SKIP) ===", flush=True)


def _live_read_admin():
    """admin.json dict; {} when the file is missing (normal) or unreadable.
    Reads never consume the commit rate limit."""
    try:
        return store.load_json("admin.json")
    except Exception as exc:  # noqa: BLE001
        print(f"  live read note: {exc}", flush=True)
        return {}


def _live_write(name, fn):
    """Run one live write step; on the HF 429 rate limit record a SKIP
    and stop the live section (SystemExit). Other errors propagate."""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        if is_rate_limit(exc):
            skip(f"{name} skipped (HF rate limit 429)",
                 "retry after ~12:10")
            raise SystemExit(0)
        raise


try:
    # Start from a known state: reset first, but only if something is set
    # (saves a dataset commit when admin.json is already empty).
    if _live_read_admin().get("password_hash"):
        _live_write("C1. live reset", store.admin_reset_pin)
    # Set the test PIN (1 write), verify on a fresh read, reset (1 write).
    _live_write("C2. live set_pin", lambda: store.admin_set_pin(LIVE_PIN))
    # Fresh reads can lag the upload (HF cache) — poll, reads are free.
    _ok = False
    _t0 = time.time()
    while time.time() - _t0 < 90:
        try:
            if (store.admin_check_pin(LIVE_PIN)
                    and not store.admin_check_pin("8642")
                    and not store.admin_needs_pin_setup()):
                _ok = True
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(3)
    check("C3. live: fresh read verifies the PIN", _ok)
    try:
        store.admin_reset_pin()
    except Exception as exc:  # noqa: BLE001
        if is_rate_limit(exc):
            print("CRITICAL: live test PIN left set — parent must reset "
                  f"admin.json (test PIN was {LIVE_PIN})", flush=True)
            FAIL.append("C4. live final reset hit the rate limit; "
                        f"test PIN {LIVE_PIN} left set")
        else:
            raise
    else:
        _ok4 = False
        _t0 = time.time()
        while time.time() - _t0 < 90:
            try:
                if (store.admin_needs_pin_setup()
                        and not store.admin_check_pin(LIVE_PIN)):
                    _ok4 = True
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(3)
        check("C4. live: reset restores first-run setup", _ok4)
except SystemExit:
    pass
except Exception:
    print("LIVE SECTION FAILED", flush=True)
    traceback.print_exc()
    FAIL.append("C. live section error (see traceback)")

# ---------------------------------------------------------------- D. cleanup + verify
print("=== cleanup ===", flush=True)
try:
    # Only write if admin.json is not already reset (saves a commit).
    if _live_read_admin().get("password_hash"):
        try:
            store.save_json("admin.json",
                            {"salt": None, "password_hash": None,
                             "kind": None})
        except Exception as exc:  # noqa: BLE001
            if is_rate_limit(exc):
                skip("D1. cleanup reset skipped (HF rate limit 429)",
                     "parent cleanup cron ~12:10 will reset admin.json")
            else:
                raise
        else:
            check("D2. cleanup: admin reset (first-run PIN setup)",
                  store.admin_is_set_up() is False
                  and store.admin_needs_pin_setup())
    else:
        check("D2. cleanup: admin already reset (first-run PIN setup)",
              store.admin_is_set_up() is False
              and store.admin_needs_pin_setup())
    users_f = store.load_json("users.json").get("users", [])
    pays_f = store.load_json("payments.json").get("payments", [])
    print(f"  dataset now: users={len(users_f)} payments={len(pays_f)} "
          "(v4 created none; leftovers are out of scope for this suite)",
          flush=True)
except Exception:
    print("CLEANUP FAILED", flush=True)
    traceback.print_exc()

print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed, "
      f"{len(SKIP)} skipped", flush=True)
if FAIL:
    print("FAILED: " + ", ".join(FAIL), flush=True)
    sys.exit(1)
if SKIP:
    print("SKIPPED: " + ", ".join(SKIP), flush=True)
print("ALL TESTS PASSED" + (" (with skips noted above)" if SKIP else ""),
      flush=True)
