# sharpe — SDL2 bindings for Baton

**Specification 0.2**

sharpe is a small SDL2 binding for Baton. The public API uses short verb names
instead of long `create_window` / `set_draw_color` style names.

The implementation is the normative companion of this document:

```
sharpe/sharpe.btl        namespace sharpe   (header-only C binding)
sharpe/constants.bt      namespace constants
sharpe/package.json      package metadata (name, version, files)
```

## 1. Importing

```baton
mod sharpe get-from <sharpe>                 -- latest installed version
mod s get-from <sharpe/constants.bt>         -- a file inside that version
```

Pin a version with `@`:

```baton
mod sharpe get-from <sharpe>@0.2
mod s get-from <sharpe/constants.bt>@0.2
```

`sharpe.btl` exposes the namespace `sharpe`; calls read `sharpe.<name>(...)`.
`constants.bt` exposes the namespace `constants`; the alias `s` makes them
`s.<NAME>`. Quoted paths still work and are resolved relative to the importing
file; they are never package lookups.

## 2. Linking

`sharpe.btl` begins with:

```c
/* baton:link -lSDL2 */
```

The compiler adds that flag to the gcc link command, so no extra flags are
needed for `baton build` or `baton run`.

Requirements:

- SDL2 development headers reachable as `SDL2/SDL.h`;
- the SDL2 shared library at link and run time;
- a display, or a valid `SDL_VIDEODRIVER` such as `dummy`.

## 3. Handles and ABI

Windows and renderers are opaque `*i` handles. They are only valid until
`sharpe.quit()`.

At the ABI boundary:

- Baton `i` is `int64_t`; every integer parameter and output is `int64_t`.
- Baton `u8` is `uint8_t`, used for color channels.
- Baton `*i` is `int64_t *`; out-parameters are addresses of live `i` values.
- Baton `*c` is `char *`, used for the error buffer.
- The window and renderer handles are `void *` on the C side.

## 4. Lifecycle

### `sharpe.init() -> i`

Initializes SDL video and events. Returns `0` on success and non-zero on
failure.

### `sharpe.window(*c title, i width, i height) -> *i`

Creates a centered, visible window. Returns a window handle or null on failure.

### `sharpe.renderer(*i window) -> *i`

Creates an accelerated renderer for the window, falling back to software if
needed. Returns a renderer handle or null on failure.

### `sharpe.quit()`

Calls `SDL_Quit()` and releases every SDL resource created by the binding.

```baton
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
```

Call `sharpe.error(...)` after a failed `init`, `window`, or `renderer` call to
retrieve SDL's message.

## 5. Events

### `sharpe.poll(*i type, *i key, *i x, *i y, *i button) -> i`

Polls one SDL event. Returns `1` if an event was written, `0` if the queue is
empty.

- `type` receives the event type.
- `key` receives the key symbol for `KEYDOWN` / `KEYUP`.
- `x` / `y` receive mouse coordinates for motion and button events.
- `button` receives the button index for mouse-button events.

Out-pointers may be null to ignore a field.

```baton
i local ev = 0
i local key = 0
i local x = 0
i local y = 0
i local btn = 0

while sharpe.poll(&ev, &key, &x, &y, &btn) == 1 {
    if ev == s.QUIT { running = 0 }
    if ev == s.KEYDOWN and key == s.KEY_ESCAPE { running = 0 }
}
```

## 6. Drawing

All drawing calls use the renderer's current color.

### `sharpe.color(*i renderer, u8 r, u8 g, u8 b)`

Sets the drawing color. Alpha is opaque (`255`).

### `sharpe.clear(*i renderer)`

Clears the whole target to the current color.

### `sharpe.present(*i renderer)`

Presents the back buffer.

### `sharpe.point(*i renderer, i x, i y) -> i`

Draws one point.

### `sharpe.line(*i renderer, i x1, i y1, i x2, i y2) -> i`

Draws a line segment.

### `sharpe.rect(*i renderer, i x, i y, i w, i h) -> i`

Draws a rectangle outline.

### `sharpe.fill(*i renderer, i x, i y, i w, i h) -> i`

Fills a rectangle.

The shape calls return `0` on success and a negative SDL error code on failure.

## 7. Timing and errors

### `sharpe.wait(i ms)`

Blocks for at least `ms` milliseconds.

### `sharpe.ticks() -> i`

Milliseconds since SDL was initialized.

### `sharpe.error(*c buf, i len) -> i`

Copies the current SDL error into `buf`, which must hold at least `len` bytes.
Writes at most `len - 1` characters plus a terminator. Returns `1` when `len` is
positive, otherwise `0`.

## 8. Constants

`constants.bt` exports the SDL values a small program needs:

| Group | Names |
| --- | --- |
| events | `QUIT`, `KEYDOWN`, `KEYUP`, `MOUSEMOTION`, `MOUSEBUTTONDOWN`, `MOUSEBUTTONUP` |
| buttons | `BUTTON_LEFT`, `BUTTON_RIGHT` |
| keys | `KEY_ESCAPE`, `KEY_SPACE`, `KEY_UP`, `KEY_DOWN`, `KEY_LEFT`, `KEY_RIGHT`, `KEY_W`, `KEY_A`, `KEY_S`, `KEY_D`, `KEY_R` |

The `init`, window, and renderer flags are no longer public; the binding chooses
simple defaults.

## 9. Installation

```
baton libinstall sharpe@0.2
baton libs
```

`libinstall` places `sharpe.btl`, `constants.bt`, and the package metadata under
`$BATON_LIB/sharpe/0.2/`, defaulting to `~/.local/lib/baton/sharpe/0.2/`. It
also points `$BATON_LIB/sharpe/latest` at the newest installed version, which is
what `<sharpe>` resolves. `baton libinstall sharpe` installs the branch tip into
the version declared by `sharpe/package.json` (currently `0.2`).

`baton libs` lists the installed versions:

```
sharpe  0.2 (latest)
```

## 10. Versioning

This document describes sharpe 0.2. The 0.2 API is intentionally smaller than
0.1:

- `create_window` / `create_renderer` became `window` / `renderer`;
- `poll_event` became `poll` and no longer reports relative mouse motion;
- `render_clear` / `render_present` became `clear` / `present`;
- `set_draw_color` became `color`;
- `draw_point`, `draw_line`, `draw_rect`, and `fill_rect` became `point`,
  `line`, `rect`, and `fill`;
- `get_ticks` / `get_error` became `ticks` / `error`;
- `delay` became `wait`;
- `init` and `quit` stay, because raw renderer handles are still useful to
  custom `.btl` modules.

## 11. Minimal example

```baton
mod sharpe get-from <sharpe>

fn main() -> i {
    if sharpe.init() != 0 {
        return 1
    }

    *i local win = sharpe.window(cstr("baton sharpe"), 640, 480)
    *i local ren = sharpe.renderer(win)

    sharpe.color(ren, 0, 100, 200)
    sharpe.clear(ren)
    sharpe.present(ren)
    sharpe.wait(100)
    sharpe.quit()
    return 0
}
```

A full event loop lives in `examples/sharpe_window.bt`.
