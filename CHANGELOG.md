# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- A settings menu behind a **⚙** button next to the pin, in both layouts. Its
  *Diseño de ventana* selector switches between `clasica` and `mapa` while the
  tracker is running, keeping the window's position and its live connection,
  and remembers the choice the same way `--ui` does.

## [0.5.1] - 2026-08-02

### Changed

- Renamed the application from `FireRedRoamerTracker` to `RoamerTracker`, now
  that FireRed is one of three supported games. The PyInstaller spec, the built
  executable, the macOS bundle identifier and the distributed archive names all
  follow the new name.
- Renamed the repository to `zanellig/roamer-tracker`.

### Upgrade notes

- Release archives are now published as `RoamerTracker-<platform>` instead of
  `FireRedRoamerTracker-<platform>`. Update any download scripts or shortcuts
  that referenced the old filenames.
- The macOS bundle identifier changed to `io.github.zanellig.roamer-tracker`,
  so macOS treats this as a separate application from earlier releases.
- GitHub redirects the previous repository URL, so existing clones and links
  keep working.

## [0.5.0] - 2026-08-02

### Added

- Added automatic LeafGreen Rev 1 and Emerald detection alongside FireRed Rev
  1, with exact per-game RAM layouts and safe rejection of unsupported ROMs.
- Added Latias and Latios tracking, the Hoenn region map, Emerald location
  names, movement forecasts, and direct route-interception recommendations.

### Changed

- Generalized both desktop layouts, the terminal reader, and asset generation
  so the displayed map, region, species, and movement rules follow the active
  game.
- Each supported game now carries its own map group, region lookups and
  movement rules, so region behaviour is resolved in one place instead of
  being re-derived per call site.

### Distribution notes

- The RAM addresses target FireRed and LeafGreen USA/Europe Rev 1 (BPRE, BPGE)
  and Emerald USA/Europe (BPEE) running in mGBA through RetroArch's Network
  Command Interface. Any other ROM is rejected before RAM is read.

## [0.4.0] - 2026-08-02

### Added

- Added automatic Entei, Raikou and Suicune detection from the active FireRed
  save, with starter-based detection before the roamer is created.
- Added a read-only live tracker with automatic RetroArch reconnection, a
  terminal view and a frameless always-on-top desktop window.
- Added movement forecasts that reproduce FireRed's route graph, random jump
  chance and location-history exclusion, including direct interception advice.
- Added the `clasica` panel layout and the compact `mapa` layout inspired by
  FireRed's town map, with persistent layout selection.
- Added native KWin keep-above integration with a portable Qt fallback.
- Added cached sprites, geometric status icons, animated town-map messages and
  map markers for the player, roamer and likely next routes.
- Added a `src/` application layout with `src/main.py` as the desktop entry
  point and retained the standalone terminal entry point.
- Added Ruff linting and formatting, Pyright type checking and pre-commit hooks.
- Added reproducible PyInstaller packaging and tagged GitHub release builds for
  Linux, Windows and macOS on native GitHub-hosted runners, including licenses
  and SHA-256 checksums.

### Changed

- Centered the map artwork within its frame and aligned status indicators,
  labels, controls and the compact layout's connection row.
- Reorganized application code under `src/`, development prototypes under
  `tools/`, and GUI tests around the new `main.py` entry point.
- Expanded the English documentation with setup, layouts, development checks,
  asset generation and native bundle instructions.
- Locked development and release dependencies with uv.

### Fixed

- Fixed close-button and `Ctrl+C` shutdown so the worker and application exit
  cleanly without a traceback.
- Fixed KWin pinning when the shortcut is unavailable, invocation fails or the
  desktop integration disappears during execution.
- Fixed invalid remembered layout values by falling back to `clasica`.
- Fixed map cropping and marker scaling so the visible Kanto artwork fills the
  frame without shifting overlays.
- Fixed icon and label vertical alignment across connection, legend and
  movement-status rows.
- Fixed production type errors around Qt application narrowing and the
  automatic pin-controller sentinel.
- Fixed Windows and macOS startup by loading the KDE D-Bus integration only on
  supported Linux systems.
- Fixed headless Linux release verification by provisioning the required EGL
  runtime library before the GUI tests.
- Hardened RAM and network response validation, active save-block bounds and
  unknown roamer state handling.

### Distribution notes

- Release archives contain unsigned native builds. Windows SmartScreen or
  macOS Gatekeeper may ask users to confirm before opening them.
- The RAM addresses target FireRed USA/Europe Rev 1 (BPRE) running in mGBA
  through RetroArch's Network Command Interface.

[Unreleased]: https://github.com/zanellig/roamer-tracker/compare/v0.5.1...HEAD
[0.5.1]: https://github.com/zanellig/roamer-tracker/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/zanellig/roamer-tracker/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/zanellig/roamer-tracker/releases/tag/v0.4.0
