# Contributing

Contributions to the tracker code are welcome under the MIT license.

1. Create a focused branch.
2. Run `uv sync` to create the isolated project environment.
3. Install the hooks with `uv run pre-commit install`.
4. Keep domain rules in `src/tracker.py`; the GUI and CLI should only render
   the normalized tracker state.
5. Run `uv run pre-commit run --all-files` and
   `uv run python -m unittest discover -s tests -v`.
6. Add user-visible changes and fixes to the `Unreleased` section of
   `CHANGELOG.md`.
7. Do not commit ROMs, save files, credentials, personal data, PID files, or
   additional copyrighted game resources.

Please keep user-facing language consistent with the existing Spanish UI.
