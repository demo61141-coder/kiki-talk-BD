# -*- coding: utf-8 -*-
"""Persistent storage for Kiki Talk (কিকি টক).

Data lives in a PRIVATE Hugging Face dataset repo (demoqqq/kiki-talk-data)
as small JSON files — it survives Streamlit Community Cloud restarts, costs
nothing, and needs no server or Google Cloud Console step.

Files in the repo:
  users.json    — signup accounts (name, mobile, password hash, trial /
                  subscription state, daily fair-use counter, first/last
                  IP + User-Agent for abuse detection)
  payments.json — manual bKash/Nagad payment submissions (with the chosen
                  package recorded on each)
  admin.json    — admin password hash (set on first admin visit, never
                  hard-coded, never in this repo)
  settings.json — admin-editable payment numbers + instructions + the
                  max-trials-per-IP limit
  packages.json — admin-manageable subscription packages (name, days,
                  price, active; never hard-deleted)
  screenshots/  — payment screenshots uploaded by users

The app authenticates to Hugging Face with a write token stored in
Streamlit secrets as HF_TOKEN (set during deploy; see README.md).
Locally, HF_TOKEN can be given as an environment variable.

NOTE on concurrency: writes are whole-file uploads (read-modify-write).
That is fine for a small user base; two admins approving at the exact
same second could in theory overwrite each other. The admin panel is
single-owner, so this is accepted for launch.
"""

import copy
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

# --- admin-editable settings (settings.json) + packages (packages.json) ---
# The owner edits these from the admin panel — no code change needed.
DEFAULT_MAX_TRIALS_PER_IP = 2
PLACEHOLDER_NUMBER = "01XXXXXXXXX"
DEFAULT_INSTRUCTIONS = (
    "১. নিচের নম্বরটি কপি করে বিকাশ বা নগদ অ্যাপ খুলুন।\n"
    "২. Send Money বেছে নিয়ে নম্বরটি বসান।\n"
    "৩. প্যাকেজের দাম অনুযায়ী টাকা লিখে পাঠান।\n"
    "৪. টাকা পাঠিয়ে এখানে ফিরে ট্রানজাকশন আইডি অথবা স্ক্রিনশট জমা দিন।\n"
    "৫. মালিক টাকা মিলিয়ে যাচাই করে আপনার অ্যাকাউন্ট চালু করে দেবেন।"
)
DEFAULT_SETTINGS = {
    "bkash_number": PLACEHOLDER_NUMBER,
    "nagad_number": PLACEHOLDER_NUMBER,
    "instructions": DEFAULT_INSTRUCTIONS,
    "max_trials_per_ip": DEFAULT_MAX_TRIALS_PER_IP,
}
DEFAULT_PACKAGES = [
    {"id": "pkg_7d", "name": "১ সপ্তাহ", "days": 7, "price": 20, "active": True},
    {"id": "pkg_30d", "name": "১ মাস", "days": 30, "price": 50, "active": True},
    {"id": "pkg_60d", "name": "২ মাস", "days": 60, "price": 90, "active": True},
]

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


def signup(name: str, mobile: str, password: str,
           client_ip: str | None = None, user_agent: str | None = None) -> dict:
    """Create an account and start the 1-hour free trial immediately.

    client_ip / user_agent are recorded for abuse detection (same-IP
    clusters in the admin panel). If this IP already has
    max_trials_per_ip trial accounts, the new account is created WITHOUT
    a free trial (it still works — it just has to pay first). Signup is
    never blocked outright, so shared family Wi-Fi cannot lock genuine
    users out.
    """
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
    ip = (client_ip or "").strip() or "unknown"
    trial_granted = True
    if ip != "unknown":
        try:
            limit = int(get_settings().get("max_trials_per_ip",
                                           DEFAULT_MAX_TRIALS_PER_IP))
        except Exception:
            limit = DEFAULT_MAX_TRIALS_PER_IP
        existing = load_json("users.json").get("users", [])
        trials_from_ip = sum(
            1 for u in existing
            if u.get("first_ip") == ip and u.get("trial_granted", True)
        )
        if trials_from_ip >= max(0, limit):
            trial_granted = False
    user = {
        "id": uuid.uuid4().hex[:12],
        "name": name,
        "mobile": mobile,
        "salt": salt,
        "password_hash": pw_hash,
        "created_at": started.isoformat(timespec="seconds"),
        "trial_started_at": started.isoformat(timespec="seconds"),
        "trial_ends_at": (started + timedelta(seconds=TRIAL_SECONDS)).isoformat(timespec="seconds")
        if trial_granted else started.isoformat(timespec="seconds"),
        "trial_granted": trial_granted,
        "first_ip": ip,
        "last_ip": ip,
        "first_user_agent": (user_agent or "")[:200],
        "last_user_agent": (user_agent or "")[:200],
        "last_login_at": started.isoformat(timespec="seconds"),
        "expires_at": None,
        "active": True,
        "daily_chars_used": 0,
        "daily_chars_date": today_str(),
    }

    def _add(data):
        data.setdefault("users", []).append(user)

    update_json("users.json", _add)
    return user


def login(mobile: str, password: str,
          client_ip: str | None = None, user_agent: str | None = None) -> dict:
    """Log in and record the login IP / User-Agent (abuse detection)."""
    user = get_user_by_mobile(mobile)
    if user is None:
        raise ValueError("এই নম্বরে কোনো অ্যাকাউন্ট নেই — আগে সাইন আপ করুন।")
    if not check_password(password, user["salt"], user["password_hash"]):
        raise ValueError("পাসওয়ার্ড ভুল হয়েছে।")
    ip = (client_ip or "").strip() or "unknown"
    if ip != "unknown" or user_agent:
        def _touch(data):
            for u in data.get("users", []):
                if u.get("id") == user["id"]:
                    if ip != "unknown":
                        u["last_ip"] = ip
                    if user_agent:
                        u["last_user_agent"] = user_agent[:200]
                    u["last_login_at"] = now_iso()
                    return

        try:
            update_json("users.json", _touch)
        except Exception:
            pass  # login must not fail because the touch-write failed
        user = get_user_by_id(user["id"]) or user
    return user


def grant_trial(user_id: str) -> None:
    """Admin grants (or re-grants) a 1-hour free trial to one user."""
    started = now()

    def _grant(data):
        for u in data.get("users", []):
            if u.get("id") == user_id:
                u["trial_granted"] = True
                u["trial_started_at"] = started.isoformat(timespec="seconds")
                u["trial_ends_at"] = (started + timedelta(seconds=TRIAL_SECONDS)).isoformat(timespec="seconds")
                return
        raise ValueError("অ্যাকাউন্ট পাওয়া যায়নি।")

    update_json("users.json", _grant)


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
                   screenshot_bytes: bytes | None, screenshot_ext: str = "png",
                   package_id: str | None = None) -> dict:
    """Record a manual payment submission. Needs txn ID and/or a screenshot.

    package_id (optional) records the package the user chose; approving
    the payment then activates that package's duration. Without a
    package the old 30-day behaviour applies.
    """
    txn_id = (txn_id or "").strip()
    if not txn_id and not screenshot_bytes:
        raise ValueError("ট্রানজাকশন আইডি অথবা স্ক্রিনশট — যেকোনো একটা দিন।")
    if amount <= 0:
        raise ValueError("অ্যামাউন্ট সঠিক নয়।")
    pkg = None
    if package_id:
        pkg = get_package(package_id)
        if pkg is None:
            raise ValueError("প্যাকেজ পাওয়া যায়নি।")
        if not pkg.get("active", True):
            raise ValueError("এই প্যাকেজটি এখন বন্ধ আছে।")
    payment = {
        "id": uuid.uuid4().hex[:12],
        "user_id": user["id"],
        "name": user["name"],
        "mobile": user["mobile"],
        "txn_id": txn_id,
        "amount": int(amount),
        "package_id": pkg["id"] if pkg else None,
        "package_name": pkg["name"] if pkg else None,
        "package_days": int(pkg["days"]) if pkg else None,
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
    """Admin decision. Approving activates the CHOSEN package's duration
    from now (30 days when no package was recorded — the old behaviour)."""
    decided = now()
    target_user_id = None
    target_status = None
    target_days = SUBSCRIPTION_DAYS

    def _decide(data):
        nonlocal target_user_id, target_status, target_days
        for p in data.get("payments", []):
            if p.get("id") == payment_id:
                if p.get("status") != "pending":
                    raise ValueError("এই পেমেন্টের সিদ্ধান্ত আগেই নেওয়া হয়েছে।")
                p["status"] = "approved" if approve else "rejected"
                p["decided_at"] = decided.isoformat(timespec="seconds")
                target_user_id = p["user_id"]
                target_status = p["status"]
                try:
                    target_days = int(p.get("package_days") or SUBSCRIPTION_DAYS)
                except (TypeError, ValueError):
                    target_days = SUBSCRIPTION_DAYS
                return
        raise ValueError("পেমেন্ট পাওয়া যায়নি.")

    update_json("payments.json", _decide)

    if approve and target_user_id:
        new_expiry = (decided + timedelta(days=target_days)).isoformat(timespec="seconds")

        def _activate(data):
            for u in data.get("users", []):
                if u.get("id") == target_user_id:
                    u["expires_at"] = new_expiry
                    u["active"] = True
                    return
            raise ValueError("অ্যাকাউন্ট পাওয়া যায়নি।")

        update_json("users.json", _activate)
    return {"payment_id": payment_id, "status": target_status,
            "days": target_days if approve else None}


def list_users() -> list[dict]:
    data = load_json("users.json")
    users = data.get("users", [])
    users.sort(key=lambda u: u.get("created_at", ""), reverse=True)
    return users


def same_ip_groups(min_size: int = 2) -> list[dict]:
    """Groups of 2+ accounts sharing the same signup IP (first_ip).

    "unknown" IPs are ignored — they cannot be attributed. Sorted by
    group size, largest first. This catches trial abuse from one
    device/network; it cannot by itself prove abuse (shared family
    Wi-Fi looks the same), so the admin panel shows the group and lets
    the admin decide.
    """
    groups: dict[str, list[dict]] = {}
    for u in list_users():
        ip = (u.get("first_ip") or "").strip()
        if not ip or ip == "unknown":
            continue
        groups.setdefault(ip, []).append(u)
    out = [{"ip": ip, "users": us} for ip, us in groups.items()
           if len(us) >= max(2, min_size)]
    out.sort(key=lambda g: len(g["users"]), reverse=True)
    return out


# ---------------------------------------------------------------------------
# Admin-editable settings (settings.json) + packages (packages.json)
# ---------------------------------------------------------------------------

def get_settings() -> dict:
    """Payment settings; defaults when the file is missing/unreadable."""
    try:
        data = load_json("settings.json")
    except Exception:
        return copy.deepcopy(DEFAULT_SETTINGS)
    merged = copy.deepcopy(DEFAULT_SETTINGS)
    for key in DEFAULT_SETTINGS:
        if key in data and data[key] is not None:
            merged[key] = data[key]
    return merged


def valid_payment_number(number: str) -> bool:
    """A bKash/Nagad number: empty or the placeholder means 'not set yet';
    anything else must be a real 11-digit 01… number."""
    n = (number or "").strip()
    if n in ("", PLACEHOLDER_NUMBER):
        return True
    return valid_mobile(n)


def save_settings(settings: dict) -> dict:
    """Validate + save payment settings (admin panel)."""
    bkash = (settings.get("bkash_number") or "").strip()
    nagad = (settings.get("nagad_number") or "").strip()
    if not valid_payment_number(bkash):
        raise ValueError("বিকাশ নম্বর সঠিক নয় (১১ সংখ্যার 01… নম্বর দিন)।")
    if not valid_payment_number(nagad):
        raise ValueError("নগদ নম্বর সঠিক নয় (১১ সংখ্যার 01… নম্বর দিন)।")
    try:
        limit = int(settings.get("max_trials_per_ip",
                                 DEFAULT_MAX_TRIALS_PER_IP))
    except (TypeError, ValueError):
        raise ValueError("এক IP-তে ট্রায়ালের সংখ্যা সঠিক নয়।")
    if limit < 0 or limit > 10:
        raise ValueError("এক IP-তে ট্রায়ালের সংখ্যা ০ থেকে ১০-এর মধ্যে হতে হবে।")
    cleaned = {
        "bkash_number": bkash or PLACEHOLDER_NUMBER,
        "nagad_number": nagad or PLACEHOLDER_NUMBER,
        "instructions": (settings.get("instructions") or "").strip()
        or DEFAULT_INSTRUCTIONS,
        "max_trials_per_ip": limit,
    }
    save_json("settings.json", cleaned)
    return cleaned


def get_packages() -> list[dict]:
    """All packages (active + deactivated); defaults if file is missing."""
    try:
        data = load_json("packages.json")
        pkgs = data.get("packages")
        if isinstance(pkgs, list) and pkgs:
            return pkgs
    except Exception:
        pass
    return copy.deepcopy(DEFAULT_PACKAGES)


def get_active_packages() -> list[dict]:
    return [p for p in get_packages() if p.get("active", True)]


def get_package(package_id: str) -> dict | None:
    for p in get_packages():
        if p.get("id") == package_id:
            return p
    return None


def save_packages(packages: list[dict]) -> None:
    save_json("packages.json", {"packages": packages})


def add_package(name: str, days: int, price: int) -> dict:
    name = (name or "").strip()
    if len(name) < 2:
        raise ValueError("প্যাকেজের নাম লিখুন।")
    try:
        days, price = int(days), int(price)
    except (TypeError, ValueError):
        raise ValueError("মেয়াদ ও দাম সংখ্যায় লিখুন।")
    if days < 1 or days > 365:
        raise ValueError("মেয়াদ ১ থেকে ৩৬৫ দিনের মধ্যে হতে হবে।")
    if price < 1:
        raise ValueError("দাম ১ টাকার কম হতে পারে না।")
    pkg = {"id": "pkg_" + uuid.uuid4().hex[:8], "name": name,
           "days": days, "price": price, "active": True}

    def _add(data):
        data.setdefault("packages", []).append(pkg)

    update_json("packages.json", _add)
    return pkg


def update_package(package_id: str, name: str | None = None,
                   days: int | None = None, price: int | None = None) -> dict:
    if name is not None and len((name or "").strip()) < 2:
        raise ValueError("প্যাকেজের নাম লিখুন।")
    if days is not None and not (1 <= int(days) <= 365):
        raise ValueError("মেয়াদ ১ থেকে ৩৬৫ দিনের মধ্যে হতে হবে।")
    if price is not None and int(price) < 1:
        raise ValueError("দাম ১ টাকার কম হতে পারে না।")
    updated = None

    def _update(data):
        nonlocal updated
        for p in data.get("packages", []):
            if p.get("id") == package_id:
                if name is not None:
                    p["name"] = name.strip()
                if days is not None:
                    p["days"] = int(days)
                if price is not None:
                    p["price"] = int(price)
                updated = dict(p)
                return
        raise ValueError("প্যাকেজ পাওয়া যায়নি।")

    update_json("packages.json", _update)
    return updated


def set_package_active(package_id: str, active: bool) -> None:
    """Deactivate (never hard-delete, so payment history stays valid)."""
    def _set(data):
        for p in data.get("packages", []):
            if p.get("id") == package_id:
                p["active"] = bool(active)
                return
        raise ValueError("প্যাকেজ পাওয়া যায়নি।")

    update_json("packages.json", _set)


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
