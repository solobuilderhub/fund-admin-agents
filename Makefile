PY ?= .venv/bin/python
PYTHON ?= python3
MIN_PY := 3.11

.PHONY: help demo test clean setup

help:
	@echo "make setup    create .venv and install requirements"
	@echo "make demo     run every stage and print the transcript (no API key)"
	@echo "make test     run the regression and gate tests"
	@echo "make clean    remove outputs and build artefacts"
	@echo
	@echo "On a machine where python3 is older than $(MIN_PY):"
	@echo "  make setup PYTHON=python3.13"

setup:
	@$(PYTHON) -c 'import sys; v=sys.version_info; assert v >= (3,11), "need Python 3.11+, this interpreter is %d.%d. Try: make setup PYTHON=python3.13" % (v.major, v.minor)'
	$(PYTHON) -m venv .venv
	.venv/bin/pip install --quiet --upgrade pip
	.venv/bin/pip install --quiet -r requirements.txt

demo:
	$(PY) src/demo.py

test:
	$(PY) -m pytest tests/ -q

clean:
	rm -rf outputs/*.json outputs/*.xlsx outputs/*.pdf outputs/capital_call outputs/waterfall
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	find . -name '.pytest_cache' -type d -prune -exec rm -rf {} +
