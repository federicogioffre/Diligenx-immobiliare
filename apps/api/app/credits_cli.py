"""Manage prepaid credits from the API container.

    python -m app.credits_cli balance <email>
    python -m app.credits_cli grant <email> <amount> [--note TEXT]
    python -m app.credits_cli list

A negative amount takes credits back. On Railway:
``railway run --service api python -m app.credits_cli grant a@b.it 500``.
"""
import argparse
import sys

from sqlalchemy import func

from app.db.session import SessionLocal
from app.models.user import User
from app.services.credits import grant


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.credits_cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="every account with its balance")
    balance = sub.add_parser("balance", help="one account's balance")
    balance.add_argument("email")
    top_up = sub.add_parser("grant", help="add (or with a negative amount remove) credits")
    top_up.add_argument("email")
    top_up.add_argument("amount", type=int)
    top_up.add_argument("--note")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        if args.command == "list":
            for user in db.query(User).order_by(User.email):
                print(f"{user.credit_balance:>8}  {user.email}")
            return 0
        user = db.query(User).filter(func.lower(User.email) == args.email.lower()).first()
        if user is None:
            print(f"No account for {args.email}", file=sys.stderr)
            return 1
        if args.command == "balance":
            print(user.credit_balance)
            return 0
        if user.credit_balance + args.amount < 0:
            print(f"{args.email} has {user.credit_balance} credits; cannot remove {-args.amount}", file=sys.stderr)
            return 1
        new_balance = grant(db, user.id, args.amount, "grant", note=args.note)
        db.commit()
        print(f"{args.email}: {new_balance} credits")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
