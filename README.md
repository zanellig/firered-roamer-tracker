# Floating roamer tracker

An always-on-top desktop window that reads Pokémon FireRed RAM through
RetroArch and marks on the Kanto map where the roaming Pokémon and the player
are. It is read-only: it never modifies RAM or the save file.

The species is detected automatically for each save. FireRed picks the roamer
based on the starter: Bulbasaur maps to Entei, Squirtle to Raikou and
Charmander to Suicune. If the save has already created the roamer, the tracker
uses the stored species directly; that is why it also works with swapped or
edited saves.

## Running

1. In RetroArch, enable **Settings > Network > Network Commands**.
2. Open FireRed with the mGBA core.
3. Create the local virtual environment and start the application:

   ```bash
   cd roamer_watcher
   uv sync
   uv run python roamer_tracker.py
   ```

The window can be dragged from the top bar and stays above the others by
default. The pin button in the title bar turns that behavior off. If the game is not open
yet or the connection drops, the tracker keeps retrying instead of exiting.
`Ctrl+C` from the terminal closes the window and the RAM reader without
printing a traceback. The **×** button also closes the application completely
and stops the reader.

## Movement forecast

When the player and the roamer are in different zones, the map highlights in
gold the likely routes after the next normal transition and shows the
percentage for each one. The calculation replicates FireRed's movement table,
including the 1-in-16 random jump and the route the game excludes based on the
player's recent history.

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
uv run python roamer_tracker.py --host 127.0.0.1 --port 55355 --interval 0.20
```

To keep using the terminal view:

```bash
uv run python roamer_ram_watch.py
```

## Dependencies

The application uses Python 3 and PySide 6. `uv sync` creates `.venv` inside
this folder and installs PySide there; it does not install packages into the
global Python. Activating the environment is not necessary because `uv run`
selects it automatically.

```bash
uv sync
```

Pillow is only used to regenerate the bundled PNGs. It is not needed to run the
tracker and lives in the optional `assets` group.

## FireRed assets

`assets/kanto_map.png` and the Raikou, Entei and Suicune sprites are generated
from the [pret/pokefirered](https://github.com/pret/pokefirered) decompilation.
The map is rebuilt with the original tileset and `kanto.bin`; the route
positions use the coordinates from `region_map_sections.json` and the same
cursor formula as `src/region_map.c`. The generic application icon is also
generated locally, but it does not use game graphics.

To regenerate them from a local checkout:

```bash
uv sync --group assets
uv run --group assets python tools/build_assets.py /path/to/pokefirered
```

The assets belong to their original owners and are included for this personal,
non-commercial project.

The RAM addresses keep the scope of the original script: FireRed USA/Europe Rev
1 (BPRE) with the mGBA core. The location is read from the game's live state;
the species and its active flag are read from whichever save block is loaded at
that moment. The forecast also reads the live history of the last three
locations used by the game itself.

## Testing

```bash
uv run python -m unittest discover -s tests -v
```

## License

The tracker code is released under the [MIT license](LICENSE). The graphical
assets generated from FireRed are not covered by that license; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
