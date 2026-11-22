# -*- coding: utf-8 -*-
"""Persistent storage for Kiki Talk (কিকি টক).

Data lives in a PRIVATE Hugging Face dataset repo (demoqqq/kiki-talk-data)
as small JSON files — it survives Streamlit Community Cloud restarts, costs
nothing, and needs no server or Google Cloud Console step.

Files in the repo:
  users.json    — signup accounts (name, mobile, password hash, trial /
                  subscription state, daily fair-use counter)
  payments.json — manual bKash/Nagad payment submissions
  admin.json    — admin password hash (set on first admin visit, never
                  hard-coded, never in this repo)
  screenshots/  — payment screenshots uploaded by users

The app authenticates to Hugging Face with a write token stored in
Streamlit secrets as HF_TOKEN (set during deploy; see README.md).
Locally, HF_TOKEN can be given as an environment variable.

NOTE on concurrency: writes are whole-file uploads (read-modify-write).
That is fine for a small user base; two admins approving at the exact
same second could in theory overwrite each other. The admin panel is
single-owner, so this is accepted for launch.
"""

import hashlib
import io
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ID = "demoqqq/kiki-talk-data"
REPO_TYPE = "dataset"

TRIAL_SECONDS = 3600            # 1-hour free trial, from signup
SUBSCRIPTION_DAYS = 30          # approval -> 30 days unlimited
DAILY_CHAR_LIMIT = 20000        # fair-use: chars per user per day
PRICE_TAKA = 50

_DHAKA = timezone(timedelta(hours=6))


def _token() -> str:
    """HF write token: Streamlit secret first, env var for local tests."""
    try:
        import streamlit as st

        tok = st.secrets.get("HF_TOKEN")
        if tok:
            return str(tok)
    except Exception:
        pass
    tok = os.environ.get("HF_TOKEN")
    if not tok:
        raise RuntimeError(
            "HF_TOKEN পাওয়া যায়নি — Streamlit secrets-এ HF_TOKEN বসাতে হবে "
            "(ডেপ্লয়ের সময়; দেখুন README.md)।"
        )
    return tok


def _api():
    from huggingface_hub import HfApi

    return HfApi(token=_token())


def now() -> datetime:
    return datetime.now(_DHAKA)


def now_iso() -> str:
    return now().isoformat(timespec="seconds")


def today_str() -> str:
    return now().date().isoformat()


def _parse_iso(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_DHAKA)
        return dt
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Low-level JSON file access
# ---------------------------------------------------------------------------

def load_json(name: str) -> dict:
    """Download + parse one JSON file from the dataset repo."""
    from huggingface_hub import hf_hub_download

    path = hf_hub_download(repo_id=REPO_ID, filename=name,
                           repo_type=REPO_TYPE, token=_token())
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(name: str, data: dict, retries: int = 3) -> None:
    """Upload one JSON file to the dataset repo (whole-file overwrite)."""
    payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    last_exc = None
    for _ in range(retries):
        try:
            _api().upload_file(
                path_or_fileobj=io.BytesIO(payload),
                path_in_repo=name,
                repo_id=REPO_ID,
                repo_type=REPO_TYPE,
            )
            return
        except Exception as exc:  # noqa: BLE001 - retry transient failures
            last_exc = exc
    raise RuntimeError(f"{name} সেভ করা যায়নি: {last_exc}")


def update_json(name: str, mutate, retries: int = 3) -> dict:
    """Read-modify-write one JSON file; mutate(data) edits it in place.
    Retries the whole cycle on transient errors."""
    last_exc = None
    for _ in range(retries):
        try:
            data = load_json(name)
            mutate(data)
            save_json(name, data, retries=1)
            return data
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
    raise RuntimeError(f"{name} আপডেট করা যায়নি: {last_exc}")


# ---------------------------------------------------------------------------
# Passwords (PBKDF2-HMAC-SHA256, per-user salt; only hashes are stored)
# ---------------------------------------------------------------------------

def hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    salt_hex = salt_hex or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                             bytes.fromhex(salt_hex), 200_000)
    return salt_hex, dk.hex()


def check_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    try:
        _, candidate = hash_password(password, salt_hex)
        return secrets.compare_digest(candidate, hash_hex)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

_BN_DIGITS = "০১২৩৪৫৬৭৮৯"
_EN_DIGITS = "0123456789"


def normalize_mobile(mobile: str) -> str:
    """Bengali digits -> ASCII, strip spaces/dashes. Returns the 11-digit form."""
    m = (mobile or "").strip()
    m = m.translate(str.maketrans(_BN_DIGITS, _EN_DIGITS))
    m = m.replace(" ", "").replace("-", "")
    if m.startswith("+880"):
        m = "0" + m[4:]
    elif m.startswith("880"):
        m = "0" + m[3:]
    return m


def valid_mobile(mobile: str) -> bool:
    m = normalize_mobile(mobile)
    return len(m) == 11 and m.startswith("01") and m.isdigit()


def get_user_by_mobile(mobile: str) -> dict | None:
    m = normalize_mobile(mobile)
    data = load_json("users.json")
    for u in data.get("users", []):
        if u.get("mobile") == m:
            return u
    return None


def get_user_by_id(user_id: str) -> dict | None:
    data = load_json("users.json")
    for u in data.get("users", []):
        if u.get("id") == user_id:
            return u
    return None


def signup(name: str, mobile: str, password: str) -> dict:
    """Create an account and start the 1-hour free trial immediately."""
    name = (name or "").strip()
    mobile = normalize_mobile(mobile)
    if len(name) < 2:
        raise ValueError("নাম লিখুন।")
    if not valid_mobile(mobile):
        raise ValueError("সঠিক মোবাইল নম্বর দিন (যেমন 01XXXXXXXXX)।")
    if len(password) < 6:
        raise ValueError("পাসওয়ার্ড কমপক্ষে ৬ অক্ষরের হতে হবে।")
    if get_user_by_mobile(mobile) is not None:
        raise ValueError("এই নম্বর দিয়ে ইতিমধ্যে অ্যাকাউন্ট খোলা আছে — লগইন করুন।")
    salt, pw_hash = hash_password(password)
    started = now()
    user = {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "mobile": mobile,
        "salt": salt,
        "password_hash": pw_hash,
        "created_at": started.isoformat(timespec="seconds"),
        "trial_started_at": started.isoformat(timespec="seconds"),
        "trial_ends_at": (started + timedelta(seconds=TRIAL_SECONDS)).isoformat(timespec="seconds"),
        "expires_at": None,
        "active": True,
        "daily_chars_used": 0,
        "daily_chars_date": today_str(),
    }

    def _add(data):
        data.setdefault("users", []).append(user)

    update_json("users.json", _add)
    return user


def login(mobile: str, password: str) -> dict:
    user = get_user_by_mobile(mobile)
    if user is None:
        raise ValueError("এই নম্বরে কোনো অ্যাকাউন্ট নেই — আগে সাইন আপ করুন।")
    if not check_password(password, user["salt"], user["password_hash"]):
        raise ValueError("পাসওয়ার্ড ভুল হয়েছে।")
    return user


def change_password(user_id: str, old_password: str, new_password: str) -> None:
    if len(new_password) < 6:
        raise ValueError("নতুন পাসওয়ার্ড কমপক্ষে ৬ অক্ষরের হতে হবে।")

    def _change(data):
        for u in data.get("users", []):
            if u.get("id") == user_id:
                if not check_password(old_password, u["salt"], u["password_hash"]):
                    raise ValueError("পুরনো পাসওয়ার্ড ভুল হয়েছে।")
                u["salt"], u["password_hash"] = hash_password(new_password)
                return
        raise ValueError("অ্যাকাউন্ট পাওয়া যায়নি।")

    update_json("users.json", _change)


def admin_set_user_password(user_id: str, new_password: str) -> None:
    """Admin resets a user's password (e.g. when the user forgot it)."""
    if len(new_password) < 6:
        raise ValueError("পাসওয়ার্ড কমপক্ষে ৬ অক্ষরের হতে হবে।")

    def _set(data):
        for u in data.get("users", []):
            if u.get("id") == user_id:
                u["salt"], u["password_hash"] = hash_password(new_password)
                return
        raise ValueError("অ্যাকাউন্ট পাওয়া যায়নি।")

    update_json("users.json", _set)


def set_user_active(user_id: str, active: bool) -> None:
    def _set(data):
        for u in data.get("users", []):
            if u.get("id") == user_id:
                u["active"] = active
                return
        raise ValueError("অ্যাকাউন্ট পাওয়া যায়নি।")

    update_json("users.json", _set)


def access_state(user: dict) -> dict:
    """Trial / subscription state for one user (computed from stored times)."""
    t = now()
    trial_end = _parse_iso(user.get("trial_ends_at"))
    expires = _parse_iso(user.get("expires_at"))
    trial_left_s = 0
    if trial_end and t < trial_end:
        trial_left_s = int((trial_end - t).total_seconds())
    sub_left_days = 0
    if expires and t < expires:
        sub_left_days = (expires - t).days
        if (expires - t).total_seconds() > 0 and sub_left_days == 0:
            sub_left_days = 0  # less than a day left; show hours instead
    has_access = bool(user.get("active", True)) and (trial_left_s > 0 or
                                                     (expires is not None and t < expires))
    if not user.get("active", True):
        state = "blocked"
    elif expires is not None and t < expires:
        state = "active"
    elif trial_left_s > 0:
        state = "trial"
    else:
        state = "expired"
    return {
        "state": state,  # trial | active | expired | blocked
        "has_access": has_access,
        "trial_left_s": trial_left_s,
        "trial_ends_at": user.get("trial_ends_at"),
        "expires_at": user.get("expires_at"),
        "sub_left_days": sub_left_days,
        "sub_left_hours": int(((expires - t).total_seconds()) // 3600) if expires and t < expires else 0,
    }


def check_and_charge_chars(user_id: str, chars: int) -> int:
    """Fair-use: charge `chars` against today's limit. Raises if over limit.
    Returns remaining chars today."""
    today = today_str()

    def _charge(data):
        for u in data.get("users", []):
            if u.get("id") == user_id:
                if u.get("daily_chars_date") != today:
                    u["daily_chars_date"] = today
                    u["daily_chars_used"] = 0
                used = int(u.get("daily_chars_used", 0))
                if used + chars > DAILY_CHAR_LIMIT:
                    raise ValueError(
                        f"আজকের সীমা শেষ (দৈনিক {DAILY_CHAR_LIMIT:,} অক্ষর)। "
                        "আগামীকাল আবার ব্যবহার করতে পারবেন।"
                    )
                u["daily_chars_used"] = used + chars
                return
        raise ValueError("অ্যাকাউন্ট পাওয়া যায়নি।")

    update_json("users.json", _charge)
    fresh = get_user_by_id(user_id) or {}
    return DAILY_CHAR_LIMIT - int(fresh.get("daily_chars_used", 0))


def daily_remaining(user: dict) -> int:
    if user.get("daily_chars_date") != today_str():
        return DAILY_CHAR_LIMIT
    return max(0, DAILY_CHAR_LIMIT - int(user.get("daily_chars_used", 0)))


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

def submit_payment(user: dict, txn_id: str, amount: int,
                   screenshot_bytes: bytes | None, screenshot_ext: str = "png") -> dict:
    """Record a manual payment submission. Needs txn ID and/or a screenshot."""
    txn_id = (txn_id or "").strip()
    if not txn_id and not screenshot_bytes:
        raise ValueError("ট্রানজাকশন আইডি অথবা স্ক্রিনশট — যেকোনো একটা দিন।")
    if amount <= 0:
        raise ValueError("অ্যামাউন্ট সঠিক নয়।")
    payment = {
        "id": uuid.uuid4().hex[:12],
        "user_id": user["id"],
        "name": user["name"],
        "mobile": user["mobile"],
        "txn_id": txn_id,
        "amount": int(amount),
        "screenshot_path": None,
        "status": "pending",
        "submitted_at": now_iso(),
        "decided_at": None,
    }
    if screenshot_bytes:
        path_in_repo = f"screenshots/{payment['id']}.{screenshot_ext}"
        _api().upload_file(
            path_or_fileobj=io.BytesIO(screenshot_bytes),
            path_in_repo=path_in_repo,
            repo_id=REPO_ID,
            repo_type=REPO_TYPE,
        )
        payment["screenshot_path"] = path_in_repo

    def _add(data):
        data.setdefault("payments", []).append(payment)

    update_json("payments.json", _add)
    return payment


def list_payments(status: str | None = None) -> list[dict]:
    data = load_json("payments.json")
    pays = data.get("payments", [])
    pays.sort(key=lambda p: p.get("submitted_at", ""), reverse=True)
    if status:
        pays = [p for p in pays if p.get("status") == status]
    return pays


def list_user_payments(user_id: str) -> list[dict]:
    return [p for p in list_payments() if p.get("user_id") == user_id]


def download_screenshot(path_in_repo: str) -> bytes:
    from huggingface_hub import hf_hub_download

    local = hf_hub_download(repo_id=REPO_ID, filename=path_in_repo,
                            repo_type=REPO_TYPE, token=_token())
    return Path(local).read_bytes()


def decide_payment(payment_id: str, approve: bool) -> dict:
    """Admin decision. Approving activates 30 days unlimited from now."""
    decided = now()
    target_user_id = None
    target_status = None

    def _decide(data):
        nonlocal target_user_id, target_status
        for p in data.get("payments", []):
            if p.get("id") == payment_id:
                if p.get("status") != "pending":
                    raise ValueError("এই পেমেন্টের সিদ্ধান্ত আগেই নেওয়া হয়েছে।")
                p["status"] = "approved" if approve else "rejected"
                p["decided_at"] = decided.isoformat(timespec="seconds")
                target_user_id = p["user_id"]
                target_status = p["status"]
                return
        raise ValueError("পেমেন্ট পাওয়া যায়নি।")

    update_json("payments.json", _decide)

    if approve and target_user_id:
        new_expiry = (decided + timedelta(days=SUBSCRIPTION_DAYS)).isoformat(timespec="seconds")

        def _activate(data):
            for u in data.get("users", []):
                if u.get("id") == target_user_id:
                    u["expires_at"] = new_expiry
                    u["active"] = True
                    return
            raise ValueError("অ্যাকাউন্ট পাওয়া যায়নি।")

        update_json("users.json", _activate)
    return {"payment_id": payment_id, "status": target_status}


def list_users() -> list[dict]:
    data = load_json("users.json")
    users = data.get("users", [])
    users.sort(key=lambda u: u.get("created_at", ""), reverse=True)
    return users


# ---------------------------------------------------------------------------
# Admin password (first-run setup; hash lives in admin.json)
# ---------------------------------------------------------------------------

def admin_is_set_up() -> bool:
    try:
        data = load_json("admin.json")
    except Exception:
        return False
    return bool(data.get("password_hash"))


def admin_set_password(new_password: str) -> None:
    if len(new_password) < 8:
        raise ValueError("অ্যাডমিন পাসওয়ার্ড কমপক্ষে ৮ অক্ষরের হতে হবে।")
    if admin_is_set_up():
        raise ValueError("অ্যাডমিন পাসওয়ার্ড আগেই সেট করা আছে।")
    salt, pw_hash = hash_password(new_password)
    save_json("admin.json", {"salt": salt, "password_hash": pw_hash})


def admin_check_password(password: str) -> bool:
    try:
        data = load_json("admin.json")
    except Exception:
        return False
    if not data.get("password_hash"):
        return False
    return check_password(password, data["salt"], data["password_hash"])
