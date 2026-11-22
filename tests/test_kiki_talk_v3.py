# -*- coding: utf-8 -*-
"""Kiki Talk v3 test — admin features (2026-11-22).

Covers the three features added after the 78/78 v2 run:
  1. admin-editable payment settings (settings.json): read/write,
     validation, payment page uses saved values
  2. admin-manageable packages (packages.json): defaults, add/edit/
     deactivate/reactivate, payment with a chosen package, approve
     activates that package's days (7-day + 30-day fallback)
  3. trial-abuse detection: IP + User-Agent capture on signup/login,
     same-IP grouping, max-trials-per-IP limit (3rd trial denied but
     signup allowed), admin grant_trial, block/unblock

Uses the REAL private HF dataset demoqqq/kiki-talk-data. No TTS here —
pure store + app-import checks, so it runs fast. Never prints any token.
"""
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

MOBILES = ["01911111111", "01922222222", "01933333333", "01944444444",
           "01955555555"]
TEST_PW = "testpass123"
IP_A = "203.0.113.10"
IP_B = "203.0.113.20"
IP_LOGIN = "203.0.113.99"

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
    """Remove every trace of v3 test users/payments; reset admin, settings,
    packages to defaults."""
    api = store._api()
    users, pays, _ = dataset_state()
    test_pays = [p for p in pays if p.get("mobile") in MOBILES]
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
                                if p.get("mobile") not in MOBILES]
        store.update_json("payments.json", _drop_pays)

    def _drop_users(data):
        data["users"] = [u for u in data.get("users", [])
                         if u.get("mobile") not in MOBILES]
    store.update_json("users.json", _drop_users)
    store.save_json("admin.json", {"salt": None, "password_hash": None})
    store.save_json("settings.json", store.DEFAULT_SETTINGS)
    store.save_json("packages.json", {"packages": store.DEFAULT_PACKAGES})


print("=== Kiki Talk v3 test — admin features — starting ===", flush=True)

# ---------------------------------------------------------------- 0. pre-check
try:
    users0, pays0, admin0 = dataset_state()
    print(f"pre-check: users={len(users0)} payments={len(pays0)} admin_set={admin0}",
          flush=True)
    cleanup_test_data()
    users0, pays0, admin0 = dataset_state()
    check("0a. no v3 test users/payments exist yet (other accounts, e.g. "
          "the live deploy test user, are out of scope)",
          not any(u.get("mobile") in MOBILES for u in users0)
          and not any(p.get("mobile") in MOBILES for p in pays0)
          and not admin0,
          f"users={len(users0)} pays={len(pays0)} admin={admin0}")
    s0 = store.get_settings()
    check("0b. settings at defaults",
          s0["bkash_number"] == "01XXXXXXXXX"
          and s0["max_trials_per_ip"] == 2,
          str(s0)[:120])
    p0 = store.get_packages()
    check("0c. packages at defaults (3 active)",
          len(p0) == 3 and len(store.get_active_packages()) == 3
          and p0[0]["days"] == 7 and p0[1]["days"] == 30 and p0[2]["days"] == 60,
          str([(p["name"], p["days"], p["price"]) for p in p0]))
except Exception:
    print("PRE-CHECK FAILED", flush=True)
    traceback.print_exc()
    print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed: {FAIL}", flush=True)
    sys.exit(1)

# ---------------------------------------------------------------- 1. settings
try:
    saved = store.save_settings({
        "bkash_number": "01712345678",
        "nagad_number": "01812345678",
        "instructions": "১. নম্বর কপি করুন।\n২. Send Money করুন।",
        "max_trials_per_ip": 2,
    })
    check("1a. save_settings ok",
          saved["bkash_number"] == "01712345678"
          and saved["nagad_number"] == "01812345678")
    wait_for("1b. settings visible on re-read",
             lambda: store.get_settings()["bkash_number"] == "01712345678")
    s1 = store.get_settings()
    check("1c. instructions saved",
          "নম্বর কপি করুন" in s1["instructions"]
          and s1["max_trials_per_ip"] == 2)
    expect_raises("1d. bad bkash number rejected",
                  lambda: store.save_settings({
                      "bkash_number": "123", "nagad_number": "01812345678",
                      "instructions": "x", "max_trials_per_ip": 2}), "বিকাশ")
    expect_raises("1e. bad nagad number rejected",
                  lambda: store.save_settings({
                      "bkash_number": "01712345678", "nagad_number": "999",
                      "instructions": "x", "max_trials_per_ip": 2}), "নগদ")
    expect_raises("1f. max_trials_per_ip 11 rejected",
                  lambda: store.save_settings({
                      "bkash_number": "01712345678", "nagad_number": "01812345678",
                      "instructions": "x", "max_trials_per_ip": 11}), "০ থেকে ১০")
    expect_raises("1g. max_trials_per_ip -1 rejected",
                  lambda: store.save_settings({
                      "bkash_number": "01712345678", "nagad_number": "01812345678",
                      "instructions": "x", "max_trials_per_ip": -1}), "০ থেকে ১০")
    saved2 = store.save_settings({
        "bkash_number": "", "nagad_number": "",
        "instructions": "  ", "max_trials_per_ip": 2,
    })
    check("1h. empty numbers/instructions fall back to defaults",
          saved2["bkash_number"] == "01XXXXXXXXX"
          and saved2["instructions"] == store.DEFAULT_INSTRUCTIONS)
    # restore the custom numbers for the payment-page checks below
    store.save_settings({
        "bkash_number": "01712345678", "nagad_number": "01812345678",
        "instructions": "১. নম্বর কপি করুন।\n২. Send Money করুন।",
        "max_trials_per_ip": 2,
    })
    wait_for("1i. settings restored on re-read",
             lambda: store.get_settings()["bkash_number"] == "01712345678")
except Exception:
    print("SETTINGS SECTION FAILED", flush=True)
    traceback.print_exc()

# ---------------------------------------------------------------- 2. packages
pkg_3d = None
try:
    pkg_3d = store.add_package("৩ দিন", 3, 10)
    check("2a. add package ৩ দিন",
          pkg_3d["days"] == 3 and pkg_3d["price"] == 10 and pkg_3d["active"],
          str(pkg_3d))
    wait_for("2b. new package visible on re-read",
             lambda: store.get_package(pkg_3d["id"]) is not None)
    upd = store.update_package("pkg_7d", price=25)
    check("2c. edit 7-day package price to 25",
          upd["price"] == 25 and upd["days"] == 7)
    wait_for("2d. edited price visible on re-read",
             lambda: store.get_package("pkg_7d")["price"] == 25)
    expect_raises("2e. add package with 0 days rejected",
                  lambda: store.add_package("শূন্য দিন", 0, 10), "মেয়াদ")
    expect_raises("2f. add package with 0 price rejected",
                  lambda: store.add_package("ফ্রি", 3, 0), "দাম")
    expect_raises("2g. add package with short name rejected",
                  lambda: store.add_package("ক", 3, 10), "নাম")
    expect_raises("2h. update missing package rejected",
                  lambda: store.update_package("pkg_nope", price=99), "পাওয়া যায়নি")
    store.set_package_active("pkg_60d", False)
    wait_for("2i. deactivated 60-day package leaves active list",
             lambda: len(store.get_active_packages()) == 3
             and store.get_package("pkg_60d")["active"] is False)
    check("2j. active packages are 7d/30d/3d after deactivation",
          sorted(p["id"] for p in store.get_active_packages())
          == sorted(["pkg_7d", "pkg_30d", pkg_3d["id"]]),
          str([p["id"] for p in store.get_active_packages()]))
    store.set_package_active("pkg_60d", True)
    wait_for("2k. reactivated 60-day package back in active list",
             lambda: len(store.get_active_packages()) == 4)
except Exception:
    print("PACKAGES SECTION FAILED", flush=True)
    traceback.print_exc()

# ---------------------------------------------------------------- 3. IP / trial
user_a = user_b = user_c = user_d = user_e = None
try:
    user_a = store.signup("ইউজার এ", MOBILES[0], TEST_PW,
                          client_ip=IP_A, user_agent="TestAgent/1.0")
    check("3a. signup A records IP + UA, trial granted",
          user_a.get("first_ip") == IP_A and user_a.get("last_ip") == IP_A
          and user_a.get("first_user_agent") == "TestAgent/1.0"
          and user_a.get("trial_granted") is True,
          f"first_ip={user_a.get('first_ip')} trial={user_a.get('trial_granted')}")
    user_b = store.signup("ইউজার বি", MOBILES[1], TEST_PW, client_ip=IP_A)
    check("3b. signup B same IP gets 2nd trial",
          user_b.get("trial_granted") is True
          and user_b.get("first_ip") == IP_A)
    user_c = store.signup("ইউজার সি", MOBILES[2], TEST_PW, client_ip=IP_A)
    check("3c. signup C same IP allowed but NO trial (limit 2)",
          user_c.get("trial_granted") is False,
          f"trial={user_c.get('trial_granted')}")
    st_c = store.access_state(store.get_user_by_id(user_c["id"]))
    check("3d. no-trial user has no access (expired)",
          st_c["state"] == "expired" and not st_c["has_access"],
          f"state={st_c['state']}")
    user_d = store.signup("ইউজার ডি", MOBILES[3], TEST_PW, client_ip=IP_B)
    check("3e. different IP unaffected — trial granted",
          user_d.get("trial_granted") is True)
    u_b2 = store.login(MOBILES[1], TEST_PW, client_ip=IP_LOGIN,
                       user_agent="TestAgent/2.0")
    check("3f. login updates last_ip + last UA, keeps first_ip",
          u_b2.get("last_ip") == IP_LOGIN
          and u_b2.get("first_ip") == IP_A
          and u_b2.get("last_user_agent") == "TestAgent/2.0",
          f"last_ip={u_b2.get('last_ip')} first_ip={u_b2.get('first_ip')}")
    groups = store.same_ip_groups()
    check("3g. same-IP grouping flags the 3-account cluster",
          len(groups) == 1 and groups[0]["ip"] == IP_A
          and len(groups[0]["users"]) == 3,
          f"groups={[(g['ip'], len(g['users'])) for g in groups]}")
    check("3h. group members are A, B, C",
          sorted(u["mobile"] for u in groups[0]["users"])
          == sorted(MOBILES[:3]))
    store.grant_trial(user_c["id"])
    wait_for("3i. admin grant_trial gives C a trial again",
             lambda: store.access_state(
                 store.get_user_by_id(user_c["id"]))["state"] == "trial")
    st_c2 = store.access_state(store.get_user_by_id(user_c["id"]))
    check("3j. granted trial has ~3600s left",
          3000 < st_c2["trial_left_s"] <= 3600,
          f"left={st_c2['trial_left_s']}s")
    user_e = store.signup("ইউজার ই", MOBILES[4], TEST_PW, client_ip=IP_A)
    check("3k. 4th signup same IP still gets no trial (count is now 3)",
          user_e.get("trial_granted") is False)
    expect_raises("3l. duplicate mobile still rejected",
                  lambda: store.signup("আবার এ", MOBILES[0], TEST_PW), "ইতিমধ্যে")
    expect_raises("3m. wrong password still rejected",
                  lambda: store.login(MOBILES[0], "wrongpass"), "পাসওয়ার্ড")
    store.set_user_active(user_e["id"], False)
    check("3n. admin block works on suspicious account",
          store.access_state(
              store.get_user_by_id(user_e["id"]))["state"] == "blocked")
    store.set_user_active(user_e["id"], True)
    check("3o. admin unblock restores (still expired, no trial)",
          store.access_state(
              store.get_user_by_id(user_e["id"]))["state"] == "expired")
except Exception:
    print("IP/TRIAL SECTION FAILED", flush=True)
    traceback.print_exc()

# ---------------------------------------------------------------- 4. payment with package
try:
    pay_a = store.submit_payment(user_a, "TEST7D111", 25, None, "png",
                                 package_id="pkg_7d")
    check("4a. payment records chosen 7-day package",
          pay_a["package_id"] == "pkg_7d"
          and pay_a["package_name"] == "১ সপ্তাহ"
          and pay_a["package_days"] == 7,
          str({k: pay_a.get(k) for k in ("package_name", "package_days")}))
    res_a = store.decide_payment(pay_a["id"], approve=True)
    check("4b. approve returns 7 days", res_a.get("days") == 7,
          str(res_a))
    wait_for("4c. user A active after 7-day approval",
             lambda: store.access_state(
                 store.get_user_by_id(user_a["id"]))["state"] == "active")
    st_a = store.access_state(store.get_user_by_id(user_a["id"]))
    check("4d. 7-day expiry set (6-7 days left)",
          st_a["sub_left_days"] in (6, 7) and 150 < st_a["sub_left_hours"] <= 168,
          f"days={st_a['sub_left_days']} hours={st_a['sub_left_hours']}")
    pay_b = store.submit_payment(user_b, "TEST30D11", 50, None, "png")
    check("4e. payment without package still works",
          pay_b["package_id"] is None and pay_b["status"] == "pending")
    res_b = store.decide_payment(pay_b["id"], approve=True)
    check("4f. no-package approve falls back to 30 days",
          res_b.get("days") == 30, str(res_b))
    st_b = store.access_state(store.get_user_by_id(user_b["id"]))
    check("4g. 30-day fallback expiry set",
          st_b["sub_left_days"] in (29, 30) and st_b["sub_left_hours"] > 600,
          f"days={st_b['sub_left_days']} hours={st_b['sub_left_hours']}")
    expect_raises("4h. payment with unknown package rejected",
                  lambda: store.submit_payment(user_d, "TESTBAD1", 50, None,
                                               "png", package_id="pkg_nope"),
                  "পাওয়া যায়নি")
    store.set_package_active("pkg_60d", False)
    wait_for("4i. 60-day package deactivated for the test",
             lambda: store.get_package("pkg_60d")["active"] is False)
    expect_raises("4j. payment with deactivated package rejected",
                  lambda: store.submit_payment(user_d, "TEST60D1", 90, None,
                                               "png", package_id="pkg_60d"),
                  "বন্ধ আছে")
    store.set_package_active("pkg_60d", True)
    wait_for("4k. 60-day package reactivated",
             lambda: store.get_package("pkg_60d")["active"] is True)
except Exception:
    print("PACKAGE PAYMENT SECTION FAILED", flush=True)
    traceback.print_exc()

# ---------------------------------------------------------------- 5. app.py
try:
    import py_compile
    py_compile.compile("app.py", doraise=True)
    check("5a. app.py compiles", True)
    import app as kiki_app
    check("5b. app.py imports", True)
    check("5c. payment placeholder constants intact (fallback)",
          kiki_app.BKASH_NUMBER == "01XXXXXXXXX"
          and kiki_app.NAGAD_NUMBER == "01XXXXXXXXX")
    ip, ua = kiki_app.client_info()
    check("5d. client_info() safe outside a Streamlit run",
          ip == "unknown" and ua == "", f"ip={ip} ua={ua!r}")
    src = open("app.py", encoding="utf-8").read()
    check("5e. admin panel has payment-settings section",
          "পেমেন্ট সেটিংস" in src)
    check("5f. admin panel has packages section",
          "📦 প্যাকেজ" in src)
    check("5g. admin panel has suspicious-accounts section",
          "সন্দেহজনক অ্যাকাউন্ট" in src)
    check("5h. payment page reads settings + packages from store",
          "store.get_settings()" in src
          and "store.get_active_packages()" in src)
    check("5i. payment submit passes the chosen package",
          "package_id=chosen" in src)
    check("5j. signup/login pass client info to store",
          "client_info()" in src and "client_ip=ip" in src)
except Exception:
    print("APP SECTION FAILED", flush=True)
    traceback.print_exc()

# ---------------------------------------------------------------- 6. cleanup
print("=== cleanup ===", flush=True)
try:
    cleanup_test_data()
    users_f, pays_f, admin_f = dataset_state()
    check("6a. cleanup: no v3 test users remain",
          not any(u.get("mobile") in MOBILES for u in users_f),
          f"users={len(users_f)}")
    check("6b. cleanup: no v3 test payments remain",
          not any(p.get("mobile") in MOBILES for p in pays_f),
          f"pays={len(pays_f)}")
    check("6c. cleanup: admin reset", not admin_f)
    s_f = store.get_settings()
    check("6d. cleanup: settings back to defaults",
          s_f == store.DEFAULT_SETTINGS, str(s_f)[:120])
    p_f = store.get_packages()
    check("6e. cleanup: packages back to defaults",
          p_f == store.DEFAULT_PACKAGES, str(p_f)[:160])
    api = store._api()
    files = api.list_repo_files(repo_id=store.REPO_ID, repo_type="dataset")
    shots = [f for f in files if f.startswith("screenshots/")]
    check("6f. cleanup: no leftover screenshots", len(shots) == 0, str(shots))
except Exception:
    print("CLEANUP FAILED", flush=True)
    traceback.print_exc()

print(f"RESULT: {len(PASS)} passed, {len(FAIL)} failed", flush=True)
if FAIL:
    print("FAILED: " + ", ".join(FAIL), flush=True)
    sys.exit(1)
print("ALL TESTS PASSED", flush=True)
