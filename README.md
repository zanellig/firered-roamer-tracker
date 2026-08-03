# Floating roamer tracker

An always-on-top desktop window that reads Pokémon FireRed, LeafGreen or
Emerald RAM through RetroArch and marks where the roaming Pokémon and the
player are on the matching Kanto or Hoenn map. It is read-only: it never
modifies RAM or the save file.

The game and species are detected automatically. FireRed and LeafGreen pick
the roamer based on the starter: Bulbasaur maps to Entei, Squirtle to Raikou
and Charmander to Suicune. If the save has already created the roamer, the
tracker uses the stored species directly. Emerald likewise reads the saved
Latias or Latios choice.

## Running

1. In RetroArch, enable **Settings > Network > Network Commands**.
2. Open a supported English FireRed, LeafGreen or Emerald ROM with the mGBA
   core.
3. Create the local virtual environment and start the application:

   ```bash
   cd roamer_watcher
   uv sync
   uv run python src/main.py
   ```

The window can be dragged from the top bar and stays above the others by
default. The pin button in the title bar turns that behavior off. If the game is not open
yet or the connection drops, the tracker keeps retrying instead of exiting.
`Ctrl+C` from the terminal closes the window and the RAM reader without
printing a traceback. The **×** button also closes the application completely
and stops the reader.

## Window layouts

There are two layouts. The **⚙** button next to the pin opens the settings
menu, where *Diseño de ventana* switches between them without restarting. The
same choice can be made on the command line:

```bash
uv run python src/main.py --ui clasica
uv run python src/main.py --ui mapa
```

`clasica` is the dark panelled window: connection row, map, legend, next-move
notice, the roamer and player cards, and the roamer's data panel. It is dragged
from the top bar.

That last panel shows the battle identity the game keeps for the roamer between
encounters: its PID, its nature, the six IVs, current and maximum HP, and any
status condition it is carrying. A roamer that escaped poisoned or asleep still
shows it there, so the next encounter can be planned before it starts. Until
the game creates the roamer the readouts stay blank. This panel only exists in
this layout.

Both layouts call the player by the name chosen in the game, and the marker on
the map carries that name's initial. Until the game shows a readable name they
fall back to `VOS` and a `V` marker.

`mapa` is inspired by the GBA town map screens. The regional map fills most of
the window, the top plate shows the species with its sprite and its zone, and
everything else is spoken through the game's message box, one page every 2.6
seconds, with the ▼ arrow blinking the way it does in dialogue. It is a
considerably smaller window and can be dragged from anywhere.

The chosen layout is remembered, from the menu as well as from the flag, so
afterwards plain `uv run python src/main.py` is enough. Without `--ui` and
without a previous choice it uses `clasica`. If the settings file ends up holding an
unknown value, the tracker falls back to `clasica` instead of failing.

## Movement forecast

When the player and the roamer are in different zones, the map highlights in
gold the likely routes after the next normal transition and shows the
percentage for each one. The calculation replicates the active game's Kanto
or Hoenn movement table, including the 1-in-16 random jump and the route the
game excludes based on the player's recent history.

If a likely route has a quick entrance from the current town, the window
recommends crossing over to it. In every other case it keeps the probabilities
on the map without recommending Fly: flying moves the roamer to a random
location and invalidates the previous forecast.

For example, entering Viridian from Route 1 with the roamer on Route 22, normal
movement excludes Route 1 and splits its options between Route 2 and Route 23.
Each one lands at **47.1%** once the 1-in-16 chance of the roamer jumping
elsewhere on the map is included. The application recommends crossing to Route
2, the immediate exit from Viridian.

Forecast routes use a gold outline and the recommended interception is
highlighted more strongly. When both share a zone, only the match notice is
kept, without a redundant instruction.

The default address is `127.0.0.1:55355`. It can be changed along with the read
frequency:

```bash
uv run python src/main.py --host 127.0.0.1 --port 55355 --interval 0.20
```

To keep using the terminal view:

```bash
uv run python src/roamer_ram_watch.py
```

## Dependencies

The application uses Python 3 and PySide 6. `uv sync` creates `.venv` inside
this folder and installs the runtime and development dependencies there; it
does not install packages into the global Python. Activating the environment
is not necessary because `uv run` selects it automatically.

```bash
uv sync
```

Pillow is only used to regenerate the bundled PNGs. It is not needed to run the
tracker and lives in the optional `assets` group.

## Development checks

The GUI entry point and the rest of the application source live in `src/`.
Ruff checks and formats the Python files, while Pyright type-checks the runtime
source:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run python -m unittest discover -s tests -v
```

Install the repository's pre-commit hooks once per checkout:

```bash
uv run pre-commit install
```

Every commit then runs Ruff's safe fixes before the formatter and finishes with
Pyright. To run the same hooks over the whole checkout manually:

```bash
uv run pre-commit run --all-files
```

Ruff can rewrite files during the hook, so review and stage those changes before
committing again.

## Building the desktop application

The PyInstaller specification builds a single windowed executable and bundles
the map, sprites and application icon:

```bash
uv run pyinstaller --clean --noconfirm RoamerTracker.spec
```

The artifact is written to `dist/RoamerTracker` (with the platform's
usual executable suffix). PyInstaller builds are platform-specific, so create
each release artifact on the operating system it targets.

Tagged releases build and publish native archives for Linux, Windows and macOS
through GitHub Actions. Each archive includes the README, license and
third-party notices; `SHA256SUMS.txt` on the release page verifies the downloads.
Release history and upgrade notes live in [CHANGELOG.md](CHANGELOG.md).

## Publishing a release

1. Move the completed entries from `Unreleased` into a dated version section in
   `CHANGELOG.md`.
2. Update the project version in `pyproject.toml` and refresh `uv.lock`.
3. Commit and push the release changes.
4. Create and push the matching `vX.Y.Z` tag.
5. Confirm the `Release native applications` workflow publishes all three
   archives and `SHA256SUMS.txt`.

Use [.github/RELEASE_TEMPLATE.md](.github/RELEASE_TEMPLATE.md) when drafting
release notes manually. GitHub's generated-note categories are configured in
`.github/release.yml`.

## Game assets

`assets/kanto_map.png` and the Raikou, Entei and Suicune sprites are generated
from the [pret/pokefirered](https://github.com/pret/pokefirered) decompilation.
`assets/hoenn_map.png` and the Latias and Latios sprites come from
[pret/pokeemerald](https://github.com/pret/pokeemerald). Both maps are rebuilt
from their original tiles and tilemaps; marker positions use each game's
region-map section data and cursor formula. The generic application icon is
also generated locally, but it does not use game graphics.

To regenerate them from a local checkout:

```bash
uv sync --group assets
uv run --group assets python tools/build_assets.py \
  /path/to/pokefirered /path/to/pokeemerald
```

The assets belong to their original owners and are included for this personal,
non-commercial project.

The supported ROMs are FireRed USA/Europe Rev 1 (`BPRE`, revision 1), LeafGreen
USA/Europe Rev 1 (`BPGE`, revision 1), and Emerald USA/Europe (`BPEE`, revision
0), all with the mGBA core. The tracker checks the ROM header before selecting
the matching RAM layout. The location is read from the game's live state; the
species and its active flag are read from whichever save block is loaded at
that moment, and the trainer's name comes from the personal save block. The
roamer's stored record is read whole in one request, so its PID, IVs, level, HP
and status all come from the same game frame; the maximum HP is rebuilt from
that level and HP IV, since the games never store it. The forecast also reads
the live history of the last three locations used by the game itself. Other revisions and localized ROMs are
rejected instead of being read with unsafe addresses.

## License

The tracker code is released under the [MIT license](LICENSE). The graphical
assets generated from the games are not covered by that license; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
