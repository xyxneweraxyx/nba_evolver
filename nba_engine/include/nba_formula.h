#ifndef NBA_FORMULA_H
#define NBA_FORMULA_H

#include <stdint.h>
#include <stddef.h>

/* ─────────────────────────────────────────────────────────────────────────────
 * nba_formula.h — Core formula engine
 * ─────────────────────────────────────────────────────────────────────────────
 *
 * A formula is a flat array of Instructions executed on a small float stack.
 * This is Reverse Polish Notation (RPN) — no recursion, cache-friendly,
 * vectorizable.
 *
 * Example: (off_rtg * 0.4) + net_rtg
 *   [LOAD 5] [CONST 0.4] [MUL] [LOAD 12] [ADD]
 *
 * Evaluated over N games simultaneously using OpenMP SIMD.
 * ─────────────────────────────────────────────────────────────────────────────
 */

/* ── Limits ──────────────────────────────────────────────────────────────── */
#define NBA_MAX_FORMULA_OPS   256   /* max instructions per formula          */
#define NBA_MAX_STACK_DEPTH   64    /* max RPN stack depth                   */
#define NBA_MAX_VARS          800   /* max stat variables per team snapshot  */
#define NBA_MAX_GAMES         20000 /* max games in a dataset                */

/* ── Opcodes ─────────────────────────────────────────────────────────────── */
typedef enum {
    /* Leaves */
    OP_LOAD_VAR  = 0,   /* push stats[var_index]                            */
    OP_CONST     = 1,   /* push value                                       */

    /* Binary operators (pop 2, push 1) */
    OP_ADD       = 2,
    OP_SUB       = 3,
    OP_MUL       = 4,
    OP_DIV       = 5,   /* safe: denominator += 1e-9                        */
    OP_MAX2      = 6,   /* max(a, b)                                        */
    OP_MIN2      = 7,   /* min(a, b)                                        */
    OP_POW       = 8,   /* pow(|a|+1e-9, clamp(|b|, 0, 4))                 */

    /* Unary operators (pop 1, push 1) */
    OP_NEG       = 9,   /* -a                                               */
    OP_ABS       = 10,  /* |a|                                              */
    OP_LOG       = 11,  /* log(|a| + 1e-9)                                  */
    OP_SQRT      = 12,  /* sqrt(|a|)                                        */
    OP_SQ        = 13,  /* a * a                                            */
    OP_INV       = 14,  /* 1 / (|a| + 1e-9)                                */

    /* Conditional (pop 4: c1, c2, v_true, v_false — push 1) */
    OP_IF_GT     = 15,  /* (c1 > c2)  ? v_true : v_false                   */
    OP_IF_LT     = 16,
    OP_IF_GTE    = 17,
    OP_IF_LTE    = 18,

    OP_COUNT     = 19
} OpCode;

/* ── Single instruction ──────────────────────────────────────────────────── */
typedef struct {
    uint8_t  op;          /* OpCode                                         */
    uint16_t var_index;   /* for OP_LOAD_VAR                                */
    float    value;       /* for OP_CONST                                   */
} Instruction;

/* ── A formula = array of instructions ──────────────────────────────────── */
typedef struct {
    Instruction ops[NBA_MAX_FORMULA_OPS];
    int         length;     /* number of valid instructions                 */
} Formula;

/* ── A game = two flat stat arrays (home + away) ─────────────────────────── */
typedef struct {
    float home[NBA_MAX_VARS];  /* home team stats, indexed by var_index     */
    float away[NBA_MAX_VARS];  /* away team stats                           */
    int   result;              /* 1 = home won, 0 = away won                */
} Game;

/* ── Dataset = array of games ────────────────────────────────────────────── */
typedef struct {
    Game  games[NBA_MAX_GAMES];
    int   n_games;
    int   n_vars;    /* how many variables are actually used                */
} Dataset;

/* ── Interest score ─────────────────────────────────────────────────────── */
typedef struct {
    double accuracy;        /* raw accuracy (0-1)                           */
    double interest;        /* |accuracy - 0.5| * 2  (0=random, 1=perfect) */
    int    n_games_eval;    /* how many games were evaluated                */
    int    direction;       /* +1 = good (>0.5), -1 = bad (<0.5)           */
} FormulaScore;

/* ─────────────────────────────────────────────────────────────────────────────
 * API
 * ─────────────────────────────────────────────────────────────────────────────
 */

/* Evaluate formula on a single game. Returns home_score - away_score.
   If home_score > away_score → predicted home win. */
float nba_eval_single(const Formula *f, const Game *g);

/* Evaluate formula on all games in dataset.
   out_predictions[i] = 1 if predicted home win, 0 otherwise.
   Returns accuracy (0-1). */
double nba_eval_dataset(const Formula *f, const Dataset *ds,
                        int *out_predictions);

/* Fast accuracy only (no predictions array needed).
   Uses OpenMP if available. */
double nba_eval_accuracy(const Formula *f, const Dataset *ds);

/* Evaluate over a block of games [start, start+block_size).
   Used for early stopping / interest filtering. */
FormulaScore nba_eval_block(const Formula *f, const Dataset *ds,
                             int start, int block_size);

/* Compute interest score for a formula over the full dataset. */
FormulaScore nba_score_formula(const Formula *f, const Dataset *ds);

/* Interest filter with ramping threshold.
 *
 * Evaluates in blocks of block_size games. At each checkpoint, checks
 * cumulative interest against a threshold that ramps from:
 *   min_interest * start_fraction   (at the first game)
 * to:
 *   min_interest                    (at the last game)
 *
 * This lets promising formulas survive early blocks where cumulative
 * statistics are noisy, while still enforcing the full threshold at the end.
 *
 * Typical usage:
 *   start_fraction = 0.5  → threshold starts at half the target and ramps up
 *   start_fraction = 1.0  → constant threshold (original behaviour)
 *
 * Returns final FormulaScore (or partial if eliminated early).
 * eliminated = 1 if pruned early, 0 if survived to the end.
 */
FormulaScore nba_filter_formula(const Formula *f, const Dataset *ds,
                                 int block_size, double min_interest,
                                 double start_fraction,
                                 int *eliminated);

/* Validate formula (no stack overflow, no underflow, proper termination).
   Returns 1 if valid, 0 if not. */
int nba_validate_formula(const Formula *f);

/* Print formula in human-readable form.
   var_names[i] = name of variable i (can be NULL for generic names). */
void nba_print_formula(const Formula *f, const char **var_names);

#endif /* NBA_FORMULA_H */