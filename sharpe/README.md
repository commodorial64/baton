# sharpe

SDL2 bindings for Baton. It's what SDL2 is to C and what pygame is to python.

## Usage

```baton
mod sharpe get-from "sharpe/sharpe.btl"
mod s get-from "sharpe/constants.bt"

fn main() -> i {
    if sharpe.init() != 0 {
        return 1
    }

    *i local win = sharpe.create_window(
        cstr("hello"),
        s.WINDOWPOS_UNDEFINED, s.WINDOWPOS_UNDEFINED,
        800, 600,
        s.WINDOW_SHOWN
    )
    *i local ren = sharpe.create_renderer(win, -1, s.RENDERER_ACCELERATED)

    i local running = 1
    i local ev = 0
    i local key = 0
    i local x = 0
    i local y = 0
    i local btn = 0
    i local xr = 0
    i local yr = 0

    while running == 1 {
        if sharpe.poll_event(&ev, &key, &x, &y, &btn, &xr, &yr) == 1 {
            if ev == s.QUIT { running = 0 }
            if ev == s.KEYDOWN {
                if key == s.KEY_ESCAPE { running = 0 }
            }
        }

        sharpe.set_draw_color(ren, 20, 40, 60, 255)
        sharpe.render_clear(ren)
        sharpe.set_draw_color(ren, 255, 100, 50, 255)
        sharpe.fill_rect(ren, 100, 100, 200, 150)
        sharpe.render_present(ren)
        sharpe.delay(16)
    }

    sharpe.quit()
    return 0
}
```

## Structure

- `sharpe.btl` — the SDL2 binding. It is header-only: the prototypes and the
  C implementations live in the same file, so a baton program needs only one
  gcc invocation. The prototypes use `int64_t` (baton's `i`) and cast to SDL's
  narrower types internally.
- `constants.bt` — SDL constants as the `constants` namespace. Import it with
  an alias (`mod s get-from "sharpe/constants.bt"`) and use `s.WINDOW_SHOWN`,
  `s.QUIT`, and so on.

## Linking

Nothing extra to pass. The binding declares its linker flags in the header:

```
/* baton:link -lSDL2 */
```

The collection of `baton:link` flags from every imported `.btl` is appended to
the gcc link command automatically. `baton build` and `baton run` pick them up.

Strings handed to C use `cstr(...)`, which yields the null-terminated bytes of
a baton string (`cstr("hello")` above).

A runnable version lives in `examples/sharpe_window.bt`.

## Specification

The full API, ABI and installation contract are in
[`../sharpe-spec.md`](../sharpe-spec.md).

