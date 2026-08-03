# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/zanellig/firered-roamer-tracker/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/zanellig/firered-roamer-tracker/releases/tag/v0.4.0
