.PHONY: test lint fmt

test:
	python3 -m unittest discover -s tests

lint:
	ruff check src tests

fmt:
	ruff format src tests
