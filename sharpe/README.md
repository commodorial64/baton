# sharpe

SDL2 bindings for Baton. It's what SDL2 is to C and what pygame is to python.

## Usage

```baton
mod sharpe get-from "sharpe/sharpe.btl"
mod s get-from "sharpe/constants.bt"

fn main() -> i {
    sharpe.init()
    *i local win = sharpe.create_window("hello", s.WINDOWPOS_UNDEFINED, s.WINDOWPOS_UNDEFINED, 800, 600, s.WINDOW_SHOWN)
    *i local ren = sharpe.create_renderer(win, -1, s.RENDERER_ACCELERATED)
    
    i local running = 1
    i local type = 0
    while running == 1 {
        if sharpe.poll_event(&type, &key, &x, &y, &btn, &xr, &yr) == 1 {
            if type == s.QUIT { running = 0 }
            if type == s.KEYDOWN {
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

## Linking

Compile with `-lSDL2`. The baton module loader will include the header automatically.
