# DevOps Audit Agent

**Rayyan Qamar | Roll number 23i-0815 | Section A**

MLOps & Production AI Engineering - Assignment 2

Python agent for evidence-based DevOps auditing of public GitHub repositories.

## Status

Project scaffold. Implementation, tests, evaluation results and the screenshot
report will be added in subsequent commits.

## Environment

Python 3.11+, Git, and a Gemini API key are required. Runtime dependencies use
Python's standard library. Development tooling is listed in `requirements-dev.txt`.
Store credentials in a local `.env` using the variable names in `.env.example`.
Never commit the `.env` file.

## Planned interface

```bash
python agent.py --repo https://github.com/owner/repository --output report.json
```

## Submission

https://github.com/bravocodes145/devops-audit-agent
