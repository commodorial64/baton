#include "sharpe.btl"
#include <string.h>

int sharpe_init(void) {
    return SDL_Init(SDL_INIT_VIDEO | SDL_INIT_EVENTS);
}

void sharpe_quit(void) {
    SDL_Quit();
}

void* sharpe_create_window(const char *title, int x, int y, int w, int h, unsigned int flags) {
    return SDL_CreateWindow(title, x, y, w, h, flags);
}

void* sharpe_create_renderer(void *window, int index, unsigned int flags) {
    return SDL_CreateRenderer((SDL_Window*)window, index, flags);
}

int sharpe_poll_event(int *type, int *key, int *x, int *y, int *button, int *xrel, int *yrel) {
    SDL_Event e;
    if (!SDL_PollEvent(&e)) return 0;
    if (type) *type = e.type;
    if (key) *key = 0;
    if (x) *x = 0;
    if (y) *y = 0;
    if (button) *button = 0;
    if (xrel) *xrel = 0;
    if (yrel) *yrel = 0;
    if (e.type == SDL_KEYDOWN || e.type == SDL_KEYUP) {
        if (key) *key = e.key.keysym.sym;
    } else if (e.type == SDL_MOUSEMOTION) {
        if (x) *x = e.motion.x;
        if (y) *y = e.motion.y;
        if (xrel) *xrel = e.motion.xrel;
        if (yrel) *yrel = e.motion.yrel;
    } else if (e.type == SDL_MOUSEBUTTONDOWN || e.type == SDL_MOUSEBUTTONUP) {
        if (x) *x = e.button.x;
        if (y) *y = e.button.y;
        if (button) *button = e.button.button;
    }
    return 1;
}

void sharpe_render_clear(void *renderer) {
    SDL_RenderClear((SDL_Renderer*)renderer);
}

void sharpe_render_present(void *renderer) {
    SDL_RenderPresent((SDL_Renderer*)renderer);
}

void sharpe_set_draw_color(void *renderer, unsigned char r, unsigned char g, unsigned char b, unsigned char a) {
    SDL_SetRenderDrawColor((SDL_Renderer*)renderer, r, g, b, a);
}

int sharpe_draw_point(void *renderer, int x, int y) {
    return SDL_RenderDrawPoint((SDL_Renderer*)renderer, x, y);
}

int sharpe_draw_line(void *renderer, int x1, int y1, int x2, int y2) {
    return SDL_RenderDrawLine((SDL_Renderer*)renderer, x1, y1, x2, y2);
}

int sharpe_draw_rect(void *renderer, int x, int y, int w, int h) {
    SDL_Rect rect = {x, y, w, h};
    return SDL_RenderDrawRect((SDL_Renderer*)renderer, &rect);
}

int sharpe_fill_rect(void *renderer, int x, int y, int w, int h) {
    SDL_Rect rect = {x, y, w, h};
    return SDL_RenderFillRect((SDL_Renderer*)renderer, &rect);
}

void sharpe_delay(int ms) {
    SDL_Delay(ms);
}

int sharpe_get_ticks(void) {
    return (int)SDL_GetTicks();
}

int sharpe_get_error(char *buf, int len) {
    const char *err = SDL_GetError();
    if (!err) return 0;
    strncpy(buf, err, len - 1);
    buf[len - 1] = '\0';
    return 1;
}
