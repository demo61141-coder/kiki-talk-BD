# -*- coding: utf-8 -*-
"""Kiki Talk end-to-end test — RUN 2 (user-approved re-run, 2026-11-22).

Covers, in order:
  0. dataset pre-check (must start clean) + idempotent pre-clean
  1. store: signup / trial / login / validation errors / fair-use /
     payment submit (+screenshot) / admin setup / approve -> 30 days /
     reject path / change password / admin reset / block-unblock
  2. script_check: digits->words, auto-fixes, warnings
  3. tts_engine: BOTH models, option 1 (audio only) + option 2
     (audio + SRT, via subtitle_tools.synthesize_aligned), speed 1.25
  4. subtitle_tools: mode A segments + SRT/JSON, mode B exact align,
     mode C proportional (sum == total)
  5. app.py import + placeholder intact + demo files present
  6. landing/: STREAMLIT_APP_URL placeholders, vercel.json, demo audio MD5
  7. cleanup: all test data removed, dataset verified clean again

Uses the REAL private HF dataset demoqqq/kiki-talk-data and the REAL
local ONNX models (BANGALTTS_*_MODEL_DIR — no HF model download).
CPU synthesis is slow-ish; prints are flushed so the log shows life.
Never prints any token.
"""
import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

# --- HF write token via the registered connector surrogate (never printed) ---
sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
from dynamic_credentials import dynamic_credential_entry

_entry = dynamic_credential_entry("custom.huggingface")
os.environ["HF_TOKEN"] = str(_entry["surrogate"]).strip()

# --- local ONNX models (verified MD5s) — no download needed ---
os.environ["BANGALTTS_AKIB_MODEL_DIR"] = (
    "/home/hatch/workspace/goals/tts/hidden_files/akib_export")
os.environ["BANGALTTS_KIKI_MODEL_DIR"] = (
    "/home/hatch/workspace/goals/tts/hidden_files/kiki_big_rerecord_export")

sys.path.insert(0, "/home/hatch/workspace/kiki-talk")
os.chdir("/home/hatch/workspace/kiki-talk")

import store
import tts_engine
import subtitle_tools as tools
import script_check

TEST_MOBILE = "01999999999"
TEST_NAME = "টেস্ট ইউজার"
TEST_PW = "testpass123"
NEW_PW = "testpass456"
ADMIN_PW = "admintest123"

# 1x1 transparent PNG (fake payment screenshot)
FAKE_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)

S1 = "ঢাকায় আজ জাতীয় সংসদের অধিবেশন শুরু হয়েছে।"
S2 = "আবহাওয়া অধিদপ্তর জানিয়েছে আগামীকাল বৃষ্টি হতে পারে।"
S3 = "দেশের অর্থনীতিতে নতুন সম্ভাবনা দেখা দিয়েছে।"
TEXT3 = f"{S1} {S2} {S3}"

PASS = []
FAIL = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}", flush=True)


def expect_raises(name, fn, substr=None):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        ok = substr is None or substr in str(exc)
        check(name, ok, f"raised: {exc}")
        return
    check(name, False, "no exception raised")


def wait_for(name, fn, timeout=90):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if fn():
                check(name, True)
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(3)
    check(name, False, "timeout after %ds" % timeout)
    return False


def dataset_state():
    users = store.load_json("users.json").get("users", [])
    pays = store.load_json("payments.json").get("payments", [])
    admin_set = store.admin_is_set_up()
    return users, pays, admin_set


def cleanup_test_data():
    """Remove every trace of the test user/payments; reset admin.json."""
    api = store._api()
    users, pays, _ = dataset_state()
    test_pays = [p for p in pays if p.get("mobile") == TEST_MOBILE]
    for p in test_pays:
        if p.get("screenshot_path"):
            try:
                api.delete_file(path_in_repo=p["screenshot_path"],
                                repo_id=store.REPO_ID, repo_type="dataset")
                print(f"  deleted screenshot {p['screenshot_path']}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"  screenshot delete note: {exc}", flush=True)
    if test_pays:
        def _drop_pays(data):
            data["payments"] = [p for p in data.get("payments", [])
                                if p.get("mobile") != TEST_MOBILE]
        store.update_json("payments.json", _drop_pays)
    def _drop_user(data):
        data["users"] = [u for u in data.get("users", [])
                         if u.get("mobile") != TEST_MOBILE]
    store.update_json("users.json", _drop_user)
    store.save_json("admin.json", {"salt": None, "password_hash": None})


print("=== Kiki Talk e2e test RUN 2 — starting ===", flush=True)
print(f"python: {sys.version.split()[0]}", flush=True)

# ---------------------------------------------------------------- 0. pre-check
try:
    users0, pays0, admin0 = dataset_state()
    print(f"pre-check: users={len(users0)} payments={len(pays0)} admin_set={admin0}",
          flush=True)
    if users0 or pays0 or admin0:
        print("pre-check NOT clean — cleaning leftovers first", flush=True)
        cleanup_test_data()
        users0, pays0, admin0 = dataset_state()
    check("0. dataset starts clean", len(users0) == 0 and len(pays0) == 0
          and not admin0, f"users={len(users0)} pays={len(pays0)} admin={admin0}")
except Exception:
    print("PRE-CHECK FAILED", flush=True)
    traceback.print_exc()
    print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed: {FAIL}", flush=True)
    sys.exit(1)

# ---------------------------------------------------------------- 1. store
user = None
try:
    user = store.signup(TEST_NAME, TEST_MOBILE, TEST_PW)
    check("1a. signup returns user with trial",
          user["mobile"] == TEST_MOBILE and user["trial_ends_at"] is not None,
          f"id={user['id']}")
    wait_for("1b. signup visible on re-read",
             lambda: store.get_user_by_mobile(TEST_MOBILE) is not None)
    st0 = store.access_state(user)
    check("1c. trial state, ~3600s left",
          st0["state"] == "trial" and 3000 < st0["trial_left_s"] <= 3600,
          f"state={st0['state']} left={st0['trial_left_s']}s")
    expect_raises("1d. duplicate signup rejected",
                  lambda: store.signup("অন্য নাম", TEST_MOBILE, "otherpass123"),
                  "ইতিমধ্যে")
    expect_raises("1e. bad mobile rejected",
                  lambda: store.signup("টেস্ট", "12345", TEST_PW), "মোবাইল")
    expect_raises("1f. short password rejected",
                  lambda: store.signup("টেস্ট", "01811111111", "123"), "৬ অক্ষর")
    expect_raises("1g. short name rejected",
                  lambda: store.signup("ক", "01811111111", TEST_PW), "নাম")
    u_login = store.login(TEST_MOBILE, TEST_PW)
    check("1h. login ok", u_login["id"] == user["id"])
    expect_raises("1i. wrong password rejected",
                  lambda: store.login(TEST_MOBILE, "wrongpass"), "পাসওয়ার্ড")
    expect_raises("1j. unknown mobile login rejected",
                  lambda: store.login("01800000000", TEST_PW), "অ্যাকাউন্ট নেই")
    # Bengali-digit mobile normalises to the same account
    u_bn = store.login("০১৯৯৯৯৯৯৯৯৯", TEST_PW)
    check("1k. Bengali-digit mobile login ok", u_bn["id"] == user["id"])
    # fair-use
    rem = store.check_and_charge_chars(user["id"], len(TEXT3))
    check("1l. fair-use charge ok",
          rem == store.DAILY_CHAR_LIMIT - len(TEXT3), f"remaining={rem}")
    check("1m. daily_remaining matches",
          store.daily_remaining(store.get_user_by_id(user["id"])) == rem)
    expect_raises("1n. over-limit charge refused",
                  lambda: store.check_and_charge_chars(user["id"], 20000),
                  "সীমা শেষ")
except Exception:
    print("STORE SECTION FAILED", flush=True)
    traceback.print_exc()

# ---------------------------------------------------------------- 2. script_check
try:
    check("2a. digits_to_words ২০২৪",
          script_check.digits_to_words("২০২৪") == "দুই হাজার চব্বিশ",
          script_check.digits_to_words("২০২৪"))
    check("2b. digits_to_words ৫০",
          script_check.digits_to_words("৫০") == "পঞ্চাশ")
    check("2c. number_to_bengali_words 2024",
          script_check.number_to_bengali_words(2024) == "দুই হাজার চব্বিশ")
    # NOTE: precomposed য়/ড়/ঢ় must be built with \u escapes — typing them
    # literally in source can produce the already-decomposed sequence.
    messy = "ঢাকা\u09df আজ ২০২৪: বড়\u09dc খবর আছে... শুনুন।।। শেষ।"
    assert "\u09df" in messy and "\u09dc" in messy  # really precomposed
    fixed = script_check.check_script(messy)
    check("2d. check_script removes precomposed য়/ড়/ঢ়",
          "\u09df" not in fixed["fixed"] and "\u09dc" not in fixed["fixed"]
          and "\u09af\u09bc" in fixed["fixed"],
          fixed["fixed"][:80])
    check("2e. check_script converts ২০২৪ + colon",
          "দুই হাজার চব্বিশ" in fixed["fixed"] and ":" not in fixed["fixed"],
          fixed["fixed"][:80])
    check("2f. check_script fixes triple danda + ellipsis",
          "।।।" not in fixed["fixed"] and "…" not in fixed["fixed"])
    check("2g. check_script reports fixes", len(fixed["fixes"]) >= 2,
          f"fixes={len(fixed['fixes'])}")
    warned = script_check.check_script("এটা কি সত্যি? Hello world।")
    check("2h. check_script warns on ? and Latin",
          len(warned["warnings"]) >= 2, f"warnings={len(warned['warnings'])}")
    ok_text = script_check.check_script(S1)
    check("2i. clean script needs no fixes", len(ok_text["fixes"]) == 0,
          f"fixes={ok_text['fixes']}")
except Exception:
    print("SCRIPT_CHECK SECTION FAILED", flush=True)
    traceback.print_exc()

# ---------------------------------------------------------------- 3+4. TTS + subtitles
srt_text = ""
kiki_segments = []
kiki_wav = b""
try:
    for key in ("akib", "kiki"):
        mp, tp = tts_engine.ensure_model(key)
        check(f"3a. ensure_model {key} (local, MD5-verified)",
              mp.exists() and tp.exists(), str(mp))
    t0 = time.time()
    samples_a, info_a = tts_engine.synthesize(TEXT3, "akib", speed=1.0)
    check("3b. option1 audio-only (akib, 3 sentences)",
          info_a["duration_s"] > 5 and info_a["peak"] > 0.1,
          f"dur={info_a['duration_s']}s peak={info_a['peak']} "
          f"rtf={info_a['rtf']} parts={info_a['parts']} "
          f"({time.time() - t0:.0f}s wall)")
    t0 = time.time()
    samples_k, info_k = tts_engine.synthesize(TEXT3, "kiki", speed=1.0)
    check("3c. option1 audio-only (kiki, 3 sentences)",
          info_k["duration_s"] > 5 and info_k["peak"] > 0.1,
          f"dur={info_k['duration_s']}s peak={info_k['peak']} "
          f"rtf={info_k['rtf']} ({time.time() - t0:.0f}s wall)")
    t0 = time.time()
    s1a, info_s1 = tts_engine.synthesize(S1, "akib", speed=1.0)
    s1b, info_s1f = tts_engine.synthesize(S1, "akib", speed=1.25)
    check("3d. speed 1.25 faster than 1.0",
          info_s1f["duration_s"] < info_s1["duration_s"],
          f"1.0x={info_s1['duration_s']}s 1.25x={info_s1f['duration_s']}s")
    # option 2 — audio + SRT, both models
    t0 = time.time()
    samples2, kiki_segments, info2 = tools.synthesize_aligned(TEXT3, "kiki")
    kiki_wav = tts_engine.samples_to_wav_bytes(samples2)
    check("4a. option2 mode A (kiki): 3 segments",
          len(kiki_segments) == 3,
          f"dur={info2['duration_s']}s segs={kiki_segments} "
          f"({time.time() - t0:.0f}s wall)")
    seq_ok = all(
        kiki_segments[i]["end"] <= kiki_segments[i + 1]["start"]
        for i in range(len(kiki_segments) - 1))
    check("4b. mode A segments sequential, non-overlapping", seq_ok)
    check("4c. mode A segment texts match script",
          [s["text"] for s in kiki_segments] == [S1, S2, S3])
    srt_text = tools.to_srt(kiki_segments)
    check("4d. SRT valid (3 cues, starts 00:00:00,000)",
          srt_text.count("-->") == 3 and srt_text.startswith("1\n00:00:00,000"),
          srt_text.splitlines()[:2])
    j = json.loads(tools.to_json("kiki_talk_audio.wav", info2["duration_s"],
                                 kiki_segments, "script-to-audio",
                                 voice="Kiki Big Rerecord (কিকি বিগ রিরেকর্ড)"))
    check("4e. JSON export valid, 3 segments",
          len(j["segments"]) == 3 and j["duration_seconds"] == info2["duration_s"])
    t0 = time.time()
    samples2a, segs_a, info2a = tools.synthesize_aligned(TEXT3, "akib")
    check("4f. option2 mode A (akib): 3 segments",
          len(segs_a) == 3, f"dur={info2a['duration_s']}s "
          f"({time.time() - t0:.0f}s wall)")
    # mode B — option 3: audio + script -> SRT
    audio_b, rate_b = tools.read_wav_bytes(kiki_wav)
    segs_b, exact_b, note_b = tools.align_audio_script(audio_b, rate_b,
                                                       [S1, S2, S3])
    check("4g. option3 mode B exact align (kiki audio)",
          exact_b and len(segs_b) == 3, note_b)
    close = all(abs(segs_b[i]["start"] - kiki_segments[i]["start"]) <= 0.15
                and abs(segs_b[i]["end"] - kiki_segments[i]["end"]) <= 0.15
                for i in range(3))
    check("4h. mode B timings match mode A (±0.15s)", close,
          f"B={segs_b} A={kiki_segments}")
    # mode C — proportional
    segs_c = tools.proportional_segments([S1, S2, S3], 60.0)
    total_c = segs_c[-1]["end"] if segs_c else 0
    check("4i. mode C proportional sums to 60.0s",
          len(segs_c) == 3 and abs(total_c - 60.0) < 0.01,
          f"sum={total_c}")
    # fair-use charge like the app does on generate
    rem2 = store.check_and_charge_chars(user["id"], len(TEXT3))
    check("4j. app-style fair-use charge on generate",
          rem2 == store.DAILY_CHAR_LIMIT - 2 * len(TEXT3), f"remaining={rem2}")
except Exception:
    print("TTS/SUBTITLE SECTION FAILED", flush=True)
    traceback.print_exc()

# ---------------------------------------------------------------- 1b. payments + admin
try:
    pay = store.submit_payment(user, "TEST9HX7K2PQR1", 50, FAKE_PNG, "png")
    check("1o. payment submit (txn + screenshot)",
          pay["status"] == "pending" and pay["screenshot_path"] is not None,
          f"id={pay['id']} shot={pay['screenshot_path']}")
    wait_for("1p. payment visible on re-read",
             lambda: any(p["id"] == pay["id"]
                         for p in store.list_payments(status="pending")))
    img_back = store.download_screenshot(pay["screenshot_path"])
    check("1q. screenshot round-trips byte-identical", img_back == FAKE_PNG)
    expect_raises("1r. payment needs txn or screenshot",
                  lambda: store.submit_payment(user, "", 50, None), "ট্রানজাকশন")
    expect_raises("1s. payment needs positive amount",
                  lambda: store.submit_payment(user, "X1", 0, None), "অ্যামাউন্ট")
    check("1t. admin not set up yet", not store.admin_is_set_up())
    expect_raises("1u. admin password needs 8+ chars",
                  lambda: store.admin_set_password("short"), "৮ অক্ষর")
    store.admin_set_password(ADMIN_PW)
    check("1v. admin password set", store.admin_is_set_up())
    check("1w. admin wrong password rejected",
          not store.admin_check_password("wrongadmin"))
    check("1x. admin right password accepted",
          store.admin_check_password(ADMIN_PW))
    expect_raises("1y. admin password cannot be set twice",
                  lambda: store.admin_set_password("anotherpass123"), "আগেই")
    res = store.decide_payment(pay["id"], approve=True)
    check("1z. admin approve payment", res["status"] == "approved")
    expect_raises("1aa. decided payment cannot be re-decided",
                  lambda: store.decide_payment(pay["id"], approve=True), "আগেই")
    wait_for("1ab. user active after approval",
             lambda: store.access_state(
                 store.get_user_by_id(user["id"]))["state"] == "active")
    st1 = store.access_state(store.get_user_by_id(user["id"]))
    check("1ac. 30-day expiry set",
          st1["has_access"] and st1["sub_left_days"] in (29, 30)
          and st1["sub_left_hours"] > 600,
          f"days={st1['sub_left_days']} hours={st1['sub_left_hours']}")
    pay2 = store.submit_payment(user, "TESTREJECT1", 50, None, "png")
    res2 = store.decide_payment(pay2["id"], approve=False)
    check("1ad. admin reject path", res2["status"] == "rejected")
    st2 = store.access_state(store.get_user_by_id(user["id"]))
    check("1ae. reject does not remove active subscription",
          st2["state"] == "active")
    store.change_password(user["id"], TEST_PW, NEW_PW)
    check("1af. user change password + login with new",
          store.login(TEST_MOBILE, NEW_PW)["id"] == user["id"])
    expect_raises("1ag. old password dead after change",
                  lambda: store.login(TEST_MOBILE, TEST_PW), "পাসওয়ার্ড")
    store.admin_set_user_password(user["id"], TEST_PW)
    check("1ah. admin resets user password",
          store.login(TEST_MOBILE, TEST_PW)["id"] == user["id"])
    store.set_user_active(user["id"], False)
    st3 = store.access_state(store.get_user_by_id(user["id"]))
    check("1ai. blocked user has no access",
          st3["state"] == "blocked" and not st3["has_access"])
    store.set_user_active(user["id"], True)
    check("1aj. unblocked user active again",
          store.access_state(store.get_user_by_id(user["id"]))["state"] == "active")
except Exception:
    print("PAYMENT/ADMIN SECTION FAILED", flush=True)
    traceback.print_exc()

# ---------------------------------------------------------------- 5. app.py + landing
try:
    import py_compile
    py_compile.compile("app.py", doraise=True)
    check("5a. app.py compiles", True)
    import app as kiki_app
    check("5b. app.py imports", True)
    check("5c. payment placeholder intact (01XXXXXXXXX)",
          kiki_app.BKASH_NUMBER == "01XXXXXXXXX"
          and kiki_app.NAGAD_NUMBER == "01XXXXXXXXX")
    check("5d. demo wav files present",
          kiki_app.DEMO_AKIB.exists() and kiki_app.DEMO_KIKI.exists())
    check("5e. model labels sane",
          tts_engine.MODELS["akib"]["label"].startswith("মডেল ১")
          and tts_engine.MODELS["kiki"]["label"].startswith("মডেল ২"))
    landing = Path("landing")
    idx = (landing / "index.html").read_text(encoding="utf-8")
    check("5f. landing has 5 STREAMLIT_APP_URL CTA links",
          idx.count('href="STREAMLIT_APP_URL"') == 5,
          f"hrefs={idx.count(chr(34) + 'STREAMLIT_APP_URL' + chr(34))} "
          f"total_occurrences={idx.count('STREAMLIT_APP_URL')}")
    vj = json.loads((landing / "vercel.json").read_text(encoding="utf-8"))
    check("5g. vercel.json valid", isinstance(vj, dict))
    for f in ("style.css", "script.js"):
        p = landing / f
        check(f"5h. landing/{f} non-empty", p.exists() and p.stat().st_size > 100)
    def _md5(p):
        return hashlib.md5(Path(p).read_bytes()).hexdigest()
    check("5i. landing demo audio = HF URLs (binaries live on HF, "
          "GitHub push is text-only)",
          "https://huggingface.co/demoqqq/banglatts-akib/resolve/main/demo_akib.wav"
          in idx
          and "https://huggingface.co/demoqqq/banglatts-kiki-big-rerecord/resolve/main/demo_kiki.wav"
          in idx
          and "audio/demo_akib.wav" not in idx
          and _md5(landing / "audio" / "demo_akib.wav")
          == _md5("assets/demo_akib.wav")
          and _md5(landing / "audio" / "demo_kiki_big_rerecord.wav")
          == _md5("assets/demo_kiki.wav"))
    check("5j. demo wavs match original samples",
          _md5("assets/demo_akib.wav")
          == "1bc6794a822f198f4a76c1b21c1875ef"
          and _md5("assets/demo_kiki.wav")
          == "34a960a8c67468c7d03423336b11a7b3")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "demo_akib.wav"
        got = kiki_app.ensure_demo_wav("akib", dest=dest)
        check("5k. ensure_demo_wav downloads from HF (verified)",
              got is not None and got.exists()
              and _md5(got) == "1bc6794a822f198f4a76c1b21c1875ef",
              f"got={got}")
        got2 = kiki_app.ensure_demo_wav("akib", dest=dest)
        check("5l. ensure_demo_wav reuses local file",
              got2 is not None and got2 == dest)
except Exception:
    print("APP/LANDING SECTION FAILED", flush=True)
    traceback.print_exc()

# ---------------------------------------------------------------- 7. cleanup
print("=== cleanup ===", flush=True)
try:
    cleanup_test_data()
    users_f, pays_f, admin_f = dataset_state()
    check("7a. cleanup: 0 users", len(users_f) == 0, f"users={len(users_f)}")
    check("7b. cleanup: 0 payments", len(pays_f) == 0, f"pays={len(pays_f)}")
    check("7c. cleanup: admin reset", not admin_f)
    # screenshots dir should be empty of test files
    api = store._api()
    files = api.list_repo_files(repo_id=store.REPO_ID, repo_type="dataset")
    shots = [f for f in files if f.startswith("screenshots/")]
    check("7d. cleanup: no leftover screenshots", len(shots) == 0, str(shots))
except Exception:
    print("CLEANUP FAILED", flush=True)
    traceback.print_exc()

print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed", flush=True)
if FAIL:
    print("FAILED: " + ", ".join(FAIL), flush=True)
    sys.exit(1)
print("ALL TESTS PASSED", flush=True)
