/* Gravity Rush: NGS2 sampler voices. Included by runtime_extra.c after the NGS2 stubs.
 * A sampler voice gets its format (setup param) and waveform blocks, starts on the play event and
 * consumes its blocks as sceNgs2SystemRender advances the clock; its state reports what a real
 * voice would (in use / playing, decoded samples and bytes, current block), which the game's
 * streaming polls before it queues the next block. PCM voices (24-bit: the game's type 0x14, and
 * 16-bit) and ATRAC9 voices (type 0x40, LibAtrac9) are mixed into the render buffer with their
 * port 0 volume and matrix; submixers, sends and effects are not modelled. Values marked
 * "assumed" are not confirmed by documentation. */
#include "third_party/LibAtrac9/C/src/libatrac9.h"

#define GR_V_MAX 1024                 /* tracked voices (open addressing) */
#define GR_V_BLOCKS 32                /* queued waveform blocks per voice */
/* Voice state flags (assumed SDK values). */
#define GR_VS_IN_USE 0x1u
#define GR_VS_PLAYING 0x2u
#define GR_VS_PAUSED 0x4u
/* Param ids seen in the game's VoiceControl calls, matched to shadPS4's structures by size. */
#define GR_P_MATRIX_LEVELS 0x1u
#define GR_P_PORT_VOLUME 0x2u        /* port, float level (the game sends 1.0) */
#define GR_P_PORT_MATRIX 0x3u        /* port, matrix id */
#define GR_P_EVENT 0x6u
#define GR_P_SETUP 0x10000000u
#define GR_P_BLOCKS 0x10000001u
#define GR_P_PITCH 0x10000005u
#define GR_WAVE_PCM24 0x14u           /* 3 bytes per sample (from the game's block sizes) */
#define GR_WAVE_PCM16 0x12u           /* assumed */
#define GR_WAVE_ATRAC9 0x40u          /* config word = the 4 ATRAC9 config bytes, 0xFE first */
#define GR_AT9_MAX_FRAME (256 * 8)    /* samples x channels of one decoded frame */
#define GR_MATRICES 4
#define GR_MATRIX_LEVELS 16
/* Event ids (assumed): play, stop (release), stop immediately, kill, pause, resume. */
enum { GR_EV_PLAY, GR_EV_STOP, GR_EV_STOP_IMM, GR_EV_KILL, GR_EV_PAUSE, GR_EV_RESUME };

typedef struct { uint32_t offset, size, repeats, skip, samples, reserved; uint64_t user; } GrNgs2Block;
typedef struct { uint16_t size; int16_t next; uint32_t id; uint32_t type, channels, rate, config, frame_offset, frame_margin; uint32_t flags, reserved; } GrNgs2SetupParam;
typedef struct { uint16_t size; int16_t next; uint32_t id; const unsigned char *data; uint32_t flags, count; const GrNgs2Block *blocks; } GrNgs2BlocksParam;
typedef struct { uint16_t size; int16_t next; uint32_t id; uint32_t event; } GrNgs2EventParam;
typedef struct { uint16_t size; int16_t next; uint32_t id; float ratio; uint32_t reserved; } GrNgs2PitchParam;
typedef struct { uint16_t size; int16_t next; uint32_t id; uint32_t matrix, count; const float *levels; } GrNgs2MatrixParam;
typedef struct { uint16_t size; int16_t next; uint32_t id; uint32_t port; int32_t matrix; } GrNgs2PortMatrixParam;
typedef struct { uint16_t size; int16_t next; uint32_t id; uint32_t port; float level; } GrNgs2PortVolumeParam;
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
    float volume;                     /* port 0 */
    int32_t matrix;                   /* port 0's matrix, -1 none */
    uint32_t matrix_count[GR_MATRICES];
    float levels[GR_MATRICES][GR_MATRIX_LEVELS];
    /* ATRAC9: decoder, codec info and the last decoded frame of the current block. */
    void *at9;
    Atrac9CodecInfo at9_info;
    uint32_t at9_base, at9_count;     /* block sample index of the frame's first sample, samples in it */
    uint32_t at9_byte, at9_frames, at9_super_left;
    int16_t at9_pcm[GR_AT9_MAX_FRAME];
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
            gr_voices[i] = (GrVoice){.handle = handle, .pitch = 1.0f, .rate = 48000, .volume = 1.0f, .matrix = -1};
            return &gr_voices[i];
        }
    }
    return NULL;
}

/* Starts decoding the current block from its first byte (the decoder keeps its state). */
static void gr_at9_block_start(GrVoice *v) {
    v->at9_base = v->at9_count = v->at9_byte = v->at9_frames = 0;
    v->at9_super_left = (uint32_t)v->at9_info.superframeSize;
}

static void gr_voice_stop(GrVoice *v) {
    v->flags = 0; v->count = v->cur = v->repeat = 0; v->in_block = 0;
    gr_at9_block_start(v);
}

/* A decoder for config word `config`; the byte order is not documented, so both are tried. */
static void gr_at9_setup(GrVoice *v, uint32_t config, int trace) {
    if (v->at9) { Atrac9ReleaseHandle(v->at9); v->at9 = NULL; }
    unsigned char orders[2][4] = {{config >> 24, config >> 16, config >> 8, config},
                                  {config, config >> 8, config >> 16, config >> 24}};
    for (int k = 0; k < 2 && !v->at9; ++k) {
        if (orders[k][0] != 0xFE) continue;
        void *h = Atrac9GetHandle();
        Atrac9CodecInfo info;
        if (h && !Atrac9InitDecoder(h, orders[k]) && !Atrac9GetCodecInfo(h, &info) &&
            info.frameSamples * info.channels <= GR_AT9_MAX_FRAME && info.framesInSuperframe > 0) {
            v->at9 = h; v->at9_info = info;
        } else if (h) Atrac9ReleaseHandle(h);
    }
    if (trace)
        printf("Runtime: NGS2 voice 0x%llx ATRAC9 %s: %d ch, %d Hz, frame %d samples, %d frames/superframe, superframe %d bytes\n",
               (unsigned long long)v->handle, v->at9 ? "ready" : "FAILED", v->at9_info.channels, v->at9_info.samplingRate,
               v->at9_info.frameSamples, v->at9_info.framesInSuperframe, v->at9_info.superframeSize);
}

/* Decodes frames of block `b` until sample `index` (from the block's start) is in the frame
 * buffer; 0 when the block's data ends first or the decoder fails. */
static int gr_at9_fetch(GrVoice *v, const GrNgs2Block *b, uint32_t index) {
    while (index >= v->at9_base + v->at9_count) {
        if (index < v->at9_base) return 0;
        if (v->at9_byte >= b->size) return 0;
        int used = 0;
        if (Atrac9Decode(v->at9, v->data + b->offset + v->at9_byte, v->at9_pcm, &used) || used <= 0) return 0;
        v->at9_base += v->at9_count;
        v->at9_count = (uint32_t)v->at9_info.frameSamples;
        v->at9_byte += (uint32_t)used; v->at9_super_left -= (uint32_t)used < v->at9_super_left ? (uint32_t)used : v->at9_super_left;
        if (++v->at9_frames == (uint32_t)v->at9_info.framesInSuperframe) {   /* skip the superframe's padding */
            v->at9_byte += v->at9_super_left; v->at9_frames = 0;
            v->at9_super_left = (uint32_t)v->at9_info.superframeSize;
        }
    }
    return 1;
}

static void gr_voice_blocks(GrVoice *v, const GrNgs2BlocksParam *p, int trace) {
    /* Flag 1 replaces the voice's blocks; without it the blocks are queued behind the pending ones
     * (the game sends its data with flag 1, then an empty list without it, before playing). */
    int append = !(p->flags & 1u);
    if (append && !p->count) return;
    if (!append) { v->count = v->cur = v->repeat = 0; v->in_block = 0; v->decoded_samples = v->decoded_bytes = 0; gr_at9_block_start(v); }
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
            if (s->type == GR_WAVE_ATRAC9) gr_at9_setup(v, s->config, trace);
            gr_voice_stop(v);
            if (trace) printf("Runtime: NGS2 voice 0x%llx setup type=0x%x channels=%u rate=%u config=0x%x flags=0x%x\n",
                              (unsigned long long)handle, s->type, s->channels, s->rate, s->config, s->flags);
            break;
        }
        case GR_P_BLOCKS: gr_voice_blocks(v, (const void *)param, trace); break;
        case GR_P_MATRIX_LEVELS: {
            const GrNgs2MatrixParam *m = (const void *)param;
            if (m->matrix < GR_MATRICES && m->levels) {
                uint32_t n = m->count < GR_MATRIX_LEVELS ? m->count : GR_MATRIX_LEVELS;
                memcpy(v->levels[m->matrix], m->levels, n * sizeof(float));
                v->matrix_count[m->matrix] = n;
                if (trace) {
                    printf("Runtime: NGS2 voice 0x%llx matrix %u levels:", (unsigned long long)handle, m->matrix);
                    for (uint32_t k = 0; k < n; ++k) printf(" %.3f", (double)m->levels[k]);
                    putchar('\n');
                }
            }
            break;
        }
        case GR_P_PORT_MATRIX: {
            const GrNgs2PortMatrixParam *m = (const void *)param;
            if (m->port == 0) v->matrix = m->matrix;
            break;
        }
        case GR_P_PORT_VOLUME: {
            const GrNgs2PortVolumeParam *m = (const void *)param;
            if (m->port == 0 && m->level >= 0.0f && m->level < 64.0f) v->volume = m->level;
            break;
        }
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

/* One input sample of channel `c` at frame `i` of a PCM block, as -1..1. */
static float gr_pcm(const GrVoice *v, const unsigned char *block, uint32_t i, uint32_t c) {
    if (v->type == GR_WAVE_PCM24) {
        const unsigned char *s = block + ((size_t)i * v->channels + c) * 3;
        int32_t x = (int32_t)((uint32_t)s[0] << 8 | (uint32_t)s[1] << 16 | (uint32_t)s[2] << 24) >> 8;
        return (float)x * (1.0f / 8388608.0f);
    }
    int16_t x;
    memcpy(&x, block + ((size_t)i * v->channels + c) * 2, 2);
    return (float)x * (1.0f / 32768.0f);
}

/* Gains of input channel `c` on the `outs` output channels (PS4 order: L R C LFE SL SR BL BR):
 * port 0's matrix when the game set one (the game's mono voices send to the centre; levels
 * assumed to run input-major), else mono to both front sides, stereo kept apart. */
static void gr_gains(const GrVoice *v, uint32_t c, uint32_t outs, float *g) {
    for (uint32_t o = 0; o < outs; ++o) g[o] = 0.0f;
    if (v->matrix >= 0 && v->matrix < GR_MATRICES && v->matrix_count[v->matrix] >= v->channels) {
        const float *m = v->levels[v->matrix];
        uint32_t per = v->matrix_count[v->matrix] / v->channels;
        for (uint32_t o = 0; o < outs && o < per; ++o) g[o] = m[c * per + o];
    } else if (v->channels == 1) { g[0] = g[1] = 0.7071f; }
    else if (c < 2) { g[c] = 1.0f; }
    /* The submixer and mastering racks that follow on a PS4 are not modelled; their gain is
     * stood in for by GOW3_NGS2_GAIN (provisional default 4, +12 dB: the game's levels are low). */
    static float master = -1.0f;
    if (master < 0.0f) { const char *e = getenv("GOW3_NGS2_GAIN"); master = e && atof(e) > 0.0 ? (float)atof(e) : 4.0f; }
    for (uint32_t o = 0; o < outs; ++o) g[o] *= v->volume * master;
}

/* Advances every playing sampler voice by `samples` output samples (48 kHz) and, when `out` is
 * given (float, `channels` interleaved, front left/right first), mixes the PCM ones into it. */
static void gr_voice_render(float *out, uint32_t channels, uint32_t samples) {
    /* GOW3_AUDIO_TRACE=1: every 375 renders (2 s), playing and mixed voices, the types of the
     * ones not mixed, and the peak of the mixed buffer. */
    static int trace = -1;
    static unsigned renders;
    if (trace < 0) { const char *e = getenv("GOW3_AUDIO_TRACE"); trace = e && e[0] == '1'; }
    int report = trace && ++renders % 375 == 1;
    unsigned playing = 0, mixed = 0, other_type = 0, other_count = 0;
    pthread_mutex_lock(&ngs2_lock);
    for (size_t i = 0; i < GR_V_MAX; ++i) {
        GrVoice *v = &gr_voices[i];
        if (!v->handle || !v->sampler || (v->flags & (GR_VS_PLAYING | GR_VS_PAUSED)) != GR_VS_PLAYING) continue;
        double step = (double)v->pitch * v->rate / 48000.0;
        int at9 = v->type == GR_WAVE_ATRAC9 && v->at9 && (uint32_t)v->at9_info.channels == v->channels;
        int pcm = out && channels && v->data && v->channels && v->channels <= 8 &&
                  (v->type == GR_WAVE_PCM24 || v->type == GR_WAVE_PCM16 || at9);
        ++playing;
        if (pcm) ++mixed;
        else { ++other_count; other_type = v->type; }
        uint32_t outs = channels < 8 ? channels : 8;
        float g[8][8];
        for (uint32_t c = 0; pcm && c < v->channels; ++c) gr_gains(v, c, outs, g[c]);
        for (uint32_t s = 0; s < samples && v->cur < v->count; ++s) {
            const GrNgs2Block *b = &v->blocks[v->cur];
            double length = b->samples > b->skip ? (double)(b->samples - b->skip) : 0;
            if (v->in_block < length && pcm && at9) {
                uint32_t at = b->skip + (uint32_t)v->in_block;
                if (gr_at9_fetch(v, b, at)) {
                    const int16_t *x = v->at9_pcm + (size_t)(at - v->at9_base) * v->channels;
                    float *frame = out + (size_t)s * channels;
                    for (uint32_t c = 0; c < v->channels; ++c)
                        for (uint32_t o = 0; o < outs; ++o) frame[o] += (float)x[c] * (1.0f / 32768.0f) * g[c][o];
                } else v->in_block = length;   /* data ran out: on to the next block */
            } else if (v->in_block < length && pcm) {
                const unsigned char *block = v->data + b->offset;
                uint32_t at = b->skip + (uint32_t)v->in_block;
                uint32_t next = at + 1 < b->samples ? at + 1 : at;
                float t = (float)(v->in_block - (double)(uint32_t)v->in_block);
                float *frame = out + (size_t)s * channels;
                for (uint32_t c = 0; c < v->channels; ++c) {
                    float x = gr_pcm(v, block, at, c) * (1.0f - t) + gr_pcm(v, block, next, c) * t;
                    for (uint32_t o = 0; o < outs; ++o) frame[o] += x * g[c][o];
                }
            }
            v->in_block += step;
            if (v->in_block >= length) {
                v->in_block = v->in_block >= length + step ? 0 : v->in_block - length;
                v->decoded_samples += (uint64_t)length;
                gr_at9_block_start(v);
                if (v->repeat < b->repeats) { ++v->repeat; continue; }
                v->repeat = 0; v->decoded_bytes += b->size; ++v->cur;
            }
        }
        if (v->cur >= v->count) gr_voice_stop(v);   /* out of data: the voice ends */
    }
    pthread_mutex_unlock(&ngs2_lock);
    float peak = 0;
    for (size_t i = 0; out && i < (size_t)samples * channels; ++i) {
        out[i] = out[i] > 1.0f ? 1.0f : out[i] < -1.0f ? -1.0f : out[i];
        float a = out[i] < 0 ? -out[i] : out[i];
        if (a > peak) peak = a;
    }
    if (report)
        printf("Audio trace: NGS2 render %u out=%p playing=%u mixed=%u not-mixed=%u (type 0x%x) peak=%.4f\n",
               renders, (void *)out, playing, mixed, other_count, other_type, peak);
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
