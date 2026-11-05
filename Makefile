PY ?= .venv/bin/python

.PHONY: help demo test clean setup

help:
	@echo "make setup   create .venv and install requirements"
	@echo "make demo    run every stage and print the transcript (no API key)"
	@echo "make test    run the regression and gate tests"
	@echo "make clean   remove outputs and build artefacts"

setup:
	python3 -m venv .venv
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
