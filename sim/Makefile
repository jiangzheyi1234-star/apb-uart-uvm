# Run from sim/: make smoke, make regression, or make dry-run.
# Python can also be invoked directly on Windows without GNU Make.
PYTHON ?= python
SIM ?= questa
RTL ?= upstream
SEEDS ?= 1 2 3
ARGS ?=

.PHONY: smoke regression dry-run test-python

smoke:
	$(PYTHON) ../py/run_regression.py --sim $(SIM) --rtl $(RTL) --test uart_smoke_test --seeds 1 $(ARGS)

regression:
	$(PYTHON) ../py/run_regression.py --sim $(SIM) --rtl $(RTL) --seeds $(SEEDS) $(ARGS)

dry-run:
	$(PYTHON) ../py/run_regression.py --sim $(SIM) --rtl $(RTL) --seeds $(SEEDS) --dry-run $(ARGS)

test-python:
	$(PYTHON) -m unittest discover -s ../tests -v
