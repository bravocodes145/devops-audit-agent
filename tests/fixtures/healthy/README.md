# Greeting utility

Small Python 3.11+ command-line utility. No third-party runtime dependencies.

Run: `python main.py`. Test: `python -m unittest discover -s tests`.
Lint: `python -m pip install ruff==0.14.2` then `ruff check .`.

CI runs tests and lint on pushes and pull requests. There is no release or
deployment pipeline because this utility is distributed as a source script.
