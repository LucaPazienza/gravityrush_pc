// gow3: SDL3 window for the Vulkan swapchain (X11 or Wayland).
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <SDL3/SDL.h>
#include "common/assert.h"
#include "common/logging/log.h"
#include "sdl_window.h"
#include "gow3_overlay.h"
#include "gow3_graphics.h"
#include "gow3_settings.h"
#ifdef _WIN32
#include <windows.h>
#endif

// Mouse look (gow3gpu.h): motion collected on the window thread while the cursor is captured,
// taken by the pad thread (runtime_pad.c) when the game reads the pad.
namespace {
std::mutex mouse_mutex;
float mouse_dx = 0.0f, mouse_dy = 0.0f;
std::atomic<bool> mouse_captured{false};
// GOW3_MOUSE_LOOK=0 turns mouse look off (the mouse is only the touchpad finger, as before).
bool MouseLookEnabled() {
    static const bool enabled = [] {
        const char* env = std::getenv("GOW3_MOUSE_LOOK");
        return !env || *env != '0';
    }();
    return enabled;
}
} // namespace

extern "C" int gow3gpu_mouse_take(float* dx, float* dy) {
    std::scoped_lock lock{mouse_mutex};
    if (dx && dy) { // NULL pointers only ask whether the cursor is captured
        *dx = mouse_dx;
        *dy = mouse_dy;
        mouse_dx = mouse_dy = 0.0f;
    }
    return mouse_captured.load(std::memory_order_relaxed) ? 1 : 0;
}

namespace Frontend {

// gow3: Borderless keeps the desktop's display mode, so a refresh rate chosen in gravityrush.ini is
// set on the window's monitor itself: the mode at the desktop size closest to it, as a temporary
// change (CDS_FULLSCREEN: never stored, Windows restores the desktop's mode when the game exits).
// hz 0 puts the desktop's mode back.
static void SetMonitorRefresh(SDL_Window* window, int hz) {
#ifdef _WIN32
    static bool changed = false;
    static WCHAR changed_device[CCHDEVICENAME] = {};
    if (hz <= 0) {
        if (changed) {
            ChangeDisplaySettingsExW(changed_device, nullptr, nullptr, 0, nullptr);
            changed = false;
            std::printf("Window: monitor back to the desktop refresh rate\n");
        }
        return;
    }
    HWND hwnd = static_cast<HWND>(SDL_GetPointerProperty(SDL_GetWindowProperties(window),
                                                         SDL_PROP_WINDOW_WIN32_HWND_POINTER, nullptr));
    MONITORINFOEXW info{};
    info.cbSize = sizeof(info);
    if (!hwnd || !GetMonitorInfoW(MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST), &info)) {
        return;
    }
    DEVMODEW current{};
    current.dmSize = sizeof(current);
    if (!EnumDisplaySettingsW(info.szDevice, ENUM_CURRENT_SETTINGS, &current)) {
        return;
    }
    DEVMODEW best{}, mode{};
    best.dmSize = mode.dmSize = sizeof(DEVMODEW);
    bool found = false;
    for (DWORD i = 0; EnumDisplaySettingsW(info.szDevice, i, &mode); ++i) {
        if (mode.dmPelsWidth != current.dmPelsWidth || mode.dmPelsHeight != current.dmPelsHeight ||
            mode.dmBitsPerPel != current.dmBitsPerPel) {
            continue;
        }
        const int gap = std::abs(int(mode.dmDisplayFrequency) - hz);
        if (!found || gap < std::abs(int(best.dmDisplayFrequency) - hz)) {
            best = mode;
            found = true;
        }
    }
    if (!found || best.dmDisplayFrequency == current.dmDisplayFrequency) {
        return;
    }
    best.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT | DM_BITSPERPEL | DM_DISPLAYFREQUENCY;
    const LONG result = ChangeDisplaySettingsExW(info.szDevice, &best, nullptr, CDS_FULLSCREEN, nullptr);
    if (result == DISP_CHANGE_SUCCESSFUL) {
        changed = true;
        std::memcpy(changed_device, info.szDevice, sizeof(changed_device));
    }
    std::printf("Window: monitor %ux%u at %u Hz (%s)\n", unsigned(best.dmPelsWidth), unsigned(best.dmPelsHeight),
                unsigned(best.dmDisplayFrequency), result == DISP_CHANGE_SUCCESSFUL ? "set" : "refused");
#else
    (void)window;
    (void)hz;
#endif
}

WindowSDL::WindowSDL(s32 width_, s32 height_, const char* title) : width{width_}, height{height_} {
    // Gamepads are sampled by runtime_pad.c; their events are pumped here with the window's.
    if (!SDL_InitSubSystem(SDL_INIT_VIDEO | SDL_INIT_GAMEPAD)) {
        UNREACHABLE_MSG("Failed to initialize SDL video: {}", SDL_GetError());
    }
    SDL_PropertiesID props = SDL_CreateProperties();
    SDL_SetStringProperty(props, SDL_PROP_WINDOW_CREATE_TITLE_STRING, title);
    SDL_SetNumberProperty(props, SDL_PROP_WINDOW_CREATE_X_NUMBER, SDL_WINDOWPOS_CENTERED);
    SDL_SetNumberProperty(props, SDL_PROP_WINDOW_CREATE_Y_NUMBER, SDL_WINDOWPOS_CENTERED);
    SDL_SetNumberProperty(props, SDL_PROP_WINDOW_CREATE_WIDTH_NUMBER, width_);
    SDL_SetNumberProperty(props, SDL_PROP_WINDOW_CREATE_HEIGHT_NUMBER, height_);
    SDL_SetBooleanProperty(props, SDL_PROP_WINDOW_CREATE_RESIZABLE_BOOLEAN, true);
    SDL_SetBooleanProperty(props, SDL_PROP_WINDOW_CREATE_VULKAN_BOOLEAN, true);
    base_title = title;
    window = SDL_CreateWindowWithProperties(props);
    SDL_DestroyProperties(props);
    ASSERT_MSG(window, "Failed to create window: {}", SDL_GetError());
    // gow3: the game's own icon (run.py converts sce_sys/icon0.png to BMP, SDL's built-in format).
    if (const char* icon_path = std::getenv("GOW3_WINDOW_ICON")) {
        if (SDL_Surface* icon = SDL_LoadBMP(icon_path)) {
            SDL_SetWindowIcon(window, icon);
            SDL_DestroySurface(icon);
        }
    }

    const char* driver = SDL_GetCurrentVideoDriver();
    const SDL_PropertiesID wp = SDL_GetWindowProperties(window);
#ifdef _WIN32
    if (driver && !std::strcmp(driver, "windows")) {
        window_info.type = WindowSystemType::Windows;
        window_info.render_surface = SDL_GetPointerProperty(wp, SDL_PROP_WINDOW_WIN32_HWND_POINTER, nullptr);
    } else
#endif
    if (driver && !std::strcmp(driver, "x11")) {
        window_info.type = WindowSystemType::X11;
        window_info.display_connection = SDL_GetPointerProperty(wp, SDL_PROP_WINDOW_X11_DISPLAY_POINTER, nullptr);
        window_info.render_surface = reinterpret_cast<void*>(SDL_GetNumberProperty(wp, SDL_PROP_WINDOW_X11_WINDOW_NUMBER, 0));
    } else if (driver && !std::strcmp(driver, "wayland")) {
        window_info.type = WindowSystemType::Wayland;
        window_info.display_connection = SDL_GetPointerProperty(wp, SDL_PROP_WINDOW_WAYLAND_DISPLAY_POINTER, nullptr);
        window_info.render_surface = SDL_GetPointerProperty(wp, SDL_PROP_WINDOW_WAYLAND_SURFACE_POINTER, nullptr);
    } else {
        UNREACHABLE_MSG("Unsupported SDL video driver {}", driver ? driver : "(none)");
    }
    // gow3: GOW3_FULLSCREEN=1 (older launchers) still asks for fullscreen.
    if (const char* fullscreen = std::getenv("GOW3_FULLSCREEN"); fullscreen && fullscreen[0] == '1' &&
        Gow3Settings::Get().display_mode == Gow3Graphics::Windowed) {
        Gow3Settings::Get().display_mode = Gow3Graphics::Borderless;
    }
    ApplyDisplayMode(Gow3Settings::Get().display_mode);
    int w = 0, h = 0;
    SDL_GetWindowSizeInPixels(window, &w, &h);
    width = w;
    height = h;
    LOG_INFO(Frontend, "Window {}x{} on {}", w, h, driver);
}

// Windowed, borderless (desktop-sized, the monitor at the chosen refresh rate) or exclusive
// fullscreen at the desktop size, with the refresh rate of gravityrush.ini (refresh_rate, 0: the
// desktop's). Window thread only (SDL). The swapchain follows the size events.
void WindowSDL::ApplyDisplayMode(int mode) {
    display_mode = mode;
    refresh_rate = Gow3Settings::Get().refresh_rate;
    // Borderless: the monitor takes the chosen refresh rate; windowed and exclusive fullscreen
    // (where SDL sets the mode) leave the desktop's.
    SetMonitorRefresh(window, mode == Gow3Graphics::Borderless ? refresh_rate : 0);
    if (mode == Gow3Graphics::Windowed) {
        SDL_SetWindowFullscreen(window, false);
    } else {
        const SDL_DisplayID display = SDL_GetDisplayForWindow(window);
        const SDL_DisplayMode* desktop = SDL_GetDesktopDisplayMode(display);
        const bool exclusive = mode == Gow3Graphics::Fullscreen && desktop;
        SDL_DisplayMode chosen{};
        const SDL_DisplayMode* target = desktop;
        if (exclusive && refresh_rate > 0 &&
            SDL_GetClosestFullscreenDisplayMode(display, desktop->w, desktop->h, float(refresh_rate), false,
                                                &chosen)) {
            target = &chosen;
        }
        if (exclusive) {
            std::printf("Window: fullscreen %dx%d at %.2f Hz\n", target->w, target->h, target->refresh_rate);
        }
        if (!SDL_SetWindowFullscreenMode(window, exclusive ? target : nullptr)) {
            LOG_WARNING(Frontend, "Fullscreen mode: {}", SDL_GetError());
        }
        SDL_SetWindowFullscreen(window, true);
    }
    SDL_SyncWindow(window);
    std::printf("Window: %s\n", Gow3Graphics::DisplayModeNames[mode]);
}

WindowSDL::~WindowSDL() {
    SDL_DestroyWindow(window);
}

void WindowSDL::BeginTextInput(const std::string& initial, const std::string& prompt) {
    std::scoped_lock lock{text_mutex};
    text = initial;
    text_prompt = prompt;
    text_state = 0;
    text_requested = true;
}

int WindowSDL::PollTextInput(std::string& out) {
    std::scoped_lock lock{text_mutex};
    out = text;
    return text_state;
}

void WindowSDL::UpdateTextTitle() {
    const std::string title = text_active ? base_title + " \u2014 " + text_prompt + ": " + text + "_  (Enter = OK, Esc = cancel)"
                                          : base_title;
    SDL_SetWindowTitle(window, title.c_str());
    Gow3Overlay::SetTextEntry(text_active, text_prompt, text);
}

bool WindowSDL::PollEvents() {
    if (Gow3Overlay::QuitDue()) {
        return false;
    }
    {
        std::scoped_lock lock{text_mutex};
        if (text_requested) { // SDL text input must be toggled from the window thread
            text_requested = false;
            text_active = true;
            SDL_StartTextInput(window);
            UpdateTextTitle();
        }
    }
    if (!text_active) {
        Gow3Overlay::UpdateTextInput(window);
    }
    if (const int mode = Gow3Settings::Get().display_mode;
        mode != display_mode || Gow3Settings::Get().refresh_rate != refresh_rate) {
        ApplyDisplayMode(mode);
    }
    UpdateMouseCapture();
    SDL_Event event;
    while (SDL_PollEvent(&event)) {
        if (event.type == SDL_EVENT_MOUSE_MOTION && mouse_captured.load(std::memory_order_relaxed)) {
            std::scoped_lock lock{mouse_mutex};
            mouse_dx += event.motion.xrel;
            mouse_dy += event.motion.yrel;
            continue;
        }
        // F8 switches mouse look off and on (the cursor is then free in the window).
        if (event.type == SDL_EVENT_KEY_DOWN && !event.key.repeat && event.key.key == SDLK_F8 &&
            MouseLookEnabled() && !text_active) {
            mouse_look_on = !mouse_look_on;
            std::printf("Window: mouse look %s (F8)\n", mouse_look_on ? "on" : "off");
            UpdateMouseCapture();
        }
        if (event.type == SDL_EVENT_WINDOW_FOCUS_LOST || event.type == SDL_EVENT_WINDOW_FOCUS_GAINED) {
            UpdateMouseCapture();
        }
        if (text_active &&(event.type == SDL_EVENT_TEXT_INPUT || event.type == SDL_EVENT_KEY_DOWN)) {
            std::scoped_lock lock{text_mutex};
            if (event.type == SDL_EVENT_TEXT_INPUT) {
                text += event.text.text;
            } else if (event.key.key == SDLK_BACKSPACE && !text.empty()) {
                size_t cut = text.size() - 1; // drop one UTF-8 code point
                while (cut > 0 && (static_cast<unsigned char>(text[cut]) & 0xC0) == 0x80) --cut;
                text.erase(cut);
            } else if (event.key.key == SDLK_RETURN || event.key.key == SDLK_KP_ENTER || event.key.key == SDLK_ESCAPE) {
                text_state = event.key.key == SDLK_ESCAPE ? 2 : 1;
                text_active = false;
                SDL_StopTextInput(window);
            }
            UpdateTextTitle();
            continue;
        }
        // The controller finishes the text dialog too: Cross (A) accepts, Circle (B) cancels.
        if (text_active && event.type == SDL_EVENT_GAMEPAD_BUTTON_DOWN &&
            (event.gbutton.button == SDL_GAMEPAD_BUTTON_SOUTH ||
             event.gbutton.button == SDL_GAMEPAD_BUTTON_EAST)) {
            std::scoped_lock lock{text_mutex};
            text_state = event.gbutton.button == SDL_GAMEPAD_BUTTON_SOUTH ? 1 : 2;
            text_active = false;
            SDL_StopTextInput(window);
            UpdateTextTitle();
            continue;
        }
        if (Gow3Overlay::HandleEvent(event)) {
            continue;
        }
        switch (event.type) {
        case SDL_EVENT_WINDOW_PIXEL_SIZE_CHANGED:
        case SDL_EVENT_WINDOW_RESIZED: {
            int w = 0, h = 0;
            SDL_GetWindowSizeInPixels(window, &w, &h);
            width = w;
            height = h;
            break;
        }
        case SDL_EVENT_QUIT:
        case SDL_EVENT_WINDOW_CLOSE_REQUESTED:
            // The process ends right after this (gow3gpu.cpp): say why, the log has nothing else.
            std::printf("Window: %s event, closing\n",
                        event.type == SDL_EVENT_QUIT ? "SDL quit" : "window close requested");
            is_open = false;
            break;
        default:
            break;
        }
    }
    return is_open;
}

// Captures the cursor (relative mouse mode: hidden, unlimited motion) while the game is played
// with the mouse: window focused, settings menu and text entry closed, Left Alt not held and mouse
// look not switched off with F8. Window thread only (SDL).
void WindowSDL::UpdateMouseCapture() {
    const SDL_WindowFlags flags = SDL_GetWindowFlags(window);
    const bool* keys = SDL_GetKeyboardState(nullptr);
    const bool want = MouseLookEnabled() && mouse_look_on && (flags & SDL_WINDOW_INPUT_FOCUS) &&
                      !(flags & SDL_WINDOW_MINIMIZED) && !text_active && !Gow3Overlay::CapturesInput() &&
                      !(keys && (keys[SDL_SCANCODE_LALT] || keys[SDL_SCANCODE_RALT]));
    if (want == mouse_captured.load(std::memory_order_relaxed)) {
        return;
    }
    if (!SDL_SetWindowRelativeMouseMode(window, want) && want) {
        LOG_WARNING(Frontend, "Mouse capture: {}", SDL_GetError());
        return;
    }
    {
        std::scoped_lock lock{mouse_mutex};
        mouse_dx = mouse_dy = 0.0f; // no jump from motion made while the cursor was free
    }
    mouse_captured.store(want, std::memory_order_relaxed);
    std::printf("Window: mouse %s\n", want ? "captured (mouse look)" : "released");
    if (!want) {
        int w = 0, h = 0;
        SDL_GetWindowSize(window, &w, &h);
        SDL_WarpMouseInWindow(window, w * 0.5f, h * 0.5f);
    }
}

} // namespace Frontend
