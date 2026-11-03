/* Mouse look straight into the game's cameras (included by runtime_pad.c).
 *
 * The right stick does not turn Gravity Rush's cameras by its position, and through the mouse
 * that lagged, kept turning after the mouse stopped and capped fast moves:
 *  - on the ground the PlayerCamera (eboot 0x98b90) takes the stick as an acceleration: its turning
 *    speed (+0x224 yaw, from the stick's x; +0x220 pitch) follows with inertia and a cap
 *    (0x98f36-0x98f88: speed = speed * decay(dt) + stick * accel * dt, clamped);
 *  - floating (gravity shift) the gravity camera (0x926b0) turns by stick x gain x frame time each
 *    frame, the gain ramping up while the stick is held (0x929b3-0x92a7d).
 * Here the mouse drives them instead. Each camera's code jumps to a cave that, while the mouse
 * moves, puts the mouse's values in place of the stick's: on the ground the two turning speeds
 * (at 0x98f88, the store of the yaw speed, after both are computed), floating the two turning
 * speeds before the frame time (at 0x92d38: the frame's angles and the rotation's size both
 * come from them). The view then turns by the
 * mouse's own counts (its DPI), at once, at any frame rate. A moment after the mouse stops the
 * stick drives the camera again. The caves count their runs: the mouse goes to the camera in use,
 * and to the right stick when neither runs (cut-scenes, other cameras).
 *
 * GOW3_MOUSE_TEST_FILE=<file> holding "x y [gravity]": those values are forced (calibration). */
#ifdef _WIN32
#include <windows.h>

typedef struct { float x, y; int active; unsigned runs; } MouseCamera;
static MouseCamera *mouse_ground, *mouse_gravity; /* in the caves' page; read by the game */
static bool mouse_camera_forced;                   /* GOW3_MOUSE_TEST_FILE holds values */

/* The camera's units, measured (the game multiplies by its frame time, so 60 and 120 FPS alike).
 * Ground: yaw 1.0 = 150 degrees/s (positive turns right), pitch 1.0 = about 113 degrees/s
 * (positive looks down); the stick at full tilt turns 207 degrees/s across. Floating the turn
 * grows with the cube of the speeds (the game scales the frame's angles by 0.03 x (x^2 + y^2)):
 * |turn| = 103.5 degrees/s x |speed|^3 (0.3 -> 2.8, 0.6 -> 22.5, 1.0 -> 103.2 measured), positive
 * x turns left and positive y looks up; the stick at full tilt turns 145 degrees/s. */
#define MOUSE_YAW_DEG_PER_UNIT 150.0f
#define MOUSE_PITCH_DEG_PER_UNIT 113.0f
#define MOUSE_GRAVITY_DEG_AT_ONE 103.5f

#define MOUSE_GROUND_SITE 0x98f88
#define MOUSE_GRAVITY_SITE 0x92d38
static const unsigned char mouse_ground_original[9]={0xc4,0xc1,0x7a,0x11,0x9d,0x24,0x02,0x00,0x00};
/* vmulss xmm2, xmm0, xmm4; vmulss xmm3, xmm1, xmm4 (y and x speed x frame time x 30) */
static const unsigned char mouse_gravity_original[8]={0xc5,0xfa,0x59,0xd4,0xc5,0xf2,0x59,0xdc};

/* A page within a rel32 jump of the game's code: the first free region Windows reports in the
 * 2 GB around it (the runtime reserves much of the space just below the image). */
static unsigned char *mouse_cave_page(unsigned char *code) {
    const uintptr_t low=(uintptr_t)code>0x7fff0000u ? (uintptr_t)code-0x7fff0000u : 0x10000;
    const uintptr_t high=(uintptr_t)code+0x7fff0000u;
    MEMORY_BASIC_INFORMATION mi;
    for (uintptr_t at=low; at<high && VirtualQuery((void *)at,&mi,sizeof(mi)); at=(uintptr_t)mi.BaseAddress+mi.RegionSize) {
        if (mi.State!=MEM_FREE || mi.RegionSize<0x20000) continue;
        const uintptr_t try_at=((uintptr_t)mi.BaseAddress+0xffff) & ~(uintptr_t)0xffff;
        if (try_at+0x1000>(uintptr_t)mi.BaseAddress+mi.RegionSize) continue;
        unsigned char *page=VirtualAlloc((void *)try_at,0x1000,MEM_RESERVE|MEM_COMMIT,PAGE_EXECUTE_READWRITE);
        if (page) return page;
    }
    return NULL;
}

/* Writes a jump at `site` (over `length` bytes) to `cave`. */
static bool mouse_cave_jump(unsigned char *site, size_t length, unsigned char *cave) {
    DWORD old;
    if (!VirtualProtect(site,length,PAGE_EXECUTE_READWRITE,&old)) return false;
    const int32_t to=(int32_t)(cave-(site+5));
    site[0]=0xe9;
    memcpy(site+1,&to,4);
    memset(site+5,0x90,length-5);
    VirtualProtect(site,length,old,&old);
    FlushInstructionCache(GetCurrentProcess(),site,length);
    return true;
}

/* A cave's start: rax = its data, one more run counted, and the jump past the mouse's part when
 * the mouse is not active (`skip` bytes on). */
static unsigned char *mouse_cave_head(unsigned char *p, MouseCamera *data, unsigned char skip) {
    const uint64_t address=(uint64_t)(uintptr_t)data;
    *p++=0x48; *p++=0xb8; memcpy(p,&address,8); p+=8;        /* movabs rax, data */
    *p++=0xf0; *p++=0xff; *p++=0x40; *p++=0x0c;              /* lock inc dword [rax+12] (runs) */
    *p++=0x83; *p++=0x78; *p++=0x08; *p++=0x00;              /* cmp dword [rax+8], 0 */
    *p++=0x74; *p++=skip;                                    /* je the original code */
    return p;
}

static unsigned char *mouse_cave_tail(unsigned char *p, const unsigned char *original, size_t length,
                                      unsigned char *back) {
    memcpy(p,original,length); p+=length;
    const int32_t to=(int32_t)(back-(p+5));
    *p++=0xe9; memcpy(p,&to,4); p+=4;                        /* jmp back after the site */
    return p;
}

/* Installs the caves once; false where the game's code differs (another eboot build). */
static bool mouse_camera_install(void) {
    static int state; /* 0 not tried, 1 ready, -1 failed */
    if (state) return state>0;
    state=-1;
    unsigned char *base=runtime_image_base();
    if (!base) return false;
    unsigned char *ground=base+MOUSE_GROUND_SITE, *gravity=base+MOUSE_GRAVITY_SITE;
    if (memcmp(ground,mouse_ground_original,sizeof(mouse_ground_original)) ||
        memcmp(gravity,mouse_gravity_original,sizeof(mouse_gravity_original))) {
        printf("Runtime: mouse camera: the game's camera code differs, the mouse moves the stick\n");
        return false;
    }
    unsigned char *page=mouse_cave_page(ground);
    if (!page || llabs((long long)(page-(ground+5)))>0x7fff0000LL || llabs((long long)(page-(gravity+5)))>0x7fff0000LL) {
        printf("Runtime: mouse camera: no memory near the game's code\n");
        return false;
    }
    mouse_ground=(MouseCamera *)(page+0x800);
    mouse_gravity=(MouseCamera *)(page+0x820);
    /* Ground: the mouse's speeds replace the computed ones (xmm5 pitch at +0x220, xmm3 yaw). */
    unsigned char *p=page;
    p=mouse_cave_head(p,mouse_ground,18);
    *p++=0xc5; *p++=0xfa; *p++=0x10; *p++=0x68; *p++=0x04;   /* vmovss xmm5, [rax+4] (pitch) */
    static const unsigned char store_pitch[9]={0xc4,0xc1,0x7a,0x11,0xad,0x20,0x02,0x00,0x00};
    memcpy(p,store_pitch,9); p+=9;                           /* vmovss [r13+0x220], xmm5 */
    *p++=0xc5; *p++=0xfa; *p++=0x10; *p++=0x18;              /* vmovss xmm3, [rax] (yaw) */
    p=mouse_cave_tail(p,mouse_ground_original,sizeof(mouse_ground_original),ground+9);
    /* Floating: the mouse's speeds replace the stick's (xmm1 x, xmm0 y, signs applied). */
    unsigned char *gravity_cave=page+0x100;
    p=gravity_cave;
    p=mouse_cave_head(p,mouse_gravity,9);
    *p++=0xc5; *p++=0xfa; *p++=0x10; *p++=0x08;              /* vmovss xmm1, [rax] (x) */
    *p++=0xc5; *p++=0xfa; *p++=0x10; *p++=0x40; *p++=0x04;   /* vmovss xmm0, [rax+4] (y) */
    p=mouse_cave_tail(p,mouse_gravity_original,sizeof(mouse_gravity_original),gravity+8);
    if (!mouse_cave_jump(ground,9,page) || !mouse_cave_jump(gravity,8,gravity_cave)) return false;
    printf("Runtime: mouse camera: the mouse turns the game's cameras (caves at %p)\n",(void *)page);
    state=1;
    return true;
}

static bool mouse_camera_drive(long long dx256, long long dy256, bool invert);

/* Calibration: GOW3_MOUSE_TEST_FILE forces the values it holds ("x y" on the ground camera,
 * "x y 1" on the gravity camera; empty releases), and logs how often each camera ran. */
static bool mouse_camera_test(void) {
    static const char *file=(const char *)1;
    static uint64_t next, next_log;
    static unsigned ground_runs, gravity_runs;
    if (file==(const char *)1) file=getenv("GOW3_MOUSE_TEST_FILE");
    if (!file || !mouse_camera_install()) return false;
    const uint64_t now=now_us();
    if (now>=next_log) {
        const unsigned g=__atomic_load_n(&mouse_ground->runs,__ATOMIC_RELAXED);
        const unsigned v=__atomic_load_n(&mouse_gravity->runs,__ATOMIC_RELAXED);
        if (next_log) printf("Mouse camera: ground %u gravity %u runs/s\n",g-ground_runs,v-gravity_runs);
        ground_runs=g; gravity_runs=v;
        next_log=now+1000000;
    }
    /* "m <counts/s x> <counts/s y>": a simulated mouse, through the same path as the real one. */
    static float mouse_x, mouse_y;
    static bool simulated;
    static uint64_t simulated_at;
    if (simulated) {
        const float seconds=simulated_at ? (float)(now-simulated_at)*1e-6f : 0.0f;
        simulated_at=now;
        mouse_camera_drive((long long)(mouse_x*seconds*256.0f),(long long)(mouse_y*seconds*256.0f),false);
    }
    if (now<next) return mouse_camera_forced;
    next=now+200000;
    float x=0, y=0;
    int which=0;
    char kind=0;
    FILE *f=fopen(file,"r");
    if (f && fscanf(f," %c",&kind)==1 && kind=='m') {
        simulated=fscanf(f,"%f %f",&mouse_x,&mouse_y)==2;
        fclose(f);
        if (!simulated) simulated_at=0;
        mouse_camera_forced=simulated; /* the free cursor does not release it */
        return simulated;
    }
    if (f) { rewind(f); }
    simulated=false;
    simulated_at=0;
    const int fields=f ? fscanf(f,"%f %f %d",&x,&y,&which) : 0;
    if (f) fclose(f);
    mouse_camera_forced=fields>=2;
    MouseCamera *on=which ? mouse_gravity : mouse_ground, *off=which ? mouse_ground : mouse_gravity;
    on->x=x; on->y=y;
    __atomic_store_n(&on->active,mouse_camera_forced ? 1 : 0,__ATOMIC_RELEASE);
    __atomic_store_n(&off->active,0,__ATOMIC_RELEASE);
    return mouse_camera_forced;
}

/* Whether a camera ran in the last 100 ms (its cave's run counter moved). */
static bool mouse_camera_running(MouseCamera *camera, unsigned *seen, uint64_t *seen_at, uint64_t now) {
    const unsigned runs=__atomic_load_n(&camera->runs,__ATOMIC_RELAXED);
    if (runs!=*seen) { *seen=runs; *seen_at=now; }
    return now-*seen_at<100000;
}

/* The mouse's counts since the last call -> the camera in use: every count turns the view by
 * MOUSE_DEG_PER_COUNT degrees (GOW3_MOUSE_DEG overrides), whatever the frame rate, so the mouse's
 * DPI set how far it turns. False when no camera of ours runs (the mouse then moves the stick). */
static bool mouse_camera_drive(long long dx256, long long dy256, bool invert) {
    if (!mouse_camera_install()) return false;
    static unsigned ground_seen, gravity_seen;
    static uint64_t ground_at, gravity_at, last, moved;
    static long long acc_x, acc_y;
    static float degrees=-1.0f;
    if (degrees<0) {
        const char *e=getenv("GOW3_MOUSE_DEG");
        degrees=e && atof(e)>0 ? (float)atof(e) : MOUSE_DEG_PER_COUNT;
    }
    const uint64_t now=now_us();
    const bool ground=mouse_camera_running(mouse_ground,&ground_seen,&ground_at,now);
    const bool gravity=!ground && mouse_camera_running(mouse_gravity,&gravity_seen,&gravity_at,now);
    MouseCamera *on=ground ? mouse_ground : gravity ? mouse_gravity : NULL;
    if (!ground) __atomic_store_n(&mouse_ground->active,0,__ATOMIC_RELEASE);
    if (!gravity) __atomic_store_n(&mouse_gravity->active,0,__ATOMIC_RELEASE);
    if (!on) return false;
    acc_x+=dx256; acc_y+=dy256;
    if (!last) last=now;
    if (now-last<4000) return true; /* read twice in a frame: keep this frame's values */
    const float seconds=(float)(now-last)*1e-6f;
    if (acc_x || acc_y) moved=now;
    const float x=(float)acc_x/256.0f/seconds*degrees, y=(float)acc_y/256.0f/seconds*degrees*(invert ? -1.0f : 1.0f);
    if (ground) {
        on->x=x/MOUSE_YAW_DEG_PER_UNIT;
        on->y=y/MOUSE_PITCH_DEG_PER_UNIT;
    } else {
        /* The cube root of the wanted turn, in its direction (mouse right turns right, down looks
         * down: both opposite to the gravity camera's signs). */
        const float turn=sqrtf(x*x+y*y);
        const float size=turn>0 ? cbrtf(turn/MOUSE_GRAVITY_DEG_AT_ONE)/turn : 0.0f;
        on->x=-x*size;
        on->y=-y*size;
    }
    __atomic_store_n(&on->active,now-moved<120000 ? 1 : 0,__ATOMIC_RELEASE);
    acc_x=acc_y=0;
    last=now;
    return true;
}

static void mouse_camera_release(void) {
    if (!mouse_ground || mouse_camera_forced) return;
    __atomic_store_n(&mouse_ground->active,0,__ATOMIC_RELEASE);
    __atomic_store_n(&mouse_gravity->active,0,__ATOMIC_RELEASE);
}
#else
static bool mouse_camera_test(void) { return false; }
static bool mouse_camera_drive(long long dx256, long long dy256, bool invert) { (void)dx256; (void)dy256; (void)invert; return false; }
static void mouse_camera_release(void) {}
#endif
