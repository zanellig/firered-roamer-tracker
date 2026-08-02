"""Authoritative FireRed RAM-reading and location model for tracker frontends."""

from __future__ import annotations

from dataclasses import dataclass
import socket
import string
from typing import Callable, Protocol


ROAMER_ADDR = 0x0203F3AE
SAVE_BLOCK1_PTR_ADDR = 0x03005008
EWRAM_START = 0x02000000
EWRAM_END = 0x02040000


class TrackerError(RuntimeError):
    """A sanitized tracker or protocol failure safe to show to a caller."""


@dataclass(frozen=True)
class MapBounds:
    """One section in FireRed's 22 by 15 Kanto region-map grid."""

    x: int
    y: int
    width: int = 1
    height: int = 1

    @property
    def center(self) -> tuple[float, float]:
        return (
            self.x + (self.width - 1) / 2,
            self.y + (self.height - 1) / 2,
        )


@dataclass(frozen=True)
class Location:
    group: int
    number: int
    name: str
    map_bounds: MapBounds | None


@dataclass(frozen=True)
class TrackerSnapshot:
    suicune: Location
    player: Location
    same_area: bool


# Map group 3 indices used by FireRed. The first 19 entries are towns and
# islands, then map 19 starts Route 1.
AREA_NAMES = {
    0: "Pallet Town",
    1: "Viridian City",
    2: "Pewter City",
    3: "Cerulean City",
    4: "Lavender Town",
    5: "Vermilion City",
    6: "Celadon City",
    7: "Fuchsia City",
    8: "Cinnabar Island",
    9: "Indigo Plateau",
    10: "Saffron City",
    11: "Saffron Connection",
    12: "One Island",
    13: "Two Island",
    14: "Three Island",
    15: "Four Island",
    16: "Five Island",
    17: "Seven Island",
    18: "Six Island",
    **{18 + route: f"Ruta {route}" for route in range(1, 26)},
}


# Exact section rectangles from pret/pokefirered's
# src/data/region_map/region_map_sections.json. Areas outside Kanto have no
# marker on this map. Saffron Connection shares Saffron City's marker.
KANTO_MAP_BOUNDS = {
    0: MapBounds(4, 11),
    1: MapBounds(4, 8),
    2: MapBounds(4, 4),
    3: MapBounds(14, 3),
    4: MapBounds(18, 6),
    5: MapBounds(14, 9),
    6: MapBounds(11, 6),
    7: MapBounds(12, 12),
    8: MapBounds(4, 14),
    9: MapBounds(2, 3),
    10: MapBounds(14, 6),
    11: MapBounds(14, 6),
    19: MapBounds(4, 9, 1, 2),
    20: MapBounds(4, 5, 1, 3),
    21: MapBounds(5, 4, 4, 1),
    22: MapBounds(8, 3, 6, 1),
    23: MapBounds(14, 4, 1, 2),
    24: MapBounds(14, 7, 1, 2),
    25: MapBounds(12, 6, 2, 1),
    26: MapBounds(15, 6, 3, 1),
    27: MapBounds(15, 3, 3, 1),
    28: MapBounds(18, 3, 1, 3),
    29: MapBounds(15, 9, 3, 1),
    30: MapBounds(18, 7, 1, 5),
    31: MapBounds(16, 11, 2, 1),
    32: MapBounds(15, 11, 1, 2),
    33: MapBounds(13, 12, 2, 1),
    34: MapBounds(7, 6, 4, 1),
    35: MapBounds(7, 7, 1, 5),
    36: MapBounds(7, 12, 5, 1),
    37: MapBounds(12, 13, 1, 2),
    38: MapBounds(5, 14, 7, 1),
    39: MapBounds(4, 12, 1, 2),
    40: MapBounds(4, 12, 1, 2),
    41: MapBounds(2, 8, 2, 1),
    42: MapBounds(2, 4, 1, 4),
    43: MapBounds(14, 1, 1, 2),
    44: MapBounds(15, 1, 2, 1),
}


def location_for(group: int, number: int) -> Location:
    """Normalize a RAM map pair into one display-ready domain location."""
    if group == 3:
        return Location(
            group,
            number,
            AREA_NAMES.get(number, f"Grupo 3 / mapa {number}"),
            KANTO_MAP_BOUNDS.get(number),
        )
    return Location(group, number, f"Grupo {group} / mapa {number}", None)


def u32le(data: bytes) -> int:
    if len(data) != 4:
        raise ValueError("Se necesitan exactamente 4 bytes")
    return int.from_bytes(data, "little")


class MemoryReader(Protocol):
    def read_memory(self, address: int, length: int) -> bytes: ...


SocketFactory = Callable[..., socket.socket]


class RetroArchNCI:
    """Small validated client for RetroArch's UDP Network Commands interface."""

    def __init__(
        self,
        host: str,
        port: int,
        timeout: float = 0.75,
        socket_factory: SocketFactory = socket.socket,
    ) -> None:
        self.target = (host, port)
        self.sock = socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(timeout)

    def close(self) -> None:
        self.sock.close()

    def __enter__(self) -> RetroArchNCI:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def read_memory(self, address: int, length: int) -> bytes:
        if not 0 <= address <= 0xFFFFFFFF or not 1 <= length <= 65535:
            raise ValueError("Lectura de memoria fuera de rango")

        command = f"READ_CORE_MEMORY {address:08X} {length}".encode("ascii")
        self.sock.sendto(command, self.target)
        response, _source = self.sock.recvfrom(65535)
        try:
            parts = response.decode("ascii").strip().split()
        except UnicodeDecodeError as exc:
            raise TrackerError("La respuesta de memoria no es válida") from exc

        if len(parts) < 3 or parts[0] != "READ_CORE_MEMORY":
            raise TrackerError("La respuesta de memoria no es válida")
        returned_address = parts[1]
        if returned_address[:2].lower() == "0x":
            returned_address = returned_address[2:]
        valid_address = (
            1 <= len(returned_address) <= 8
            and all(character in string.hexdigits for character in returned_address)
            and int(returned_address, 16) == address
        )
        # RetroArch echoes addresses without leading zeroes, so compare their
        # numeric value while still strictly validating the untrusted token.
        if not valid_address or parts[2] == "-1":
            raise TrackerError("La lectura de memoria fue rechazada")

        values = parts[2:]
        if len(values) != length:
            raise TrackerError("La respuesta de memoria está incompleta")
        try:
            parsed = [int(value, 16) for value in values]
        except ValueError as exc:
            raise TrackerError("La respuesta de memoria no es válida") from exc
        if any(value < 0 or value > 0xFF for value in parsed):
            raise TrackerError("La respuesta de memoria no es válida")
        return bytes(parsed)


def read_snapshot(reader: MemoryReader) -> TrackerSnapshot:
    """Read one coherent-enough tracker update through the public memory seam."""
    roamer = reader.read_memory(ROAMER_ADDR, 2)
    save_block1_ptr = u32le(reader.read_memory(SAVE_BLOCK1_PTR_ADDR, 4))
    if not EWRAM_START <= save_block1_ptr <= EWRAM_END - 6:
        raise TrackerError("El bloque de guardado activo no está disponible")
    player = reader.read_memory(save_block1_ptr + 4, 2)

    suicune = location_for(roamer[0], roamer[1])
    current = location_for(player[0], player[1])
    return TrackerSnapshot(
        suicune=suicune,
        player=current,
        same_area=(
            suicune.group == current.group == 3
            and suicune.number == current.number
        ),
    )
