"""Authoritative GBA RAM-reading and roamer model for tracker frontends."""

from __future__ import annotations

import socket
import string
from dataclasses import dataclass
from typing import Callable, Protocol

ROM_HEADER_ADDR = 0x080000AC
ROM_HEADER_LENGTH = 17
FIRERED_LEAFGREEN_ROAMER_ADDR = 0x0203F3AE
FIRERED_LEAFGREEN_SAVE_BLOCK1_PTR_ADDR = 0x03005008
PLAYER_LOCATION_OFFSET = 0x0004
FIRERED_LEAFGREEN_STARTER_VAR_OFFSET = 0x1062
FIRERED_LEAFGREEN_ROAMER_SPECIES_OFFSET = 0x30D8
FIRERED_LEAFGREEN_ROAMER_ACTIVE_OFFSET = 0x30E3
EMERALD_SAVE_BLOCK1_PTR_ADDR = 0x03005D8C
EMERALD_ROAMER_ADDR = 0x0203BC86
EMERALD_ROAMER_SPECIES_OFFSET = 0x31E4
EMERALD_ROAMER_ACTIVE_OFFSET = 0x31EF
EWRAM_START = 0x02000000
EWRAM_END = 0x02040000


class TrackerError(RuntimeError):
    """A sanitized tracker or protocol failure safe to show to a caller."""


@dataclass(frozen=True)
class MapBounds:
    """One rectangular section in a game's region-map grid."""

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
class RegionMap:
    """Rendering metadata shared by every frontend for one game region."""

    name: str
    asset_name: str
    source_rect: tuple[int, int, int, int]
    grid_origin: tuple[int, int]


@dataclass(frozen=True)
class Game:
    id: str
    name: str
    region_map: RegionMap
    # Map group holding the towns and routes the roamer walks.
    map_group: int


KANTO = RegionMap(
    name="Kanto",
    asset_name="kanto_map.png",
    source_rect=(16, 16, 208, 144),
    grid_origin=(32, 32),
)
HOENN = RegionMap(
    name="Hoenn",
    asset_name="hoenn_map.png",
    source_rect=(0, 0, 240, 160),
    grid_origin=(8, 16),
)
FIRERED = Game("firered", "Pokémon FireRed", KANTO, map_group=3)
LEAFGREEN = Game("leafgreen", "Pokémon LeafGreen", KANTO, map_group=3)
EMERALD = Game("emerald", "Pokémon Emerald", HOENN, map_group=0)


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
LATIAS = RoamerSpecies(407, "Latias")
LATIOS = RoamerSpecies(408, "Latios")

# FireRed and LeafGreen store VAR_STARTER_MON as an index, not a species ID.
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
    game: Game
    roamer: Roamer
    player: Location
    same_area: bool
    forecast: MovementForecast | None = None


# Map group 3 indices used by FireRed and LeafGreen. The first 19 entries are
# towns and islands, then map 19 starts Route 1.
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


# Map group 0 indices from pokeemerald's gMapGroup_TownsAndRoutes.
HOENN_AREA_NAMES = {
    0: "Petalburg City",
    1: "Slateport City",
    2: "Mauville City",
    3: "Rustboro City",
    4: "Fortree City",
    5: "Lilycove City",
    6: "Mossdeep City",
    7: "Sootopolis City",
    8: "Ever Grande City",
    9: "Littleroot Town",
    10: "Oldale Town",
    11: "Dewford Town",
    12: "Lavaridge Town",
    13: "Fallarbor Town",
    14: "Verdanturf Town",
    15: "Pacifidlog Town",
    **{route - 85: f"Ruta {route}" for route in range(101, 135)},
}

# Exact section rectangles from pret/pokeemerald's
# src/data/region_map/region_map_sections.json.
HOENN_MAP_BOUNDS = {
    0: MapBounds(1, 9),
    1: MapBounds(8, 10, 1, 2),
    2: MapBounds(8, 6, 2, 1),
    3: MapBounds(0, 5, 1, 2),
    4: MapBounds(12, 0),
    5: MapBounds(18, 3, 2, 1),
    6: MapBounds(24, 5, 2, 1),
    7: MapBounds(21, 7),
    8: MapBounds(27, 8, 1, 2),
    9: MapBounds(4, 11),
    10: MapBounds(4, 9),
    11: MapBounds(2, 14),
    12: MapBounds(5, 3),
    13: MapBounds(3, 0),
    14: MapBounds(4, 6),
    15: MapBounds(17, 10),
    16: MapBounds(4, 10),
    17: MapBounds(2, 9, 2, 1),
    18: MapBounds(4, 8, 4, 1),
    19: MapBounds(0, 7, 1, 3),
    20: MapBounds(0, 10, 1, 3),
    21: MapBounds(0, 13, 2, 1),
    22: MapBounds(3, 14, 3, 1),
    23: MapBounds(6, 14, 2, 1),
    24: MapBounds(8, 12, 1, 3),
    25: MapBounds(8, 7, 1, 3),
    26: MapBounds(8, 0, 1, 6),
    27: MapBounds(6, 3, 2, 1),
    28: MapBounds(4, 0, 4, 1),
    29: MapBounds(1, 0, 2, 3),
    30: MapBounds(0, 2, 1, 3),
    31: MapBounds(1, 5, 4, 1),
    32: MapBounds(5, 6, 3, 1),
    33: MapBounds(10, 6, 2, 1),
    34: MapBounds(11, 0, 1, 6),
    35: MapBounds(13, 0, 1, 4),
    36: MapBounds(14, 3, 4, 1),
    37: MapBounds(16, 4, 1, 2),
    38: MapBounds(12, 6, 5, 1),
    39: MapBounds(20, 3, 4, 3),
    40: MapBounds(24, 3, 2, 2),
    41: MapBounds(20, 6, 3, 3),
    42: MapBounds(23, 6, 3, 3),
    43: MapBounds(23, 9, 4, 1),
    44: MapBounds(24, 10, 2, 1),
    45: MapBounds(21, 10, 3, 1),
    46: MapBounds(18, 10, 3, 1),
    47: MapBounds(15, 10, 2, 1),
    48: MapBounds(12, 10, 3, 1),
    49: MapBounds(9, 10, 3, 1),
}


# Exact neighbor rows from FireRed and LeafGreen's sRoamerLocations table.
# Route 21 uses its north map (39); the south map (40) is never selected.
KANTO_ROAMER_ROUTE_GRAPH = {
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
RANDOM_RELOCATION_CHANCE = 1 / 16

# Routes with an immediate open-border crossing from each hunting city.
_KANTO_HUNTING_ROUTES_BY_CITY = {
    0: (19,),  # Pallet Town -> Route 1
    1: (19, 20),  # Viridian City -> Route 1 / Route 2
    3: (23,),  # Cerulean City -> Route 5
    4: (26,),  # Lavender Town -> Route 8
    5: (24,),  # Vermilion City -> Route 6
}

# Exact neighbor rows from Emerald's sRoamerLocations table. Map group 0 uses
# map numbers 25 through 49 for Routes 110 through 134.
EMERALD_ROAMER_ROUTE_GRAPH = {
    25: (26, 32, 33, 49),
    26: (25, 32, 33),
    32: (26, 25, 33),
    33: (32, 25, 26, 34, 38),
    34: (33, 35),
    35: (34, 36),
    36: (35, 37, 38),
    37: (36, 38),
    38: (37, 33),
    39: (36, 40, 41),
    40: (39, 42),
    41: (39, 42),
    42: (40, 41, 43),
    43: (42, 44),
    44: (43, 45),
    45: (44, 46),
    46: (45, 47),
    47: (46, 48),
    48: (47, 49),
    49: (48, 25),
}

_EMERALD_HUNTING_ROUTES_BY_CITY = {
    1: (25, 49),  # Slateport City -> Routes 110 / 134
    2: (25, 26, 32, 33),  # Mauville City -> Routes 110 / 111 / 117 / 118
    4: (34, 35),  # Fortree City -> Routes 119 / 120
    5: (36, 39),  # Lilycove City -> Routes 121 / 124
    6: (39, 40, 42),  # Mossdeep City -> Routes 124 / 125 / 127
    15: (46, 47),  # Pacifidlog Town -> Routes 131 / 132
}


# Per-region lookups keyed by the region map each game renders.
_REGION_AREAS = {
    KANTO: (AREA_NAMES, KANTO_MAP_BOUNDS),
    HOENN: (HOENN_AREA_NAMES, HOENN_MAP_BOUNDS),
}

# Roamer movement rules keyed by game: the sRoamerLocations neighbor table and
# the routes reachable straight out of each hunting city.
_ROUTE_RULES = {
    FIRERED: (KANTO_ROAMER_ROUTE_GRAPH, _KANTO_HUNTING_ROUTES_BY_CITY),
    LEAFGREEN: (KANTO_ROAMER_ROUTE_GRAPH, _KANTO_HUNTING_ROUTES_BY_CITY),
    EMERALD: (EMERALD_ROAMER_ROUTE_GRAPH, _EMERALD_HUNTING_ROUTES_BY_CITY),
}


def location_for(group: int, number: int, game: Game = FIRERED) -> Location:
    """Normalize a RAM map pair into one display-ready domain location."""
    fallback = f"Grupo {group} / mapa {number}"
    if group != game.map_group:
        return Location(group, number, fallback, None)
    area_names, map_bounds = _REGION_AREAS[game.region_map]
    return Location(
        group,
        number,
        area_names.get(number, fallback),
        map_bounds.get(number),
    )


def forecast_movement(
    roamer_location: Location,
    player_location: Location,
    next_history_exclusion: Location,
    game: Game = FIRERED,
) -> MovementForecast | None:
    """Calculate the next-transition distribution and any direct interception."""
    route_graph, hunting_routes_by_city = _ROUTE_RULES[game]
    map_group = game.map_group
    if roamer_location.group != map_group or roamer_location.number not in route_graph:
        return None

    excluded_map = (
        next_history_exclusion.number
        if next_history_exclusion.group == map_group
        else None
    )
    neighbors = tuple(
        map_number
        for map_number in route_graph[roamer_location.number]
        if map_number != excluded_map
    )
    random_route_probability = RANDOM_RELOCATION_CHANCE / (len(route_graph) - 1)
    normal_probability = (1 - RANDOM_RELOCATION_CHANCE) / len(neighbors)
    likely_routes = tuple(
        RouteChance(
            location=location_for(map_group, map_number, game),
            probability=normal_probability + random_route_probability,
        )
        for map_number in neighbors
    )

    chance_by_route = {chance.location.number: chance for chance in likely_routes}
    hunting_routes = (
        hunting_routes_by_city.get(player_location.number, ())
        if player_location.group == map_group
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
        random_route_probability=random_route_probability,
        recommendation=(
            HuntRecommendation(
                route=best_chance.location,
                probability=best_chance.probability,
            )
            if best_chance is not None
            else None
        ),
    )


@dataclass(frozen=True)
class _MemoryProfile:
    game: Game
    game_code: bytes
    revision: int
    save_block1_ptr_addr: int
    roamer_addr: int
    roamer_species_offset: int
    roamer_active_offset: int
    species: tuple[RoamerSpecies, ...]
    starter_var_offset: int | None = None


_FIRERED_PROFILE = _MemoryProfile(
    game=FIRERED,
    game_code=b"BPRE",
    revision=1,
    save_block1_ptr_addr=FIRERED_LEAFGREEN_SAVE_BLOCK1_PTR_ADDR,
    roamer_addr=FIRERED_LEAFGREEN_ROAMER_ADDR,
    roamer_species_offset=FIRERED_LEAFGREEN_ROAMER_SPECIES_OFFSET,
    roamer_active_offset=FIRERED_LEAFGREEN_ROAMER_ACTIVE_OFFSET,
    species=(RAIKOU, ENTEI, SUICUNE),
    starter_var_offset=FIRERED_LEAFGREEN_STARTER_VAR_OFFSET,
)
_LEAFGREEN_PROFILE = _MemoryProfile(
    game=LEAFGREEN,
    game_code=b"BPGE",
    revision=1,
    save_block1_ptr_addr=FIRERED_LEAFGREEN_SAVE_BLOCK1_PTR_ADDR,
    roamer_addr=FIRERED_LEAFGREEN_ROAMER_ADDR,
    roamer_species_offset=FIRERED_LEAFGREEN_ROAMER_SPECIES_OFFSET,
    roamer_active_offset=FIRERED_LEAFGREEN_ROAMER_ACTIVE_OFFSET,
    species=(RAIKOU, ENTEI, SUICUNE),
    starter_var_offset=FIRERED_LEAFGREEN_STARTER_VAR_OFFSET,
)
_EMERALD_PROFILE = _MemoryProfile(
    game=EMERALD,
    game_code=b"BPEE",
    revision=0,
    save_block1_ptr_addr=EMERALD_SAVE_BLOCK1_PTR_ADDR,
    roamer_addr=EMERALD_ROAMER_ADDR,
    roamer_species_offset=EMERALD_ROAMER_SPECIES_OFFSET,
    roamer_active_offset=EMERALD_ROAMER_ACTIVE_OFFSET,
    species=(LATIAS, LATIOS),
)
_MEMORY_PROFILES = {
    (profile.game_code, profile.revision): profile
    for profile in (_FIRERED_PROFILE, _LEAFGREEN_PROFILE, _EMERALD_PROFILE)
}


def u32le(data: bytes) -> int:
    if len(data) != 4:
        raise ValueError("Se necesitan exactamente 4 bytes")
    return int.from_bytes(data, "little")


class MemoryReader(Protocol):
    def read_memory(self, address: int, length: int) -> bytes: ...


SocketFactory = Callable[..., socket.socket]


def _read_memory_profile(reader: MemoryReader) -> _MemoryProfile:
    header = reader.read_memory(ROM_HEADER_ADDR, ROM_HEADER_LENGTH)
    if len(header) != ROM_HEADER_LENGTH:
        raise TrackerError("No se pudo identificar el juego abierto")
    profile = _MEMORY_PROFILES.get((header[:4], header[-1]))
    if profile is None:
        raise TrackerError("El juego abierto no es una versión compatible")
    return profile


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
    profile = _read_memory_profile(reader)
    save_block1_ptr = u32le(reader.read_memory(profile.save_block1_ptr_addr, 4))
    if not (
        EWRAM_START <= save_block1_ptr <= EWRAM_END - profile.roamer_active_offset - 1
    ):
        raise TrackerError("El bloque de guardado activo no está disponible")

    player = reader.read_memory(save_block1_ptr + PLAYER_LOCATION_OFFSET, 2)
    roamer_state = reader.read_memory(
        save_block1_ptr + profile.roamer_species_offset,
        profile.roamer_active_offset - profile.roamer_species_offset + 1,
    )
    species_id = int.from_bytes(roamer_state[:2], "little")
    species_by_id = {species.id: species for species in profile.species}
    species = species_by_id.get(species_id)
    if species is None and profile.starter_var_offset is not None:
        starter_id = int.from_bytes(
            reader.read_memory(save_block1_ptr + profile.starter_var_offset, 2),
            "little",
        )
        species = ROAMER_BY_STARTER.get(starter_id)
    if species is None:
        raise TrackerError("No se pudo identificar el roamer de esta partida")

    active_value = roamer_state[
        profile.roamer_active_offset - profile.roamer_species_offset
    ]
    if active_value not in (0, 1):
        raise TrackerError("El estado del roamer no es válido")

    # Every supported game keeps three player-map history pairs immediately
    # before the live roamer pair. Before the next move, the game shifts pair 1
    # into pair 2 and excludes it, so the current middle pair is next.
    runtime_state = reader.read_memory(profile.roamer_addr - 6, 8)
    next_history_exclusion = location_for(
        runtime_state[2], runtime_state[3], profile.game
    )
    roamer_map = runtime_state[6:8]
    roamer_location = location_for(roamer_map[0], roamer_map[1], profile.game)
    current = location_for(player[0], player[1], profile.game)
    roamer = Roamer(
        species=species,
        location=roamer_location,
        active=bool(active_value),
    )
    same_area = (
        roamer.active
        and roamer.location.group == current.group == profile.game.map_group
        and roamer.location.number == current.number
    )
    forecast = (
        forecast_movement(
            roamer.location,
            current,
            next_history_exclusion,
            profile.game,
        )
        if roamer.active
        else None
    )
    return TrackerSnapshot(
        game=profile.game,
        roamer=roamer,
        player=current,
        same_area=same_area,
        forecast=forecast,
    )
