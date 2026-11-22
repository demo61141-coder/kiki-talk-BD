"""Create the PRIVATE Hugging Face dataset repo that stores Kiki Talk data
(users, payments, admin password hash). One-time setup.

Uses the same credential mechanism as the other HF helpers: the stored
custom.huggingface credential via the dynamic-credential surrogate.
Only repo ids, file names and commit hashes are printed.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
from dynamic_credentials import dynamic_credential_entry

HF_REPO = "kiki-talk-data"

INITIAL_FILES = {
    "users.json": {"users": []},
    "payments.json": {"payments": []},
    "admin.json": {"salt": None, "password_hash": None},
    "README.md": (
        "# kiki-talk-data\n\n"
        "Private data store for the Kiki Talk (কিকি টক) Bengali TTS "
        "subscription app.\n\n"
        "- `users.json` — signup accounts (name, mobile, password hash, "
        "trial / subscription state)\n"
        "- `payments.json` — manual bKash/Nagad payment submissions\n"
        "- `admin.json` — admin password hash (set on first admin visit)\n"
        "- `screenshots/` — payment screenshots uploaded by users\n\n"
        "DO NOT make this repo public: it holds password hashes and "
        "mobile numbers. The Streamlit app reads/writes it with a "
        "write token stored in Streamlit secrets as HF_TOKEN.\n"
    ),
}


def main():
    entry = dynamic_credential_entry("custom.huggingface")
    token = str(entry["surrogate"]).strip()
    from huggingface_hub import HfApi

    api = HfApi(token=token)
    user = api.whoami()
    username = user["name"]
    repo_id = f"{username}/{HF_REPO}"
    print("username:", username)
    print("repo_id:", repo_id)

    api.create_repo(repo_id=HF_REPO, repo_type="dataset", private=True, exist_ok=True)
    print("repo ready (private dataset)")

    with tempfile.TemporaryDirectory() as tmp:
        for name, content in INITIAL_FILES.items():
            local = Path(tmp) / name
            if name.endswith(".json"):
                local.write_text(json.dumps(content, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
            else:
                local.write_text(content, encoding="utf-8")
            info = api.upload_file(
                path_or_fileobj=str(local),
                path_in_repo=name,
                repo_id=repo_id,
                repo_type="dataset",
            )
            print("uploaded:", name, "commit:", info.oid, flush=True)

    files = api.list_repo_files(repo_id=repo_id, repo_type="dataset")
    print("repo files:", sorted(files))


if __name__ == "__main__":
    main()
