"""
formula_engine.py — Layer 2: Python AST Formula Engine
========================================================
Defines all AST node types, random generation, mutations, crossover,
and RPN serialization for the C engine.

Architecture:
  Python AST (this file)
    → to_rpn() → list of (op, var_idx, value)
    → Formula.from_ops() → CFormula
    → FormulaEngine.score() → C evaluation

Key design decisions:
  - Immutable nodes (clone before mutating)
  - Feature importance weighting for variable selection
  - 6 mutation types controlled by strength (0.0–1.0)
  - Full JSON serialization for persistence
"""

from __future__ import annotations
import random
import math
import json
import copy
from typing import List, Optional, Tuple, Dict, Any

# Import registry and opcodes from binding
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nba_engine_binding import (
    get_registry, OP, Formula as CFormula_builder,
    MAX_FORMULA_OPS,
)

# ─────────────────────────────────────────────────────────────────────────────
# OPERATORS
# ─────────────────────────────────────────────────────────────────────────────

BINARY_OPS  = ["+", "-", "*", "/", "max", "min", "pow"]
UNARY_OPS   = ["neg", "abs", "log", "sqrt", "sq", "inv"]
CMP_OPS     = [">", "<", ">=", "<="]

OP_TO_CODE  = {
    "+":    OP["ADD"],  "-":   OP["SUB"],  "*":  OP["MUL"],
    "/":    OP["DIV"],  "max": OP["MAX2"], "min":OP["MIN2"],
    "pow":  OP["POW"],
    "neg":  OP["NEG"],  "abs": OP["ABS"],  "log":OP["LOG"],
    "sqrt": OP["SQRT"], "sq":  OP["SQ"],   "inv":OP["INV"],
    ">":    OP["IF_GT"],"<":   OP["IF_LT"],
    ">=":   OP["IF_GTE"],"<=": OP["IF_LTE"],
}

# Maps symbolic op strings to the keys expected by Formula.from_ops
# (which calls OP.get(name.upper(), 0) internally)
_RPN_OP = {
    "+":    "ADD",   "-":   "SUB",   "*":   "MUL",   "/":   "DIV",
    "max":  "MAX2",  "min": "MIN2",  "pow": "POW",
    "neg":  "NEG",   "abs": "ABS",   "log": "LOG",
    "sqrt": "SQRT",  "sq":  "SQ",    "inv": "INV",
    ">":    "IF_GT", "<":   "IF_LT", ">=":  "IF_GTE","<=":  "IF_LTE",
}

# ─────────────────────────────────────────────────────────────────────────────
# FEATURE IMPORTANCE WEIGHTING
# Variables that are known to be predictive get higher sampling probability.
# ─────────────────────────────────────────────────────────────────────────────

# Tier 1 (high importance): win/loss metrics, efficiency ratings
TIER1_PATTERNS = [
    "season_stats.w_pct", "season_stats.net_rtg", "season_stats.off_rtg",
    "season_stats.def_rtg", "season_stats.pie", "season_stats.ts_pct",
    "season_stats.efg_pct", "season_stats.ast_tov_ratio",
    "last10_stats.w_pct", "last10_stats.net_rtg", "last10_stats.off_rtg",
    "last5_stats.w_pct",  "last5_stats.net_rtg",
    "context.win_streak", "context.rest_days",
    "binary.is_home", "binary.is_back_to_back",
    "player0.per", "player0.bpm", "player0.pts",
]

# Tier 2 (medium): traditional box stats
TIER2_PATTERNS = [
    "season_stats.pts", "season_stats.pace", "season_stats.oreb_pct",
    "season_stats.tov_pct", "season_stats.ast",
    "last10_stats.pts",  "last10_stats.pace",
    "home_stats.w_pct",  "home_stats.net_rtg",
    "away_stats.w_pct",  "away_stats.net_rtg",
    "context.home_win_streak", "context.games_last_7_days",
    "player1.per", "player1.pts",
]

# Tier 3 (low): tracking, hustle, deep bench
# Everything else falls into tier 3

TIER_WEIGHTS = {1: 6.0, 2: 2.5, 3: 1.0}  # relative sampling weights

_WEIGHTED_VARS: Optional[List[Tuple[str, int, float]]] = None

def _build_weighted_vars() -> List[Tuple[str, int, float]]:
    """Build weighted variable list (name, index, weight) once."""
    reg = get_registry()
    result = []
    for name, idx in reg.items():
        if any(name == p for p in TIER1_PATTERNS):
            w = TIER_WEIGHTS[1]
        elif any(name == p for p in TIER2_PATTERNS):
            w = TIER_WEIGHTS[2]
        else:
            w = TIER_WEIGHTS[3]
        result.append((name, idx, w))
    return result

def _get_weighted_vars() -> List[Tuple[str, int, float]]:
    global _WEIGHTED_VARS
    if _WEIGHTED_VARS is None:
        _WEIGHTED_VARS = _build_weighted_vars()
    return _WEIGHTED_VARS

def _sample_var() -> Tuple[str, int]:
    """Sample a variable index with importance weighting."""
    wvars = _get_weighted_vars()
    weights = [w for _, _, w in wvars]
    chosen = random.choices(wvars, weights=weights, k=1)[0]
    return chosen[0], chosen[1]  # (name, index)

# ─────────────────────────────────────────────────────────────────────────────
# AST NODES
# ─────────────────────────────────────────────────────────────────────────────

class Node:
    """Base class for all AST nodes."""

    def eval(self, stats: dict) -> float:
        raise NotImplementedError

    def size(self) -> int:
        """Total number of nodes in subtree."""
        raise NotImplementedError

    def depth(self) -> int:
        """Max depth of subtree."""
        raise NotImplementedError

    def clone(self) -> "Node":
        return copy.deepcopy(self)

    def to_dict(self) -> dict:
        raise NotImplementedError

    def to_rpn(self) -> List[Tuple]:
        """
        Convert subtree to RPN instruction list.
        Each tuple: (op_str_or_code, var_index, float_value)
        """
        raise NotImplementedError

    def __repr__(self) -> str:
        raise NotImplementedError


class VarNode(Node):
    def __init__(self, name: str, index: int):
        self.name  = name
        self.index = index

    def size(self)  -> int: return 1
    def depth(self) -> int: return 0

    def to_dict(self) -> dict:
        return {"t": "var", "name": self.name, "index": self.index}

    def to_rpn(self) -> List[Tuple]:
        return [("LOAD", self.index, 0.0)]

    def __repr__(self) -> str:
        # Short display name
        parts = self.name.split(".")
        return parts[-1] if len(parts) > 1 else self.name


class ConstNode(Node):
    def __init__(self, value: float):
        self.value = value

    def size(self)  -> int: return 1
    def depth(self) -> int: return 0

    def to_dict(self) -> dict:
        return {"t": "const", "v": round(self.value, 6)}

    def to_rpn(self) -> List[Tuple]:
        return [("CONST", 0, float(self.value))]

    def __repr__(self) -> str:
        return f"{self.value:.4g}"


class UnaryNode(Node):
    def __init__(self, op: str, child: Node):
        assert op in UNARY_OPS, f"Unknown unary op: {op}"
        self.op    = op
        self.child = child

    def size(self)  -> int: return 1 + self.child.size()
    def depth(self) -> int: return 1 + self.child.depth()

    def to_dict(self) -> dict:
        return {"t": "unary", "op": self.op, "child": self.child.to_dict()}

    def to_rpn(self) -> List[Tuple]:
        return self.child.to_rpn() + [(_RPN_OP[self.op], 0, 0.0)]

    def __repr__(self) -> str:
        return f"{self.op}({self.child})"


class BinaryNode(Node):
    def __init__(self, op: str, left: Node, right: Node):
        assert op in BINARY_OPS, f"Unknown binary op: {op}"
        self.op    = op
        self.left  = left
        self.right = right

    def size(self)  -> int: return 1 + self.left.size() + self.right.size()
    def depth(self) -> int: return 1 + max(self.left.depth(), self.right.depth())

    def to_dict(self) -> dict:
        return {"t": "bin", "op": self.op,
                "l": self.left.to_dict(), "r": self.right.to_dict()}

    def to_rpn(self) -> List[Tuple]:
        return self.left.to_rpn() + self.right.to_rpn() + [(_RPN_OP[self.op], 0, 0.0)]

    def __repr__(self) -> str:
        return f"({self.left} {self.op} {self.right})"


class IfNode(Node):
    """if (c1 cmp c2) then v_true else v_false"""
    def __init__(self, cmp: str, c1: Node, c2: Node,
                 v_true: Node, v_false: Node):
        assert cmp in CMP_OPS, f"Unknown cmp: {cmp}"
        self.cmp     = cmp
        self.c1      = c1
        self.c2      = c2
        self.v_true  = v_true
        self.v_false = v_false

    def size(self) -> int:
        return 1 + self.c1.size() + self.c2.size() + \
               self.v_true.size() + self.v_false.size()

    def depth(self) -> int:
        return 1 + max(self.c1.depth(), self.c2.depth(),
                       self.v_true.depth(), self.v_false.depth())

    def to_dict(self) -> dict:
        return {"t": "if", "cmp": self.cmp,
                "c1": self.c1.to_dict(),   "c2": self.c2.to_dict(),
                "vt": self.v_true.to_dict(), "vf": self.v_false.to_dict()}

    def to_rpn(self) -> List[Tuple]:
        # RPN order: c1 c2 v_true v_false IF_CMP
        return (self.c1.to_rpn() + self.c2.to_rpn() +
                self.v_true.to_rpn() + self.v_false.to_rpn() +
                [(_RPN_OP[self.cmp], 0, 0.0)])

    def __repr__(self) -> str:
        return f"if({self.c1} {self.cmp} {self.c2}, {self.v_true}, {self.v_false})"

# ─────────────────────────────────────────────────────────────────────────────
# SERIALIZATION
# ─────────────────────────────────────────────────────────────────────────────

def node_from_dict(d: dict) -> Node:
    t = d["t"]
    if t == "var":    return VarNode(d["name"], d["index"])
    if t == "const":  return ConstNode(d["v"])
    if t == "unary":  return UnaryNode(d["op"], node_from_dict(d["child"]))
    if t == "bin":
        return BinaryNode(d["op"], node_from_dict(d["l"]), node_from_dict(d["r"]))
    if t == "if":
        return IfNode(d["cmp"],
                      node_from_dict(d["c1"]),  node_from_dict(d["c2"]),
                      node_from_dict(d["vt"]),  node_from_dict(d["vf"]))
    raise ValueError(f"Unknown node type: {t}")

# ─────────────────────────────────────────────────────────────────────────────
# RPN COMPILATION
# ─────────────────────────────────────────────────────────────────────────────

def ast_to_c_formula(root: Node) -> CFormula_builder:
    """
    Convert an AST to a CFormula ready for C evaluation.
    Returns None if the RPN exceeds MAX_FORMULA_OPS or is invalid.
    """
    rpn = root.to_rpn()
    if len(rpn) > MAX_FORMULA_OPS:
        return None
    return CFormula_builder.from_ops(rpn)

# ─────────────────────────────────────────────────────────────────────────────
# RANDOM GENERATION
# ─────────────────────────────────────────────────────────────────────────────

def _random_const() -> ConstNode:
    """Generate a realistic constant value."""
    kind = random.random()
    if kind < 0.30:
        val = random.gauss(0, 50)           # large scale (e.g. pts/rtg)
    elif kind < 0.55:
        val = random.uniform(0, 1)          # ratio/percentage
    elif kind < 0.72:
        val = random.uniform(90, 125)       # rating range
    elif kind < 0.85:
        val = random.uniform(-15, 15)       # net rating range
    else:
        val = float(random.randint(1, 20))  # small integer
    return ConstNode(round(val, 4))


def _random_leaf() -> Node:
    """Generate a random leaf node (variable or constant)."""
    if random.random() < 0.72:
        name, idx = _sample_var()
        return VarNode(name, idx)
    return _random_const()


def _random_node(depth_remaining: int, max_ops_budget: int = MAX_FORMULA_OPS) -> Node:
    """Recursively generate a random AST node."""
    if depth_remaining <= 0 or max_ops_budget <= 1:
        return _random_leaf()

    # Probability of leaf increases as we get deeper
    p_leaf = 0.15 if depth_remaining >= 4 else \
             0.30 if depth_remaining >= 3 else \
             0.50 if depth_remaining >= 2 else 0.75

    if random.random() < p_leaf:
        return _random_leaf()

    r = random.random()

    if r < 0.45:  # binary
        op  = random.choice(BINARY_OPS)
        # Budget split roughly 50/50 between left and right
        half = max(1, max_ops_budget // 2 - 1)
        l   = _random_node(depth_remaining - 1, half)
        r2  = _random_node(depth_remaining - 1, max_ops_budget - l.size() - 1)
        return BinaryNode(op, l, r2)

    elif r < 0.62:  # unary
        op  = random.choice(UNARY_OPS)
        ch  = _random_node(depth_remaining - 1, max_ops_budget - 1)
        return UnaryNode(op, ch)

    elif r < 0.80:  # if/conditional
        # IfNode needs 4 children — give each budget/4
        sub = max(1, max_ops_budget // 4 - 1)
        cmp = random.choice(CMP_OPS)
        c1  = _random_node(depth_remaining - 1, sub)
        c2  = _random_node(depth_remaining - 1, sub)
        vt  = _random_node(depth_remaining - 1, sub)
        vf  = _random_node(depth_remaining - 1, sub)
        return IfNode(cmp, c1, c2, vt, vf)

    else:
        return _random_leaf()


def random_formula(max_depth: int = 4, max_size: int = 60) -> Node:
    """
    Generate a random formula AST.
    Retries up to 20 times to respect max_size.
    """
    for _ in range(20):
        f = _random_node(max_depth, max_size)
        if f.size() <= max_size:
            return f
    return _random_leaf()  # fallback

# ─────────────────────────────────────────────────────────────────────────────
# TREE TRAVERSAL
# ─────────────────────────────────────────────────────────────────────────────

def _collect_nodes(node: Node, parent: Optional[Node],
                   attr: str, results: list):
    """Collect all (parent, attr, node) triples recursively."""
    results.append((parent, attr, node))
    if isinstance(node, BinaryNode):
        _collect_nodes(node.left,    node, "left",    results)
        _collect_nodes(node.right,   node, "right",   results)
    elif isinstance(node, UnaryNode):
        _collect_nodes(node.child,   node, "child",   results)
    elif isinstance(node, IfNode):
        _collect_nodes(node.c1,      node, "c1",      results)
        _collect_nodes(node.c2,      node, "c2",      results)
        _collect_nodes(node.v_true,  node, "v_true",  results)
        _collect_nodes(node.v_false, node, "v_false", results)


def all_nodes(root: Node) -> List[Tuple]:
    """Return list of (parent, attr, node) for every node."""
    results = []
    _collect_nodes(root, None, None, results)
    return results


def _set_child(parent: Node, attr: str, new_child: Node):
    setattr(parent, attr, new_child)

# ─────────────────────────────────────────────────────────────────────────────
# MUTATIONS
# ─────────────────────────────────────────────────────────────────────────────

def mutate_point(root: Node, max_depth: int, strength: float = 0.5) -> Node:
    """
    Replace one random node with a new random subtree.
    Higher strength → prefer replacing bigger/deeper nodes.
    """
    root  = root.clone()
    nodes = all_nodes(root)
    if not nodes: return root

    if strength > 0.4 and len(nodes) > 2:
        # Weight by subtree size — larger subtrees more likely replaced at high strength
        weights = [max(1, n.size()) ** strength for _, _, n in nodes]
        total   = sum(weights)
        r       = random.random() * total
        chosen  = 0
        for i, w in enumerate(weights):
            r -= w
            if r <= 0: chosen = i; break
        parent, attr, _ = nodes[chosen]
    else:
        parent, attr, _ = random.choice(nodes)

    sub_depth = max(1, int(max_depth * (0.3 + 0.7 * strength)))
    new_sub   = _random_node(sub_depth)

    if parent is None: return new_sub
    _set_child(parent, attr, new_sub)
    return root


def mutate_const(root: Node, strength: float = 0.5) -> Node:
    """
    Tweak one constant by ±σ.
    strength=0 → σ=5%, strength=1 → σ=200%.
    """
    root   = root.clone()
    nodes  = all_nodes(root)
    consts = [(p, a, n) for p, a, n in nodes if isinstance(n, ConstNode)]
    if not consts: return mutate_point(root, 3, strength * 0.3)

    parent, attr, node = random.choice(consts)
    std     = 0.05 + strength * 1.95
    delta   = node.value * random.gauss(0, std)
    new_val = round(node.value + delta, 4)
    new_node = ConstNode(new_val)
    if parent is None: return new_node
    _set_child(parent, attr, new_node)
    return root


def mutate_operator(root: Node) -> Node:
    """Swap one operator for another of the same arity."""
    root  = root.clone()
    nodes = all_nodes(root)
    ops   = [(p, a, n) for p, a, n in nodes
             if isinstance(n, (BinaryNode, UnaryNode, IfNode))]
    if not ops: return root

    parent, attr, node = random.choice(ops)
    if isinstance(node, BinaryNode):
        node.op  = random.choice(BINARY_OPS)
    elif isinstance(node, UnaryNode):
        node.op  = random.choice(UNARY_OPS)
    elif isinstance(node, IfNode):
        node.cmp = random.choice(CMP_OPS)
    return root


def mutate_var_swap(root: Node) -> Node:
    """Replace one variable with a different one (importance-weighted)."""
    root  = root.clone()
    nodes = all_nodes(root)
    vars_ = [(p, a, n) for p, a, n in nodes if isinstance(n, VarNode)]
    if not vars_: return mutate_point(root, 2, 0.3)

    parent, attr, _ = random.choice(vars_)
    name, idx = _sample_var()
    new_node  = VarNode(name, idx)
    if parent is None: return new_node
    _set_child(parent, attr, new_node)
    return root


def mutate_hoist(root: Node) -> Node:
    """
    Replace a node with one of its own children (simplifies the tree).
    Effective against bloat and convergence.
    """
    root  = root.clone()
    nodes = all_nodes(root)
    internal = [(p, a, n) for p, a, n in nodes
                if isinstance(n, (BinaryNode, UnaryNode, IfNode))]
    if not internal: return root

    parent, attr, node = random.choice(internal)

    if isinstance(node, BinaryNode):
        child = random.choice([node.left, node.right]).clone()
    elif isinstance(node, UnaryNode):
        child = node.child.clone()
    else:
        child = random.choice([node.c1, node.c2,
                                node.v_true, node.v_false]).clone()

    if parent is None: return child
    _set_child(parent, attr, child)
    return root


def mutate_subtree(root: Node, max_depth: int) -> Node:
    """
    Replace an entire internal subtree with a fresh random tree.
    More disruptive than mutate_point.
    """
    root     = root.clone()
    nodes    = all_nodes(root)
    internal = [(p, a, n) for p, a, n in nodes
                if isinstance(n, (BinaryNode, UnaryNode, IfNode))]
    if not internal:
        return mutate_point(root, max_depth, 1.0)

    parent, attr, _ = random.choice(internal)
    new_sub         = _random_node(max_depth)
    if parent is None: return new_sub
    _set_child(parent, attr, new_sub)
    return root


def mutate(root: Node, max_depth: int, strength: float = 0.5) -> Node:
    """
    Apply one random mutation, biased by strength (0.0–1.0).

    strength=0.0 → gentle : mostly const tweaks + var swaps
    strength=0.5 → balanced (default)
    strength=1.0 → violent: mostly subtree + hoist

    Probability table:
      mutation       s=0.0   s=0.5   s=1.0
      hoist          0%      12%     25%
      subtree        0%      17%     35%
      point          30%     30%     30%
      var_swap       25%     13%     5%
      operator       25%     13%     5%
      const          20%     15%     0%
    """
    s = max(0.0, min(1.0, strength))
    p_hoist    = s * 0.25
    p_subtree  = s * 0.35
    p_point    = 0.30
    p_varswap  = 0.25 - s * 0.20
    p_operator = 0.25 - s * 0.20
    p_const    = 0.20 - s * 0.20

    total = p_hoist + p_subtree + p_point + p_varswap + p_operator + p_const
    r     = random.random() * total

    if r < p_hoist:    return mutate_hoist(root)
    r -= p_hoist
    if r < p_subtree:  return mutate_subtree(root, max_depth)
    r -= p_subtree
    if r < p_point:    return mutate_point(root, max_depth, s)
    r -= p_point
    if r < p_varswap:  return mutate_var_swap(root)
    r -= p_varswap
    if r < p_operator: return mutate_operator(root)
    return mutate_const(root, s)

# ─────────────────────────────────────────────────────────────────────────────
# CROSSOVER
# ─────────────────────────────────────────────────────────────────────────────

def crossover(root_a: Node, root_b: Node) -> Tuple[Node, Node]:
    """
    Swap a random subtree between two formulas.
    Returns two new children. Neither parent is mutated.
    """
    a = root_a.clone()
    b = root_b.clone()

    nodes_a = all_nodes(a)
    nodes_b = all_nodes(b)

    # Need at least 2 nodes each (can't swap the root itself if we want
    # both children to be non-trivial)
    if len(nodes_a) < 2 or len(nodes_b) < 2:
        return a, b

    pa, aa, na = random.choice(nodes_a[1:])  # skip root
    pb, ab, nb = random.choice(nodes_b[1:])

    na_clone = na.clone()
    nb_clone = nb.clone()

    _set_child(pa, aa, nb_clone)
    _set_child(pb, ab, na_clone)

    return a, b

# ─────────────────────────────────────────────────────────────────────────────
# VARIABLE SET (for niching)
# ─────────────────────────────────────────────────────────────────────────────

def variable_set(root: Node) -> set:
    """Extract set of variable names used in the formula."""
    names = set()
    def _walk(n):
        if isinstance(n, VarNode):
            names.add(n.name)
        elif isinstance(n, BinaryNode):
            _walk(n.left); _walk(n.right)
        elif isinstance(n, UnaryNode):
            _walk(n.child)
        elif isinstance(n, IfNode):
            _walk(n.c1); _walk(n.c2)
            _walk(n.v_true); _walk(n.v_false)
    _walk(root)
    return names


def jaccard_similarity(a: Node, b: Node) -> float:
    """Jaccard similarity of variable sets (0=disjoint, 1=identical)."""
    va, vb = variable_set(a), variable_set(b)
    union = len(va | vb)
    return len(va & vb) / union if union else 0.0
