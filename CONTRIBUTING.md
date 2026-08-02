# Contributing

Contributions to the tracker code are welcome under the MIT license.

1. Create a focused branch.
2. Run `uv sync` to create the isolated project environment.
3. Keep domain rules in `tracker.py`; the GUI and CLI should only render the
   normalized tracker state.
4. Run `uv run python -m unittest discover -s tests -v`.
5. Do not commit ROMs, save files, credentials, personal data, PID files, or
   additional copyrighted game resources.

Please keep user-facing language consistent with the existing Spanish UI.
