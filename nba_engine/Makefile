# Makefile — NBA Formula Engine
# Usage: make          → build nba_engine.so
#        make test     → build + run all tests
#        make clean    → remove compiled files
#        make bench    → build with max optimization + profiling

CC      = gcc
CFLAGS  = -O3 -march=native -Wall -Wextra -ffast-math
LDFLAGS = -lm
SHARED  = -shared -fPIC

# OpenMP (parallel evaluation) — disable with: make OMP=0
OMP ?= 1
ifeq ($(OMP), 1)
    CFLAGS  += -fopenmp
    LDFLAGS += -fopenmp
endif

SRC     = src/nba_formula.c
INC     = -Iinclude
OUT     = nba_engine.so
TEST_BIN= tests/run_tests

.PHONY: all test clean bench info

all: $(OUT)

$(OUT): $(SRC)
	$(CC) $(CFLAGS) $(SHARED) $(INC) $(SRC) -o $(OUT) $(LDFLAGS)
	@echo "Built $(OUT)"

test: $(OUT)
	$(CC) $(CFLAGS) $(INC) tests/test_engine.c $(SRC) -o $(TEST_BIN) $(LDFLAGS)
	@echo "Running tests..."
	@./$(TEST_BIN)

bench: $(SRC)
	$(CC) -O3 -march=native -ffast-math -fopenmp $(SHARED) $(INC) \
	      $(SRC) -o $(OUT) $(LDFLAGS) -pg
	@echo "Built with profiling"

clean:
	rm -f $(OUT) $(TEST_BIN)
	@echo "Cleaned"

info:
	@echo "CC=$(CC)"
	@$(CC) --version | head -1
	@echo "OMP=$(OMP)"
