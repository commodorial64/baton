# BATON Minesweeper

A 10x10 Minesweeper game written in Baton and rendered with SHARPE/SDL2.

## Controls

- Left click: reveal a tile
- Right click: place/remove a flag
- `R`: restart
- `Escape`: quit

The board contains 15 mines. The first tile clicked is guaranteed safe. Empty tiles reveal their neighboring area automatically.

## Build

From the root of the BATON checkout, with SDL2 development headers and libraries installed:

```sh
baton build examples/minesweeper.bt -o minesweeper
./minesweeper
```

The example imports SHARPE from the sibling `sharpe/` directory.
