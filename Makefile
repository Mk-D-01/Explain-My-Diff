.PHONY: test run web evaluate

test:
	python -m unittest discover -s tests -v

run:
	python -m app

web:
	python -m app.web

evaluate:
	python scripts/evaluate.py
