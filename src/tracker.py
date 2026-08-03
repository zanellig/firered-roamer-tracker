"""Authoritative FireRed RAM-reading and roamer model for tracker frontends."""

from __future__ import annotations

import socket
import string
from dataclasses import dataclass
from typing import Callable, Protocol

ROAMER_ADDR = 0x0203F3AE
LOCATION_HISTORY_ADDR = ROAMER_ADDR - 6
SAVE_BLOCK1_PTR_ADDR = 0x03005008
PLAYER_LOCATION_OFFSET = 0x0004
STARTER_VAR_OFFSET = 0x1062
ROAMER_SPECIES_OFFSET = 0x30D8
ROAMER_ACTIVE_OFFSET = 0x30E3
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
class RoamerSpecies:
    id: int
    name: str


RAIKOU = RoamerSpecies(243, "Raikou")
ENTEI = RoamerSpecies(244, "Entei")
SUICUNE = RoamerSpecies(245, "Suicune")

ROAMER_SPECIES = {species.id: species for species in (RAIKOU, ENTEI, SUICUNE)}

# FireRed stores VAR_STARTER_MON as an index, not a species ID.
ROAMER_BY_STARTER = {
    0: ENTEI,  # Bulbasaur
    1: RAIKOU,  # Squirtle
    2: SUICUNE,  # Charmander
}


@dataclass(frozen=True)
class Roamer:
    species: RoamerSpecies
    location: Location
    active: bool


@dataclass(frozen=True)
class RouteChance:
    location: Location
    probability: float


@dataclass(frozen=True)
class HuntRecommendation:
    route: Location
    probability: float


@dataclass(frozen=True)
class MovementForecast:
    likely_routes: tuple[RouteChance, ...]
    random_route_probability: float
    recommendation: HuntRecommendation | None


@dataclass(frozen=True)
class TrackerSnapshot:
    roamer: Roamer
    player: Location
    same_area: bool
    forecast: MovementForecast | None = None


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
    **{18 + route: f"Ruta {route}" for route in range(1, 22)},
    40: "Ruta 21",
    **{19 + route: f"Ruta {route}" for route in range(22, 26)},
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


# Exact neighbor rows from FireRed's sRoamerLocations table. Route 21 uses its
# north map (39); the south map (40) is never selected for the roamer.
ROAMER_ROUTE_GRAPH = {
    19: (20, 39, 41),
    20: (19, 21, 41),
    21: (20, 22),
    22: (21, 23, 27, 43),
    23: (22, 24, 25, 26, 27, 43),
    24: (23, 25, 26, 29),
    25: (23, 24, 26, 34),
    26: (23, 24, 25, 28, 30),
    27: (22, 23, 28, 43),
    28: (26, 27, 30),
    29: (24, 30),
    30: (28, 29, 31),
    31: (30, 32),
    32: (31, 33),
    33: (32, 36, 37),
    34: (25, 35),
    35: (34, 36),
    36: (33, 35, 37),
    37: (33, 36, 38),
    38: (37, 39),
    39: (19, 38),
    41: (19, 20, 42),
    42: (41, 20),
    43: (22, 23, 27),
    44: (43, 27),
}
ROAMER_ROUTE_MAPS = tuple(ROAMER_ROUTE_GRAPH)
RANDOM_RELOCATION_CHANCE = 1 / 16
RANDOM_ROUTE_PROBABILITY = RANDOM_RELOCATION_CHANCE / (len(ROAMER_ROUTE_MAPS) - 1)

# Routes with an immediate open-border crossing from each hunting city.
_HUNTING_ROUTES_BY_CITY = {
    0: (19,),  # Pallet Town -> Route 1
    1: (19, 20),  # Viridian City -> Route 1 / Route 2
    3: (23,),  # Cerulean City -> Route 5
    4: (26,),  # Lavender Town -> Route 8
    5: (24,),  # Vermilion City -> Route 6
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


def forecast_movement(
    roamer_location: Location,
    player_location: Location,
    next_history_exclusion: Location,
) -> MovementForecast | None:
    """Calculate the next-transition distribution and any direct interception."""
    if roamer_location.group != 3 or roamer_location.number not in ROAMER_ROUTE_GRAPH:
        return None

    excluded_map = (
        next_history_exclusion.number if next_history_exclusion.group == 3 else None
    )
    neighbors = tuple(
        map_number
        for map_number in ROAMER_ROUTE_GRAPH[roamer_location.number]
        if map_number != excluded_map
    )
    normal_probability = (1 - RANDOM_RELOCATION_CHANCE) / len(neighbors)
    likely_routes = tuple(
        RouteChance(
            location=location_for(3, map_number),
            probability=normal_probability + RANDOM_ROUTE_PROBABILITY,
        )
        for map_number in neighbors
    )

    chance_by_route = {chance.location.number: chance for chance in likely_routes}
    hunting_routes = (
        _HUNTING_ROUTES_BY_CITY.get(player_location.number, ())
        if player_location.group == 3
        else ()
    )
    actionable = tuple(
        chance_by_route[route] for route in hunting_routes if route in chance_by_route
    )
    best_chance = (
        max(actionable, key=lambda chance: chance.probability) if actionable else None
    )

    return MovementForecast(
        likely_routes=likely_routes,
        random_route_probability=RANDOM_ROUTE_PROBABILITY,
        recommendation=(
            HuntRecommendation(
                route=best_chance.location,
                probability=best_chance.probability,
            )
            if best_chance is not None
            else None
        ),
    )


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
    save_block1_ptr = u32le(reader.read_memory(SAVE_BLOCK1_PTR_ADDR, 4))
    if not EWRAM_START <= save_block1_ptr <= EWRAM_END - ROAMER_ACTIVE_OFFSET - 1:
        raise TrackerError("El bloque de guardado activo no está disponible")

    player = reader.read_memory(save_block1_ptr + PLAYER_LOCATION_OFFSET, 2)
    roamer_state = reader.read_memory(
        save_block1_ptr + ROAMER_SPECIES_OFFSET,
        ROAMER_ACTIVE_OFFSET - ROAMER_SPECIES_OFFSET + 1,
    )
    species_id = int.from_bytes(roamer_state[:2], "little")
    species = ROAMER_SPECIES.get(species_id)
    if species is None:
        starter_id = int.from_bytes(
            reader.read_memory(save_block1_ptr + STARTER_VAR_OFFSET, 2),
            "little",
        )
        species = ROAMER_BY_STARTER.get(starter_id)
    if species is None:
        raise TrackerError("No se pudo identificar el roamer de esta partida")

    active_value = roamer_state[ROAMER_ACTIVE_OFFSET - ROAMER_SPECIES_OFFSET]
    if active_value not in (0, 1):
        raise TrackerError("El estado del roamer no es válido")

    # FireRed keeps three player-map history pairs immediately before the live
    # roamer pair. Before the next move, the game shifts pair 1 into pair 2 and
    # excludes it, so the current middle pair is the next exclusion.
    runtime_state = reader.read_memory(LOCATION_HISTORY_ADDR, 8)
    next_history_exclusion = location_for(runtime_state[2], runtime_state[3])
    roamer_map = runtime_state[6:8]
    roamer_location = location_for(roamer_map[0], roamer_map[1])
    current = location_for(player[0], player[1])
    roamer = Roamer(
        species=species,
        location=roamer_location,
        active=bool(active_value),
    )
    same_area = (
        roamer.active
        and roamer.location.group == current.group == 3
        and roamer.location.number == current.number
    )
    forecast = (
        forecast_movement(roamer.location, current, next_history_exclusion)
        if roamer.active
        else None
    )
    return TrackerSnapshot(
        roamer=roamer,
        player=current,
        same_area=same_area,
        forecast=forecast,
    )
