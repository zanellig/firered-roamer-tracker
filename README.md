# Rastreador flotante de roamers

Una ventana de escritorio siempre visible que lee la RAM de Pokémon FireRed a
través de RetroArch y marca en el mapa de Kanto dónde están el Pokémon errante
y el jugador. Es de solo lectura: no modifica la RAM ni la partida.

La especie se detecta automáticamente en cada save. FireRed elige el roamer
según el starter: Bulbasaur corresponde a Entei, Squirtle a Raikou y Charmander
a Suicune. Si la partida ya creó al roamer, el rastreador usa directamente la
especie guardada; por eso también funciona con saves intercambiados o editados.

## Ejecutar

1. En RetroArch, activá **Settings > Network > Network Commands**.
2. Abrí FireRed con el core mGBA.
3. Creá el entorno virtual local e iniciá la aplicación:

   ```bash
   cd roamer_watcher
   uv sync
   uv run python roamer_tracker.py
   ```

La ventana se puede arrastrar desde la barra superior y queda sobre las demás
por defecto. El botón **FIJO** permite desactivar ese comportamiento. Si el
juego todavía no está abierto o se corta la conexión, el rastreador sigue
intentando conectarse sin cerrarse. `Ctrl+C` desde la terminal cierra la
ventana y el lector de RAM sin mostrar un traceback. El botón **×** también
cierra por completo la aplicación y detiene el lector.

## Pronóstico de movimiento

Cuando el jugador y el roamer están en zonas distintas, el mapa marca en dorado
las rutas probables después de la próxima transición normal y muestra el
porcentaje de cada una. El cálculo replica la tabla de movimiento de FireRed,
incluido el salto aleatorio de 1 entre 16 y la ruta que el juego excluye según
el historial reciente del jugador.

Si una ruta probable tiene una entrada rápida desde la ciudad actual, la
ventana recomienda cruzarla. En los demás casos conserva las probabilidades en
el mapa sin recomendar Fly: volar cambia la ubicación del roamer al azar e
invalida el pronóstico anterior.

Por ejemplo, al entrar a Viridian desde Ruta 1 con el roamer en Ruta 22, el
movimiento normal excluye Ruta 1 y reparte sus opciones entre Ruta 2 y Ruta 23.
Cada una queda en **47,1%** al incluir la posibilidad de 1 entre 16 de que el
roamer salte a otra parte del mapa. La aplicación recomienda cruzar a Ruta 2,
la salida inmediata desde Viridian.

Las rutas pronosticadas usan contorno dorado y la intercepción recomendada se
resalta con mayor intensidad. Cuando ambos comparten zona se conserva
únicamente el aviso de coincidencia, sin una instrucción redundante.

La dirección predeterminada es `127.0.0.1:55355`. Se puede cambiar junto con la
frecuencia de lectura:

```bash
uv run python roamer_tracker.py --host 127.0.0.1 --port 55355 --interval 0.20
```

Para seguir usando la vista de terminal:

```bash
uv run python roamer_ram_watch.py
```

## Dependencias

La aplicación usa Python 3 y PySide 6. `uv sync` crea `.venv` dentro de esta
carpeta e instala PySide ahí; no instala paquetes en el Python global. No hace
falta activar el entorno porque `uv run` lo selecciona automáticamente.

```bash
uv sync
```

Pillow solo se usa para regenerar los PNG incluidos. No hace falta para
ejecutar el rastreador y vive en el grupo opcional `assets`.

## Recursos de FireRed

`assets/kanto_map.png` y los sprites de Raikou, Entei y Suicune se generan desde
el decompilado de [pret/pokefirered](https://github.com/pret/pokefirered). El
mapa se reconstruye con el tileset original y `kanto.bin`; las posiciones de
las rutas usan las coordenadas de `region_map_sections.json` y la misma fórmula
de cursor de `src/region_map.c`. El ícono genérico de la aplicación también se
genera localmente, pero no usa gráficos del juego.

Para regenerarlos desde un checkout local:

```bash
uv sync --group assets
uv run --group assets python tools/build_assets.py /ruta/a/pokefirered
```

Los recursos pertenecen a sus titulares originales y se incluyen para este
proyecto personal y no comercial.

Las direcciones de RAM conservan el alcance del script original: FireRed
USA/Europe Rev 1 (BPRE) con el core mGBA. La ubicación se lee del estado vivo
del juego; la especie y su estado activo se leen del bloque de guardado que esté
cargado en ese momento. El pronóstico también lee el historial vivo de las tres
últimas ubicaciones usado por el propio juego.

## Probar

```bash
uv run python -m unittest discover -s tests -v
```

## Licencia

El código del rastreador se publica bajo la [licencia MIT](LICENSE). Los
recursos gráficos generados desde FireRed no están cubiertos por esa licencia;
consultá [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
