"""
review_cli.py
REFERENCE STUB — this is Person B's Phase 3 task (3.3: Review/Governance
track), included here only so Person A's extraction output has somewhere
to go for an end-to-end demo. Not your official Phase 3 deliverable.

Simple CLI: reads candidate_edges.csv (from extract_candidates.py), asks
y/n for each candidate, writes approved ones to reviewed_approved.csv.
"""

import csv
import os

CANDIDATES_PATH = os.path.join(os.path.dirname(__file__), "candidate_edges.csv")
APPROVED_PATH = os.path.join(os.path.dirname(__file__), "reviewed_approved.csv")


def main():
    if not os.path.exists(CANDIDATES_PATH):
        print(f"No candidates file found at {CANDIDATES_PATH}. Run extract_candidates.py first.")
        return

    with open(CANDIDATES_PATH, newline="", encoding="utf-8") as f:
        candidates = list(csv.DictReader(f))

    if not candidates:
        print("No candidates to review.")
        return

    approved = []
    for c in candidates:
        print("\n---")
        print(f"Proposed: '{c['from_skill']}' -> '{c['to_skill']}'")
        print(f"Confidence: {c['confidence']}")
        print(f"Source snippet: {c['source_snippet']}")
        decision = input("Approve this edge? (y/n): ").strip().lower()
        if decision == "y":
            approved.append(c)

    with open(APPROVED_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["from_skill", "to_skill", "confidence", "source_snippet"])
        writer.writeheader()
        writer.writerows(approved)

    print(f"\n{len(approved)} of {len(candidates)} candidates approved. Written to {APPROVED_PATH}")


if __name__ == "__main__":
    main()
