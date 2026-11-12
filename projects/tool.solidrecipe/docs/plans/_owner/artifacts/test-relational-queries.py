"""Finite relational checks for proposed topology-query operators.

Exhaustively checks small abstract incidence graphs, including overlapping
face-source sets, and graph reachability. These tests establish properties of
the mathematical operators for tested finite instances, not kernel correctness.
"""

from itertools import permutations, product


def subsets(items):
    for bits in product((False, True), repeat=len(items)):
        yield frozenset(v for v, take in zip(items, bits) if take)


def join(left, right, left_key, right_key):
    return {x + y for x in left for y in right if x[left_key] == y[right_key]}


def relation_interface(uses, a, b):
    # Join edge/face incidences to themselves on edge, retain distinct face
    # witnesses in A and B, and project the edge. Uses are collapsed here;
    # this checks co-incidence, not radial order around non-manifold edges.
    pairs = join(uses, uses, 0, 0)
    return {e for e, f, _, g in pairs if f != g and f in a and g in b}


def independently_computed_interface(uses, a, b):
    result = set()
    for edge in {e for e, _ in uses}:
        faces = {f for e, f in uses if e == edge}
        for f in faces & a:
            if (faces & b) - {f}:
                result.add(edge)
    return result


def reachable(nodes, arcs, seeds):
    seen = set(seeds)
    todo = list(seeds)
    while todo:
        current = todo.pop()
        for left, right in arcs:
            if left == current and right not in seen:
                seen.add(right)
                todo.append(right)
    return seen


def reachability_reference(nodes, arcs, seeds):
    reach = {(x, x) for x in nodes} | set(arcs)
    for k in nodes:
        reach |= {(i, j) for i in nodes for j in nodes if (i, k) in reach and (k, j) in reach}
    return {j for i in seeds for j in nodes if (i, j) in reach}


def main():
    edges, faces = (0, 1), (0, 1, 2)
    incidence = tuple(product(edges, faces))
    cases = false_positive_cases = interface_permutations = 0
    for uses, a, b in product(subsets(incidence), subsets(faces), subsets(faces)):
        expected = independently_computed_interface(uses, a, b)
        assert relation_interface(uses, a, b) == expected
        for ep, fp in product(permutations(edges), permutations(faces)):
            er, fr = dict(zip(edges, ep)), dict(zip(faces, fp))
            actual = relation_interface({(er[e], fr[f]) for e, f in uses},
                                        {fr[f] for f in a}, {fr[f] for f in b})
            assert actual == {er[e] for e in expected}
            interface_permutations += 1
        naive = {e for e, f in uses if f in a} & {e for e, f in uses if f in b}
        if naive - expected:
            false_positive_cases += 1
        cases += 1
    print(f"{cases} co-incidence cases agree with relational join and {interface_permutations} renumberings; "
          f"independent adjacency gives false positives in {false_positive_cases}")

    nodes = (0, 1, 2)
    graph_cases = permutation_cases = 0
    for arcs, seeds in product(subsets(tuple(product(nodes, nodes))), subsets(nodes)):
        expected = reachability_reference(nodes, arcs, seeds)
        assert reachable(nodes, arcs, seeds) == expected
        graph_cases += 1
        for perm in permutations(nodes):
            rename = dict(zip(nodes, perm))
            renamed_arcs = {(rename[a], rename[b]) for a, b in arcs}
            renamed_seeds = {rename[s] for s in seeds}
            assert reachable(nodes, renamed_arcs, renamed_seeds) == {rename[e] for e in expected}
            permutation_cases += 1
    print(f"{graph_cases} reachability cases and {permutation_cases} renumberings agree")

    # Two otherwise indistinguishable entities swapped by an automorphism cannot
    # be uniquely selected by a renaming-invariant query over these facts.
    symmetric = {"hole_a", "hole_b"}
    swap = {"hole_a": "hole_b", "hole_b": "hole_a"}
    invariant_subsets = [s for s in subsets(tuple(sorted(symmetric))) if {swap[x] for x in s} == set(s)]
    assert all(len(s) != 1 for s in invariant_subsets)
    print("Symmetric two-entity structure: no invariant query selects exactly one")


if __name__ == "__main__":
    main()
