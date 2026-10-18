"""``python -m catenax_simplified.admin hash-password``: the value of CXS_ADMIN_PASSWORD_HASH.

``python -m catenax_simplified.admin secret-key`` prints a random CXS_SECRET_KEY.
"""

from __future__ import annotations

import getpass
import secrets
import sys

from .security import hash_password


def main(argv: list[str]) -> int:
    """Runs the command in ``argv[1]``; returns the exit code."""
    command = argv[1] if len(argv) > 1 else ""
    if command == "hash-password":
        password = getpass.getpass("Admin password: ")
        if len(password) < 12:
            print("Use at least 12 characters.", file=sys.stderr)
            return 1
        if getpass.getpass("Again: ") != password:
            print("The passwords differ.", file=sys.stderr)
            return 1
        print(hash_password(password))
        return 0
    if command == "secret-key":
        print(secrets.token_urlsafe(48))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
