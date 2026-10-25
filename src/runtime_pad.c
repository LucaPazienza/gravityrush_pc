/* libScePad on SDL3 gamepads, with a keyboard fallback. SDL events are pumped
 * by the window thread (gpu/shim/window.cpp); here state is only sampled.
 *
 * Default keyboard layout (GOW3_KEY_MAP changes the buttons, see apply_button_map):
 *   WASD left stick, arrow keys right stick, Space Cross, LShift Circle,
 *   E Square, Q Triangle, 1 L1, 3 R1, R L2, F R2, Z L3, C R3,
 *   Enter Options, Tab left touchpad, Backspace right touchpad,
 *   IJKL d-pad (I up, K down, J left, L right). */
#define _GNU_SOURCE
#include "runtime.h"
#include "gpu/gow3gpu.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <pthread.h>
#include <time.h>
#include <SDL3/SDL.h>
#include <sys/stat.h>

#define ERR_INVALID_ARG ((int32_t)0x80920001)
#define ERR_INVALID_HANDLE ((int32_t)0x80920003)
#define ERR_ALREADY_OPENED ((int32_t)0x80920004)
#define ERR_NOT_INITIALIZED ((int32_t)0x80920005)
#define PAD_HANDLE 1

enum {
    BTN_L3=0x2, BTN_R3=0x4, BTN_OPTIONS=0x8, BTN_UP=0x10, BTN_RIGHT=0x20, BTN_DOWN=0x40, BTN_LEFT=0x80,
    BTN_L2=0x100, BTN_R2=0x200, BTN_L1=0x400, BTN_R1=0x800, BTN_TRIANGLE=0x1000, BTN_CIRCLE=0x2000,
    BTN_CROSS=0x4000, BTN_SQUARE=0x8000, BTN_TOUCHPAD=0x100000,
};
typedef struct { uint16_t x, y; uint8_t id, reserve[3]; } PadTouch;
typedef struct {
    uint32_t buttons;
    uint8_t left_x, left_y, right_x, right_y;
    uint8_t l2, r2, analog_padding[2];
    float orientation[4], acceleration[3], angular_velocity[3];
    uint8_t touch_count, touch_reserve[3];
    uint32_t touch_held_time;
    PadTouch touches[2];
    uint8_t connected, pad0[3];
    uint64_t timestamp;
    uint8_t extension[16];
    uint8_t connected_count, reserve[2], unique_length, unique[12];
} PadData;
typedef struct {
    float pixel_density; uint16_t resolution_x, resolution_y;
    uint8_t dead_zone_left, dead_zone_right, connection_type, connected_count;
    uint8_t connected, pad[3];
    int32_t device_class;
    uint8_t reserve[8];
} ControllerInfo;
_Static_assert(sizeof(PadData)==120,"OrbisPadData layout");
_Static_assert(sizeof(PadTouch)==8,"OrbisPadTouch layout");
_Static_assert(__builtin_offsetof(PadData,touches)==60,"OrbisPadData touch offset");
_Static_assert(__builtin_offsetof(PadData,timestamp)==80,"OrbisPadData timestamp offset");
_Static_assert(sizeof(ControllerInfo)==28,"OrbisPadControllerInformation layout");

static pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;
static int initialized, opened, sdl_ready;
static SDL_Gamepad *gamepad;
static size_t reads;
static uint8_t connected_count;

static uint64_t now_us(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return (uint64_t)t.tv_sec*1000000u+(uint64_t)t.tv_nsec/1000u; }
static uint8_t axis(int16_t v) { int x=(v+32768)>>8; return (uint8_t)(x<0 ? 0 : x>255 ? 255 : x); }
static uint8_t trigger(int16_t v) { int x=v>>7; return (uint8_t)(x<0 ? 0 : x>255 ? 255 : x); }
static uint16_t touch_axis(float v, int max) {
    return (uint16_t)(v<=0.0f ? 0 : v>=1.0f ? max : (int)(v*max+0.5f));
}
static void touch_click(PadData *d, int right) {
    d->buttons|=BTN_TOUCHPAD;
    d->touch_count=1;
    d->touches[0]=(PadTouch){.x=right ? 1440 : 480,.y=471,.id=0};
}

/* Opens the first gamepad SDL knows about; called under lock. */
static SDL_Gamepad *current_gamepad(void) {
    if (!sdl_ready) sdl_ready = SDL_WasInit(SDL_INIT_GAMEPAD) ? 1 : SDL_InitSubSystem(SDL_INIT_GAMEPAD) ? 1 : -1;
    if (sdl_ready<0) return NULL;
    if (gamepad && !SDL_GamepadConnected(gamepad)) { SDL_CloseGamepad(gamepad); gamepad=NULL; }
    if (!gamepad) {
        int count=0;
        SDL_JoystickID *ids=SDL_GetGamepads(&count);
        if (ids && count>0) {
            gamepad=SDL_OpenGamepad(ids[0]);
            if (gamepad) { ++connected_count; printf("Runtime: gamepad connected: %s\n",SDL_GetGamepadName(gamepad)); }
        }
        SDL_free(ids);
    }
    return gamepad;
}
/* Button sources: a host button or key and the PS4 button it presses. The defaults below can be
 * changed per PS4 button with GOW3_PAD_MAP (gamepad) and GOW3_KEY_MAP (keyboard), e.g.
 * GOW3_KEY_MAP="cross=Q,square=Left Shift" or GOW3_PAD_MAP="cross=b,circle=a": comma-separated
 * <ps4 button>=<SDL key or gamepad button name>. A mapped PS4 button loses its default sources.
 * Sticks, triggers and the overlay shortcuts are not remapped. */
static const struct { const char *name; uint32_t ps; } ps_names[]={
    {"cross",BTN_CROSS}, {"circle",BTN_CIRCLE}, {"square",BTN_SQUARE}, {"triangle",BTN_TRIANGLE},
    {"l1",BTN_L1}, {"r1",BTN_R1}, {"l2",BTN_L2}, {"r2",BTN_R2}, {"l3",BTN_L3}, {"r3",BTN_R3},
    {"options",BTN_OPTIONS}, {"touchpad",BTN_TOUCHPAD},
    {"up",BTN_UP}, {"down",BTN_DOWN}, {"left",BTN_LEFT}, {"right",BTN_RIGHT},
};
typedef struct { int source; uint32_t ps; } ButtonSource;
typedef struct { ButtonSource entries[48]; size_t count; } ButtonMap;
static ButtonMap pad_map={{
    {SDL_GAMEPAD_BUTTON_SOUTH,BTN_CROSS}, {SDL_GAMEPAD_BUTTON_EAST,BTN_CIRCLE},
    {SDL_GAMEPAD_BUTTON_WEST,BTN_SQUARE}, {SDL_GAMEPAD_BUTTON_NORTH,BTN_TRIANGLE},
    {SDL_GAMEPAD_BUTTON_LEFT_SHOULDER,BTN_L1}, {SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER,BTN_R1},
    {SDL_GAMEPAD_BUTTON_LEFT_STICK,BTN_L3}, {SDL_GAMEPAD_BUTTON_RIGHT_STICK,BTN_R3},
    {SDL_GAMEPAD_BUTTON_START,BTN_OPTIONS}, {SDL_GAMEPAD_BUTTON_BACK,BTN_TOUCHPAD},
    {SDL_GAMEPAD_BUTTON_TOUCHPAD,BTN_TOUCHPAD},
    {SDL_GAMEPAD_BUTTON_DPAD_UP,BTN_UP}, {SDL_GAMEPAD_BUTTON_DPAD_DOWN,BTN_DOWN},
    {SDL_GAMEPAD_BUTTON_DPAD_LEFT,BTN_LEFT}, {SDL_GAMEPAD_BUTTON_DPAD_RIGHT,BTN_RIGHT},
},15};
static ButtonMap key_map={{
    {SDL_SCANCODE_SPACE,BTN_CROSS}, {SDL_SCANCODE_LSHIFT,BTN_CIRCLE}, {SDL_SCANCODE_E,BTN_SQUARE},
    {SDL_SCANCODE_Q,BTN_TRIANGLE}, {SDL_SCANCODE_1,BTN_L1}, {SDL_SCANCODE_3,BTN_R1},
    {SDL_SCANCODE_R,BTN_L2}, {SDL_SCANCODE_F,BTN_R2}, {SDL_SCANCODE_Z,BTN_L3}, {SDL_SCANCODE_C,BTN_R3},
    {SDL_SCANCODE_RETURN,BTN_OPTIONS},
    {SDL_SCANCODE_I,BTN_UP}, {SDL_SCANCODE_K,BTN_DOWN}, {SDL_SCANCODE_J,BTN_LEFT}, {SDL_SCANCODE_L,BTN_RIGHT},
},15};

static char *trim(char *text) {
    while (*text==' ' || *text=='\t') ++text;
    char *end=text+strlen(text);
    while (end>text && (end[-1]==' ' || end[-1]=='\t' || end[-1]=='\r' || end[-1]=='\n')) *--end=0;
    return text;
}

/* Applies a GOW3_PAD_MAP/GOW3_KEY_MAP value; returns how many entries were used. Bad entries are
 * logged and skipped, so their PS4 button keeps its default. */
static int apply_button_map(ButtonMap *map, const char *spec, bool keyboard) {
    if (!spec || !*spec) return 0;
    char copy[1024];
    snprintf(copy,sizeof(copy),"%s",spec);
    int used=0;
    char *entry=copy;
    while (entry) {
        char *next=strchr(entry,',');
        if (next) *next++=0;
        char *eq=strchr(entry,'=');
        if (!eq) {
            if (*trim(entry)) printf("Runtime: pad map: ignored '%s' (expected button=name)\n",trim(entry));
            entry=next;
            continue;
        }
        *eq=0;
        const char *button=trim(entry), *name=trim(eq+1);
        entry=next;
        uint32_t ps=0;
        for (size_t i=0;i<sizeof(ps_names)/sizeof(*ps_names);++i) if (!SDL_strcasecmp(button,ps_names[i].name)) ps=ps_names[i].ps;
        const int source=!*name ? -1 : keyboard ? (int)SDL_GetScancodeFromName(name) : (int)SDL_GetGamepadButtonFromString(name);
        if (!ps || source<=(keyboard ? (int)SDL_SCANCODE_UNKNOWN : (int)SDL_GAMEPAD_BUTTON_INVALID)) {
            printf("Runtime: pad map: ignored '%s=%s'\n",button,name);
            continue;
        }
        size_t kept=0;
        for (size_t i=0;i<map->count;++i) if (map->entries[i].ps!=ps) map->entries[kept++]=map->entries[i];
        map->count=kept;
        if (map->count<sizeof(map->entries)/sizeof(*map->entries)) map->entries[map->count++]=(ButtonSource){source,ps};
        ++used;
    }
    return used;
}

static void load_button_maps(void) {
    static bool loaded;
    if (loaded) return;
    loaded=true;
    const int pad=apply_button_map(&pad_map,getenv("GOW3_PAD_MAP"),false);
    const int keys=apply_button_map(&key_map,getenv("GOW3_KEY_MAP"),true);
    if (pad || keys) printf("Runtime: pad map: %d gamepad and %d keyboard buttons remapped\n",pad,keys);
}

/* 1 when the key presses a PS4 button (key_map). */
static int key_bound(int scancode) {
    for (size_t i=0;i<key_map.count;++i) if (key_map.entries[i].source==scancode) return 1;
    return 0;
}
static void key_axis(uint8_t *axis, bool negative, bool positive) {
    if (negative || positive) *axis=(uint8_t)(128-(negative ? 128 : 0)+(positive ? 127 : 0));
}

/* Mouse look. While the window has captured the cursor (gow3gpu_mouse_take), mouse motion moves
 * the right stick, which turns the camera and aims the gravity shift, and the mouse buttons press
 * PS4 buttons. Left Alt held or F8 frees the cursor: the left button is then the touchpad finger.
 *   GOW3_MOUSE_SENS     sensitivity (default 1.0)
 *   GOW3_MOUSE_INVERT_Y 1: moving the mouse forward looks down
 *   GOW3_MOUSE_MAP      PS4 button per mouse button, e.g. "left=square,right=r1,middle=l1,x1=l2,x2=r2"
 *                       (the default; "right=" leaves a button unused). */
enum { MOUSE_LEFT, MOUSE_MIDDLE, MOUSE_RIGHT, MOUSE_X1, MOUSE_X2, MOUSE_BUTTONS };
static const char *const mouse_names[MOUSE_BUTTONS]={"left","middle","right","x1","x2"};
static uint32_t mouse_map[MOUSE_BUTTONS]={BTN_SQUARE,BTN_L1,BTN_R1,BTN_L2,BTN_R2};
static struct { float sens, invert, vx, vy; uint64_t last_us; int loaded; } mouse={.sens=1.0f,.invert=1.0f};

static int apply_mouse_map(const char *spec) {
    if (!spec || !*spec) return 0;
    char copy[512];
    snprintf(copy,sizeof(copy),"%s",spec);
    int used=0;
    for (char *entry=copy, *next; entry; entry=next) {
        if ((next=strchr(entry,','))) *next++=0;
        char *eq=strchr(entry,'=');
        if (!eq) continue;
        *eq=0;
        const char *name=trim(entry), *button=trim(eq+1);
        int index=-1;
        for (int i=0;i<MOUSE_BUTTONS;++i) if (!SDL_strcasecmp(name,mouse_names[i])) index=i;
        uint32_t ps=0;
        for (size_t i=0;i<sizeof(ps_names)/sizeof(*ps_names);++i) if (!SDL_strcasecmp(button,ps_names[i].name)) ps=ps_names[i].ps;
        if (index<0 || (!ps && *button)) { printf("Runtime: mouse map: ignored '%s=%s'\n",name,button); continue; }
        mouse_map[index]=ps;
        ++used;
    }
    return used;
}
static void load_mouse_settings(void) {
    if (mouse.loaded) return;
    mouse.loaded=1;
    const char *sens=getenv("GOW3_MOUSE_SENS"), *invert=getenv("GOW3_MOUSE_INVERT_Y");
    if (sens && atof(sens)>0.0) mouse.sens=(float)atof(sens);
    if (invert && *invert=='1') mouse.invert=-1.0f;
    const int used=apply_mouse_map(getenv("GOW3_MOUSE_MAP"));
    printf("Runtime: mouse look sensitivity %.2f%s, %d mouse buttons remapped\n",mouse.sens,
           mouse.invert<0.0f ? ", inverted" : "",used);
}
/* Stick deflection (-1..1) for a mouse speed in pixels per second: a dead zone the game ignores is
 * skipped so that slow motion still turns the camera, and full deflection is reached at
 * 2400 px/s for sensitivity 1. */
static float mouse_deflection(float speed, float sens) {
    const float dead=0.12f;
    const float v=speed*sens/2400.0f;
    if (v==0.0f) return 0.0f;
    const float a=fabsf(v), out=a>=1.0f ? 1.0f : dead+(1.0f-dead)*sqrtf(a);
    return v<0.0f ? -out : out;
}
static uint8_t stick_value(float deflection) {
    const int v=128+(int)lrintf(deflection*(deflection<0.0f ? 128.0f : 127.0f));
    return (uint8_t)(v<0 ? 0 : v>255 ? 255 : v);
}
/* PS4 buttons the held mouse buttons press (mouse_map). */
static uint32_t mouse_buttons(void) {
    static const SDL_MouseButtonFlags masks[MOUSE_BUTTONS]={SDL_BUTTON_LMASK,SDL_BUTTON_MMASK,SDL_BUTTON_RMASK,
                                                           SDL_BUTTON_X1MASK,SDL_BUTTON_X2MASK};
    const SDL_MouseButtonFlags held=SDL_GetMouseState(NULL,NULL);
    uint32_t buttons=0;
    for (int i=0;i<MOUSE_BUTTONS;++i) if (held & masks[i]) buttons|=mouse_map[i];
    return buttons;
}
/* Applies the mouse to `d`; returns 1 while the cursor is captured. */
static int sample_mouse(PadData *d) {
    load_mouse_settings();
    float dx=0.0f, dy=0.0f;
    const int captured=gow3gpu_mouse_take(&dx,&dy);
    const uint64_t now=d->timestamp;
    /* Speed = motion over the last MOUSE_WINDOW_US, whatever the read rate: the game polls the pad
     * far more often than it draws frames, so a per-read speed was back at zero long before the
     * camera looked at the stick. */
    enum { MOUSE_WINDOW_US=33000, MOUSE_HISTORY=256 };
    typedef struct { uint64_t us; float dx, dy; } MouseMotion;
    static MouseMotion history[MOUSE_HISTORY];
    static unsigned head, count;
    static uint64_t rate_start; static unsigned rate_reads;
    if (!rate_start) rate_start=now;
    if (++rate_reads, now-rate_start>=1000000) { /* pad reads per second, logged a few times */
        static int rate_logs;
        if (rate_logs++<3) printf("Runtime: pad read %u times per second\n",rate_reads);
        rate_start=now; rate_reads=0;
    }
    if (!captured) { count=0; mouse.vx=mouse.vy=0.0f; return 0; }
    if (dx!=0.0f || dy!=0.0f) {
        history[head]=(MouseMotion){now,dx,dy};
        head=(head+1)%MOUSE_HISTORY;
        if (count<MOUSE_HISTORY) ++count;
    }
    float sx=0.0f, sy=0.0f;
    unsigned kept=0;
    for (unsigned i=0;i<count;++i) {
        const unsigned at=(head+MOUSE_HISTORY-1-i)%MOUSE_HISTORY;
        if (now-history[at].us>MOUSE_WINDOW_US) break;
        sx+=history[at].dx; sy+=history[at].dy; ++kept;
    }
    count=kept;
    mouse.vx=sx*(1e6f/MOUSE_WINDOW_US);
    mouse.vy=sy*(1e6f/MOUSE_WINDOW_US);
    if (mouse.vx!=0.0f) d->right_x=stick_value(mouse_deflection(mouse.vx,mouse.sens));
    if (mouse.vy!=0.0f) d->right_y=stick_value(mouse_deflection(mouse.vy*mouse.invert,mouse.sens));
    d->buttons|=mouse_buttons();
    /* The first motions, then one line every 2 s while moving: what the game gets as right stick. */
    static unsigned logged;
    static uint64_t next_log;
    if ((dx!=0.0f || dy!=0.0f) && (logged<5 || now>=next_log)) {
        printf("Runtime: mouse %.0f,%.0f px -> right stick %u,%u\n",dx,dy,d->right_x,d->right_y);
        ++logged;
        next_log=now+2000000;
    }
    return 1;
}
/* Motion sensors (DualSense / DualShock 4 through SDL, as shadPS4 does): angular velocity in
 * rad/s on the PS4's axes, acceleration in g (SDL's m/s^2 x 0.098), and an orientation
 * quaternion (scePadResetOrientation brings it back to identity). The orientation comes from
 * gr_motion_filter.h: the gyro bias is learned while the controller lies still, and with the
 * game's tilt correction (Gravity Rush asks for it) the accelerometer keeps pitch and roll from
 * drifting; before, the raw integration made the view turn by itself (the apple scene).
 * Sensors are switched on again whenever the gamepad changes (hot-plugging). */
#include "gr_motion_filter.h"
static struct { SDL_Gamepad *pad; int gyro, accel, tilt; MotionFilter filter; uint64_t last_us; } motion;
static void motion_reset(void) { motion_filter_reset(&motion.filter); motion.last_us=0; }
/* The orientation the game sees: the filtered one with its rotation angle scaled by the gyro
 * sensitivity (scaling the integration instead would fight the tilt correction). */
static void scaled_orientation(const float q[4], float sens, float out[4]) {
    float w=q[3] < -1.0f ? -1.0f : q[3] > 1.0f ? 1.0f : q[3];
    float s=sqrtf(q[0]*q[0]+q[1]*q[1]+q[2]*q[2]);
    if (s<1e-6f || sens==1.0f) { memcpy(out,q,4*sizeof(float)); return; }
    float half=atan2f(s,w)*sens, k=sinf(half)/s;
    out[0]=q[0]*k; out[1]=q[1]*k; out[2]=q[2]*k; out[3]=cosf(half);
}
static void sample_motion(SDL_Gamepad *g, PadData *d) {
    if (g!=motion.pad) {
        motion.pad=g;
        motion.gyro=SDL_GamepadHasSensor(g,SDL_SENSOR_GYRO) && SDL_SetGamepadSensorEnabled(g,SDL_SENSOR_GYRO,true);
        motion.accel=SDL_GamepadHasSensor(g,SDL_SENSOR_ACCEL) && SDL_SetGamepadSensorEnabled(g,SDL_SENSOR_ACCEL,true);
        motion_filter_init(&motion.filter);
        motion.last_us=0;
        printf("Runtime: gamepad motion sensors: gyro %s, accelerometer %s\n",motion.gyro ? "on" : "none",motion.accel ? "on" : "none");
    }
    float v[3], a[3];
    const int have_accel=motion.accel && SDL_GetGamepadSensorData(g,SDL_SENSOR_ACCEL,a,3);
    if (have_accel)
        for (int i=0;i<3;++i) { a[i]*=0.098f; d->acceleration[i]=a[i]; }
    /* GOW3_GYRO_SENS: gyro sensitivity (default 1.4: the player found 1.0 a little slow). */
    static float sens=-1.0f;
    if (sens<0.0f) { const char *e=getenv("GOW3_GYRO_SENS"); sens=e && atof(e)>0.0 ? (float)atof(e) : 1.4f; }
    if (motion.gyro && SDL_GetGamepadSensorData(g,SDL_SENSOR_GYRO,v,3)) {
        uint64_t now=d->timestamp;
        float dt=motion.last_us && now>motion.last_us ? (float)(now-motion.last_us)/1e6f : 0.0f;
        motion.last_us=now;
        float w[3];
        motion_filter_update(&motion.filter,v,have_accel ? a : NULL,motion.tilt,dt,w);
        for (int i=0;i<3;++i) d->angular_velocity[i]=w[i]*sens;
        /* GOW3_MOTION_LOG=1: the filtered orientation and the learned bias every 2 s. */
        static int motion_log=-1;
        static uint64_t next_log;
        if (motion_log<0) motion_log=getenv("GOW3_MOTION_LOG")!=NULL;
        if (motion_log && now>=next_log) {
            const float *q=motion.filter.q, *bias=motion.filter.bias;
            printf("Motion: q %.4f %.4f %.4f %.4f (%.1f deg) bias %.4f %.4f %.4f tilt %d still %.1f s"
                   " gyro %.4f %.4f %.4f accel %.3f %.3f %.3f dt %.4f\n",
                   q[0],q[1],q[2],q[3],2.0f*acosf(fminf(1.0f,fabsf(q[3])))*57.2958f,
                   bias[0],bias[1],bias[2],motion.tilt,motion.filter.still_s,
                   v[0],v[1],v[2],have_accel ? a[0] : 0.0f,have_accel ? a[1] : 0.0f,have_accel ? a[2] : 0.0f,dt);
            next_log=now+2000000;
        }
    }
    scaled_orientation(motion.filter.q,sens,d->orientation);
}
static void sample_host(PadData *d) {
    memset(d,0,sizeof(*d));
    d->left_x=d->left_y=d->right_x=d->right_y=128;
    d->orientation[3]=1.0f;
    d->connected=1; d->connected_count=connected_count ? connected_count : 1;
    d->timestamp=now_us();
    SDL_Gamepad *g=current_gamepad();
    if (gow3gpu_overlay_captures_input()) return; /* settings menu open: neutral input */
    const bool *k=SDL_WasInit(SDL_INIT_VIDEO) ? SDL_GetKeyboardState(NULL) : NULL;
    load_button_maps();
    if (g) {
        for (size_t i=0;i<pad_map.count;++i)
            if (SDL_GetGamepadButton(g,(SDL_GamepadButton)pad_map.entries[i].source)) d->buttons|=pad_map.entries[i].ps;
        const uint32_t mapped=d->buttons;
        d->left_x=axis(SDL_GetGamepadAxis(g,SDL_GAMEPAD_AXIS_LEFTX)); d->left_y=axis(SDL_GetGamepadAxis(g,SDL_GAMEPAD_AXIS_LEFTY));
        d->right_x=axis(SDL_GetGamepadAxis(g,SDL_GAMEPAD_AXIS_RIGHTX)); d->right_y=axis(SDL_GetGamepadAxis(g,SDL_GAMEPAD_AXIS_RIGHTY));
        d->l2=trigger(SDL_GetGamepadAxis(g,SDL_GAMEPAD_AXIS_LEFT_TRIGGER)); d->r2=trigger(SDL_GetGamepadAxis(g,SDL_GAMEPAD_AXIS_RIGHT_TRIGGER));
        if (d->l2>30) d->buttons|=BTN_L2;
        if (d->r2>30) d->buttons|=BTN_R2;
        if (mapped & BTN_L2) d->l2=255;
        if (mapped & BTN_R2) d->r2=255;
        sample_motion(g,d);
        if (SDL_GetNumGamepadTouchpads(g)>0) {
            const int fingers=SDL_GetNumGamepadTouchpadFingers(g,0);
            for (int finger=0;finger<fingers && d->touch_count<2;++finger) {
                bool down=false;
                float x=0, y=0;
                if (SDL_GetGamepadTouchpadFinger(g,0,finger,&down,&x,&y,NULL) && down) {
                    d->touches[d->touch_count++]=(PadTouch){.x=touch_axis(x,1919),
                        .y=touch_axis(y,942),.id=(uint8_t)finger};
                }
            }
        }
        // Back/Select on pads without a touch surface is a left-side click.
        if ((d->buttons & BTN_TOUCHPAD) && !d->touch_count) touch_click(d,0);
    }
    /* The keyboard works with or without a gamepad: its buttons add to the pad's, and a stick
     * follows the keys only while one of them is held. */
    if (!k) return;
    for (size_t i=0;i<key_map.count;++i) if (k[key_map.entries[i].source]) d->buttons|=key_map.entries[i].ps;
    if (k[SDL_SCANCODE_TAB]) touch_click(d,0);
    if ((d->buttons & BTN_TOUCHPAD) && !d->touch_count) touch_click(d,0); /* a remapped touchpad key */
    if (k[SDL_SCANCODE_BACKSPACE]) touch_click(d,1);
    /* Mouse look while the cursor is captured; otherwise the left mouse button held over the
     * window is a finger at the pointer, so dragging is a swipe. */
    const int mouse_look=sample_mouse(d);
    SDL_Window *mw=SDL_GetMouseFocus();
    float mx=0, my=0;
    int ww=0, wh=0;
    if (!mouse_look && mw && (SDL_GetMouseState(&mx,&my) & SDL_BUTTON_LMASK) && SDL_GetWindowSize(mw,&ww,&wh) && ww>0 && wh>0) {
        d->buttons|=BTN_TOUCHPAD;
        d->touch_count=1;
        d->touches[0]=(PadTouch){.x=touch_axis(mx/ww,1919),.y=touch_axis(my/wh,942),.id=0};
    }
    if (d->buttons & BTN_L2) d->l2=255;
    if (d->buttons & BTN_R2) d->r2=255;
    key_axis(&d->left_x,k[SDL_SCANCODE_A],k[SDL_SCANCODE_D]);
    key_axis(&d->left_y,k[SDL_SCANCODE_W],k[SDL_SCANCODE_S]);
    /* Arrow keys are the right stick unless the player gave them to a button (the d-pad, often). */
    key_axis(&d->right_x,k[SDL_SCANCODE_LEFT] && !key_bound(SDL_SCANCODE_LEFT),
             k[SDL_SCANCODE_RIGHT] && !key_bound(SDL_SCANCODE_RIGHT));
    key_axis(&d->right_y,k[SDL_SCANCODE_UP] && !key_bound(SDL_SCANCODE_UP),
             k[SDL_SCANCODE_DOWN] && !key_bound(SDL_SCANCODE_DOWN));
}

/* GOW3_PAD_FILE=<file>: scripted input for automated runs. The file holds whitespace-separated
 * tokens, re-read when it changes: button names (cross circle square triangle l1 r1 l2 r2 l3 r3
 * options touchpad touchpad_left touchpad_right up down left right) are held while listed;
 * touchpad defaults to a left-side click; lx= ly= rx= ry= (0..255) override
 * the sticks. An empty file releases everything. */
static struct { uint32_t buttons; int stick[4]; int touch_side; } injected={0,{-1,-1,-1,-1},-1};
static int replay_armed;      /* 1 while a GOW3_PAD_REPLAY recording plays, 2 once it ended */
static uint64_t replay_start; /* 0: (re)start at the next sample */
static void read_inject(void) {
    static const char *path; static int checked; static uint64_t last_check; static struct timespec mtime;
    if (!checked) { path=getenv("GOW3_PAD_FILE"); checked=1; }
    if (!path || !*path) return;
    uint64_t now=now_us();
    if (now-last_check<20000) return;
    last_check=now;
    struct stat st;
    if (stat(path,&st)!=0) return;
#ifdef _WIN32
    /* Whole-second mtimes: the size tells two edits within a second apart. */
    if (st.st_mtime==mtime.tv_sec && st.st_size==mtime.tv_nsec) return;
    mtime=(struct timespec){st.st_mtime,(long)st.st_size};
#else
    if (st.st_mtim.tv_sec==mtime.tv_sec && st.st_mtim.tv_nsec==mtime.tv_nsec) return;
    mtime=st.st_mtim;
#endif
    FILE *f=fopen(path,"r");
    if (!f) return;
    static const char *sticks[]={"lx=","ly=","rx=","ry="};
    injected.buttons=0;
    injected.touch_side=-1;
    for (int i=0;i<4;++i) injected.stick[i]=-1;
    char token[64];
    while (fscanf(f,"%63s",token)==1) {
        if (!strcmp(token,"replay") && replay_armed!=1) { replay_armed=1; replay_start=0; } /* GOW3_PAD_REPLAY */
        if (!strcmp(token,"touchpad_left") || !strcmp(token,"touchpad_right")) {
            injected.buttons|=BTN_TOUCHPAD;
            injected.touch_side=!strcmp(token,"touchpad_right");
        }
        for (size_t i=0;i<sizeof(ps_names)/sizeof(*ps_names);++i) if (!strcmp(token,ps_names[i].name)) injected.buttons|=ps_names[i].ps;
        for (int i=0;i<4;++i) if (!strncmp(token,sticks[i],3)) { int v=atoi(token+3); injected.stick[i]=v<0 ? 0 : v>255 ? 255 : v; }
    }
    fclose(f);
    printf("Runtime: pad file: buttons 0x%x sticks %d %d %d %d\n",injected.buttons,
           injected.stick[0],injected.stick[1],injected.stick[2],injected.stick[3]);
}
/* GOW3_PAD_RECORD=<file>: F9 starts and stops recording the pad state (gamepad or keyboard) with
 * the time since F9; GOW3_PAD_REPLAY=<file> plays such a recording back, started by the token
 * "replay" in GOW3_PAD_FILE (scripted tests repeat a route the player ran once). Lines: ms buttons
 * lx ly rx ry l2 r2, written when the state changes. */
typedef struct { uint32_t ms, buttons; uint8_t axes[4], l2, r2; } PadSample;
static FILE *record_file;
static uint64_t record_start;
static PadSample record_last;
static void record_sample(const PadData *d) {
    static const char *path; static int checked, f9_was_down;
    if (!checked) { path=getenv("GOW3_PAD_RECORD"); checked=1; }
    if (!path || !*path || !sdl_ready) return;
    const bool *k=SDL_GetKeyboardState(NULL);
    const int f9=k && k[SDL_SCANCODE_F9];
    if (f9 && !f9_was_down) {
        if (record_file) {
            fclose(record_file); record_file=NULL;
            printf("Runtime: pad recording stopped (%s)\n",path);
        } else if ((record_file=fopen(path,"w"))) {
            record_start=now_us();
            memset(&record_last,0xff,sizeof(record_last));
            printf("Runtime: pad recording started (%s, F9 stops)\n",path);
        }
    }
    f9_was_down=f9;
    if (!record_file) return;
    PadSample s={(uint32_t)((now_us()-record_start)/1000),d->buttons,
                 {d->left_x,d->left_y,d->right_x,d->right_y},d->l2,d->r2};
    if (s.buttons==record_last.buttons && !memcmp(s.axes,record_last.axes,4) &&
        s.l2==record_last.l2 && s.r2==record_last.r2) return;
    record_last=s;
    fprintf(record_file,"%u %u %u %u %u %u %u %u\n",s.ms,s.buttons,s.axes[0],s.axes[1],s.axes[2],
            s.axes[3],s.l2,s.r2);
    fflush(record_file);
}
static PadSample *replay; static size_t replay_count, replay_next;
static void replay_sample(PadData *d) {
    if (!replay_armed) return;
    if (!replay_start) {
        static int loaded;
        if (!loaded) {
            loaded=1;
            const char *path=getenv("GOW3_PAD_REPLAY");
            FILE *f=path ? fopen(path,"r") : NULL;
            PadSample s; unsigned v[8]; size_t cap=0;
            while (f && fscanf(f,"%u %u %u %u %u %u %u %u",&v[0],&v[1],&v[2],&v[3],&v[4],&v[5],&v[6],&v[7])==8) {
                s=(PadSample){v[0],v[1],{(uint8_t)v[2],(uint8_t)v[3],(uint8_t)v[4],(uint8_t)v[5]},(uint8_t)v[6],(uint8_t)v[7]};
                if (replay_count==cap && !(replay=realloc(replay,(cap=cap ? cap*2 : 1024)*sizeof(*replay)))) break;
                replay[replay_count++]=s;
            }
            if (f) fclose(f);
            printf("Runtime: pad replay of %zu samples from %s\n",replay_count,path ? path : "(unset)");
        }
        /* GOW3_PAD_REPLAY_SKIP_MS: start that far into the recording (a run that reaches the same
         * point of the game another way, e.g. by the autotest's apple taps). */
        const char *skip=getenv("GOW3_PAD_REPLAY_SKIP_MS");
        replay_start=now_us()-(skip ? (uint64_t)strtoull(skip,NULL,10)*1000 : 0);
        replay_next=0;
    }
    const uint32_t ms=(uint32_t)((now_us()-replay_start)/1000);
    while (replay_next<replay_count && replay[replay_next].ms<=ms) ++replay_next;
    if (!replay_next) return;
    if (replay_next==replay_count && ms>replay[replay_count-1].ms+500) {
        if (replay_armed==1) { puts("Runtime: pad replay finished"); replay_armed=2; }
        return;
    }
    const PadSample *s=&replay[replay_next-1];
    d->buttons=s->buttons;
    d->left_x=s->axes[0]; d->left_y=s->axes[1]; d->right_x=s->axes[2]; d->right_y=s->axes[3];
    d->l2=s->l2; d->r2=s->r2;
}
/* After the menu or the text dialog closes, buttons still held (the Cross that accepted a
 * name) stay hidden until released: the game would take them as a new press. */
static int hold_after_capture;
/* Buttons of the gamepad and keyboard as mapped, even while the overlay holds the game neutral. */
static uint32_t host_buttons(void) {
    uint32_t buttons=0;
    load_button_maps();
    SDL_Gamepad *g=current_gamepad();
    if (g) for (size_t i=0;i<pad_map.count;++i)
        if (SDL_GetGamepadButton(g,(SDL_GamepadButton)pad_map.entries[i].source)) buttons|=pad_map.entries[i].ps;
    const bool *k=SDL_WasInit(SDL_INIT_VIDEO) ? SDL_GetKeyboardState(NULL) : NULL;
    if (k) for (size_t i=0;i<key_map.count;++i) if (k[key_map.entries[i].source]) buttons|=key_map.entries[i].ps;
    if (k && gow3gpu_mouse_take(NULL,NULL)) { /* captured: mouse buttons as mapped (no motion taken) */
        load_mouse_settings();
        buttons|=mouse_buttons();
    }
    return buttons;
}
/* Buttons for the port's save list (sceSaveDataDialog), polled by the overlay every frame while
 * it is open: the game stops reading the pad during the dialog. Gamepad and keyboard as mapped,
 * scripted input, and the left stick as up/down. */
static uint32_t list_buttons(void) {
    pthread_mutex_lock(&lock);
    read_inject();
    uint32_t buttons=host_buttons()|injected.buttons;
    SDL_Gamepad *g=current_gamepad();
    if (g) {
        const int y=SDL_GetGamepadAxis(g,SDL_GAMEPAD_AXIS_LEFTY);
        if (y<-16000) buttons|=BTN_UP;
        else if (y>16000) buttons|=BTN_DOWN;
    }
    if (injected.stick[1]>=0 && injected.stick[1]<64) buttons|=BTN_UP;
    else if (injected.stick[1]>192) buttons|=BTN_DOWN;
    pthread_mutex_unlock(&lock);
    return buttons;
}
/* Like the real pad (and shadPS4): every new finger gets a fresh id 1..127, kept while it stays
 * down, and touch_held_time counts microseconds since the first finger went down. */
static void assign_touch_ids(PadData *d) {
    static uint8_t slot_id[2], next_id=1;
    static uint64_t down_since;
    if (d->buttons==0 && hold_after_capture) d->touch_count=0;
    for (int i=0;i<2;++i) {
        if (i>=d->touch_count) { slot_id[i]=0; continue; }
        if (!slot_id[i]) { slot_id[i]=next_id; next_id=next_id==127 ? 1 : next_id+1; }
        d->touches[i].id=slot_id[i];
    }
    if (!d->touch_count) down_since=0;
    else if (!down_since) down_since=d->timestamp;
    d->touch_held_time=down_since ? (uint32_t)(d->timestamp-down_since) : 0;
}
/* GOW3_MOTION_FAKE=qx,qy,qz,qw[,ax,ay,az]: a fixed orientation (and acceleration in g), and
 * GOW3_MOTION_FAKE_GYRO=wx,wy,wz a fixed angular velocity (rad/s), integrated into the orientation
 * when no fixed one is given, from GOW3_MOTION_FAKE_AFTER seconds on, with or without a gamepad
 * (diagnostics: what the game does with the motion sensors). */
static void fake_motion(PadData *d) {
    static int parsed, count, gyro_count;
    static float v[7], w[3];
    static uint64_t from;
    if (!parsed) {
        parsed=1;
        const char *e=getenv("GOW3_MOTION_FAKE"), *g=getenv("GOW3_MOTION_FAKE_GYRO");
        const char *after=getenv("GOW3_MOTION_FAKE_AFTER");
        if (e) count=sscanf(e,"%f,%f,%f,%f,%f,%f,%f",&v[0],&v[1],&v[2],&v[3],&v[4],&v[5],&v[6]);
        if (g) gyro_count=sscanf(g,"%f,%f,%f",&w[0],&w[1],&w[2]);
        from=now_us()+(uint64_t)((after ? atof(after) : 0.0)*1e6);
    }
    if ((count<4 && gyro_count<3) || now_us()<from) return;
    static int logged;
    if (!logged++) printf("Runtime: GOW3_MOTION_FAKE from now on\n");
    if (count>=4) memcpy(d->orientation,v,4*sizeof(float));
    if (count>=7) memcpy(d->acceleration,v+4,3*sizeof(float));
    if (gyro_count>=3) memcpy(d->angular_velocity,w,3*sizeof(float));
    if (gyro_count>=3 && count<4) {
        static float q[4]={0,0,0,1};
        static uint64_t last;
        const float dt=last && d->timestamp>last ? (float)(d->timestamp-last)/1e6f : 0.0f;
        last=d->timestamp;
        if (dt>0.0f && dt<1.0f) {
            const float dq[4]={q[3]*w[0]+q[1]*w[2]-q[2]*w[1], q[3]*w[1]+q[2]*w[0]-q[0]*w[2],
                               q[3]*w[2]+q[0]*w[1]-q[1]*w[0], -q[0]*w[0]-q[1]*w[1]-q[2]*w[2]};
            for (int i=0;i<4;++i) q[i]+=0.5f*dq[i]*dt;
            const float n=sqrtf(q[0]*q[0]+q[1]*q[1]+q[2]*q[2]+q[3]*q[3]);
            if (n>0.0f) for (int i=0;i<4;++i) q[i]/=n;
        }
        memcpy(d->orientation,q,sizeof(q));
    }
}
static void sample(PadData *d) {
    sample_host(d);
    fake_motion(d);
    if (gow3gpu_overlay_captures_input()) { hold_after_capture=1; return; }
    record_sample(d);
    read_inject();
    replay_sample(d);
    d->buttons|=injected.buttons;
    if (injected.touch_side>=0) touch_click(d,injected.touch_side);
    else if ((d->buttons & BTN_TOUCHPAD) && !d->touch_count) touch_click(d,0);
    if (injected.buttons & BTN_L2) d->l2=255;
    if (injected.buttons & BTN_R2) d->r2=255;
    uint8_t *axes[4]={&d->left_x,&d->left_y,&d->right_x,&d->right_y};
    for (int i=0;i<4;++i) if (injected.stick[i]>=0) *axes[i]=(uint8_t)injected.stick[i];
    if (hold_after_capture) {
        if (d->buttons) d->buttons=0;
        else hold_after_capture=0;
    }
    assign_touch_ids(d);
}

static ABI int32_t pad_init(void) {
    pthread_mutex_lock(&lock); initialized=1; pthread_mutex_unlock(&lock);
    gow3gpu_choice_set_input(list_buttons);
    return 0;
}
static ABI int32_t pad_open(int32_t user, int32_t type, int32_t index, const void *param) {
    (void)param;
    if (!initialized) return ERR_NOT_INITIALIZED;
    if (user!=1) return ERR_INVALID_ARG;
    if (type!=0 && type!=2) return ERR_INVALID_ARG; /* standard / special port */
    if (index) return ERR_INVALID_ARG;
    pthread_mutex_lock(&lock);
    int already=opened; opened=1;
    pthread_mutex_unlock(&lock);
    if (already) return ERR_ALREADY_OPENED;
    puts("Runtime: pad opened for user 1 (SDL gamepad or keyboard)");
    return PAD_HANDLE;
}
static ABI int32_t pad_close(int32_t handle) {
    if (handle!=PAD_HANDLE || !opened) return ERR_INVALID_HANDLE;
    opened=0; return 0;
}
static ABI int32_t pad_read_state(int32_t handle, PadData *data) {
    if (handle!=PAD_HANDLE || !opened) return ERR_INVALID_HANDLE;
    if (!data) return ERR_INVALID_ARG;
    pthread_mutex_lock(&lock);
    sample(data); ++reads;
    pthread_mutex_unlock(&lock);
    return 0;
}
/* Buffered read: the port samples once per call, so one entry is returned. */
static ABI int32_t pad_read(int32_t handle, PadData *data, int32_t count) {
    if (handle!=PAD_HANDLE || !opened) return ERR_INVALID_HANDLE;
    if (!data || count<1 || count>64) return ERR_INVALID_ARG;
    pad_read_state(handle,data);
    return 1;
}
static ABI int32_t pad_info(int32_t handle, ControllerInfo *info) {
    if (handle!=PAD_HANDLE || !opened) return ERR_INVALID_HANDLE;
    if (!info) return ERR_INVALID_ARG;
    memset(info,0,sizeof(*info));
    info->pixel_density=44.86f; info->resolution_x=1920; info->resolution_y=943;
    info->dead_zone_left=info->dead_zone_right=2;
    info->connection_type=0; info->connected=1; info->device_class=0;
    pthread_mutex_lock(&lock);
    current_gamepad();
    info->connected_count=connected_count ? connected_count : 1;
    pthread_mutex_unlock(&lock);
    return 0;
}
static ABI int32_t pad_vibration(int32_t handle, const uint8_t *param) {
    if (handle!=PAD_HANDLE || !opened) return ERR_INVALID_HANDLE;
    if (!param) return ERR_INVALID_ARG;
    pthread_mutex_lock(&lock);
    SDL_Gamepad *g=current_gamepad();
    if (g) SDL_RumbleGamepad(g,(uint16_t)(param[0]*257),(uint16_t)(param[1]*257),1000);
    pthread_mutex_unlock(&lock);
    return 0;
}
static ABI int32_t pad_ok_handle(int32_t handle) { return handle==PAD_HANDLE && opened ? 0 : ERR_INVALID_HANDLE; }
static ABI int32_t pad_ok_handle_flag(int32_t handle, uint8_t flag) { (void)flag; return pad_ok_handle(handle); }
/* The game's motion sensor settings: the tilt correction is applied (gr_motion_filter.h). */
static ABI int32_t pad_deadband_state(int32_t handle, uint8_t flag) {
    static int logged;
    if (!logged++) printf("Runtime: scePadSetAngularVelocityDeadbandState(%d)\n",flag);
    return pad_ok_handle(handle);
}
static ABI int32_t pad_tilt_correction_state(int32_t handle, uint8_t flag) {
    static int logged;
    if (!logged++) printf("Runtime: scePadSetTiltCorrectionState(%d)\n",flag);
    int32_t r=pad_ok_handle(handle);
    if (!r) { pthread_mutex_lock(&lock); motion.tilt=flag!=0; pthread_mutex_unlock(&lock); }
    return r;
}
static ABI int32_t pad_reset_orientation(int32_t handle) {
    static int logged;
    if (logged++<5) printf("Runtime: scePadResetOrientation\n");
    int32_t r=pad_ok_handle(handle);
    if (!r) { pthread_mutex_lock(&lock); motion_reset(); pthread_mutex_unlock(&lock); }
    return r;
}

static ABI int32_t pad_light_bar(int32_t handle, const uint8_t *rgb) {
    if (handle!=PAD_HANDLE || !opened) return ERR_INVALID_HANDLE;
    (void)rgb; return 0;
}
/* scePadGetHandle: the handle scePadOpen returned for this user's standard port. */
static ABI int32_t pad_get_handle(int32_t user, int32_t type, int32_t index) {
    if (!initialized) return ERR_NOT_INITIALIZED;
    if (user!=1 || (type!=0 && type!=2) || index) return ERR_INVALID_ARG;
    return opened ? PAD_HANDLE : (int32_t)0x80920008; /* SCE_PAD_ERROR_NO_HANDLE */
}
static const RuntimeExport exports[]={
    {"scePadGetHandle",pad_get_handle},
    {"scePadSetLightBar",pad_light_bar}, {"scePadResetLightBar",pad_ok_handle},
    {"scePadInit",pad_init}, {"scePadOpen",pad_open}, {"scePadClose",pad_close},
    {"scePadReadState",pad_read_state}, {"scePadRead",pad_read},
    {"scePadGetControllerInformation",pad_info}, {"scePadSetVibration",pad_vibration},
    {"scePadResetOrientation",pad_reset_orientation},
    {"scePadSetAngularVelocityDeadbandState",pad_deadband_state}, {"scePadSetTiltCorrectionState",pad_tilt_correction_state},
    {"scePadSetMotionSensorState",pad_ok_handle_flag},
};
uintptr_t runtime_pad_resolve(const char *name) { return RUNTIME_LOOKUP(exports,name); }
void runtime_pad_report(void) { printf("Runtime: pad reads=%zu, gamepad=%s\n",reads,gamepad ? SDL_GetGamepadName(gamepad) : "none"); }
