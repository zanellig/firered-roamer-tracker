"""Terminal view of the shared FireRed live roamer tracker."""

from __future__ import annotations

import argparse
import sys
import time

if __package__:
    from .tracker import RetroArchNCI, TrackerError, read_snapshot
else:
    from tracker import RetroArchNCI, TrackerError, read_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Muestra la ubicación del roamer leyendo la RAM de RetroArch."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=55355)
    parser.add_argument("--interval", type=float, default=0.20)
    args = parser.parse_args()

    print("Leyendo RAM de RetroArch. Ctrl+C para salir.")
    try:
        with RetroArchNCI(args.host, args.port) as nci:
            while True:
                snapshot = read_snapshot(nci)
                alert = (
                    "  <<< MISMA ZONA: CAMINÁ EN EL PASTO >>>"
                    if snapshot.same_area
                    else ""
                )
                roamer_location = (
                    snapshot.roamer.location.name
                    if snapshot.roamer.active
                    else "INACTIVO"
                )
                line = (
                    f"{snapshot.roamer.species.name}: "
                    f"{roamer_location:<18} | "
                    f"Vos: {snapshot.player.name:<18}{alert}"
                )
                print("\r" + line.ljust(100), end="", flush=True)
                time.sleep(max(args.interval, 0.05))
    except KeyboardInterrupt:
        print()
        return 0
    except (OSError, TrackerError, ValueError) as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        print(
            "Revisá que RetroArch esté abierto, el juego corriendo y "
            "Settings > Network > Network Commands activado.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
