/* Gravity Rush: NGS2 voices that play in time (still silent). Included by runtime_extra.c after
 * gr_ngs2.inc. A sampler voice gets its format (setup param) and waveform blocks, starts on the
 * play event and consumes its blocks as sceNgs2SystemRender advances the clock; its state reports
 * what a real voice would (in use / playing, decoded samples and bytes, current block), which the
 * game's streaming polls before it queues the next block. Values marked "assumed" below are not
 * confirmed by documentation. */

#define GR_V_MAX 1024                 /* tracked voices (open addressing) */
#define GR_V_BLOCKS 32                /* queued waveform blocks per voice */
/* Voice state flags (assumed SDK values). */
#define GR_VS_IN_USE 0x1u
#define GR_VS_PLAYING 0x2u
#define GR_VS_PAUSED 0x4u
/* Param ids seen in the game's VoiceControl calls, matched to shadPS4's structures by size. */
#define GR_P_EVENT 0x6u
#define GR_P_SETUP 0x10000000u
#define GR_P_BLOCKS 0x10000001u
#define GR_P_PITCH 0x10000005u
/* Event ids (assumed): play, stop (release), stop immediately, kill, pause, resume. */
enum { GR_EV_PLAY, GR_EV_STOP, GR_EV_STOP_IMM, GR_EV_KILL, GR_EV_PAUSE, GR_EV_RESUME };

typedef struct { uint32_t offset, size, repeats, skip, samples, reserved; uint64_t user; } GrNgs2Block;
typedef struct { uint16_t size; int16_t next; uint32_t id; uint32_t type, channels, rate, config, frame_offset, frame_margin; uint32_t flags, reserved; } GrNgs2SetupParam;
typedef struct { uint16_t size; int16_t next; uint32_t id; const unsigned char *data; uint32_t flags, count; const GrNgs2Block *blocks; } GrNgs2BlocksParam;
typedef struct { uint16_t size; int16_t next; uint32_t id; uint32_t event; } GrNgs2EventParam;
typedef struct { uint16_t size; int16_t next; uint32_t id; float ratio; uint32_t reserved; } GrNgs2PitchParam;
typedef struct {
    uint32_t flags; float envelope, peak; uint32_t reserved;
    uint64_t decoded_samples, decoded_bytes, user; const void *data;
} GrNgs2SamplerState;

typedef struct {
    uintptr_t handle;
    int sampler;                      /* got a setup param */
    uint32_t flags, type, channels, rate;
    float pitch;
    const unsigned char *data;
    GrNgs2Block blocks[GR_V_BLOCKS];
    uint32_t count, cur, repeat;
    double in_block;                  /* samples consumed in the current pass of the current block */
    uint64_t decoded_samples, decoded_bytes;
} GrVoice;

static GrVoice gr_voices[GR_V_MAX];
static size_t gr_voices_used;

/* Called with ngs2_lock held. */
static GrVoice *gr_voice_find(uintptr_t handle, int create) {
    size_t i = (handle >> 4) * 2654435761u % GR_V_MAX;
    for (size_t n = 0; n < GR_V_MAX; ++n, i = (i + 1) % GR_V_MAX) {
        if (gr_voices[i].handle == handle) return &gr_voices[i];
        if (!gr_voices[i].handle) {
            if (!create || gr_voices_used >= GR_V_MAX - 1) return NULL;
            ++gr_voices_used;
            gr_voices[i] = (GrVoice){.handle = handle, .pitch = 1.0f, .rate = 48000};
            return &gr_voices[i];
        }
    }
    return NULL;
}

static void gr_voice_stop(GrVoice *v) {
    v->flags = 0; v->count = v->cur = v->repeat = 0; v->in_block = 0;
}

static void gr_voice_blocks(GrVoice *v, const GrNgs2BlocksParam *p, int trace) {
    /* A new block list while the voice is idle starts over; while it plays, it is queued behind
     * the blocks still pending (streaming). */
    int append = (v->flags & GR_VS_PLAYING) && v->cur < v->count;
    if (!append) { v->count = v->cur = v->repeat = 0; v->in_block = 0; v->decoded_samples = v->decoded_bytes = 0; }
    else if (v->cur > 0) { /* drop finished blocks to make room */
        memmove(v->blocks, v->blocks + v->cur, (v->count - v->cur) * sizeof(*v->blocks));
        v->count -= v->cur; v->cur = 0;
    }
    v->data = p->data;
    for (uint32_t i = 0; p->blocks && i < p->count && v->count < GR_V_BLOCKS; ++i) v->blocks[v->count++] = p->blocks[i];
    if (trace)
        printf("Runtime: NGS2 voice 0x%llx blocks data=%p flags=0x%x n=%u%s first{off=%u size=%u rep=%u skip=%u samples=%u user=0x%llx}\n",
               (unsigned long long)v->handle, (const void *)p->data, p->flags, p->count, append ? " (queued)" : "",
               p->count && p->blocks ? p->blocks[0].offset : 0, p->count && p->blocks ? p->blocks[0].size : 0,
               p->count && p->blocks ? p->blocks[0].repeats : 0, p->count && p->blocks ? p->blocks[0].skip : 0,
               p->count && p->blocks ? p->blocks[0].samples : 0,
               p->count && p->blocks ? (unsigned long long)p->blocks[0].user : 0ull);
}

static void gr_voice_control(uintptr_t handle, const Ngs2ParamHeader *param, int trace) {
    pthread_mutex_lock(&ngs2_lock);
    GrVoice *v = gr_voice_find(handle, 1);
    for (int i = 0; v && param && i < 64; ++i) {
        switch (param->id) {
        case GR_P_SETUP: {
            const GrNgs2SetupParam *s = (const void *)param;
            v->sampler = 1; v->type = s->type; v->channels = s->channels; v->rate = s->rate ? s->rate : 48000;
            gr_voice_stop(v);
            if (trace) printf("Runtime: NGS2 voice 0x%llx setup type=0x%x channels=%u rate=%u config=0x%x flags=0x%x\n",
                              (unsigned long long)handle, s->type, s->channels, s->rate, s->config, s->flags);
            break;
        }
        case GR_P_BLOCKS: gr_voice_blocks(v, (const void *)param, trace); break;
        case GR_P_PITCH: { float r = ((const GrNgs2PitchParam *)param)->ratio; v->pitch = r > 0.0f && r < 16.0f ? r : 1.0f; break; }
        case GR_P_EVENT:
            switch (((const GrNgs2EventParam *)param)->event) {
            case GR_EV_PLAY: v->flags = GR_VS_IN_USE | GR_VS_PLAYING; break;
            case GR_EV_STOP: case GR_EV_STOP_IMM: case GR_EV_KILL: gr_voice_stop(v); break;
            case GR_EV_PAUSE: if (v->flags) v->flags |= GR_VS_PAUSED; break;
            case GR_EV_RESUME: v->flags &= ~GR_VS_PAUSED; break;
            }
            break;
        }
        param = param->next ? (const Ngs2ParamHeader *)((const char *)param + param->next) : NULL;
    }
    pthread_mutex_unlock(&ngs2_lock);
}

/* Advances every playing sampler voice by `samples` output samples (48 kHz). */
static void gr_voice_render(uint32_t samples) {
    pthread_mutex_lock(&ngs2_lock);
    for (size_t i = 0; i < GR_V_MAX; ++i) {
        GrVoice *v = &gr_voices[i];
        if (!v->handle || !v->sampler || (v->flags & (GR_VS_PLAYING | GR_VS_PAUSED)) != GR_VS_PLAYING) continue;
        double left = samples * (double)v->pitch * v->rate / 48000.0;
        while (left > 0 && v->cur < v->count) {
            const GrNgs2Block *b = &v->blocks[v->cur];
            double length = b->samples > b->skip ? (double)(b->samples - b->skip) : 0;
            double take = length - v->in_block < left ? length - v->in_block : left;
            if (take < 0) take = 0;
            v->in_block += take; left -= take; v->decoded_samples += (uint64_t)take;
            if (v->in_block >= length) {
                v->in_block = 0;
                if (v->repeat < b->repeats) { ++v->repeat; continue; }
                v->repeat = 0; v->decoded_bytes += b->size; ++v->cur;
            }
        }
        if (v->cur >= v->count) gr_voice_stop(v);   /* out of data: the voice ends */
    }
    pthread_mutex_unlock(&ngs2_lock);
}

static void gr_voice_state(uintptr_t handle, void *state, uint64_t size) {
    if (!state || !size) return;
    pthread_mutex_lock(&ngs2_lock);
    GrVoice *v = gr_voice_find(handle, 0);
    GrNgs2SamplerState s = {.envelope = 1.0f};
    if (v) {
        s.flags = v->flags;
        s.decoded_samples = v->decoded_samples; s.decoded_bytes = v->decoded_bytes;
        if (v->cur < v->count) { s.user = v->blocks[v->cur].user; s.data = v->data ? v->data + v->blocks[v->cur].offset : NULL; }
    }
    pthread_mutex_unlock(&ngs2_lock);
    memset(state, 0, size);
    memcpy(state, &s, size < sizeof(s) ? size : sizeof(s));
}

static uint32_t gr_voice_flags(uintptr_t handle) {
    pthread_mutex_lock(&ngs2_lock);
    GrVoice *v = gr_voice_find(handle, 0);
    uint32_t f = v ? v->flags : 0;
    pthread_mutex_unlock(&ngs2_lock);
    return f;
}
