/*
 * tests/test_engine.c — Batterie de tests complète pour le moteur C
 */

#include "nba_formula.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>

/* ── Test framework ──────────────────────────────────────────────────────── */
static int _passed = 0, _failed = 0;

#define TEST(name) static void test_##name(void)
#define RUN(name) do { \
    printf("  %-52s", #name); \
    _cur_fail=0; _tests_run++; \
    test_##name(); \
    if(!_cur_fail){printf("PASS\n");_passed++;} \
    else{_failed++;} \
} while(0)
static int _tests_run=0, _cur_fail=0;

#define ASSERT(c) do { if(!(c)){ \
    printf("FAIL (line %d: %s)\n",__LINE__,#c); _cur_fail=1; return; }} while(0)
#define ASSERT_FEQ(a,b,t) do { if(fabsf((float)(a)-(float)(b))>(float)(t)){ \
    printf("FAIL (line %d: %.5f != %.5f)\n",__LINE__,(double)(a),(double)(b)); \
    _cur_fail=1; return; }} while(0)
#define ASSERT_DEQ(a,b,t) do { if(fabs((double)(a)-(double)(b))>(double)(t)){ \
    printf("FAIL (line %d: %.7f != %.7f)\n",__LINE__,(double)(a),(double)(b)); \
    _cur_fail=1; return; }} while(0)

/* ── Single global Dataset (91MB BSS — allocated once) ───────────────────── */
static Dataset G_DS;

static void fill_ds(int n, float home_v, float away_v, int result) {
    memset(&G_DS, 0, sizeof(G_DS));
    G_DS.n_games = n; G_DS.n_vars = 10;
    for (int i = 0; i < n; i++) {
        for (int j = 0; j < 10; j++) {
            G_DS.games[i].home[j] = home_v + j;
            G_DS.games[i].away[j] = away_v + j;
        }
        G_DS.games[i].result = result;
    }
}

/* ── Formula builders ────────────────────────────────────────────────────── */
static Formula mk_const(float v) {
    Formula f={0}; f.ops[0].op=OP_CONST; f.ops[0].value=v; f.length=1; return f;
}
static Formula mk_load(int idx) {
    Formula f={0}; f.ops[0].op=OP_LOAD_VAR; f.ops[0].var_index=idx; f.length=1; return f;
}
static Formula mk_add(int a, int b) {
    Formula f={0};
    f.ops[0].op=OP_LOAD_VAR; f.ops[0].var_index=a;
    f.ops[1].op=OP_LOAD_VAR; f.ops[1].var_index=b;
    f.ops[2].op=OP_ADD; f.length=3; return f;
}
static Formula mk_mul_c(int a, float v) {
    Formula f={0};
    f.ops[0].op=OP_LOAD_VAR; f.ops[0].var_index=a;
    f.ops[1].op=OP_CONST; f.ops[1].value=v;
    f.ops[2].op=OP_MUL; f.length=3; return f;
}

/* ═══════════════════════════════════════════════════════════════════════════
 * GROUP 1: single-game evaluation
 * ═══════════════════════════════════════════════════════════════════════════ */

TEST(eval_const_zero_diff) {
    Formula f=mk_const(42.0f); Game g={0};
    ASSERT_FEQ(nba_eval_single(&f,&g), 0.0f, 1e-5f);
}
TEST(eval_load_var) {
    Formula f=mk_load(3); Game g={0};
    g.home[3]=110.5f; g.away[3]=105.2f;
    ASSERT_FEQ(nba_eval_single(&f,&g), 5.3f, 1e-3f);
}
TEST(eval_add_two_vars) {
    Formula f=mk_add(0,1); Game g={0};
    g.home[0]=10.0f; g.home[1]=5.0f;
    g.away[0]=8.0f;  g.away[1]=4.0f;
    ASSERT_FEQ(nba_eval_single(&f,&g), 3.0f, 1e-4f);
}
TEST(eval_mul_const) {
    Formula f=mk_mul_c(0,0.4f); Game g={0};
    g.home[0]=120.0f; g.away[0]=100.0f;
    ASSERT_FEQ(nba_eval_single(&f,&g), 8.0f, 1e-3f);
}
TEST(eval_sub) {
    Formula f={0};
    f.ops[0].op=OP_LOAD_VAR; f.ops[0].var_index=0;
    f.ops[1].op=OP_LOAD_VAR; f.ops[1].var_index=1;
    f.ops[2].op=OP_SUB; f.length=3;
    Game g={0};
    g.home[0]=50.0f; g.home[1]=30.0f;
    g.away[0]=40.0f; g.away[1]=25.0f;
    ASSERT_FEQ(nba_eval_single(&f,&g), 5.0f, 1e-3f);
}
TEST(eval_div_by_zero_safe) {
    Formula f={0};
    f.ops[0].op=OP_CONST; f.ops[0].value=10.0f;
    f.ops[1].op=OP_CONST; f.ops[1].value=0.0f;
    f.ops[2].op=OP_DIV; f.length=3;
    Game g={0};
    float r=nba_eval_single(&f,&g);
    ASSERT(!isnan(r) && !isinf(r) && r < 1e9f);
}
TEST(eval_log) {
    Formula f={0};
    f.ops[0].op=OP_CONST; f.ops[0].value=100.0f;
    f.ops[1].op=OP_LOG; f.length=2;
    Game g={0};
    ASSERT_FEQ(nba_eval_single(&f,&g), 0.0f, 1e-4f); /* same both sides */
}
TEST(eval_sqrt) {
    Formula f={0};
    f.ops[0].op=OP_LOAD_VAR; f.ops[0].var_index=0;
    f.ops[1].op=OP_SQRT; f.length=2;
    Game g={0}; g.home[0]=100.0f; g.away[0]=64.0f;
    ASSERT_FEQ(nba_eval_single(&f,&g), 2.0f, 1e-4f);
}
TEST(eval_neg) {
    Formula f={0};
    f.ops[0].op=OP_LOAD_VAR; f.ops[0].var_index=0;
    f.ops[1].op=OP_NEG; f.length=2;
    Game g={0}; g.home[0]=5.0f; g.away[0]=3.0f;
    ASSERT_FEQ(nba_eval_single(&f,&g), -2.0f, 1e-4f);
}
TEST(eval_if_gt) {
    Formula f={0};
    f.ops[0].op=OP_LOAD_VAR; f.ops[0].var_index=0; /* c1 */
    f.ops[1].op=OP_LOAD_VAR; f.ops[1].var_index=1; /* c2 */
    f.ops[2].op=OP_LOAD_VAR; f.ops[2].var_index=2; /* v_true */
    f.ops[3].op=OP_LOAD_VAR; f.ops[3].var_index=3; /* v_false */
    f.ops[4].op=OP_IF_GT; f.length=5;
    Game g={0};
    g.home[0]=10.0f; g.home[1]=5.0f; g.home[2]=100.0f; g.home[3]=0.0f;
    g.away[0]=1.0f;  g.away[1]=2.0f; g.away[2]=50.0f;  g.away[3]=1.0f;
    /* home: 10>5=true→100; away: 1>2=false→1; diff=99 */
    ASSERT_FEQ(nba_eval_single(&f,&g), 99.0f, 1e-3f);
}
TEST(eval_nan_inf_in_data) {
    Formula f=mk_load(0); Game g={0};
    g.home[0] = 1.0f/0.0f; g.away[0] = -1.0f/0.0f;
    float r=nba_eval_single(&f,&g);
    ASSERT(!isnan(r) && !isinf(r));
}
TEST(eval_negative_net_rtg) {
    Formula f=mk_load(0); Game g={0};
    g.home[0]=-5.0f; g.away[0]=-8.0f;
    ASSERT_FEQ(nba_eval_single(&f,&g), 3.0f, 1e-4f);
}

/* ═══════════════════════════════════════════════════════════════════════════
 * GROUP 2: dataset accuracy
 * ═══════════════════════════════════════════════════════════════════════════ */

TEST(acc_home_wins_100pct) {
    Formula f=mk_load(0);
    fill_ds(1000,10.0f,5.0f,1);
    ASSERT_DEQ(nba_eval_accuracy(&f,&G_DS), 1.0, 1e-6);
}
TEST(acc_away_wins_100pct) {
    Formula f=mk_load(0);
    fill_ds(1000,5.0f,10.0f,0);
    ASSERT_DEQ(nba_eval_accuracy(&f,&G_DS), 1.0, 1e-6);
}
TEST(acc_fifty_fifty) {
    Formula f=mk_load(0);
    memset(&G_DS,0,sizeof(G_DS)); G_DS.n_games=1000; G_DS.n_vars=5;
    for(int i=0;i<1000;i++){
        G_DS.games[i].home[0]=10.0f; G_DS.games[i].away[0]=5.0f;
        G_DS.games[i].result=(i<500)?1:0;
    }
    ASSERT_DEQ(nba_eval_accuracy(&f,&G_DS), 0.5, 1e-6);
}
TEST(acc_empty_dataset) {
    Formula f=mk_const(1.0f); memset(&G_DS,0,sizeof(G_DS)); G_DS.n_games=0;
    ASSERT_DEQ(nba_eval_accuracy(&f,&G_DS), 0.5, 1e-6);
}
TEST(score_80pct_interest) {
    Formula f=mk_load(0);
    memset(&G_DS,0,sizeof(G_DS)); G_DS.n_games=100; G_DS.n_vars=5;
    for(int i=0;i<100;i++){
        G_DS.games[i].home[0]=10.0f; G_DS.games[i].away[0]=5.0f;
        G_DS.games[i].result=(i<80)?1:0;
    }
    FormulaScore s=nba_score_formula(&f,&G_DS);
    ASSERT_DEQ(s.accuracy, 0.80, 1e-6);
    ASSERT_DEQ(s.interest, 0.60, 1e-6);
    ASSERT(s.direction==1);
}
TEST(score_bad_direction) {
    Formula f=mk_load(0);
    memset(&G_DS,0,sizeof(G_DS)); G_DS.n_games=100; G_DS.n_vars=5;
    for(int i=0;i<100;i++){
        G_DS.games[i].home[0]=5.0f; G_DS.games[i].away[0]=10.0f;
        G_DS.games[i].result=(i<20)?0:1;
    }
    FormulaScore s=nba_score_formula(&f,&G_DS);
    ASSERT_DEQ(s.accuracy, 0.20, 1e-6);
    ASSERT(s.direction==-1);
}

/* ═══════════════════════════════════════════════════════════════════════════
 * GROUP 3: interest filter
 * ═══════════════════════════════════════════════════════════════════════════ */

TEST(filter_survives) {
    Formula f=mk_load(0);
    memset(&G_DS,0,sizeof(G_DS)); G_DS.n_games=500; G_DS.n_vars=5;
    for(int i=0;i<500;i++){
        G_DS.games[i].home[0]=10.0f; G_DS.games[i].away[0]=5.0f;
        G_DS.games[i].result=(i<450)?1:0;
    }
    int elim=0;
    FormulaScore s=nba_filter_formula(&f,&G_DS,100,0.20,&elim);
    ASSERT(elim==0);
    ASSERT_DEQ(s.n_games_eval,500,0.1);
}
TEST(filter_eliminated_at_first_block) {
    Formula f=mk_load(0);
    memset(&G_DS,0,sizeof(G_DS)); G_DS.n_games=1000; G_DS.n_vars=5;
    for(int i=0;i<1000;i++){
        G_DS.games[i].home[0]=10.0f; G_DS.games[i].away[0]=5.0f;
        G_DS.games[i].result=(i%2==0)?1:0; /* 50% → interest≈0 */
    }
    int elim=0;
    FormulaScore s=nba_filter_formula(&f,&G_DS,100,0.10,&elim);
    ASSERT(elim==1);
    ASSERT(s.n_games_eval<=200);
}
TEST(filter_min_interest_zero_never_elim) {
    Formula f=mk_load(0);
    memset(&G_DS,0,sizeof(G_DS)); G_DS.n_games=300; G_DS.n_vars=5;
    for(int i=0;i<300;i++){
        G_DS.games[i].home[0]=10.0f; G_DS.games[i].away[0]=5.0f;
        G_DS.games[i].result=(i%2==0)?1:0;
    }
    int elim=0;
    nba_filter_formula(&f,&G_DS,100,0.0,&elim);
    ASSERT(elim==0);
}

/* ═══════════════════════════════════════════════════════════════════════════
 * GROUP 4: validation
 * ═══════════════════════════════════════════════════════════════════════════ */

TEST(valid_const)       { Formula f=mk_const(1.0f); ASSERT(nba_validate_formula(&f)==1); }
TEST(valid_load)        { Formula f=mk_load(0);     ASSERT(nba_validate_formula(&f)==1); }
TEST(valid_add)         { Formula f=mk_add(0,1);    ASSERT(nba_validate_formula(&f)==1); }
TEST(invalid_empty)     { Formula f={0}; f.length=0; ASSERT(nba_validate_formula(&f)==0); }
TEST(invalid_underflow) {
    Formula f={0}; f.ops[0].op=OP_ADD; f.length=1;
    ASSERT(nba_validate_formula(&f)==0);
}
TEST(invalid_two_values) {
    Formula f={0};
    f.ops[0].op=OP_CONST; f.ops[0].value=1.0f;
    f.ops[1].op=OP_CONST; f.ops[1].value=2.0f;
    f.length=2; ASSERT(nba_validate_formula(&f)==0);
}
TEST(invalid_if_not_enough_args) {
    Formula f={0};
    f.ops[0].op=OP_CONST; f.ops[0].value=1.0f;
    f.ops[1].op=OP_CONST; f.ops[1].value=2.0f;
    f.ops[2].op=OP_IF_GT; f.length=3;
    ASSERT(nba_validate_formula(&f)==0);
}
TEST(valid_if_correct) {
    Formula f={0};
    for(int i=0;i<4;i++){ f.ops[i].op=OP_LOAD_VAR; f.ops[i].var_index=i; }
    f.ops[4].op=OP_IF_GT; f.length=5;
    ASSERT(nba_validate_formula(&f)==1);
}
TEST(invalid_var_out_of_range) {
    Formula f={0}; f.ops[0].op=OP_LOAD_VAR;
    f.ops[0].var_index=NBA_MAX_VARS+1; f.length=1;
    ASSERT(nba_validate_formula(&f)==0);
}
TEST(invalid_null) { ASSERT(nba_validate_formula(NULL)==0); }

/* ═══════════════════════════════════════════════════════════════════════════
 * GROUP 5: performance benchmarks
 * ═══════════════════════════════════════════════════════════════════════════ */

TEST(bench_10k_simple) {
    Formula f=mk_load(0);
    memset(&G_DS,0,sizeof(G_DS)); G_DS.n_games=10000; G_DS.n_vars=5;
    for(int i=0;i<10000;i++){
        G_DS.games[i].home[0]=10.0f; G_DS.games[i].away[0]=5.0f;
        G_DS.games[i].result=1;
    }
    clock_t t0=clock();
    double acc=nba_eval_accuracy(&f,&G_DS);
    double ms=(double)(clock()-t0)/CLOCKS_PER_SEC*1000.0;
    printf("[%.1fms acc=%.4f] ", ms, acc);
    ASSERT(ms<200.0); ASSERT_DEQ(acc,1.0,1e-6);
}
TEST(bench_10k_complex_12ops) {
    Formula f={0};
    f.ops[0].op=OP_LOAD_VAR;  f.ops[0].var_index=0;
    f.ops[1].op=OP_CONST;     f.ops[1].value=0.4f;
    f.ops[2].op=OP_MUL;
    f.ops[3].op=OP_LOAD_VAR;  f.ops[3].var_index=1;
    f.ops[4].op=OP_ADD;
    f.ops[5].op=OP_LOAD_VAR;  f.ops[5].var_index=2;
    f.ops[6].op=OP_LOG;
    f.ops[7].op=OP_MUL;
    f.ops[8].op=OP_LOAD_VAR;  f.ops[8].var_index=3;
    f.ops[9].op=OP_SUB;
    f.length=10;
    memset(&G_DS,0,sizeof(G_DS)); G_DS.n_games=10000; G_DS.n_vars=5;
    for(int i=0;i<10000;i++){
        G_DS.games[i].home[0]=115.0f+(i%20); G_DS.games[i].home[1]=8.0f;
        G_DS.games[i].home[2]=98.0f;         G_DS.games[i].home[3]=2.0f;
        G_DS.games[i].away[0]=110.0f+(i%15); G_DS.games[i].away[1]=5.0f;
        G_DS.games[i].away[2]=95.0f;         G_DS.games[i].away[3]=1.5f;
        G_DS.games[i].result=(G_DS.games[i].home[0]>G_DS.games[i].away[0])?1:0;
    }
    clock_t t0=clock();
    double acc=nba_eval_accuracy(&f,&G_DS);
    double ms=(double)(clock()-t0)/CLOCKS_PER_SEC*1000.0;
    printf("[%.1fms acc=%.4f] ", ms, acc);
    ASSERT(ms<500.0); (void)acc;
}
TEST(bench_filter_500_formulas) {
    memset(&G_DS,0,sizeof(G_DS)); G_DS.n_games=5000; G_DS.n_vars=5;
    for(int i=0;i<5000;i++){
        G_DS.games[i].home[0]=10.0f+(i%30);
        G_DS.games[i].away[0]=8.0f+(i%25);
        G_DS.games[i].result=(i%2==0)?1:0;
    }
    clock_t t0=clock(); int surv=0,elim_n=0;
    for(int k=0;k<500;k++){
        Formula f=mk_load(k%5);
        int e=0; nba_filter_formula(&f,&G_DS,100,0.05,&e);
        if(e) elim_n++; else surv++;
    }
    double ms=(double)(clock()-t0)/CLOCKS_PER_SEC*1000.0;
    printf("[%.0fms surv=%d elim=%d] ", ms, surv, elim_n);
    ASSERT(ms<5000.0);
}

/* ═══════════════════════════════════════════════════════════════════════════
 * MAIN
 * ═══════════════════════════════════════════════════════════════════════════ */

int main(void) {
    printf("\n╔══════════════════════════════════════════════════════════╗\n");
    printf("║   NBA Formula Engine — C Test Suite                      ║\n");
    printf("╚══════════════════════════════════════════════════════════╝\n\n");

    printf("── 1. Single-game evaluation ────────────────────────────────\n");
    RUN(eval_const_zero_diff); RUN(eval_load_var); RUN(eval_add_two_vars);
    RUN(eval_mul_const); RUN(eval_sub); RUN(eval_div_by_zero_safe);
    RUN(eval_log); RUN(eval_sqrt); RUN(eval_neg); RUN(eval_if_gt);
    RUN(eval_nan_inf_in_data); RUN(eval_negative_net_rtg);

    printf("\n── 2. Dataset accuracy ──────────────────────────────────────\n");
    RUN(acc_home_wins_100pct); RUN(acc_away_wins_100pct);
    RUN(acc_fifty_fifty); RUN(acc_empty_dataset);
    RUN(score_80pct_interest); RUN(score_bad_direction);

    printf("\n── 3. Interest filter ───────────────────────────────────────\n");
    RUN(filter_survives); RUN(filter_eliminated_at_first_block);
    RUN(filter_min_interest_zero_never_elim);

    printf("\n── 4. Validation ────────────────────────────────────────────\n");
    RUN(valid_const); RUN(valid_load); RUN(valid_add);
    RUN(invalid_empty); RUN(invalid_underflow); RUN(invalid_two_values);
    RUN(invalid_if_not_enough_args); RUN(valid_if_correct);
    RUN(invalid_var_out_of_range); RUN(invalid_null);

    printf("\n── 5. Performance ───────────────────────────────────────────\n");
    RUN(bench_10k_simple); RUN(bench_10k_complex_12ops);
    RUN(bench_filter_500_formulas);

    printf("\n╔══════════════════════════════════════════════════════════╗\n");
    printf("║  Results: %3d passed  %3d failed  %3d total               ║\n",
           _passed, _failed, _tests_run);
    printf("╚══════════════════════════════════════════════════════════╝\n\n");
    return (_failed==0)?0:1;
}
