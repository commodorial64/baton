# sharpe

Simple SDL2 bindings for Baton.

The API uses short, underscore-free names: `window`, `renderer`, `poll`,
`clear`, `present`, `fill`, `rect`, `color`, `wait`, and so on.

## Install

```
baton libinstall sharpe@0.2
```

This installs into `~/.local/lib/baton/sharpe/0.2/` and points
`~/.local/lib/baton/sharpe/latest` at the newest version. `BATON_LIB` overrides
the library root. Use `<sharpe>@0.2` to pin an exact version.

## Usage

```baton
mod sharpe get-from <sharpe>
mod s get-from <sharpe/constants.bt>

fn main() -> i {
    if sharpe.init() != 0 {
        return 1
    }

    *i local win = sharpe.window(cstr("hello"), 800, 600)
    if isnull(win) {
        return 1
    }

    *i local ren = sharpe.renderer(win)
    if isnull(ren) {
        return 1
    }

    i local running = 1
    i local ev = 0
    i local key = 0
    i local x = 0
    i local y = 0
    i local btn = 0

    while running == 1 {
        while sharpe.poll(&ev, &key, &x, &y, &btn) == 1 {
            if ev == s.QUIT {
                running = 0
            }
            if ev == s.KEYDOWN and key == s.KEY_ESCAPE {
                running = 0
            }
        }

        sharpe.color(ren, 20, 40, 60)
        sharpe.clear(ren)
        sharpe.color(ren, 255, 100, 50)
        sharpe.fill(ren, 100, 100, 200, 150)
        sharpe.present(ren)
        sharpe.wait(16)
    }

    sharpe.quit()
    return 0
}
```

A runnable version lives in `examples/sharpe_window.bt`.

## API

| Call | Purpose |
| --- | --- |
| `sharpe.init()` | Start SDL video and events |
| `sharpe.quit()` | Stop SDL and release its resources |
| `sharpe.window(title, width, height)` | Create a centered, visible window |
| `sharpe.renderer(window)` | Create a renderer for the window |
| `sharpe.poll(&type, &key, &x, &y, &button)` | Poll one event; returns `1` if one was read |
| `sharpe.color(renderer, r, g, b)` | Set the drawing color |
| `sharpe.clear(renderer)` | Clear to the current color |
| `sharpe.present(renderer)` | Show the rendered frame |
| `sharpe.point(renderer, x, y)` | Draw one point |
| `sharpe.line(renderer, x1, y1, x2, y2)` | Draw a line |
| `sharpe.rect(renderer, x, y, w, h)` | Draw a rectangle outline |
| `sharpe.fill(renderer, x, y, w, h)` | Fill a rectangle |
| `sharpe.wait(ms)` | Sleep for milliseconds |
| `sharpe.ticks()` | Milliseconds since SDL started |
| `sharpe.error(buf, len)` | Copy the current SDL error into `buf` |

`window` and `renderer` return null on failure. `color` uses an opaque alpha.

## Constants

`constants.bt` exposes the SDL event, mouse-button, and key values used by
sharpe. Import it with a short alias:

```baton
mod s get-from <sharpe/constants.bt>
```

```baton
s.QUIT
s.KEYDOWN
s.KEY_ESCAPE
s.BUTTON_LEFT
```

## Linking

Nothing extra to pass. The binding declares its linker flag in the header:

```c
/* baton:link -lSDL2 */
```

`baton build` and `baton run` collect that flag automatically. SDL2 headers and
library must be installed.

Strings handed to C use `cstr(...)`, which yields the null-terminated bytes of
a Baton string.

## Specification

The full API and ABI contract are in
[`../sharpe-spec.md`](../sharpe-spec.md).
