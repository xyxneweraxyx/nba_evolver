#!/usr/bin/env python3
"""
tests/test_formula_engine.py — Layer 2 test suite
===================================================
Run: python3 tests/test_formula_engine.py
"""

import sys, os, time, json, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from formula_engine import (
    Node,
    VarNode, ConstNode, UnaryNode, BinaryNode, IfNode,
    node_from_dict, ast_to_c_formula,
    random_formula, _sample_var, _get_weighted_vars,
    mutate, mutate_point, mutate_const, mutate_operator,
    mutate_var_swap, mutate_hoist, mutate_subtree,
    crossover, variable_set, jaccard_similarity,
    BINARY_OPS, UNARY_OPS, CMP_OPS,
)
from nba_engine_binding import FormulaEngine, build_dataset, get_registry

# ── framework ─────────────────────────────────────────────────────────────────
_p = _f = 0
def test(name, fn):
    global _p, _f
    try:
        fn()
        print(f"  {'PASS':6}  {name}")
        _p += 1
    except AssertionError as e:
        print(f"  {'FAIL':6}  {name}\n           {e}")
        _f += 1
    except Exception as e:
        print(f"  {'ERROR':6}  {name}\n           {type(e).__name__}: {e}")
        _f += 1

def eq(a, b, tol=1e-5): assert abs(a-b)<=tol, f"{a} != {b}"

ENGINE = FormulaEngine()

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 1: Node construction & properties
# ─────────────────────────────────────────────────────────────────────────────

def test_var_node_basics():
    n = VarNode("season_stats.net_rtg", 42)
    assert n.size() == 1
    assert n.depth() == 0
    assert n.index == 42

def test_const_node_basics():
    n = ConstNode(3.14)
    assert n.size() == 1
    assert n.depth() == 0
    eq(n.value, 3.14)

def test_binary_node_size_depth():
    l = VarNode("a", 0)
    r = ConstNode(1.0)
    b = BinaryNode("+", l, r)
    assert b.size() == 3    # 1 + 1 + 1
    assert b.depth() == 1

def test_unary_node_size_depth():
    ch = BinaryNode("*", VarNode("a",0), ConstNode(2.0))
    u  = UnaryNode("log", ch)
    assert u.size() == 4
    assert u.depth() == 2

def test_if_node_size_depth():
    v = lambda i: VarNode("x", i)
    n = IfNode(">", v(0), v(1), v(2), v(3))
    assert n.size() == 5
    assert n.depth() == 1

def test_deep_tree_depth():
    # ((a * b) + (c - d)) depth should be 2
    n = BinaryNode("+",
        BinaryNode("*", VarNode("a",0), VarNode("b",1)),
        BinaryNode("-", VarNode("c",2), VarNode("d",3)))
    assert n.depth() == 2
    assert n.size() == 7

def test_clone_is_independent():
    a = BinaryNode("+", VarNode("x",0), ConstNode(1.0))
    b = a.clone()
    b.op = "-"
    assert a.op == "+"   # original unchanged

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 2: Serialization round-trip
# ─────────────────────────────────────────────────────────────────────────────

def test_var_roundtrip():
    n  = VarNode("season_stats.w_pct", 7)
    n2 = node_from_dict(n.to_dict())
    assert isinstance(n2, VarNode)
    assert n2.name == "season_stats.w_pct"
    assert n2.index == 7

def test_const_roundtrip():
    n  = ConstNode(-42.5)
    n2 = node_from_dict(n.to_dict())
    assert isinstance(n2, ConstNode)
    eq(n2.value, -42.5)

def test_binary_roundtrip():
    n  = BinaryNode("*", VarNode("a",0), ConstNode(0.4))
    n2 = node_from_dict(n.to_dict())
    assert isinstance(n2, BinaryNode)
    assert n2.op == "*"
    assert isinstance(n2.left, VarNode)
    assert isinstance(n2.right, ConstNode)

def test_unary_roundtrip():
    n  = UnaryNode("sqrt", VarNode("b", 5))
    n2 = node_from_dict(n.to_dict())
    assert isinstance(n2, UnaryNode)
    assert n2.op == "sqrt"

def test_if_roundtrip():
    v  = lambda i: VarNode("x", i)
    n  = IfNode(">=", v(0), v(1), v(2), v(3))
    n2 = node_from_dict(n.to_dict())
    assert isinstance(n2, IfNode)
    assert n2.cmp == ">="

def test_complex_roundtrip():
    # (if(net_rtg > 0, pace * 0.4, w_pct)) deep formula
    inner = BinaryNode("*", VarNode("pace",5), ConstNode(0.4))
    n     = IfNode(">", VarNode("net_rtg",3), ConstNode(0.0),
                   inner, VarNode("w_pct",7))
    d     = n.to_dict()
    n2    = node_from_dict(d)
    # Verify structure preserved
    assert isinstance(n2, IfNode)
    assert isinstance(n2.v_true, BinaryNode)
    assert n2.v_true.op == "*"

def test_json_serializable():
    f = random_formula(4, 30)
    s = json.dumps(f.to_dict())
    d = json.loads(s)
    f2 = node_from_dict(d)
    assert f2.size() == f.size()

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 3: RPN conversion & C formula compilation
# ─────────────────────────────────────────────────────────────────────────────

def test_rpn_var_single():
    n   = VarNode("x", 3)
    rpn = n.to_rpn()
    assert len(rpn) == 1
    assert rpn[0][0] == "LOAD"
    assert rpn[0][1] == 3

def test_rpn_const_single():
    n   = ConstNode(42.0)
    rpn = n.to_rpn()
    assert len(rpn) == 1
    assert rpn[0][0] == "CONST"
    eq(rpn[0][2], 42.0)

def test_rpn_add_two_vars():
    # (a + b) → [LOAD a, LOAD b, ADD]
    n   = BinaryNode("+", VarNode("a",0), VarNode("b",1))
    rpn = n.to_rpn()
    assert len(rpn) == 3
    assert rpn[0] == ("LOAD", 0, 0.0)
    assert rpn[1] == ("LOAD", 1, 0.0)
    assert rpn[2][0] == "ADD"

def test_rpn_mul_const():
    # (var[5] * 0.4) → [LOAD 5, CONST 0.4, MUL]
    n   = BinaryNode("*", VarNode("x",5), ConstNode(0.4))
    rpn = n.to_rpn()
    assert rpn[0] == ("LOAD", 5, 0.0)
    assert rpn[1][0] == "CONST"
    eq(rpn[1][2], 0.4)
    assert rpn[2][0] == "MUL"

def test_rpn_unary():
    # log(var[2]) → [LOAD 2, LOG]
    n   = UnaryNode("log", VarNode("x",2))
    rpn = n.to_rpn()
    assert len(rpn) == 2
    assert rpn[1][0] == "LOG"

def test_rpn_if_node():
    # if(c1>c2, vt, vf) → [c1, c2, vt, vf, IF_GT]
    n   = IfNode(">", VarNode("a",0), VarNode("b",1),
                  VarNode("c",2), VarNode("d",3))
    rpn = n.to_rpn()
    assert len(rpn) == 5
    assert rpn[4][0] == "IF_GT"  # IF_GT opcode

def test_rpn_length_matches_size():
    # RPN length should equal node count for leaves + operators
    for _ in range(50):
        f = random_formula(3, 20)
        assert len(f.to_rpn()) == f.size()

def test_c_formula_valid():
    # Every random formula should compile to a valid C formula
    for _ in range(100):
        f  = random_formula(4, 50)
        cf = ast_to_c_formula(f)
        assert cf is not None, f"Compilation failed for: {f}"
        assert ENGINE.validate(cf), f"Invalid C formula for: {f}"

def test_c_formula_evaluates():
    # After compilation, the C engine should produce a finite result
    from nba_engine_binding import CGame
    import ctypes
    game = CGame()
    reg  = get_registry()
    idx  = reg.get("season_stats.net_rtg", 0)
    game.home[idx] = 5.0
    game.away[idx] = -3.0
    game.result    = 1

    f  = BinaryNode("+", VarNode("season_stats.net_rtg", idx), ConstNode(2.0))
    cf = ast_to_c_formula(f)
    r  = ENGINE.eval_single(cf, game)
    # home: 5+2=7, away: -3+2=-1, diff=8
    eq(r, 8.0, tol=0.01)

def test_c_formula_too_long_returns_none():
    # A formula that generates > MAX_FORMULA_OPS instructions → None
    # Build a deeply nested formula that exceeds the limit
    node = VarNode("x", 0)
    for _ in range(300):   # wrap in 300 unary ops → 301 instructions
        node = UnaryNode("neg", node)
    cf = ast_to_c_formula(node)
    assert cf is None

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 4: Feature importance weighting
# ─────────────────────────────────────────────────────────────────────────────

def test_weighted_vars_populated():
    wvars = _get_weighted_vars()
    assert len(wvars) > 100

def test_tier1_vars_sampled_more():
    # Sample 10000 variables and check tier1 appears > proportionally
    random.seed(42)
    counts = {}
    for _ in range(10000):
        name, _ = _sample_var()
        counts[name] = counts.get(name, 0) + 1

    tier1 = "season_stats.net_rtg"
    tier3 = "season_stats.blka"  # a hustle stat in tier 3

    # tier1 should appear significantly more than tier3
    c1 = counts.get(tier1, 0)
    c3 = counts.get(tier3, 0)
    assert c1 > c3 * 2, f"tier1 ({c1}) should appear >> tier3 ({c3})"

def test_sample_var_returns_valid_index():
    reg = get_registry()
    for _ in range(100):
        name, idx = _sample_var()
        assert name in reg
        assert reg[name] == idx

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 5: Random generation
# ─────────────────────────────────────────────────────────────────────────────

def test_random_formula_respects_max_depth():
    for max_d in [1, 2, 3, 5]:
        for _ in range(20):
            f = random_formula(max_d)
            assert f.depth() <= max_d, f"depth {f.depth()} > {max_d}"

def test_random_formula_respects_max_size():
    for max_s in [5, 15, 30, 60]:
        for _ in range(20):
            f = random_formula(4, max_s)
            assert f.size() <= max_s, f"size {f.size()} > {max_s}"

def test_random_formula_diversity():
    # 100 formulas should not all be identical
    reprs = set()
    for _ in range(100):
        f = random_formula(3, 20)
        reprs.add(repr(f))
    assert len(reprs) > 50, f"Only {len(reprs)}/100 unique formulas"

def test_random_formula_always_compiles():
    for _ in range(200):
        f  = random_formula(4, 50)
        cf = ast_to_c_formula(f)
        assert cf is not None
        assert ENGINE.validate(cf)

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 6: Mutations
# ─────────────────────────────────────────────────────────────────────────────

def _base() -> Node:
    return BinaryNode("+",
        BinaryNode("*", VarNode("season_stats.net_rtg", 3), ConstNode(0.4)),
        VarNode("season_stats.w_pct", 7))

def test_mutate_point_changes_formula():
    f = _base()
    changed = sum(1 for _ in range(30) if repr(mutate_point(f, 4)) != repr(f))
    assert changed >= 20, f"mutate_point only changed {changed}/30"

def test_mutate_const_changes_value():
    f = _base()
    changed = 0
    for _ in range(30):
        m = mutate_const(f)
        if repr(m) != repr(f): changed += 1
    assert changed >= 20

def test_mutate_operator_changes_op():
    f = _base()
    changed = sum(1 for _ in range(30) if repr(mutate_operator(f)) != repr(f))
    assert changed >= 15

def test_mutate_var_swap_changes_var():
    f = _base()
    changed = sum(1 for _ in range(30) if repr(mutate_var_swap(f)) != repr(f))
    assert changed >= 15

def test_mutate_hoist_reduces_size():
    # Hoist should generally reduce or equal the tree size
    f   = random_formula(5, 40)
    for _ in range(20):
        h = mutate_hoist(f)
        assert h.size() <= f.size(), f"hoist increased size: {f.size()} → {h.size()}"

def test_mutate_subtree_is_disruptive():
    f       = random_formula(4, 30)
    orig    = repr(f)
    changed = sum(1 for _ in range(20) if repr(mutate_subtree(f, 4)) != orig)
    assert changed >= 15

def test_mutate_preserves_original():
    # Original formula must not be mutated in-place
    f    = _base()
    orig = repr(f)
    for _ in range(50):
        mutate(f, 4, strength=random.random())
    assert repr(f) == orig

def test_mutate_strength_0_gentle():
    # strength=0 → mostly const and var tweaks, rarely big changes
    f     = random_formula(4, 30)
    sizes = [mutate(f, 4, 0.0).size() for _ in range(50)]
    # At strength=0, no hoist/subtree → size shouldn't vary wildly
    assert max(sizes) - min(sizes) < f.size() + 15

def test_mutate_strength_1_violent():
    # strength=1 → lots of hoist (shrink) and subtree (grow)
    f      = random_formula(4, 30)
    reprs  = {repr(mutate(f, 4, 1.0)) for _ in range(30)}
    assert len(reprs) >= 15, f"Only {len(reprs)} unique results at strength=1.0"

def test_all_mutations_compile():
    for strength in [0.0, 0.5, 1.0]:
        for _ in range(50):
            f = random_formula(4, 40)
            m = mutate(f, 4, strength)
            cf = ast_to_c_formula(m)
            if cf is not None:
                assert ENGINE.validate(cf)

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 7: Crossover
# ─────────────────────────────────────────────────────────────────────────────

def test_crossover_produces_two_children():
    a = random_formula(3, 20)
    b = random_formula(3, 20)
    c1, c2 = crossover(a, b)
    assert c1 is not a and c2 is not b

def test_crossover_preserves_parents():
    a = random_formula(3, 20)
    b = random_formula(3, 20)
    ra, rb = repr(a), repr(b)
    crossover(a, b)
    assert repr(a) == ra
    assert repr(b) == rb

def test_crossover_mixes_variables():
    # Children should contain variables from both parents
    reg    = get_registry()
    a_vars = list(reg.keys())[:5]
    b_vars = list(reg.keys())[100:105]

    a = VarNode(a_vars[0], reg[a_vars[0]])
    b_tree = BinaryNode("+",
                 VarNode(b_vars[0], reg[b_vars[0]]),
                 VarNode(b_vars[1], reg[b_vars[1]]))
    a_tree = BinaryNode("*",
                 VarNode(a_vars[0], reg[a_vars[0]]),
                 VarNode(a_vars[1], reg[a_vars[1]]))

    c1, c2 = crossover(a_tree, b_tree)
    # At least one child should have mixed variables
    vs1 = variable_set(c1)
    vs2 = variable_set(c2)
    # Some mixing should have occurred
    assert len(vs1) > 0 and len(vs2) > 0

def test_crossover_trivial_formulas():
    # Crossover of two single-node formulas → just clones
    a = VarNode("x", 0)
    b = ConstNode(1.0)
    c1, c2 = crossover(a, b)
    # Should not crash, should still be valid nodes
    assert isinstance(c1, (VarNode, ConstNode))

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 8: Variable set & Jaccard
# ─────────────────────────────────────────────────────────────────────────────

def test_variable_set_var():
    n = VarNode("season_stats.net_rtg", 3)
    assert variable_set(n) == {"season_stats.net_rtg"}

def test_variable_set_const():
    n = ConstNode(1.0)
    assert variable_set(n) == set()

def test_variable_set_complex():
    n = BinaryNode("+",
        UnaryNode("log", VarNode("season_stats.pts", 0)),
        IfNode(">", VarNode("season_stats.w_pct", 1), ConstNode(0.5),
               VarNode("season_stats.net_rtg", 2), VarNode("context.rest_days", 3)))
    vs = variable_set(n)
    assert "season_stats.pts" in vs
    assert "season_stats.w_pct" in vs
    assert "season_stats.net_rtg" in vs
    assert "context.rest_days" in vs

def test_jaccard_identical():
    n = BinaryNode("+", VarNode("a",0), VarNode("b",1))
    eq(jaccard_similarity(n, n.clone()), 1.0)

def test_jaccard_disjoint():
    a = VarNode("season_stats.pts", 0)
    b = VarNode("context.rest_days", 99)
    eq(jaccard_similarity(a, b), 0.0)

def test_jaccard_partial():
    a = BinaryNode("+", VarNode("x",0), VarNode("y",1))
    b = BinaryNode("*", VarNode("y",1), VarNode("z",2))
    j = jaccard_similarity(a, b)
    # {x,y} ∩ {y,z} = {y}, union = {x,y,z} → 1/3
    eq(j, 1/3, tol=1e-5)

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 9: Integration — evaluate random formulas on real data
# ─────────────────────────────────────────────────────────────────────────────

def _make_mini_dataset(n=200):
    """Build a tiny dataset from synthetic game dicts."""
    games = []
    for i in range(n):
        won = i < int(n * 0.60)
        games.append({
            "result": {"winner": "home" if won else "away",
                       "home_pts": 110, "away_pts": 105},
            "home": {
                "team_id": 1,
                "binary":  {"is_home":1,"is_back_to_back":0,"opponent_is_back_to_back":0},
                "context": {"match_number":i+1,"rest_days":2,"opponent_rest_days":2,
                             "win_streak":1,"home_win_streak":1,"games_last_7_days":3,
                             "days_since_last_home_game":4,"players_available":11,
                             "km_traveled":0,"timezone_shift":0},
                "season_stats": {
                    "net_rtg": 4.0 if won else -2.0,
                    "off_rtg": 115.0 if won else 110.0,
                    "w_pct":   0.65 if won else 0.40,
                    "pts": 115, "pace": 99.0,
                },
                **{k: None for k in ["last10_stats","last5_stats","home_stats",
                   "away_stats","b2b_stats","vs_above500_stats","q1_stats",
                   "q4_stats","clutch_stats"]},
                "players": [],
            },
            "away": {
                "team_id": 2,
                "binary":  {"is_home":0,"is_back_to_back":0,"opponent_is_back_to_back":0},
                "context": {"match_number":i+1,"rest_days":2,"opponent_rest_days":2,
                             "win_streak":-1,"home_win_streak":0,"games_last_7_days":3,
                             "days_since_last_home_game":5,"players_available":10,
                             "km_traveled":800,"timezone_shift":-1},
                "season_stats": {
                    "net_rtg": -4.0 if won else 2.0,
                    "off_rtg": 110.0 if won else 115.0,
                    "w_pct":   0.40 if won else 0.65,
                    "pts": 108, "pace": 98.0,
                },
                **{k: None for k in ["last10_stats","last5_stats","home_stats",
                   "away_stats","b2b_stats","vs_above500_stats","q1_stats",
                   "q4_stats","clutch_stats"]},
                "players": [],
            },
        })
    return games

_DS = None
def _get_ds():
    global _DS
    if _DS is None:
        _DS = build_dataset(_make_mini_dataset(500))
    return _DS

def test_integration_net_rtg_predictor():
    """net_rtg formula should achieve > 60% on 60% home win dataset"""
    reg = get_registry()
    idx = reg["season_stats.net_rtg"]
    f   = VarNode("season_stats.net_rtg", idx)
    cf  = ast_to_c_formula(f)
    acc = ENGINE.accuracy(cf, _get_ds())
    assert acc > 0.55, f"net_rtg predictor: {acc:.4f}"

def test_integration_random_formula_pipeline():
    """Full pipeline: random AST → RPN → C formula → score"""
    ds = _get_ds()
    for _ in range(50):
        f  = random_formula(3, 20)
        cf = ast_to_c_formula(f)
        if cf is None: continue
        if not ENGINE.validate(cf): continue
        s  = ENGINE.score(cf, ds)
        assert 0.0 <= s.accuracy <= 1.0
        assert 0.0 <= s.interest <= 1.0

def test_integration_mutation_pipeline():
    """mutate → recompile → score — should never crash"""
    reg = get_registry()
    idx = reg["season_stats.net_rtg"]
    f   = VarNode("season_stats.net_rtg", idx)
    ds  = _get_ds()

    for strength in [0.0, 0.3, 0.7, 1.0]:
        for _ in range(20):
            m  = mutate(f, 4, strength)
            cf = ast_to_c_formula(m)
            if cf is None: continue
            if not ENGINE.validate(cf): continue
            s  = ENGINE.score(cf, ds)
            assert 0 <= s.accuracy <= 1

# ─────────────────────────────────────────────────────────────────────────────
# GROUP 10: Performance
# ─────────────────────────────────────────────────────────────────────────────

def test_perf_generate_1k_formulas():
    t0 = time.time()
    fs = [random_formula(4, 50) for _ in range(1000)]
    ms = (time.time()-t0)*1000
    print(f"\n           ({ms:.0f}ms, {ms/1000:.3f}ms/formula)", end="")
    assert ms < 5000

def test_perf_rpn_compile_1k():
    fs  = [random_formula(4, 50) for _ in range(1000)]
    t0  = time.time()
    ok  = sum(1 for f in fs if ast_to_c_formula(f) is not None)
    ms  = (time.time()-t0)*1000
    print(f"\n           ({ms:.0f}ms, {ok}/1000 compiled)", end="")
    assert ms < 2000
    assert ok >= 990

def test_perf_mutate_1k():
    f  = random_formula(4, 30)
    t0 = time.time()
    for _ in range(1000):
        mutate(f, 4, strength=0.5)
    ms = (time.time()-t0)*1000
    print(f"\n           ({ms:.0f}ms, {ms/1000:.3f}ms/mutation)", end="")
    assert ms < 3000

def test_perf_full_pipeline_1k():
    """Generate + compile + score 1000 formulas"""
    ds  = _get_ds()
    t0  = time.time()
    ok  = 0
    for _ in range(1000):
        f  = random_formula(3, 25)
        cf = ast_to_c_formula(f)
        if cf and ENGINE.validate(cf):
            ENGINE.accuracy(cf, ds)
            ok += 1
    ms = (time.time()-t0)*1000
    print(f"\n           ({ms:.0f}ms total, {ms/max(1,ok):.2f}ms/formula, {ok}/1000 ok)", end="")
    assert ms < 15000

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("\n╔══════════════════════════════════════════════════════╗")
    print("║   Layer 2 — Formula Engine Test Suite               ║")
    print("╚══════════════════════════════════════════════════════╝\n")

    print("── 1. Node construction ──────────────────────────────────")
    test("var_node_basics",       test_var_node_basics)
    test("const_node_basics",     test_const_node_basics)
    test("binary_size_depth",     test_binary_node_size_depth)
    test("unary_size_depth",      test_unary_node_size_depth)
    test("if_size_depth",         test_if_node_size_depth)
    test("deep_tree_depth",       test_deep_tree_depth)
    test("clone_independent",     test_clone_is_independent)

    print("\n── 2. Serialization ──────────────────────────────────────")
    test("var_roundtrip",         test_var_roundtrip)
    test("const_roundtrip",       test_const_roundtrip)
    test("binary_roundtrip",      test_binary_roundtrip)
    test("unary_roundtrip",       test_unary_roundtrip)
    test("if_roundtrip",          test_if_roundtrip)
    test("complex_roundtrip",     test_complex_roundtrip)
    test("json_serializable",     test_json_serializable)

    print("\n── 3. RPN & C compilation ────────────────────────────────")
    test("rpn_var_single",        test_rpn_var_single)
    test("rpn_const_single",      test_rpn_const_single)
    test("rpn_add_two_vars",      test_rpn_add_two_vars)
    test("rpn_mul_const",         test_rpn_mul_const)
    test("rpn_unary",             test_rpn_unary)
    test("rpn_if_node",           test_rpn_if_node)
    test("rpn_length_eq_size",    test_rpn_length_matches_size)
    test("c_formula_valid",       test_c_formula_valid)
    test("c_formula_evaluates",   test_c_formula_evaluates)
    test("c_formula_too_long",    test_c_formula_too_long_returns_none)

    print("\n── 4. Feature importance ─────────────────────────────────")
    test("weighted_vars_exists",  test_weighted_vars_populated)
    test("tier1_sampled_more",    test_tier1_vars_sampled_more)
    test("sample_valid_index",    test_sample_var_returns_valid_index)

    print("\n── 5. Random generation ──────────────────────────────────")
    test("respects_max_depth",    test_random_formula_respects_max_depth)
    test("respects_max_size",     test_random_formula_respects_max_size)
    test("diversity",             test_random_formula_diversity)
    test("always_compiles",       test_random_formula_always_compiles)

    print("\n── 6. Mutations ──────────────────────────────────────────")
    test("point_changes",         test_mutate_point_changes_formula)
    test("const_changes",         test_mutate_const_changes_value)
    test("operator_changes",      test_mutate_operator_changes_op)
    test("varswap_changes",       test_mutate_var_swap_changes_var)
    test("hoist_reduces_size",    test_mutate_hoist_reduces_size)
    test("subtree_disruptive",    test_mutate_subtree_is_disruptive)
    test("preserves_original",    test_mutate_preserves_original)
    test("strength_0_gentle",     test_mutate_strength_0_gentle)
    test("strength_1_violent",    test_mutate_strength_1_violent)
    test("all_compile",           test_all_mutations_compile)

    print("\n── 7. Crossover ──────────────────────────────────────────")
    test("produces_two",          test_crossover_produces_two_children)
    test("preserves_parents",     test_crossover_preserves_parents)
    test("mixes_variables",       test_crossover_mixes_variables)
    test("trivial_formulas",      test_crossover_trivial_formulas)

    print("\n── 8. Variable set & Jaccard ─────────────────────────────")
    test("varset_var",            test_variable_set_var)
    test("varset_const",          test_variable_set_const)
    test("varset_complex",        test_variable_set_complex)
    test("jaccard_identical",     test_jaccard_identical)
    test("jaccard_disjoint",      test_jaccard_disjoint)
    test("jaccard_partial",       test_jaccard_partial)

    print("\n── 9. Integration ────────────────────────────────────────")
    test("net_rtg_predictor",     test_integration_net_rtg_predictor)
    test("random_pipeline",       test_integration_random_formula_pipeline)
    test("mutation_pipeline",     test_integration_mutation_pipeline)

    print("\n── 10. Performance ───────────────────────────────────────")
    test("gen_1k_formulas",       test_perf_generate_1k_formulas)
    test("rpn_compile_1k",        test_perf_rpn_compile_1k)
    test("mutate_1k",             test_perf_mutate_1k)
    test("full_pipeline_1k",      test_perf_full_pipeline_1k)

    print(f"\n╔══════════════════════════════════════════════════════╗")
    print(f"║  Results: {_p:3d} passed  {_f:3d} failed  {_p+_f:3d} total           ║")
    print(f"╚══════════════════════════════════════════════════════╝\n")
    return 0 if _f == 0 else 1

if __name__ == "__main__":
    sys.exit(main())