/* System functions added for Gravity Rush Remastered (CUSA01113) and Unreal Engine 4 games, with the same offline,
 * single-user contracts as runtime_services.c:
 *   - kernel event flags (full implementation), small kernel/libc queries;
 *   - POSIX names for rwlocks and scheduling;
 *   - sockets unavailable (network unplugged);
 *   - NGS2 renders silence (no voices play yet);
 *   - Json2 parsing fails cleanly (callers fall back to defaults).
 * Every entry is an explicit contract; unknown functions still stop. */
#define _GNU_SOURCE
#define _CRT_RAND_S /* rand_s */
#include "runtime.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <errno.h>
#include <time.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <unistd.h>
#include <sys/syscall.h>
#include <sys/stat.h>
#endif

#define ERR(n) ((int32_t)(UINT32_C(0x80020000)|(n)))
#define E_SRCH 3
#define E_BADF 9
#define E_NOMEM 12
#define E_BUSY 16
#define E_INVAL 22
#define E_NETDOWN 50
#define E_TIMEDOUT 60
#define E_CANCELED 85

/* ---- Event flags ---- */
#define EF_MAGIC 0x45464c47u
#define EF_ATTR_MULTI 0x20
#define EF_WAIT_AND 0x01
#define EF_WAIT_OR 0x02
#define EF_CLEAR_ALL 0x10
#define EF_CLEAR_PAT 0x20
typedef struct EventFlag {
    uint32_t magic, attr;
    uint64_t bits;
    unsigned waiters;
    uint64_t generation; /* bumped by cancel/delete so waiters can tell */
    int deleted;
    pthread_mutex_t lock;
    pthread_cond_t cond;
    char name[32];
} EventFlag;
static size_t flags_created;

static EventFlag *flag(void *handle) {
    EventFlag *f=handle;
    return f && f->magic==EF_MAGIC && !f->deleted ? f : NULL;
}
static ABI int32_t ef_create(EventFlag **out, const char *name, uint32_t attr, uint64_t init, const void *param) {
    (void)param;
    if (!out) return ERR(E_INVAL);
    EventFlag *f=calloc(1,sizeof(*f));
    if (!f) return ERR(E_NOMEM);
    f->magic=EF_MAGIC; f->attr=attr; f->bits=init;
    pthread_mutex_init(&f->lock,NULL); pthread_cond_init(&f->cond,NULL);
    if (name) snprintf(f->name,sizeof(f->name),"%s",name);
    *out=f; ++flags_created;
    return 0;
}
static ABI int32_t ef_delete(EventFlag *handle) {
    EventFlag *f=flag(handle);
    if (!f) return ERR(E_SRCH);
    pthread_mutex_lock(&f->lock);
    f->deleted=1; ++f->generation;
    pthread_cond_broadcast(&f->cond);
    pthread_mutex_unlock(&f->lock);
    /* Freed lazily: a waiter may still hold the lock; the leak is bounded by deletions. */
    return 0;
}
static ABI int32_t ef_set(EventFlag *handle, uint64_t bits) {
    EventFlag *f=flag(handle);
    if (!f) return ERR(E_SRCH);
    pthread_mutex_lock(&f->lock);
    f->bits|=bits;
    pthread_cond_broadcast(&f->cond);
    pthread_mutex_unlock(&f->lock);
    return 0;
}
static ABI int32_t ef_clear(EventFlag *handle, uint64_t bits) {
    EventFlag *f=flag(handle);
    if (!f) return ERR(E_SRCH);
    pthread_mutex_lock(&f->lock);
    f->bits&=bits; /* PS4 contract: the argument is the mask of bits to keep */
    pthread_mutex_unlock(&f->lock);
    return 0;
}
static int ef_match(EventFlag *f, uint64_t bits, uint32_t mode) {
    return (mode & EF_WAIT_AND) ? (f->bits & bits)==bits : (f->bits & bits)!=0;
}
static void ef_consume(EventFlag *f, uint64_t bits, uint32_t mode, uint64_t *result) {
    if (result) *result=f->bits;
    if (mode & EF_CLEAR_ALL) f->bits=0;
    else if (mode & EF_CLEAR_PAT) f->bits&=~bits;
}
static int ef_valid_mode(uint32_t mode) {
    uint32_t wait=mode & 3, clear=mode & 0x30;
    return (wait==EF_WAIT_AND || wait==EF_WAIT_OR) && clear!=0x30 && !(mode & ~0x33u);
}
static ABI int32_t ef_poll(EventFlag *handle, uint64_t bits, uint32_t mode, uint64_t *result) {
    EventFlag *f=flag(handle);
    if (!f) return ERR(E_SRCH);
    if (!bits || !ef_valid_mode(mode)) return ERR(E_INVAL);
    pthread_mutex_lock(&f->lock);
    int32_t r=0;
    if (!(f->attr & EF_ATTR_MULTI) && f->waiters) r=ERR(1); /* EPERM: single-waiter flag in use */
    else if (ef_match(f,bits,mode)) ef_consume(f,bits,mode,result);
    else { if (result) *result=f->bits; r=ERR(E_BUSY); }
    pthread_mutex_unlock(&f->lock);
    return r;
}
static ABI int32_t ef_wait(EventFlag *handle, uint64_t bits, uint32_t mode, uint64_t *result, uint32_t *timeout_us) {
    EventFlag *f=flag(handle);
    if (!f) return ERR(E_SRCH);
    if (!bits || !ef_valid_mode(mode)) return ERR(E_INVAL);
    pthread_mutex_lock(&f->lock);
    if (!(f->attr & EF_ATTR_MULTI) && f->waiters) { pthread_mutex_unlock(&f->lock); return ERR(1); }
    struct timespec deadline;
    if (timeout_us) {
        clock_gettime(CLOCK_REALTIME,&deadline);
        uint64_t ns=(uint64_t)deadline.tv_nsec+(uint64_t)*timeout_us*1000u;
        deadline.tv_sec+=(time_t)(ns/1000000000u); deadline.tv_nsec=(long)(ns%1000000000u);
    }
    uint64_t generation=f->generation;
    int32_t r=0;
    ++f->waiters;
    while (!ef_match(f,bits,mode)) {
        if (f->generation!=generation) { r=f->deleted ? ERR(E_SRCH) : ERR(E_CANCELED); break; }
        if (timeout_us) {
            if (pthread_cond_timedwait(&f->cond,&f->lock,&deadline)==ETIMEDOUT && !ef_match(f,bits,mode)) {
                r=ERR(E_TIMEDOUT); *timeout_us=0; break;
            }
        } else pthread_cond_wait(&f->cond,&f->lock);
    }
    --f->waiters;
    if (!r) ef_consume(f,bits,mode,result);
    else if (result) *result=f->bits;
    pthread_mutex_unlock(&f->lock);
    return r;
}
static ABI int32_t ef_cancel(EventFlag *handle, uint64_t bits, int32_t *waiters) {
    EventFlag *f=flag(handle);
    if (!f) return ERR(E_SRCH);
    pthread_mutex_lock(&f->lock);
    if (waiters) *waiters=(int32_t)f->waiters;
    f->bits=bits; ++f->generation;
    pthread_cond_broadcast(&f->cond);
    pthread_mutex_unlock(&f->lock);
    return 0;
}

/* ---- Small kernel and libc queries ---- */
/* Base PS4, or PS4 Pro with GOW3_NEO=1 (games then pick their Pro render path and resolution). */
static ABI int32_t is_neo_mode(void) {
    static int neo=-1;
    if (neo<0) { const char *v=getenv("GOW3_NEO"); neo=v && *v=='1'; if (neo) puts("Runtime: reporting a PS4 Pro (Neo mode)"); }
    return neo;
}
static ABI int32_t get_cpumode(void) { return 0; }        /* SCE_KERNEL_CPUMODE_6CPU */
static ABI int32_t thread_id(void) {
#ifdef _WIN32
    return (int32_t)GetCurrentThreadId();
#else
    return (int32_t)syscall(SYS_gettid);
#endif
}
static ABI int32_t thread_name(void *thread, char *name) {
    if (!name) return ERR(E_INVAL);
    const char *n=runtime_thread_name(thread);
    if (!n) return ERR(E_SRCH);
    snprintf(name,32,"%s",n);
    return 0;
}
static ABI int32_t ok_noop(void) { return 0; }
static ABI void *null_pointer(void) { return NULL; }
static ABI int32_t not_found(void) { return ERR(E_SRCH); }
static ABI int32_t kernel_chmod(const char *path, uint16_t mode) { (void)path; (void)mode; return 0; }
static ABI int32_t kernel_utimes(const char *path, const void *times) { (void)path; (void)times; return 0; }
static ABI int32_t kernel_getdents(int fd, char *buffer, uint64_t size) {
    int64_t r=runtime_file_getdents(fd,buffer,size,NULL);
    return r<0 ? ERR(runtime_guest_errno((int)-r)) : (int32_t)r;
}
static ABI int32_t prt_aperture(int index, void **address, uint64_t *size) {
    if (index<0 || index>2 || !address || !size) return ERR(E_INVAL);
    *address=NULL; *size=0;
    return 0;
}
static ABI int32_t kernel_nanosleep(const struct timespec *request, struct timespec *remain) {
    if (!request) return ERR(E_INVAL);
    compat_sleep_ns((uint64_t)request->tv_sec*1000000000u+(uint64_t)request->tv_nsec);
    if (remain) remain->tv_sec=remain->tv_nsec=0;
    return 0;
}
/* sceKernelConvert{Localtime,Utc}...(time_t, ..., SceKernelTimezone*, int *dst) */
typedef struct { int32_t minuteswest, dsttime; } GuestTimezone;
static int32_t host_offset_seconds(time_t t, int *dst) {
    struct tm local, utc;
#ifdef _WIN32
    localtime_s(&local,&t); gmtime_s(&utc,&t);
#else
    localtime_r(&t,&local); gmtime_r(&t,&utc);
#endif
    if (dst) *dst=local.tm_isdst>0;
    utc.tm_isdst=local.tm_isdst;
    return (int32_t)difftime(mktime(&local),mktime(&utc));
}
static ABI int32_t local_to_utc(int64_t local, uint64_t unused, int64_t *utc, GuestTimezone *tz, int32_t *dst) {
    (void)unused;
    if (!utc) return ERR(E_INVAL);
    int d=0; int32_t off=host_offset_seconds((time_t)local,&d);
    *utc=local-off;
    if (tz) { tz->minuteswest=-off/60; tz->dsttime=d; }
    if (dst) *dst=d ? 3600 : 0;
    return 0;
}
static ABI int32_t utc_to_local(int64_t utc, int64_t *local, GuestTimezone *tz, int32_t *dst) {
    if (!local) return ERR(E_INVAL);
    int d=0; int32_t off=host_offset_seconds((time_t)utc,&d);
    *local=utc+off;
    if (tz) { tz->minuteswest=-off/60; tz->dsttime=d; }
    if (dst) *dst=d ? 3600 : 0;
    return 0;
}
static ABI uint64_t available_flexible(uint64_t *out) {
    if (!out) return (uint64_t)ERR(E_INVAL);
    *out=runtime_memory_flexible_available();
    return 0;
}
static ABI int32_t random_number(void *buffer, uint64_t size) {
    if (!buffer || size>64) return (int32_t)0x817C0016; /* SCE_RANDOM_ERROR_INVALID */
    unsigned char *p=buffer;
    for (uint64_t i=0;i<size;++i) {
#ifdef _WIN32
        unsigned v; rand_s(&v); p[i]=(unsigned char)v;
#else
        p[i]=(unsigned char)random();
#endif
    }
    return 0;
}

/* ---- POSIX rwlocks and scheduling (errno results, not SCE codes) ---- */
typedef int32_t (ABI *RwInit)(void **, void *const *, const char *);
typedef int32_t (ABI *RwOne)(void **);
static int32_t posix_code(int32_t r) { return r ? (int32_t)((uint32_t)r & 0xffff) : 0; }
static ABI int32_t posix_rw_init(void **rw, void *const *attr) {
    return posix_code(((RwInit)runtime_rwlock_resolve("6ULAa0fq4jA#libkernel"))(rw,attr,NULL));
}
#define POSIX_RW(name,nid) static ABI int32_t posix_rw_##name(void **rw) { \
    return posix_code(((RwOne)runtime_rwlock_resolve(nid))(rw)); }
POSIX_RW(destroy,"BB+kb08Tl9A#libkernel")
POSIX_RW(rdlock,"Ox9i0c7L5w0#libkernel")
POSIX_RW(wrlock,"mqdNorrB+gI#libkernel")
POSIX_RW(unlock,"+L98PIbGttk#libkernel")
typedef struct { int32_t priority; } GuestSchedParam;
static ABI int32_t posix_getschedparam(void *thread, int32_t *policy, GuestSchedParam *param) {
    (void)thread;
    if (policy) *policy=1; /* SCHED_FIFO, as the PS4 default */
    if (param) param->priority=700;
    return 0;
}
static ABI int32_t posix_setschedparam(void *thread, int32_t policy, const GuestSchedParam *param) {
    (void)thread; (void)policy; (void)param; return 0; /* host scheduler decides */
}
static ABI int32_t sched_max(int32_t policy) { (void)policy; return 767; }
static ABI int32_t sched_min(int32_t policy) { (void)policy; return 256; }
static ABI int32_t mutexattr_setprotocol(void *attr, int32_t protocol) { (void)attr; (void)protocol; return 0; }

/* ---- Sockets: network cable unplugged ---- */
static ABI int32_t socket_none(void) { *runtime_errno()=E_NETDOWN; return -1; }
static ABI int32_t socket_badf(void) { *runtime_errno()=E_BADF; return -1; }

/* ---- Coredump, PlayGo, AppContent ---- */
static ABI int32_t playgo_eta(int32_t handle, const uint16_t *chunks, uint32_t count, int64_t *eta) {
    (void)handle; (void)chunks; (void)count;
    if (!eta) return (int32_t)0x80B2000A;
    *eta=0; return 0;
}
static ABI int32_t playgo_todo(int32_t handle, void *list, uint32_t count, uint32_t *entries) {
    (void)handle; (void)list; (void)count;
    if (!entries) return (int32_t)0x80B2000A;
    *entries=0; return 0; /* whole package installed */
}
typedef struct { char data[16]; } MountPoint;
static ABI int32_t temp_mount2(uint32_t option, MountPoint *mount) {
    (void)option;
    if (!mount) return (int32_t)0x80D90002; /* SCE_APP_CONTENT_ERROR_PARAMETER */
    char host[1024];
    snprintf(host,sizeof(host),"%s/temp0",runtime_file_user_dir());
    mkdir(host,0755);
    if (runtime_file_mount("/temp0",host)) return (int32_t)0x80D90007; /* BUSY */
    memset(mount,0,sizeof(*mount));
    strcpy(mount->data,"/temp0");
    printf("Runtime: temporary data mounted at /temp0 -> %s\n",host);
    return 0;
}

/* ---- NGS2: silent renderer. Handles are distinct non-null tokens; voices never play. ---- */
static uintptr_t ngs2_next=0x1000;
static pthread_mutex_t ngs2_lock=PTHREAD_MUTEX_INITIALIZER;
static size_t ngs2_renders;
static uintptr_t ngs2_token(void) {
    pthread_mutex_lock(&ngs2_lock);
    uintptr_t t=(ngs2_next+=0x10);
    pthread_mutex_unlock(&ngs2_lock);
    return t;
}
static ABI int32_t ngs2_system_create(const void *option, const void *allocator, uintptr_t *out) {
    (void)option; (void)allocator;
    if (!out) return (int32_t)0x804A0003;
    *out=ngs2_token();
    puts("Runtime: NGS2 system created (silent renderer)");
    return 0;
}
/* Call counts (printed with the F12 thread dump) and, with GOW3_AUDIO_TRACE=1, the first voice
 * commands, to see what the game waits for while no sound plays. */
static long ngs2_n_state, ngs2_n_flags, ngs2_n_control;
static int ngs2_trace_left(void) {
    static int left=-1;
    if (left<0) { const char *e=getenv("GOW3_AUDIO_TRACE"); left=e && e[0]=='1' ? 3000 : 0; }
    return left>0 ? left-- : 0;
}
void runtime_ngs2_report(void) {
    printf("NGS2 calls so far: VoiceGetState=%ld VoiceGetStateFlags=%ld VoiceControl=%ld SystemRender=%zu\n",
           __atomic_load_n(&ngs2_n_state,__ATOMIC_RELAXED),__atomic_load_n(&ngs2_n_flags,__ATOMIC_RELAXED),
           __atomic_load_n(&ngs2_n_control,__ATOMIC_RELAXED),ngs2_renders);
}
static ABI int32_t ngs2_rack_create(uintptr_t system, uint32_t rack, const void *option, const void *allocator, uintptr_t *out) {
    (void)system; (void)option; (void)allocator;
    if (!out) return (int32_t)0x804A0003;
    *out=ngs2_token();
    if (ngs2_trace_left()) printf("Runtime: NGS2 rack id 0x%x -> 0x%llx\n",rack,(unsigned long long)*out);
    return 0;
}
typedef struct { uint16_t size; int16_t next; uint32_t id; } Ngs2ParamHeader;
#include "gr_ngs2_voice.inc"
static ABI int32_t ngs2_voice_control(uintptr_t voice, const Ngs2ParamHeader *param) {
    __atomic_add_fetch(&ngs2_n_control,1,__ATOMIC_RELAXED);
    int trace=param && ngs2_trace_left();
    gr_voice_control(voice,param,trace);
    if (trace) {
        char line[512];
        int n=snprintf(line,sizeof(line),"Runtime: NGS2 VoiceControl 0x%llx:",(unsigned long long)voice);
        /* Room for one more param (up to ~80 characters); snprintf's return can pass the end. */
        for (int i=0;param && i<16 && n>=0 && n<(int)sizeof(line)-96;++i) {
            n+=snprintf(line+n,sizeof(line)-n," [id 0x%x size %u",param->id,param->size);
            if (param->size>=12) n+=snprintf(line+n,sizeof(line)-n," v 0x%x",((const uint32_t *)param)[2]);
            if (param->size>=16) {
                float f; memcpy(&f,(const uint32_t *)param+3,4);
                n+=snprintf(line+n,sizeof(line)-n," w 0x%x (%g)",((const uint32_t *)param)[3],(double)f);
            }
            n+=snprintf(line+n,sizeof(line)-n,"]");
            param=param->next ? (const Ngs2ParamHeader *)((const char *)param+param->next) : NULL;
        }
        puts(line);
    }
    return 0;
}
static ABI int32_t ngs2_voice_handle(uintptr_t rack, uint32_t index, uintptr_t *out) {
    if (!out) return (int32_t)0x804A0003;
    *out=rack+0x100000+(uintptr_t)index*0x10; return 0;
}
static ABI int32_t ngs2_voice_state(uintptr_t voice, void *state, uint64_t size) {
    __atomic_add_fetch(&ngs2_n_state,1,__ATOMIC_RELAXED);
    gr_voice_state(voice,state,size);
    return 0;
}
static ABI int32_t ngs2_voice_flags(uintptr_t voice, uint32_t *flags) {
    __atomic_add_fetch(&ngs2_n_flags,1,__ATOMIC_RELAXED);
    if (flags) *flags=gr_voice_flags(voice);
    return 0;
}
typedef struct { void *buffer; uint64_t size; uint32_t waveform, channels; } Ngs2RenderBuffer;
static ABI int32_t ngs2_render(uintptr_t system, Ngs2RenderBuffer *buffers, uint32_t count) {
    (void)system;
    uint32_t samples=256; /* default grain; the first buffer (float samples) tells the real one */
    for (uint32_t i=0;buffers && i<count;++i) if (buffers[i].buffer) {
        memset(buffers[i].buffer,0,buffers[i].size);
        if (i==0 && buffers[i].channels) samples=(uint32_t)(buffers[i].size/(4u*buffers[i].channels));
    }
    if (!ngs2_renders && count && buffers && ngs2_trace_left())
        printf("Runtime: NGS2 render buffers=%u first: size=%llu waveform=0x%x channels=%u\n",count,
               (unsigned long long)buffers[0].size,buffers[0].waveform,buffers[0].channels);
    gr_voice_render(count && buffers && buffers[0].buffer ? buffers[0].buffer : NULL,count && buffers ? buffers[0].channels : 0,samples);
    ++ngs2_renders;
    return 0;
}
static ABI int32_t ngs2_unsupported_waveform(void) { return (int32_t)0x804A0200; } /* invalid waveform */
/* GOW3_AUDIO_TRACE=1: the first waveforms the game asks NGS2 to parse (all reported as invalid). */
static ABI int32_t ngs2_parse_waveform(const unsigned char *data, uint64_t size, void *info) {
    static int left=-1;
    if (left<0) { const char *e=getenv("GOW3_AUDIO_TRACE"); left=e && e[0]=='1' ? 40 : 0; }
    if (left>0) {
        --left;
        printf("Runtime: NGS2 parse waveform %p size=%llu head=%02x%02x%02x%02x '%.4s' info=%p\n",(const void *)data,
               (unsigned long long)size,data ? data[0] : 0,data ? data[1] : 0,data ? data[2] : 0,data ? data[3] : 0,
               data ? (const char *)data : "",info);
        fflush(stdout);
    }
    return ngs2_unsupported_waveform();
}

/* ---- Json2 (C++ ABI, this in rdi). Parsing reports failure; values read as null/empty. ---- */
static unsigned char json_null[64];
static ABI void json_nothing(void *self) { (void)self; }
static ABI int32_t json_initialize(void *self, const void *param) { (void)self; (void)param; return 0; }
static ABI void json_notify_error(void *self, int32_t error, uint64_t size, void *user) {
    (void)self; (void)user;
    printf("Runtime: Json2 allocator error %d (size %llu)\n",error,(unsigned long long)size);
}
static ABI int32_t json_parse(void *self, void *value, const char *text, uint64_t size) {
    (void)self; (void)value;
    printf("Runtime: Json2 parse of %llu bytes not supported, reported as invalid\n",(unsigned long long)size);
    (void)text;
    return (int32_t)0x80920005; /* SCE_JSON_ERROR_PARSE_INVALID_CHAR */
}
static ABI uint64_t json_zero(void *self) { (void)self; return 0; }
static ABI void *json_null_value(void *self) { (void)self; return json_null; }
static ABI const char *json_c_str(void *self) { (void)self; return ""; }
static ABI int32_t json_empty(void *self) { (void)self; return 1; }
static ABI int32_t json_equals(void *self, const char *text) { (void)self; return text && !*text; }

/* ---- Console features with no PC counterpart: accepted and ignored ---- */
static ABI int32_t privacy_setting(int32_t type, int32_t *value) {
    (void)type;
    if (!value) return (int32_t)0x80A10003; /* SCE_SYSTEM_SERVICE_ERROR_PARAMETER */
    *value=0; return 0;
}

/* ---- Error dialog: logs the code the game wanted to show and finishes at once ---- */
static int32_t error_dialog_status=1; /* 1 INITIALIZED, 2 RUNNING, 3 FINISHED */
static ABI int32_t error_dialog_open(const int32_t *param) {
    if (!param) return (int32_t)0x80ED0003; /* SCE_ERROR_DIALOG_ERROR_PARAM_INVALID */
    printf("Runtime: error dialog requested for code 0x%08x (closed immediately)\n",(unsigned)param[1]);
    fflush(stdout);
    error_dialog_status=3;
    return 0;
}
static ABI int32_t error_dialog_status_get(void) { return error_dialog_status; }

/* ---- VoiceQoS (voice chat transport): endpoints exist, no packets ever arrive ---- */
static int32_t voice_next=1;
static ABI int32_t voiceqos_create(int32_t *out) {
    if (!out) return (int32_t)0x80A30002; /* SCE_VOICE_QOS_ERROR_INVALID_ARGUMENT */
    *out=__atomic_add_fetch(&voice_next,1,__ATOMIC_RELAXED);
    return 0;
}
static ABI int32_t voiceqos_get_attr(int32_t id, int32_t attr, void *value, int32_t size) {
    (void)id; (void)attr;
    if (value && size>0) memset(value,0,(size_t)size);
    return 0;
}
static ABI int32_t voiceqos_read(int32_t connection, void *data, uint32_t *size) {
    (void)connection; (void)data;
    if (size) *size=0;
    return 0;
}

/* ---- Dynamic modules: everything the game needs is linked up front ---- */
static ABI int32_t load_start_module(const char *path, uint64_t argc, const void *argv, uint32_t flags,
                                     const void *option, int32_t *result) {
    (void)argc; (void)argv; (void)flags; (void)option;
    printf("Runtime: sceKernelLoadStartModule(%s) -> not available\n",path ? path : "(null)");
    if (result) *result=0;
    return ERR(2); /* ENOENT */
}
static ABI int32_t posix_fcntl(int32_t fd, int32_t cmd, int64_t arg) {
    (void)fd; (void)arg;
    return cmd==1 || cmd==3 ? 0 : 0; /* F_GETFD/F_GETFL: no flags; set commands accepted */
}
static ABI int32_t posix_cancel(void *thread) { (void)thread; return E_SRCH; }

/* ---- HTTP extras: the network is unplugged ---- */
static ABI int32_t http_last_errno(int32_t request, int32_t *error) {
    (void)request;
    if (!error) return (int32_t)0x80431077;
    *error=65; /* EHOSTUNREACH */
    return 0;
}
static ABI int32_t http_network(void) { return (int32_t)0x80431063; } /* SCE_HTTP_ERROR_NETWORK */
static ABI int32_t http_bad_url(void) { return (int32_t)0x80431061; } /* SCE_HTTP_ERROR_INVALID_URL */

/* ---- Dialogs the offline console never shows: opening fails, status stays idle ---- */
static ABI int32_t dialog_unavailable(void) { return (int32_t)0x80B80001; } /* COMMON_DIALOG not available */
static ABI int32_t dialog_none(void) { return 0; }                           /* status NONE */

/* ---- Misc devices ---- */
static ABI int32_t net_mac(uint8_t *mac, int32_t flags) {
    (void)flags;
    if (!mac) return (int32_t)0x80410116;
    static const uint8_t fixed[6]={0x02,0x00,0x4d,0x45,0x44,0x49}; /* locally administered */
    memcpy(mac,fixed,6);
    return 0;
}
static ABI int32_t move_absent(void) { return (int32_t)0x80EE0002; }  /* SCE_MOVE_ERROR_NOT_INIT */
static ABI int32_t streaming_off(void) { return (int32_t)0x804E0002; } /* not streaming */
static ABI int32_t trophy_no_icon(void) { return (int32_t)0x80551616; } /* SCE_NP_TROPHY_ERROR_ICON_FILE_NOT_FOUND */
static ABI __attribute__((noreturn)) void load_exec(const char *path, const void *argv) {
    (void)argv;
    printf("Runtime: game asked to launch %s; exiting\n",path ? path : "(null)");
    fflush(NULL);
    _exit(0);
}

#include "gr_fiber.inc"
#include "gr_ngs2.inc"
static const RuntimeExport exports[]={
    {"sceKernelLoadStartModule",load_start_module}, {"sceKernelDlsym",not_found},
    {"fcntl",posix_fcntl}, {"pthread_cancel",posix_cancel},
    {"sceHttpGetLastErrno",http_last_errno}, {"sceHttpAbortRequest",ok_noop},
    {"sceHttpGetAllResponseHeaders",http_network}, {"sceHttpGetMemoryPoolStats",http_network},
    {"sceHttpUriParse",http_bad_url}, {"sceHttpUriBuild",http_bad_url}, {"sceHttpUriEscape",http_bad_url},
    {"sceWebBrowserDialogOpen",dialog_unavailable}, {"sceWebBrowserDialogOpenForPredeterminedContent",dialog_unavailable},
    {"sceWebBrowserDialogUpdateStatus",dialog_none}, {"sceWebBrowserDialogGetResult",dialog_unavailable},
    {"sceWebBrowserDialogClose",ok_noop}, {"sceWebBrowserDialogResetCookie",ok_noop},
    {"sceGameCustomDataDialogOpenA",dialog_unavailable}, {"sceGameCustomDataDialogUpdateStatus",dialog_none},
    {"sceGameCustomDataDialogGetResultA",dialog_unavailable},
    {"sceInvitationDialogOpenA",dialog_unavailable}, {"sceInvitationDialogUpdateStatus",dialog_none},
    {"sceInvitationDialogGetResultA",dialog_unavailable},
    {"sceSigninDialogOpen",dialog_unavailable}, {"sceSigninDialogUpdateStatus",dialog_none},
    {"sceSigninDialogGetResult",dialog_unavailable},
    {"sceNpSnsFacebookDialogOpen",dialog_unavailable}, {"sceNpSnsFacebookDialogUpdateStatus",dialog_none},
    {"sceNpSnsFacebookDialogGetResult",dialog_unavailable},
    {"sceNpProfileDialogOpenA",dialog_unavailable}, {"sceNpCommerceDialogGetResult",dialog_unavailable},
    {"sceImeDialogGetPanelSizeExtended",dialog_unavailable},
    {"sceNetGetMacAddress",net_mac}, {"sceNetGetSockInfo",socket_badf},
    {"sceMoveGetDeviceInfo",move_absent}, {"sceMoveSetVibration",move_absent},
    {"sceGameLiveStreamingGetCurrentStatus2",streaming_off}, {"sceGameLiveStreamingGetProgramInfo",streaming_off},
    {"sceNpTrophyShowTrophyList",ok_noop}, {"sceNpTrophyCaptureScreenshot",ok_noop},
    {"sceNpTrophyGetGameIcon",trophy_no_icon}, {"sceNpTrophyGetGroupIcon",trophy_no_icon},
    {"sceNpTrophyGetTrophyIcon",trophy_no_icon}, {"sceNpTrophyGetGroupInfo",trophy_no_icon},
    {"sceSystemServiceLoadExec",load_exec},
    {"sceVoiceQoSInit",ok_noop}, {"sceVoiceQoSEnd",ok_noop},
    {"sceVoiceQoSCreateLocalEndpoint",voiceqos_create}, {"sceVoiceQoSDeleteLocalEndpoint",ok_noop},
    {"sceVoiceQoSCreateRemoteEndpoint",voiceqos_create}, {"sceVoiceQoSDeleteRemoteEndpoint",ok_noop},
    {"sceVoiceQoSConnect",voiceqos_create}, {"sceVoiceQoSDisconnect",ok_noop},
    {"sceVoiceQoSGetLocalEndpointAttribute",voiceqos_get_attr}, {"sceVoiceQoSSetLocalEndpointAttribute",ok_noop},
    {"sceVoiceQoSReadPacket",voiceqos_read}, {"sceVoiceQoSWritePacket",ok_noop},
    {"sceScreenShotEnable",ok_noop}, {"sceScreenShotDisable",ok_noop},
    {"sceSharePlayInitialize",ok_noop}, {"sceSharePlaySetProhibition",ok_noop}, {"sceSharePlayTerminate",ok_noop},
    {"sceGameLiveStreamingInitialize",ok_noop}, {"sceGameLiveStreamingTerminate",ok_noop},
    {"sceGameLiveStreamingEnableLiveStreaming",ok_noop},
    {"sceNetCtlTerm",ok_noop}, {"sceNpCommerceShowPsStoreIcon",ok_noop}, {"sceNpCommerceHidePsStoreIcon",ok_noop},
    {"sceSystemServiceGetPlatformPrivacySetting",privacy_setting},
    {"sceContentExportInit",ok_noop}, {"sceContentExportTerm",ok_noop},
    {"sceErrorDialogInitialize",ok_noop}, {"sceErrorDialogTerminate",ok_noop},
    {"sceErrorDialogOpen",error_dialog_open}, {"sceErrorDialogUpdateStatus",error_dialog_status_get},
    {"sceWebBrowserDialogInitialize",ok_noop}, {"sceWebBrowserDialogTerminate",ok_noop},
    {"sceGameCustomDataDialogInitialize",ok_noop}, {"sceGameCustomDataDialogTerminate",ok_noop},
    {"sceInvitationDialogInitialize",ok_noop}, {"sceInvitationDialogTerminate",ok_noop},
    /* Video recording (share button clips): accepted, nothing is recorded (as in shadPS4). */
    {"sceVideoRecordingSetInfo",ok_noop}, {"sceVideoRecordingQueryMemSize2",ok_noop},
    {"sceVideoRecordingOpen2",ok_noop}, {"sceVideoRecordingStart",ok_noop}, {"sceVideoRecordingStop",ok_noop},
    {"sceVideoRecordingClose",ok_noop}, {"sceVideoRecordingGetStatus",ok_noop},
    {"sceKernelCreateEventFlag",ef_create}, {"sceKernelDeleteEventFlag",ef_delete},
    {"sceKernelSetEventFlag",ef_set}, {"sceKernelClearEventFlag",ef_clear},
    {"sceKernelPollEventFlag",ef_poll}, {"sceKernelWaitEventFlag",ef_wait},
    {"sceKernelCancelEventFlag",ef_cancel},
    {"sceKernelIsNeoMode",is_neo_mode}, {"sceKernelGetCpumode",get_cpumode},
    {"scePthreadGetthreadid",thread_id}, {"scePthreadGetname",thread_name},
    {"sceKernelChmod",kernel_chmod}, {"sceKernelUtimes",kernel_utimes}, {"sceKernelGetdents",kernel_getdents},
    {"sceKernelGetPrtAperture",prt_aperture}, {"_nanosleep",kernel_nanosleep},
    {"sceKernelConvertLocaltimeToUtc",local_to_utc}, {"sceKernelConvertUtcToLocaltime",utc_to_local},
    {"sceKernelAvailableFlexibleMemorySize",available_flexible},
    {"_sceKernelRtldThreadAtexitIncrement",ok_noop}, {"_sceKernelRtldThreadAtexitDecrement",ok_noop},
    {"_sceKernelSetThreadAtexitCount",ok_noop}, {"_sceKernelSetThreadAtexitReport",ok_noop},
    {"_sceKernelSetThreadDtors",ok_noop},
    {"sceKernelIsAddressSanitizerEnabled",ok_noop},
    {"sceKernelGetSanitizerMallocReplaceExternal",null_pointer},
    {"sceKernelGetSanitizerNewReplaceExternal",null_pointer},
    {"sceKernelGetModuleInfoForUnwind",not_found}, {"sceKernelInternalMemoryGetModuleSegmentInfo",not_found},
    {"sceSysmoduleGetModuleInfoForUnwind",not_found}, {"sceLibcHeapGetTraceInfo",not_found},
    {"sceRandomGetRandomNumber",random_number},
    {"pthread_rwlock_init",posix_rw_init}, {"pthread_rwlock_destroy",posix_rw_destroy},
    {"pthread_rwlock_rdlock",posix_rw_rdlock}, {"pthread_rwlock_wrlock",posix_rw_wrlock},
    {"pthread_rwlock_unlock",posix_rw_unlock},
    {"pthread_getschedparam",posix_getschedparam}, {"pthread_setschedparam",posix_setschedparam},
    {"sched_get_priority_max",sched_max}, {"sched_get_priority_min",sched_min},
    {"pthread_mutexattr_setprotocol",mutexattr_setprotocol},
    {"socket",socket_none},
    {"accept",socket_badf}, {"bind",socket_badf}, {"connect",socket_badf}, {"getpeername",socket_badf},
    {"getsockname",socket_badf}, {"getsockopt",socket_badf}, {"setsockopt",socket_badf}, {"listen",socket_badf},
    {"recv",socket_badf}, {"recvfrom",socket_badf}, {"send",socket_badf}, {"sendto",socket_badf},
    {"shutdown",socket_badf}, {"select",socket_badf},
    {"sceCoredumpRegisterCoredumpHandler",ok_noop}, {"sceCoredumpWriteUserData",ok_noop},
    {"scePlayGoGetEta",playgo_eta}, {"scePlayGoGetToDoList",playgo_todo}, {"scePlayGoPrefetch",ok_noop},
    {"sceAppContentTemporaryDataMount2",temp_mount2},
    {"sceNgs2SystemCreateWithAllocator",ngs2_system_create}, {"sceNgs2SystemDestroy",ok_noop},
    {"sceNgs2RackCreateWithAllocator",ngs2_rack_create}, {"sceNgs2RackDestroy",ok_noop},
    {"sceNgs2RackGetVoiceHandle",ngs2_voice_handle}, {"sceNgs2VoiceControl",ngs2_voice_control},
    {"sceNgs2VoiceGetState",ngs2_voice_state}, {"sceNgs2VoiceGetStateFlags",ngs2_voice_flags},
    {"sceNgs2SystemRender",ngs2_render}, {"sceNgs2PanInit",ok_noop}, {"sceNgs2PanGetVolumeMatrix",ok_noop},
    {"sceNgs2ParseWaveformData",ngs2_parse_waveform}, {"sceNgs2CalcWaveformBlock",ngs2_unsupported_waveform},
    {"_ZN3sce4Json11InitializerC1Ev",json_nothing}, {"_ZN3sce4Json11InitializerD1Ev",json_nothing},
    {"_ZN3sce4Json11Initializer10initializeEPKNS0_13InitParameterE",json_initialize},
    {"_ZN3sce4Json12MemAllocatorC2Ev",json_nothing}, {"_ZN3sce4Json12MemAllocatorD2Ev",json_nothing},
    {"_ZN3sce4Json12MemAllocator11notifyErrorEimPv",json_notify_error},
    {"_ZN3sce4Json5ValueC1Ev",json_nothing}, {"_ZN3sce4Json5ValueD1Ev",json_nothing},
    {"_ZN3sce4Json6Parser5parseERNS0_5ValueEPKcm",json_parse},
    {"_ZN3sce4Json6StringC1ERKS1_",json_nothing}, {"_ZN3sce4Json6StringD1Ev",json_nothing},
    {"_ZNK3sce4Json5Value10getBooleanEv",json_zero}, {"_ZNK3sce4Json5Value10getIntegerEv",json_zero},
    {"_ZNK3sce4Json5Value11getUIntegerEv",json_zero}, {"_ZNK3sce4Json5Value5countEv",json_zero},
    {"_ZNK3sce4Json5Value9getStringEv",json_null_value},
    {"_ZNK3sce4Json5ValueixEPKc",json_null_value}, {"_ZNK3sce4Json5ValueixEm",json_null_value},
    {"_ZNK3sce4Json6String4sizeEv",json_zero}, {"_ZNK3sce4Json6String5c_strEv",json_c_str},
    {"_ZNK3sce4Json6String5emptyEv",json_empty}, {"_ZNK3sce4Json6StringeqEPKc",json_equals},
    /* gr-stubs */
    {"sceAudioOutSetMixLevelPadSpk",ok_noop},
    
    {"sceNetCtlInit",ok_noop},
    {"sceNgs2SystemQueryBufferSize",gr_ngs2_system_query}, {"sceNgs2RackQueryBufferSize",gr_ngs2_rack_query}, {"sceNgs2SystemCreate",gr_ngs2_system_create}, {"sceNgs2RackCreate",gr_ngs2_rack_create},
    {"_sceFiberInitializeImpl",gr_fiber_initialize}, {"sceFiberFinalize",gr_fiber_finalize}, {"sceFiberRun",gr_fiber_run}, {"sceFiberSwitch",gr_fiber_switch}, {"sceFiberReturnToThread",gr_fiber_return_to_thread}, {"sceFiberGetSelf",gr_fiber_get_self},
    {"scePthreadRwlockattrInit",ok_noop}, {"scePthreadRwlockattrDestroy",ok_noop}, {"scePthreadRwlockattrSettype",ok_noop}, {"scePthreadRwlockattrGettype",ok_noop},
    {"sceScreenShotSetParam",ok_noop}, {"sceScreenShotSetOverlayImage",ok_noop}, {"sceScreenShotSetOverlayImageWithOrigin",ok_noop}, {"sceScreenShotIsDisabled",ok_noop},
};
/* Unreal Engine 4 native output (GOW3_UE4_SETRES=WxH, run.py): the base PS4 renderer makes its buffers at
 * the display size at start and only a live r.SetRes change resizes them (the debug menu's
 * Cinematic button). After about 10 s of play this sets the game's own r.SetRes console variable
 * as UE4's FSystemResolution::RequestResolutionChange does (0x2765ef1): flags = GetFlags()
 * & 0xff000000 (vtable +0x20), Set(value, flags) (vtable +0x68). Called from scePadReadState on
 * the game's input thread. CUSA11227 01.00 only: TAutoConsoleVariable at 0x5c28320, its
 * IConsoleVariable* at +8. */
/* Sets r.SetRes on the calling (game) thread; 0 when the game's variable is not where expected. */
static int ue4_setres(const char *text) {
    uint16_t value[24];
    size_t n=strlen(text);
    if (!n || n>=sizeof(value)/sizeof(value[0])) return 0;
    for (size_t i=0;i<=n;++i) value[i]=(uint16_t)(unsigned char)text[i];
    unsigned char *image=runtime_image_base();
    if (!image) return 0;
    const uintptr_t lo=(uintptr_t)image, hi=lo+0x6000000;
    uintptr_t cvar=*(const uintptr_t *)(image+0x5c28328);
    if (!cvar) { printf("Native output: r.SetRes not found\n"); return 0; }
    uintptr_t vtable=*(const uintptr_t *)cvar;
    if (vtable<lo || vtable>=hi) { printf("Native output: unexpected r.SetRes object\n"); return 0; }
    typedef uint32_t (ABI *GetFlags)(uintptr_t);
    typedef void (ABI *Set)(uintptr_t, const uint16_t *, uint32_t);
    uintptr_t get_flags=*(const uintptr_t *)(vtable+0x20), set=*(const uintptr_t *)(vtable+0x68);
    if (get_flags<lo || get_flags>=hi || set<lo || set>=hi) { printf("Native output: unexpected r.SetRes methods\n"); return 0; }
    uint32_t flags=((GetFlags)get_flags)(cvar)&0xff000000u;
    ((Set)set)(cvar,value,flags);
    printf("Native output: r.SetRes %s (live resolution change)\n",text);
    return 1;
}

/* A switch asked for by the in-game menu (window thread), done on the next game-thread poll. */
static char ue4_requested[24];
static int ue4_request_pending;
void runtime_ue4_request_setres(const char *text) {
    if (!text || strlen(text)>=sizeof(ue4_requested)) return;
    strcpy(ue4_requested,text);
    __atomic_store_n(&ue4_request_pending,1,__ATOMIC_RELEASE);
}

/* Unreal Engine 4 native output (GOW3_UE4_SETRES=WxH, run.py): the base PS4 renderer makes its buffers at
 * the display size at start and only a live r.SetRes change resizes them (the debug menu's
 * Cinematic button). After about 10 s of play this sets the game's own r.SetRes console variable
 * as UE4's FSystemResolution::RequestResolutionChange does (0x2765ef1): flags = GetFlags()
 * & 0xff000000 (vtable +0x20), Set(value, flags) (vtable +0x68). Called from scePadReadState on
 * the game's input thread. CUSA11227 01.00 only: TAutoConsoleVariable at 0x5c28320, its
 * IConsoleVariable* at +8. */
void runtime_ue4_setres_poll(void) {
    static int automatic_done;
    static unsigned reads;
    if (__atomic_exchange_n(&ue4_request_pending,0,__ATOMIC_ACQ_REL)) {
        char text[sizeof(ue4_requested)];
        strcpy(text,ue4_requested);
        if (reads>=600) ue4_setres(text);
        automatic_done=1; /* a choice in the menu wins over the start setting */
    }
    if (automatic_done) return;
    if (++reads<600) return; /* the main menu, with the game viewport up */
    automatic_done=1;
    const char *want=getenv("GOW3_UE4_SETRES");
    if (want && *want) ue4_setres(want);
}

uintptr_t runtime_extra_resolve(const char *name) { return RUNTIME_LOOKUP(exports,name); }
void runtime_extra_report(void) {
    printf("Runtime: event flags created=%zu, NGS2 silent renders=%zu\n",flags_created,ngs2_renders);
}
