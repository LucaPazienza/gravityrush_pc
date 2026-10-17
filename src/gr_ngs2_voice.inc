/* Gravity Rush: NGS2 sampler voices. Included by runtime_extra.c after the NGS2 stubs.
 * A sampler voice gets its format (setup param), a queue of waveform blocks and play / stop /
 * pause events; sceNgs2SystemRender consumes the queue in real time and mixes PCM voices (24-bit:
 * the game's type 0x14, and 16-bit) and ATRAC9 voices (type 0x40, LibAtrac9) into the render
 * buffer through each voice's port 0 volume and matrix. Submixers, sends and effects are not
 * modelled. Values marked "assumed" are not confirmed by documentation.
 *
 * Streaming, as the game's SNDX library drives it (seen with its own debug log, GOW3_POKE): every
 * segment of a stream (music, wind, ambience) is one blocks param with flag 1, sent while the
 * voice plays, each with its own data pointer into the stream's ring buffer, so flag 1 queues.
 * A one-shot sound gets its block the same way, then an empty list without the flag: no more
 * data, the voice ends when its queue is done. A stream whose queue runs dry stays in use with
 * the empty flag (0x20, which the game counts as an underrun) until the next segment arrives.
 * The game reads decoded samples and bytes from the voice state to pace its segments. */
#include "third_party/LibAtrac9/C/src/libatrac9.h"

#define GR_V_MAX 1024                 /* tracked voices (open addressing) */
#define GR_V_BLOCKS 32                /* queued waveform blocks per voice */
/* Voice state flags: the game's state loop (0xd7b430) treats 0x1 as in use (cleared: the voice
 * is finished), 0x2 as playing and 0x20 as empty. Paused is assumed. */
#define GR_VS_IN_USE 0x1u
#define GR_VS_PLAYING 0x2u
#define GR_VS_PAUSED 0x4u
#define GR_VS_EMPTY 0x20u
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
/* Event ids, confirmed by the SNDX log: play, stop (release), stop immediately, kill, pause, resume. */
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
    GrNgs2Block blocks[GR_V_BLOCKS];
    const unsigned char *block_data[GR_V_BLOCKS];   /* each block's data param (its offset adds to it) */
    uint32_t count, cur, repeat;
    int ended;                        /* no more blocks will come: finish when the queue is done */
    double in_block;                  /* samples consumed in the current pass of the current block */
    double decoded;                   /* input samples consumed since setup */
    uint64_t decoded_bytes;           /* bytes of finished blocks since setup */
    float volume;                     /* port 0 */
    int32_t matrix;                   /* port 0's matrix, -1 none */
    uint32_t matrix_count[GR_MATRICES];
    float levels[GR_MATRICES][GR_MATRIX_LEVELS];
    /* ATRAC9: decoder, codec info and the last decoded frame of the current block. */
    void *at9;
    Atrac9CodecInfo at9_info;
    uint32_t at9_base, at9_count;     /* block sample index of the frame's first sample, samples in it */
    uint32_t at9_byte, at9_frames, at9_super_left;
    int at9_silent;                   /* the samples in hand are silence (after a decode error) */
    unsigned char at9_config[4];
    int16_t at9_pcm[GR_AT9_MAX_FRAME];
} GrVoice;

/* The mastering voice's gain and limiter, as the game sets them (it sends gain 0.5 and a limiter
 * at 1.0); GOW3_NGS2_GAIN multiplies on top (default 1). */
static float gr_master_gain = 1.0f, gr_limiter_threshold = 1.0f, gr_limiter_gain = 1.0f;
static int gr_limiter_on = 1;

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
    v->at9_silent = 0;
    v->at9_super_left = (uint32_t)v->at9_info.superframeSize;
}

/* A fresh decoder with the voice's config: LibAtrac9 counts the frames of each superframe and
 * refuses a superframe start in the middle of one, so a stream that lost its place (a block cut
 * short, a decode error) must start over. */
static void gr_at9_reinit(GrVoice *v) {
    if (!v->at9) return;
    Atrac9ReleaseHandle(v->at9);
    v->at9 = Atrac9GetHandle();
    if (v->at9 && Atrac9InitDecoder(v->at9, v->at9_config)) { Atrac9ReleaseHandle(v->at9); v->at9 = NULL; }
    v->at9_frames = 0; v->at9_super_left = (uint32_t)v->at9_info.superframeSize;
}

/* Stop / kill, and the end of a voice's data: not in use any more, queue dropped. */
static void gr_voice_stop(GrVoice *v) {
    v->flags = 0; v->count = v->cur = v->repeat = 0; v->in_block = 0; v->ended = 0;
    if (v->at9 && v->at9_frames) gr_at9_reinit(v);
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
            memcpy(v->at9_config, orders[k], 4);
        } else if (h) Atrac9ReleaseHandle(h);
    }
    if (trace)
        printf("Runtime: NGS2 voice 0x%llx ATRAC9 %s: %d ch, %d Hz, frame %d samples, %d frames/superframe, superframe %d bytes\n",
               (unsigned long long)v->handle, v->at9 ? "ready" : "FAILED", v->at9_info.channels, v->at9_info.samplingRate,
               v->at9_info.frameSamples, v->at9_info.framesInSuperframe, v->at9_info.superframeSize);
}

/* Decodes one frame of block `b` at the voice's byte position; 0 at the end of the block's data.
 * A decode error restarts the decoder and makes the rest of that superframe silence. */
static int gr_at9_decode_next(GrVoice *v, const unsigned char *data, const GrNgs2Block *b) {
    if (!v->at9 || v->at9_byte >= b->size) return 0;
    int used = 0;
    int error = Atrac9Decode(v->at9, data + b->offset + v->at9_byte, v->at9_pcm, &used);
    v->at9_base += v->at9_count;
    if (error || used <= 0) {
        static int left = 30;   /* the first failures, with where they happened */
        if (left > 0) {
            --left;
            printf("Runtime: NGS2 voice 0x%llx ATRAC9 decode error 0x%x at byte %u of %u (frame %u of the superframe); restarting the decoder\n",
                   (unsigned long long)v->handle, (unsigned)error, v->at9_byte, b->size, v->at9_frames);
        }
        uint32_t frames_left = (uint32_t)v->at9_info.framesInSuperframe - v->at9_frames;
        v->at9_byte += v->at9_super_left;
        gr_at9_reinit(v);
        v->at9_count = frames_left * (uint32_t)v->at9_info.frameSamples;
        v->at9_silent = 1;
        return 1;
    }
    v->at9_count = (uint32_t)v->at9_info.frameSamples;
    v->at9_silent = 0;
    v->at9_byte += (uint32_t)used; v->at9_super_left -= (uint32_t)used < v->at9_super_left ? (uint32_t)used : v->at9_super_left;
    if (++v->at9_frames == (uint32_t)v->at9_info.framesInSuperframe) {   /* skip the superframe's padding */
        v->at9_byte += v->at9_super_left; v->at9_frames = 0;
        v->at9_super_left = (uint32_t)v->at9_info.superframeSize;
    }
    return 1;
}

/* Sample `index` (counted from the block's first decoded sample, skipped ones included) of the
 * current block, one int16 per channel; NULL when the block's data ends before it. */
static const int16_t *gr_at9_sample(GrVoice *v, const unsigned char *data, const GrNgs2Block *b, uint32_t index) {
    static const int16_t silence[8];
    while (index >= v->at9_base + v->at9_count)
        if (!gr_at9_decode_next(v, data, b)) return NULL;
    return v->at9_silent ? silence : v->at9_pcm + (size_t)(index - v->at9_base) * v->channels;
}

/* At the end of a block: decode the rest of its last superframe, so the decoder expects a
 * superframe start for the next block (or restart it when the data is not there). */
static void gr_at9_finish_block(GrVoice *v, const unsigned char *data, const GrNgs2Block *b) {
    while (v->at9 && v->at9_frames && gr_at9_decode_next(v, data, b)) {}
    if (v->at9_frames) gr_at9_reinit(v);
    gr_at9_block_start(v);
}

static void gr_voice_blocks(GrVoice *v, const GrNgs2BlocksParam *p, int trace) {
    if (!(p->flags & 1u) && !p->count) {   /* no more data for this voice */
        v->ended = 1;
        if (trace) printf("Runtime: NGS2 voice 0x%llx blocks: end of data\n", (unsigned long long)v->handle);
        return;
    }
    if (v->cur > 0) {                      /* drop finished blocks to make room */
        memmove(v->blocks, v->blocks + v->cur, (v->count - v->cur) * sizeof(*v->blocks));
        memmove(v->block_data, v->block_data + v->cur, (v->count - v->cur) * sizeof(*v->block_data));
        v->count -= v->cur; v->cur = 0;
    }
    uint32_t added = 0;
    for (uint32_t i = 0; p->data && p->blocks && i < p->count && v->count < GR_V_BLOCKS; ++i, ++added) {
        v->blocks[v->count] = p->blocks[i];
        v->block_data[v->count++] = p->data;
    }
    if (added) { v->ended = 0; v->flags &= ~GR_VS_EMPTY; }
    if (trace)
        printf("Runtime: NGS2 voice 0x%llx blocks data=%p flags=0x%x n=%u queued=%u first{off=%u size=%u rep=%u skip=%u samples=%u}\n",
               (unsigned long long)v->handle, (const void *)p->data, p->flags, p->count, v->count,
               p->count && p->blocks ? p->blocks[0].offset : 0, p->count && p->blocks ? p->blocks[0].size : 0,
               p->count && p->blocks ? p->blocks[0].repeats : 0, p->count && p->blocks ? p->blocks[0].skip : 0,
               p->count && p->blocks ? p->blocks[0].samples : 0);
}

/* Mastering voice params (rack 0x3000; shadPS4's structures, in order from 0x30000000: setup,
 * matrix, LFE, limiter {enable, threshold}, gain {fbw level, LFE level}, output, peak meter). */
static void gr_mastering_control(const Ngs2ParamHeader *param, int trace) {
    for (int i = 0; param && i < 64; ++i) {
        const uint32_t *w = (const uint32_t *)param;
        float f;
        if (param->id == 0x30000003u && param->size >= 16) {
            memcpy(&f, w + 3, 4);
            gr_limiter_on = w[2] != 0;
            if (f > 0.0f && f <= 4.0f) gr_limiter_threshold = f;
            if (trace) printf("Runtime: NGS2 mastering limiter %s, threshold %.3f\n", gr_limiter_on ? "on" : "off", (double)gr_limiter_threshold);
        } else if (param->id == 0x30000004u && param->size >= 16) {
            memcpy(&f, w + 2, 4);
            if (f >= 0.0f && f <= 16.0f) gr_master_gain = f;
            if (trace) printf("Runtime: NGS2 mastering gain %.3f\n", (double)gr_master_gain);
        }
        param = param->next ? (const Ngs2ParamHeader *)((const char *)param + param->next) : NULL;
    }
}

static void gr_voice_control(uintptr_t handle, const Ngs2ParamHeader *param, int trace) {
    /* Only sampler voices make sound here; the mastering voice gives the master gain and limiter,
     * submixer voices (and their effects) are not modelled and must not touch sampler voices. */
    uint32_t rack_id = ngs2_voice_rack_id(handle);
    if (rack_id == 0x3000u) { pthread_mutex_lock(&ngs2_lock); gr_mastering_control(param, trace); pthread_mutex_unlock(&ngs2_lock); return; }
    if (rack_id != 0x1000u) return;
    pthread_mutex_lock(&ngs2_lock);
    GrVoice *v = gr_voice_find(handle, 1);
    for (int i = 0; v && param && i < 64; ++i) {
        switch (param->id) {
        case GR_P_SETUP: {
            const GrNgs2SetupParam *s = (const void *)param;
            v->sampler = 1; v->type = s->type; v->channels = s->channels; v->rate = s->rate ? s->rate : 48000;
            if (s->type == GR_WAVE_ATRAC9) gr_at9_setup(v, s->config, trace);
            gr_voice_stop(v);
            v->decoded = 0; v->decoded_bytes = 0;
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
        case GR_P_EVENT: {
            uint32_t event = ((const GrNgs2EventParam *)param)->event;
            if (trace) printf("Runtime: NGS2 voice 0x%llx event %u (queued %u, ended %d)\n",
                              (unsigned long long)handle, event, v->count - v->cur, v->ended);
            switch (event) {
            case GR_EV_PLAY: v->flags = GR_VS_IN_USE | GR_VS_PLAYING; break;
            case GR_EV_STOP: case GR_EV_STOP_IMM: case GR_EV_KILL: gr_voice_stop(v); break;
            case GR_EV_PAUSE: if (v->flags) v->flags |= GR_VS_PAUSED; break;
            case GR_EV_RESUME: v->flags &= ~GR_VS_PAUSED; break;
            }
            break;
        }
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
 * port 0's matrix when the game set one, else mono to both front sides, stereo kept apart.
 * Levels run output-major, level[out * channels + in]: the game's stereo streams send
 * 0.3 0 0 0.3 (left to left, right to right) and its mono voices go to the centre. */
static void gr_gains(const GrVoice *v, uint32_t c, uint32_t outs, float *g) {
    for (uint32_t o = 0; o < outs; ++o) g[o] = 0.0f;
    if (v->matrix >= 0 && v->matrix < GR_MATRICES && v->matrix_count[v->matrix] >= v->channels) {
        const float *m = v->levels[v->matrix];
        uint32_t per = v->matrix_count[v->matrix] / v->channels;
        for (uint32_t o = 0; o < outs && o < per; ++o) g[o] = m[o * v->channels + c];
    } else if (v->channels == 1) { g[0] = g[1] = 0.7071f; }
    else if (c < 2) { g[c] = 1.0f; }
    /* The mastering voice's gain (the game sets 0.5), times GOW3_NGS2_GAIN (default 1). */
    static float user = -1.0f;
    if (user < 0.0f) { const char *e = getenv("GOW3_NGS2_GAIN"); user = e && atof(e) > 0.0 ? (float)atof(e) : 1.0f; }
    for (uint32_t o = 0; o < outs; ++o) g[o] *= v->volume * gr_master_gain * user;
}

/* Advances every playing sampler voice by `samples` output samples (48 kHz) and, when `out` is
 * given (float, `channels` interleaved, front left/right first), mixes them into it. */
static void gr_voice_render(float *out, uint32_t channels, uint32_t samples) {
    /* GOW3_AUDIO_TRACE=1: every 375 renders (2 s), playing / empty / paused voices and the peak. */
    static int trace = -1;
    static unsigned renders;
    if (trace < 0) { const char *e = getenv("GOW3_AUDIO_TRACE"); trace = e && e[0] == '1'; }
    int report = trace && ++renders % 375 == 1;
    unsigned playing = 0, empty = 0, paused = 0, unmixed = 0, unmixed_type = 0;
    uint32_t outs = channels < 8 ? channels : 8;
    pthread_mutex_lock(&ngs2_lock);
    for (size_t i = 0; i < GR_V_MAX; ++i) {
        GrVoice *v = &gr_voices[i];
        if (!v->handle || !v->sampler || !(v->flags & GR_VS_PLAYING)) continue;
        if (v->flags & GR_VS_PAUSED) { ++paused; continue; }
        if (v->cur >= v->count) {             /* nothing queued */
            if (v->ended) gr_voice_stop(v);
            else { v->flags |= GR_VS_EMPTY; ++empty; }
            continue;
        }
        ++playing;
        double step = (double)v->pitch * v->rate / 48000.0;
        int at9 = v->type == GR_WAVE_ATRAC9 && v->at9 && (uint32_t)v->at9_info.channels == v->channels;
        int mix = out && outs && v->channels && v->channels <= 8 &&
                  (v->type == GR_WAVE_PCM24 || v->type == GR_WAVE_PCM16 || at9);
        if (!mix) { ++unmixed; unmixed_type = v->type; }
        float g[8][8];
        for (uint32_t c = 0; mix && c < v->channels; ++c) gr_gains(v, c, outs, g[c]);
        for (uint32_t s = 0; s < samples && v->cur < v->count; ++s) {
            const GrNgs2Block *b = &v->blocks[v->cur];
            const unsigned char *data = v->block_data[v->cur];
            /* numSamples is what plays after the skipped ones: the block holds skip + samples
             * (the game's first music segment: skip 256, 149248 samples, 149504 in the data). */
            double length = (double)b->samples;
            uint32_t end = b->skip + b->samples;
            float *frame = out ? out + (size_t)s * channels : NULL;
            if (v->in_block < length && mix && at9) {
                const int16_t *x = gr_at9_sample(v, data, b, b->skip + (uint32_t)v->in_block);
                if (x) {
                    for (uint32_t c = 0; c < v->channels; ++c)
                        for (uint32_t o = 0; o < outs; ++o) frame[o] += (float)x[c] * (1.0f / 32768.0f) * g[c][o];
                } else v->in_block = length;   /* the block's data ran out: on to the next one */
            } else if (v->in_block < length && mix) {
                const unsigned char *block = data + b->offset;
                uint32_t at = b->skip + (uint32_t)v->in_block;
                uint32_t next = at + 1 < end ? at + 1 : at;
                float t = (float)(v->in_block - (double)(uint32_t)v->in_block);
                for (uint32_t c = 0; c < v->channels; ++c) {
                    float x = gr_pcm(v, block, at, c) * (1.0f - t) + gr_pcm(v, block, next, c) * t;
                    for (uint32_t o = 0; o < outs; ++o) frame[o] += x * g[c][o];
                }
            }
            v->in_block += step; v->decoded += step;
            if (v->in_block >= length) {
                v->in_block = v->in_block >= length + step ? 0 : v->in_block - length;
                if (at9) gr_at9_finish_block(v, data, b);
                else gr_at9_block_start(v);
                if (v->repeat < b->repeats) { ++v->repeat; continue; }
                v->repeat = 0; v->decoded_bytes += b->size; ++v->cur;
            }
        }
        if (v->cur >= v->count) {
            if (v->ended) gr_voice_stop(v);
            else v->flags |= GR_VS_EMPTY;
        }
    }
    float threshold = gr_limiter_threshold < 1.0f ? gr_limiter_threshold : 1.0f;
    int limiter = gr_limiter_on;
    pthread_mutex_unlock(&ngs2_lock);
    /* The mastering limiter (the game enables it at 1.0): a block whose peak passes the threshold
     * is brought under it, ramping the gain across the block (no clicks), and the gain recovers
     * over about 100 ms. Without it loud moments clip hard. A final clamp stays as a guard. */
    float peak = 0;
    for (size_t i = 0; out && i < (size_t)samples * channels; ++i) {
        float a = out[i] < 0 ? -out[i] : out[i];
        if (a > peak) peak = a;
    }
    if (out && samples) {
        float target = limiter && peak * gr_limiter_gain > threshold ? threshold / peak : gr_limiter_gain;
        if (target >= gr_limiter_gain) target = gr_limiter_gain + (1.0f - gr_limiter_gain) * 0.05f; /* release */
        if (target > 1.0f) target = 1.0f;
        if (limiter && peak * target > threshold) target = threshold / peak;
        float from = gr_limiter_gain;
        for (uint32_t s = 0; s < samples; ++s) {
            float k = from + (target - from) * (float)(s + 1) / (float)samples;
            for (uint32_t c = 0; c < channels; ++c) {
                float x = out[(size_t)s * channels + c] * k;
                out[(size_t)s * channels + c] = x > 1.0f ? 1.0f : x < -1.0f ? -1.0f : x;
            }
        }
        gr_limiter_gain = target;
        peak *= target;
    }
    if (report)
        printf("Audio trace: NGS2 render %u playing=%u empty=%u paused=%u unmixed=%u (type 0x%x) peak=%.4f\n",
               renders, playing, empty, paused, unmixed, unmixed_type, peak);
}

static void gr_voice_state(uintptr_t handle, void *state, uint64_t size) {
    if (!state || !size) return;
    pthread_mutex_lock(&ngs2_lock);
    GrVoice *v = gr_voice_find(handle, 0);
    GrNgs2SamplerState s = {.envelope = 1.0f};
    if (v) {
        s.flags = v->flags;
        s.decoded_samples = (uint64_t)v->decoded;
        s.decoded_bytes = v->decoded_bytes;
        if (v->cur < v->count) {
            const GrNgs2Block *b = &v->blocks[v->cur];
            double length = (double)b->samples;
            if (length > 0) s.decoded_bytes += (uint64_t)((double)b->size * (v->in_block < length ? v->in_block : length) / length);
            s.user = b->user;
            s.data = v->block_data[v->cur] + b->offset;
        }
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
