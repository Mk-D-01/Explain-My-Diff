.PHONY: test run evaluate

test:
	python -m unittest discover -s tests -v

run:
	python -m app

evaluate:
	python scripts/evaluate.py
