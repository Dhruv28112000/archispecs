"""(Re)build the Chroma enterprise memory from memory/seed_data.json.

Usage: python memory/seed_memory.py [--reset]
  --reset  delete all collections first (also removes user feedback and past runs)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # allow `python memory/seed_memory.py` from any folder

from memory import store  # noqa: E402

SEED_FILE = ROOT / "memory" / "seed_data.json"


def main() -> None:
    """Upsert seed records by key and print counts per type."""
    if "--reset" in sys.argv:
        store.reset()
        print("Collections deleted.")
    records = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    n = store.upsert_records(records, source="seed")
    print(f"Upserted {n} seed records into '{store.MEMORY_COLLECTION}' at {store.CHROMA_PATH}")
    for type_, count in sorted(store.count_by_type().items()):
        print(f"  {type_:<11} {count}")


if __name__ == "__main__":
    main()
