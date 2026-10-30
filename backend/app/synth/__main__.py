"""python -m app.synth --seed 42 [--reset]"""
import argparse

from app.db import SessionLocal
from app.synth.generator import generate
from app.synth.loader import SynthAlreadyLoaded, load_synth, reset_domain_data


def main() -> int:
    ap = argparse.ArgumentParser(description="Load repeatable synthetic demo data")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--reset", action="store_true", help="delete existing orders/shipments/stock first (users and audit log are kept)")
    args = ap.parse_args()
    with SessionLocal() as db:
        if args.reset:
            reset_domain_data(db)
        try:
            counts = load_synth(db, generate(args.seed), seed=args.seed)
        except SynthAlreadyLoaded as exc:
            print(exc)
            return 1
        db.commit()
    print("Loaded synthetic demo data:", ", ".join(f"{k}={v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
