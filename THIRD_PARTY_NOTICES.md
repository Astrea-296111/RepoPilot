# Third party notices

RepoPilot's application code was independently written for this project. No code
was copied from mini-coding-agent, mini-swe-agent, or Aider. Their ideas about
agent loops, repository context and evaluation are acknowledged in README.
Runtime dependencies (FastAPI, Pydantic, Typer, httpx, uvicorn, python-dotenv)
and test dependency (pytest) retain their own licenses; see their distributions.
The optional Docker executor uses the official Python container image under its
own terms. This project's MIT license does not relicense those dependencies.


## Vendored evaluation snapshots

`eval/external/repos` and `eval/external/reference` contain pinned historical
source modules from `mahmoud/boltons` (BSD 3-Clause),
`more-itertools/more-itertools` (MIT), and `un33k/python-slugify` (MIT).
These are benchmark inputs and reference implementations, not RepoPilot
application code. Original notices and the per-task `LICENSE` files are retained.
`eval/external/provenance.json` records each parent/fix commit and source URL.
The snapshots are module-scoped and do not reproduce complete upstream repos.
The sandbox's `text-unidecode` dependency retains its distribution's terms.
