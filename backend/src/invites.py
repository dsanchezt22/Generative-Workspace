"""Provision alpha invites: python -m src.invites create "Name" | list | revoke <id>"""

import os
import sys

from src import db


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    base = os.environ.get("TRUS_PUBLIC_URL", "http://localhost:3000")
    if cmd == "create":
        u = db.create_user(sys.argv[2])
        print(f"{u['name']}: {base}/claim?token={u['invite_token']}")
    elif cmd == "revoke":
        print("revoked" if db.revoke_user(sys.argv[2]) else "not found")
    else:
        for u in db.list_users():
            state = "REVOKED" if u["revoked_at"] else "active"
            print(f"{u['id']}  {u['name']:<20} {state}  {base}/claim?token={u['invite_token']}")


if __name__ == "__main__":
    main()
