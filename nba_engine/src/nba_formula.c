/*
 * nba_formula.c — Core formula evaluation engine
 * ================================================
 * RPN evaluator, dataset scoring, interest filtering.
 * Compile with: gcc -O3 -march=native -fopenmp -shared -fPIC
 *               -o nba_engine.so nba_formula.c -lm
 */

#include "nba_formula.h"
#include <math.h>
#include <stdio.h>
#include <string.h>
#include <float.h>

/* ─────────────────────────────────────────────────────────────────────────────
 * HELPERS
 * ─────────────────────────────────────────────────────────────────────────────
 */

static inline float _clampf(float v, float lo, float hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

static inline float _safef(float v) {
    if (isnan(v) || isinf(v)) return 0.0f;
    return _clampf(v, -1e8f, 1e8f);
}

/* ─────────────────────────────────────────────────────────────────────────────
 * SINGLE-GAME EVALUATION
 * ─────────────────────────────────────────────────────────────────────────────
 */

static float _eval_team(const Formula *f, const float *stats) {
    float stack[NBA_MAX_STACK_DEPTH];
    int   top = 0;

#define PUSH(x)  do { stack[top++] = _safef(x); } while(0)
#define POP()    (stack[--top])

    for (int i = 0; i < f->length; i++) {
        const Instruction *ins = &f->ops[i];

        switch ((OpCode)ins->op) {

        case OP_LOAD_VAR:
            PUSH(stats[ins->var_index]);
            break;

        case OP_CONST:
            PUSH(ins->value);
            break;

        case OP_ADD: { float b=POP(), a=POP(); PUSH(a+b); break; }
        case OP_SUB: { float b=POP(), a=POP(); PUSH(a-b); break; }
        case OP_MUL: { float b=POP(), a=POP(); PUSH(a*b); break; }
        case OP_DIV: { float b=POP(), a=POP(); PUSH(a/(fabsf(b)+1e-9f)); break; }
        case OP_MAX2:{ float b=POP(), a=POP(); PUSH(a>b?a:b); break; }
        case OP_MIN2:{ float b=POP(), a=POP(); PUSH(a<b?a:b); break; }
        case OP_POW: {
            float b=POP(), a=POP();
            float exp = _clampf(fabsf(b), 0.0f, 4.0f);
            PUSH(powf(fabsf(a)+1e-9f, exp));
            break;
        }

        case OP_NEG:  { float a=POP(); PUSH(-a);                         break; }
        case OP_ABS:  { float a=POP(); PUSH(fabsf(a));                   break; }
        case OP_LOG:  { float a=POP(); PUSH(logf(fabsf(a)+1e-9f));       break; }
        case OP_SQRT: { float a=POP(); PUSH(sqrtf(fabsf(a)));            break; }
        case OP_SQ:   { float a=POP(); PUSH(a*a);                        break; }
        case OP_INV:  { float a=POP(); PUSH(1.0f/(fabsf(a)+1e-9f));      break; }

        case OP_IF_GT:
        case OP_IF_LT:
        case OP_IF_GTE:
        case OP_IF_LTE: {
            if (top < 4) { PUSH(0.0f); break; }
            float vf   = POP();
            float vt   = POP();
            float c2   = POP();
            float c1   = POP();
            int cond = 0;
            if      (ins->op == OP_IF_GT)  cond = (c1 > c2);
            else if (ins->op == OP_IF_LT)  cond = (c1 < c2);
            else if (ins->op == OP_IF_GTE) cond = (c1 >= c2);
            else                           cond = (c1 <= c2);
            PUSH(cond ? vt : vf);
            break;
        }

        default:
            PUSH(0.0f);
            break;
        }

        if (top >= NBA_MAX_STACK_DEPTH - 1) break;
        if (top < 0) { top = 0; }
    }

#undef PUSH
#undef POP

    return (top > 0) ? stack[0] : 0.0f;
}

float nba_eval_single(const Formula *f, const Game *g) {
    float hs = _eval_team(f, g->home);
    float as = _eval_team(f, g->away);
    return hs - as;
}

/* ─────────────────────────────────────────────────────────────────────────────
 * DATASET EVALUATION
 * ─────────────────────────────────────────────────────────────────────────────
 */

double nba_eval_dataset(const Formula *f, const Dataset *ds,
                        int *out_predictions) {
    int correct = 0;

#ifdef _OPENMP
    #pragma omp parallel for reduction(+:correct) schedule(dynamic, 32)
#endif
    for (int i = 0; i < ds->n_games; i++) {
        float diff = nba_eval_single(f, &ds->games[i]);
        int pred   = (diff >= 0.0f) ? 1 : 0;
        if (out_predictions) out_predictions[i] = pred;
        if (pred == ds->games[i].result) correct++;
    }

    return (ds->n_games > 0) ? (double)correct / ds->n_games : 0.5;
}

double nba_eval_accuracy(const Formula *f, const Dataset *ds) {
    return nba_eval_dataset(f, ds, NULL);
}

/* ─────────────────────────────────────────────────────────────────────────────
 * BLOCK EVALUATION
 * ─────────────────────────────────────────────────────────────────────────────
 */

FormulaScore nba_eval_block(const Formula *f, const Dataset *ds,
                             int start, int block_size) {
    FormulaScore score = {0};
    int end = start + block_size;
    if (end > ds->n_games) end = ds->n_games;
    if (start >= end) return score;

    int correct = 0;
    int n       = end - start;

    for (int i = start; i < end; i++) {
        float diff = nba_eval_single(f, &ds->games[i]);
        int pred   = (diff >= 0.0f) ? 1 : 0;
        if (pred == ds->games[i].result) correct++;
    }

    score.accuracy      = (double)correct / n;
    score.interest      = fabs(score.accuracy - 0.5) * 2.0;
    score.n_games_eval  = n;
    score.direction     = (score.accuracy >= 0.5) ? 1 : -1;
    return score;
}

/* ─────────────────────────────────────────────────────────────────────────────
 * FULL SCORE
 * ─────────────────────────────────────────────────────────────────────────────
 */

FormulaScore nba_score_formula(const Formula *f, const Dataset *ds) {
    FormulaScore score = {0};
    if (ds->n_games == 0) return score;

    score.accuracy     = nba_eval_accuracy(f, ds);
    score.interest     = fabs(score.accuracy - 0.5) * 2.0;
    score.n_games_eval = ds->n_games;
    score.direction    = (score.accuracy >= 0.5) ? 1 : -1;
    return score;
}

/* ─────────────────────────────────────────────────────────────────────────────
 * INTEREST FILTER WITH RAMPING THRESHOLD
 * ─────────────────────────────────────────────────────────────────────────────
 *
 * The threshold ramps linearly from (min_interest * start_fraction) at the
 * first game to (min_interest) at the last game:
 *
 *   threshold(t) = min_interest * (start_fraction + (1 - start_fraction) * t)
 *   where t = games_evaluated / total_games  (0.0 → 1.0)
 *
 * This prevents eliminating formulas that start slowly but are genuinely
 * interesting over the full dataset. With start_fraction = 0.5:
 *
 *   t=0.0 → threshold = 0.5 * min_interest   (e.g. 55% accuracy for 60% target)
 *   t=0.5 → threshold = 0.75 * min_interest  (e.g. 57.5% accuracy)
 *   t=1.0 → threshold = 1.0 * min_interest   (e.g. 60% accuracy — full target)
 *
 * start_fraction = 1.0 reproduces the original constant-threshold behaviour.
 * ─────────────────────────────────────────────────────────────────────────────
 */

FormulaScore nba_filter_formula(const Formula *f, const Dataset *ds,
                                 int block_size, double min_interest,
                                 double start_fraction,
                                 int *eliminated) {
    FormulaScore score = {0};
    *eliminated = 0;

    if (ds->n_games == 0 || block_size <= 0) return score;

    /* Clamp start_fraction to [0, 1] */
    if (start_fraction < 0.0) start_fraction = 0.0;
    if (start_fraction > 1.0) start_fraction = 1.0;

    int total_correct = 0;
    int total_eval    = 0;

    for (int start = 0; start < ds->n_games; start += block_size) {
        int end = start + block_size;
        if (end > ds->n_games) end = ds->n_games;
        int n = end - start;

        int block_correct = 0;
        for (int i = start; i < end; i++) {
            float diff = nba_eval_single(f, &ds->games[i]);
            int pred   = (diff >= 0.0f) ? 1 : 0;
            if (pred == ds->games[i].result) block_correct++;
        }

        total_correct += block_correct;
        total_eval    += n;

        double cum_acc      = (double)total_correct / total_eval;
        double cum_interest = fabs(cum_acc - 0.5) * 2.0;

        /* Ramping threshold: lenient at start, strict at end */
        double t         = (double)total_eval / ds->n_games;
        double threshold = min_interest * (start_fraction + (1.0 - start_fraction) * t);

        if (cum_interest < threshold) {
            score.accuracy     = cum_acc;
            score.interest     = cum_interest;
            score.n_games_eval = total_eval;
            score.direction    = (cum_acc >= 0.5) ? 1 : -1;
            *eliminated = 1;
            return score;
        }
    }

    score.accuracy     = (double)total_correct / total_eval;
    score.interest     = fabs(score.accuracy - 0.5) * 2.0;
    score.n_games_eval = total_eval;
    score.direction    = (score.accuracy >= 0.5) ? 1 : -1;
    return score;
}

/* ─────────────────────────────────────────────────────────────────────────────
 * VALIDATION
 * ─────────────────────────────────────────────────────────────────────────────
 */

int nba_validate_formula(const Formula *f) {
    if (!f || f->length <= 0 || f->length > NBA_MAX_FORMULA_OPS)
        return 0;

    int stack_depth = 0;

    for (int i = 0; i < f->length; i++) {
        const Instruction *ins = &f->ops[i];

        if (ins->op >= OP_COUNT) return 0;

        int pops = 0, pushes = 0;
        switch ((OpCode)ins->op) {
            case OP_LOAD_VAR:
            case OP_CONST:
                pops = 0; pushes = 1; break;
            case OP_ADD: case OP_SUB: case OP_MUL: case OP_DIV:
            case OP_MAX2: case OP_MIN2: case OP_POW:
                pops = 2; pushes = 1; break;
            case OP_NEG: case OP_ABS: case OP_LOG:
            case OP_SQRT: case OP_SQ: case OP_INV:
                pops = 1; pushes = 1; break;
            case OP_IF_GT: case OP_IF_LT:
            case OP_IF_GTE: case OP_IF_LTE:
                pops = 4; pushes = 1; break;
            default: return 0;
        }

        if (stack_depth < pops) return 0;
        stack_depth -= pops;
        stack_depth += pushes;

        if (stack_depth > NBA_MAX_STACK_DEPTH) return 0;

        if (ins->op == OP_LOAD_VAR && ins->var_index >= NBA_MAX_VARS)
            return 0;
    }

    return (stack_depth == 1) ? 1 : 0;
}

/* ─────────────────────────────────────────────────────────────────────────────
 * HUMAN-READABLE PRINT
 * ─────────────────────────────────────────────────────────────────────────────
 */

static const char *_op_names[] = {
    "LOAD", "CONST",
    "+", "-", "*", "/", "max", "min", "pow",
    "neg", "abs", "log", "sqrt", "sq", "inv",
    "if>", "if<", "if>=", "if<="
};

void nba_print_formula(const Formula *f, const char **var_names) {
    printf("Formula (%d ops):\n", f->length);
    for (int i = 0; i < f->length; i++) {
        const Instruction *ins = &f->ops[i];
        printf("  [%3d] %6s", i, _op_names[ins->op]);
        if (ins->op == OP_LOAD_VAR) {
            if (var_names && var_names[ins->var_index])
                printf("  var[%d] = %s", ins->var_index, var_names[ins->var_index]);
            else
                printf("  var[%d]", ins->var_index);
        } else if (ins->op == OP_CONST) {
            printf("  %.6g", ins->value);
        }
        printf("\n");
    }
}