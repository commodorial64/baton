# sharpe — SDL2 bindings for Baton

**Specification 0.1** · ships with Baton 0.3.0

sharpe is the SDL2 binding for Baton: the low-level window, renderer, event and
timing surface needed to put pixels on screen without writing C. It is a
normal Baton module pair, not a compiler feature.

## 1. Scope

This document specifies:

- the `sharpe` module's public functions and their semantics;
- the `constants` module's public constants;
- the ABI rules the binding follows when baton values cross into C;
- how the module is linked and installed.

The implementation is the normative companion of this document:

```
sharpe/sharpe.btl        namespace sharpe   (header-only C binding)
sharpe/constants.bt      namespace constants
```

Only the functions and constants listed here are part of the public API.
Everything else in the header is an implementation detail.

## 2. Files and imports

```baton
mod sharpe get-from "sharpe/sharpe.btl"
mod s get-from "sharpe/constants.bt"
```

- `sharpe.btl` exposes the namespace `sharpe`; calls read `sharpe.<name>(...)`.
- `constants.bt` exposes the namespace `constants`; the alias `s` in the
  example above makes them `s.<NAME>`.
- Both are ordinary `.bt`/`.btl` imports (Baton spec section 19). An alias may
  be any name, e.g. `mod consts get-from "sharpe/constants.bt"` gives
  `consts.QUIT`.
- The `.btl` file is header-only: its prototypes and implementations live in
  the same file. The compiler reads the prototypes; the generated C includes
  the file and therefore the code.

## 3. Linking and platform requirements

`sharpe.btl` begins with:

```c
/* baton:link -lSDL2 */
```

The compiler appends this flag to the single gcc link command (Baton spec
section 19), so `baton build` and `baton run` need no extra flags.

Requirements:

- SDL2 development headers reachable as `SDL2/SDL.h`;
- the SDL2 shared library available at link and run time;
- a display or a valid `SDL_VIDEODRIVER` (for example `dummy`) at run time.

sharpe does not bundle, download, or configure SDL2.

## 4. Handles and ABI

`SDL_Window *` and `SDL_Renderer *` are exposed as Baton `*i` opaque handles.
Callers must not dereference, index, or perform arithmetic on them. They are
only valid until `sharpe.quit()`.

At the ABI boundary:

- Baton `i` is `int64_t`. Every integer parameter and output is `int64_t`;
  the binding casts to SDL's narrower `int`/`Uint32` inside.
- Baton `u8` is `uint8_t`, used for color channels.
- Baton `*i` is `int64_t *`; every out-parameter is an addressable `i`.
- Baton `*c` is `char *`, used for the error buffer.
- `void *` return values are mapped to `*i`.

Because outputs are `int64_t`, a caller must pass the address of an `i`
variable (`&ev`), not an `i32`/`u8`.

## 5. Window and renderer lifecycle

```baton
i local rc = sharpe.init()
if rc != 0 { return 1 }

*i local win = sharpe.create_window(
    cstr("hello"),
    s.WINDOWPOS_UNDEFINED, s.WINDOWPOS_UNDEFINED,
    800, 600,
    s.WINDOW_SHOWN
)
*i local ren = sharpe.create_renderer(win, -1, s.RENDERER_ACCELERATED)
```

`init() -> i`
: Initializes SDL video and events. Returns `0` on success, non-zero on
  failure (the SDL convention). Call once before anything else.

`quit()`
: Shuts SDL down and destroys all windows, renderers and other SDL resources
  created through the binding. Call once at the end.

`create_window(*c title, i x, i y, i w, i h, i flags) -> *i`
: Creates a window. `title` is a C string (`cstr(...)`); `x` and `y` may be
  `WINDOWPOS_UNDEFINED` to let the window manager place the window; `w`/`h`
  are the client size in pixels; `flags` is a bitwise OR of `WINDOW_*`.
  Returns a window handle, or a null pointer on failure.

`create_renderer(*i window, i index, i flags) -> *i`
: Creates a renderer for `window`. `index` selects the rendering driver,
  with `-1` meaning "the first one that works". `flags` is a bitwise OR of
  `RENDERER_*`. Returns a renderer handle, or a null pointer on failure.

The binding currently exposes no `destroy_window`/`destroy_renderer`;
resources are released by `quit()`. Programs that create many windows in one
run should account for that.

## 6. Event polling

```
sharpe.poll_event(*i type, *i key, *i x, *i y,
                  *i button, *i xrel, *i yrel) -> i
```

Polls one pending event.

- Returns `1` if an event was written, `0` if the queue is empty.
- On a `1` return, `type` always receives the event type.
- `key` is written only for `KEYDOWN`/`KEYUP`; it receives the key symbol
  (compare against `KEY_*`).
- `x`/`y` receive mouse coordinates for `MOUSEMOTION` and mouse-button events.
- `xrel`/`yrel` receive relative motion for `MOUSEMOTION`.
- `button` receives the button index for `MOUSEBUTTONDOWN`/`MOUSEBUTTONUP`.
- Fields that do not apply to the event are set to `0`.
- Any out-pointer may be null to ignore that field. In Baton, a zeroed `*i`
  is null; a pointer to a live `i` is the usual form.

```baton
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
}
```

## 7. Drawing

`render_clear(*i renderer)`
: Clears the whole target to the renderer's current draw color.

`render_present(*i renderer)`
: Presents the back buffer. Nothing appears on screen until this is called.

`set_draw_color(*i renderer, u8 r, u8 g, u8 b, u8 a)`
: Sets the color used by `render_clear` and the drawing calls. Channels are
  `0..255`.

`draw_point(*i renderer, i x, i y) -> i`
: Draws one point.

`draw_line(*i renderer, i x1, i y1, i x2, i y2) -> i`
: Draws a line segment.

`draw_rect(*i renderer, i x, i y, i w, i h) -> i`
: Draws a rectangle outline.

`fill_rect(*i renderer, i x, i y, i w, i h) -> i`
: Fills a rectangle.

Drawing calls return `0` on success and a negative value on error, following
SDL. They draw with the renderer's current draw color.

## 8. Timing and errors

`delay(i ms)`
: Blocks for at least `ms` milliseconds.

`get_ticks() -> i`
: Milliseconds since SDL was initialized. Suitable for frame timing.

`get_error(*c buf, i len) -> i`
: Copies the current SDL error message into `buf`, which must hold at least
  `len` bytes. Writes at most `len - 1` characters plus a terminating null.
  Returns `1` when `len` is positive (the buffer receives the current message,
  which may be empty) and `0` when `len` is not positive. Call this after a
  failed `init`, window or renderer creation.

## 9. Constants namespace

The `constants` namespace mirrors the SDL values Baton programs need. All are
`i`.

| Group | Names | Notes |
| --- | --- | --- |
| init flags | `INIT_VIDEO`, `INIT_EVENTS` | SDL subsystem bits |
| window position | `WINDOWPOS_UNDEFINED` | pass as `x`/`y` to center |
| window flags | `WINDOW_OPENGL`, `WINDOW_SHOWN`, `WINDOW_RESIZABLE` | OR them for `create_window` |
| renderer flags | `RENDERER_ACCELERATED`, `RENDERER_PRESENTVSYNC` | OR them for `create_renderer` |
| event types | `QUIT`, `KEYDOWN`, `KEYUP`, `MOUSEMOTION`, `MOUSEBUTTONDOWN`, `MOUSEBUTTONUP` | compare with the `type` output |
| mouse buttons | `BUTTON_LEFT`, `BUTTON_RIGHT` | compare with the `button` output |
| keys | `KEY_ESCAPE`, `KEY_SPACE`, `KEY_UP`, `KEY_DOWN`, `KEY_LEFT`, `KEY_RIGHT`, `KEY_W`, `KEY_A`, `KEY_S`, `KEY_D` | compare with the `key` output |

Values are the SDL2 definitions, kept as decimal literals in
`sharpe/constants.bt`. `init()` always requests both video and events, so the
init flags are exported for reference rather than as arguments.

## 10. Installation and versioning

The published package is installed with the Baton package manager:

```
baton libinstall sharpe
baton libs
```

`libinstall` places `sharpe.btl` and `constants.bt` under
`$BATON_LIB/sharpe/`, defaulting to `~/.local/share/baton/lib/sharpe/`.
Imports that do not resolve relative to the importing file are then looked up
under the library directory, so every program can use the same relative paths:

```baton
mod sharpe get-from "sharpe/sharpe.btl"
mod s get-from "sharpe/constants.bt"
```

The package is content-addressed at install time: `libinstall` resolves the
source branch to a commit before downloading, so a push is picked up
immediately.

This document describes sharpe specification 0.1. Additive changes (new
functions, new constants) keep the version; a change to existing signatures
or semantics requires a new specification version.

## 11. Conformance

An implementation conforms to this specification when:

- it exposes the functions of section 5–8 with the given parameter and return
  shapes;
- it exposes the constants of section 9 with the SDL2 values;
- it links with SDL2 when the module is imported (section 3);
- integer out-parameters are 64-bit (`int64_t`), so Baton `i` variables and
  `&i` addresses are safe.

The reference implementation is `sharpe/sharpe.btl`; the constants reference
is `sharpe/constants.bt`.

## 12. Minimal example

```baton
mod sharpe get-from "sharpe/sharpe.btl"
mod s get-from "sharpe/constants.bt"

fn main() -> i {
    if sharpe.init() != 0 {
        return 1
    }
    *i local win = sharpe.create_window(
        cstr("baton sharpe"),
        s.WINDOWPOS_UNDEFINED, s.WINDOWPOS_UNDEFINED,
        640, 480,
        s.WINDOW_SHOWN
    )
    *i local ren = sharpe.create_renderer(win, -1, s.RENDERER_ACCELERATED)
    sharpe.set_draw_color(ren, 0, 100, 200, 255)
    sharpe.render_clear(ren)
    sharpe.render_present(ren)
    sharpe.delay(100)
    sharpe.quit()
    return 0
}
```

A full event loop lives in `examples/sharpe_window.bt`.
