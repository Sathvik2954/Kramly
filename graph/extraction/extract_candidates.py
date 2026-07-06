"""
extract_candidates.py
Phase 3, Person A — Task 3.2: LLM-assisted extraction of candidate
prerequisite relationships from source text.

VERIFY BEFORE RUNNING:
- Requires Ollama installed and running locally (https://ollama.com).
- Requires the `ollama` Python package: `pip install ollama`
- The exact `ollama.chat()` call signature below is what I believe is
  current, but I am not fully certain it hasn't changed — verify against
  the package's current README/docs before trusting this is correct.
- MODEL_NAME below is a placeholder. Run `ollama list` yourself to see
  which models you actually have pulled, and set MODEL_NAME to match —
  I cannot confirm which model tags are valid on your machine.

WHAT THIS DOES:
Reads a source text file, prompts a local LLM to propose candidate
prerequisite relationships between concepts mentioned in the text, and
writes them to a CSV for human review. Nothing here writes to the graph
directly — per the project's human-in-the-loop design principle, these are
SUGGESTIONS ONLY.
"""

import csv
import json
import os

import ollama  # VERIFY: pip install ollama, and current import/usage against its docs

MODEL_NAME = "llama3"  # VERIFY: run `ollama list` and replace with a model you actually have

SOURCE_TEXT_PATH = os.path.join(os.path.dirname(__file__), "example_source_text.md")
OUTPUT_CSV_PATH = os.path.join(os.path.dirname(__file__), "candidate_edges.csv")

EXTRACTION_PROMPT_TEMPLATE = """You are helping build a prerequisite skill graph for an educational platform.

Below is a piece of text describing a learning domain. Identify pairs of
concepts where one is a PREREQUISITE of the other — i.e., a learner should
understand the first concept before the second.

Respond with ONLY a JSON array, no other text, in this exact format:
[
  {{"from_skill": "concept name", "to_skill": "concept name", "confidence": 0.0-1.0, "source_snippet": "short quote from the text supporting this"}}
]

If you find no clear prerequisite relationships, respond with an empty array: []

TEXT:
{source_text}
"""


def read_source_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def call_llm_for_extraction(source_text):
    prompt = EXTRACTION_PROMPT_TEMPLATE.format(source_text=source_text)

    # VERIFY: this call shape (ollama.chat with model= and messages=) against
    # current ollama package docs — I am not fully certain this is unchanged.
    response = ollama.chat(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
    )

    # VERIFY: response structure — I believe the text is at
    # response['message']['content'], but confirm against current docs,
    # since response object shape can change between package versions.
    raw_content = response["message"]["content"]

    try:
        candidates = json.loads(raw_content)
    except json.JSONDecodeError:
        print("WARNING: Model did not return valid JSON. Raw output was:")
        print(raw_content)
        print("You may need to adjust the prompt or manually clean the output.")
        return []

    return candidates


def write_candidates_csv(candidates, path):
    fieldnames = ["from_skill", "to_skill", "confidence", "source_snippet"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for c in candidates:
            writer.writerow({
                "from_skill": c.get("from_skill", ""),
                "to_skill": c.get("to_skill", ""),
                "confidence": c.get("confidence", ""),
                "source_snippet": c.get("source_snippet", ""),
            })


def main():
    source_text = read_source_text(SOURCE_TEXT_PATH)
    print(f"Read {len(source_text)} characters from {SOURCE_TEXT_PATH}")
    print(f"Calling local Ollama model '{MODEL_NAME}' for extraction...")

    candidates = call_llm_for_extraction(source_text)
    print(f"Model proposed {len(candidates)} candidate prerequisite relationships.")

    write_candidates_csv(candidates, OUTPUT_CSV_PATH)
    print(f"Written to {OUTPUT_CSV_PATH}")
    print("IMPORTANT: these are SUGGESTIONS ONLY. Do not merge into the graph "
          "without human review — use review_cli.py next (Person B's Phase 3 "
          "review/governance track, included here as a reference stub).")


if __name__ == "__main__":
    main()
