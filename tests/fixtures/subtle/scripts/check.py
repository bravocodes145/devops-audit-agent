import os

if len(os.environ.get("PR_TITLE", "")) < 5:
    raise SystemExit("Title must contain at least five characters")
