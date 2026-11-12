"""Exhaustively check a finite model of uncertain set operations.

Each selection is represented by a certain lower bound and possible upper bound.
This is an executable check of the formulas, not a proof about the CAD kernel.
"""

from itertools import product


def interval(states):
    return (frozenset(i for i, s in enumerate(states) if s == 2),
            frozenset(i for i, s in enumerate(states) if s != 0))


def members(lower, upper):
    optional = tuple(upper - lower)
    for bits in product((False, True), repeat=len(optional)):
        yield lower | {v for v, take in zip(optional, bits) if take}


def abstract(op, a, b):
    lo_a, hi_a = a
    lo_b, hi_b = b
    if op == "union":
        return lo_a | lo_b, hi_a | hi_b
    if op == "intersection":
        return lo_a & lo_b, hi_a & hi_b
    if op == "difference":
        return lo_a - hi_b, hi_a - lo_b
    raise ValueError(op)


def concrete(op, a, b):
    return {"union": lambda: a | b, "intersection": lambda: a & b,
            "difference": lambda: a - b}[op]()


def main():
    cases = list(product(range(3), repeat=3))  # absent, possible, certain
    checks = 0
    for left, right, op in product(cases, cases, ("union", "intersection", "difference")):
        a, b = interval(left), interval(right)
        lo, hi = abstract(op, a, b)
        outcomes = [concrete(op, x, y) for x in members(*a) for y in members(*b)]
        assert all(lo <= actual <= hi for actual in outcomes)
        # Bounds are tight when the two inputs can vary independently.
        assert lo == frozenset.intersection(*map(frozenset, outcomes))
        assert hi == frozenset.union(*map(frozenset, outcomes))
        checks += 1
    print(f"{checks} interval operation cases passed; 3-entity universes")
    # Correlation is lost: if A and B are the same unknown set, A - B is
    # necessarily empty, though independent interval evaluation cannot prove it.
    unknown = (frozenset(), frozenset({0}))
    assert abstract("difference", unknown, unknown) == (frozenset(), frozenset({0}))
    print("Correlation counterexample confirmed: bounds are safe but not always exact")

    def between(uses, a, b):
        return {e for e, f in uses for edge, g in uses
                if edge == e and f != g and f in a and g in b}

    # Monotone incidence query over all two-edge/two-face relation instances,
    # with all partial memberships in both face sets. Enumerate all concrete
    # completions independently and compare with lower/upper evaluation.
    incidence = tuple(product(range(2), range(2)))
    membership = list(product(range(3), repeat=2))
    checks = 0
    for use_bits, left, right in product(product((False, True), repeat=4), membership, membership):
        uses = {u for u, present in zip(incidence, use_bits) if present}
        a, b = interval(left), interval(right)
        lo, hi = between(uses, a[0], b[0]), between(uses, a[1], b[1])
        outcomes = [between(uses, x, y) for x in members(*a) for y in members(*b)]
        assert all(lo <= result <= hi for result in outcomes)
        assert lo == set.intersection(*outcomes) and hi == set.union(*outcomes)
        checks += 1
    print(f"{checks} uncertain incidence cases have sound, tight independent bounds")


if __name__ == "__main__":
    main()
