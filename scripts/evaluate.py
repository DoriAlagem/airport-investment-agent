"""Answer evaluation: are the replies true, or merely fluent?

Two independent checks per question.

1. FACTS - assertions about what the answer must and must not say. Written from
   what the data actually contains, so a wrong ranking or a dropped caveat
   fails.

2. PROVENANCE - every number in the prose is traced back to a tool result. This
   is the check that matters: a model can produce a confident, well-formed,
   entirely invented figure, and no amount of reading the sentence will reveal
   it. Numbers are matched tolerantly, because the model legitimately restates
   0.816 as "81.6 percent" and rounds 79.62 to 79.6.

Not part of the pytest suite: it costs live API calls and free-tier quota.

    PYTHONPATH=src python3 scripts/evaluate.py
    PYTHONPATH=src python3 scripts/evaluate.py --verbose
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from airport_intel.agent import Agent  # noqa: E402

# Figures a reader treats as prose, not as claims about the data.
IGNORED_NUMBERS = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 100, 1000}

# Years and windows: real, but they come from the meta table rather than from a
# metric, and appear in tool payloads as strings like "2025-01".
YEAR_RANGE = range(1990, 2100)


CASES = [
    {
        "id": "new-england",
        "question": "Which airports in New England are strong candidates for "
                    "terminal expansion?",
        "must_contain": [r"\bBOS\b|Boston", r"terminal[- ]limited"],
        "must_not_contain": [r"\bLAX\b", r"\bHeathrow\b"],
        "why": "BOS leads New England and the question is about terminal work, "
               "so the constraint type has to appear.",
    },
    {
        "id": "la-vs-sna",
        "question": "Compare LA and Santa Ana airport congestion levels.",
        "must_contain": [r"\bSNA\b|Santa Ana|John Wayne", r"\bLAX\b",
                         # The requirement is peer-relative framing, not one
                         # particular word for it. "more constrained relative to
                         # its peers than LAX is to its own" satisfies it as
                         # well as "different tier" does - and a bare "SNA is
                         # more congested than LAX" still fails, which is the
                         # answer this case exists to catch.
                         r"not directly comparable|tier|peer|its own|"
                         r"medium hub|large hub"],
        "must_not_contain": [],
        "why": "Different tiers, so the answer must frame each airport against "
               "its own peers rather than declaring a cross-tier winner.",
    },
    {
        "id": "anchorage-longhaul",
        "question": "What is the percentage of long haul flights out of "
                    "Anchorage airport?",
        "must_contain": [r"2\.4", r"52\.9", r"cargo|freight"],
        "must_not_contain": [],
        "why": "Passenger and cargo must be separate; a blended figure at ANC "
               "is dominated by freight.",
    },
    {
        "id": "sfo-unmet-demand",
        "question": "What is the unmet flight demand in SFO airport and why?",
        "must_contain": [r"\bSFO\b",
                         r"do not|don't|cannot|not estimate|no.*estimate"],
        "must_not_contain": [r"\bexactly\b"],
        "why": "We do not model spilled passengers. The answer must decline to "
               "invent a count rather than produce one.",
    },
    {
        "id": "out-of-scope",
        "question": "How congested is London Heathrow?",
        "must_contain": [r"US|United States|scope"],
        "must_not_contain": [r"score of \d", r"percentile"],
        "why": "Out of scope. It must say so, not score a foreign airport.",
    },
    {
        "id": "unknown-airport",
        "question": "Give me the congestion score for airport ZZZ.",
        "must_contain": [r"no|not|unable|don't|cannot"],
        "must_not_contain": [r"percentile", r"final score of \d"],
        "why": "An unknown code must produce a refusal, never an invented score.",
    },
    {
        "id": "cargo-hub-excluded",
        "question": "What is the congestion score for Fort Worth Alliance airport?",
        "must_contain": [r"threshold|excluded|not scored|passenger"],
        "must_not_contain": [r"final score of \d+\.\d"],
        "why": "AFW is below the passenger floor. It must explain the exclusion "
               "rather than score it.",
    },
]


def numbers_in(text):
    """Numeric claims in prose, ignoring years and small counting words."""
    found = set()
    for raw in re.findall(r"(?<![\w.])\d{1,3}(?:,\d{3})*(?:\.\d+)?(?![\w])", text):
        value = float(raw.replace(",", ""))
        if value in IGNORED_NUMBERS or int(value) in YEAR_RANGE:
            continue
        found.add(value)
    return found


def numbers_from_tools(tool_calls):
    """Every number any tool returned, plus the forms a model may restate it in."""
    pool = set()

    def walk(node):
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, bool):
            return
        elif isinstance(node, (int, float)):
            pool.add(float(node))
        elif isinstance(node, str):
            # Thousands separators matter: the exclusion message formats the
            # threshold as "10,000", and a naive \d+ reads that as 10 and 000,
            # then reports the agent invented 10000.
            for raw in re.findall(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?",
                                  node):
                pool.add(float(raw.replace(",", "")))

    for call in tool_calls:
        walk(call.get("result"))

    # A ratio of 0.816 is legitimately spoken as "81.6 percent"; a score of
    # 79.62 as "79.6". Derived forms are generated once rather than guessed at
    # comparison time.
    derived = set()
    for value in pool:
        derived.update({value * 100, value / 100, round(value, 1),
                        round(value, 0), round(value * 100, 1)})
    return pool | derived


def unsupported(answer, tool_calls, tolerance=0.05):
    """Numbers in the answer with no plausible source in any tool result."""
    pool = numbers_from_tools(tool_calls)
    orphans = []
    for value in sorted(numbers_in(answer)):
        if any(abs(value - candidate) <= max(tolerance, abs(candidate) * 0.005)
               for candidate in pool):
            continue
        orphans.append(value)
    return orphans


def run_case(case, verbose=False):
    agent = Agent()
    result = agent.ask(case["question"])
    answer = (result.get("answer") or "").strip()
    calls = result.get("tool_calls") or []

    failures = []
    for pattern in case["must_contain"]:
        if not re.search(pattern, answer, re.I):
            failures.append("missing /%s/" % pattern)
    for pattern in case["must_not_contain"]:
        if re.search(pattern, answer, re.I):
            failures.append("should not contain /%s/" % pattern)

    orphans = unsupported(answer, calls)
    if orphans:
        failures.append("unsupported numbers: %s" % orphans)

    status = "PASS" if not failures else "FAIL"
    print("%-4s %-20s %2d tools  %3d words" %
          (status, case["id"], len(calls), len(answer.split())))
    for failure in failures:
        print("       - %s" % failure)
    if verbose or failures:
        print("       why: %s" % case["why"])
        print("       tools: %s" % [c["tool"] for c in calls])
        print("       %s" % answer.replace("\n", " ")[:300])
        print()
    return not failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--only", help="run one case by id")
    args = parser.parse_args()

    cases = [c for c in CASES if not args.only or c["id"] == args.only]
    print("Evaluating %d cases against the live agent\n" % len(cases))

    passed = sum(run_case(c, args.verbose) for c in cases)
    print("\n%d/%d passed" % (passed, len(cases)))
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
