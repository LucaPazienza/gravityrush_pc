/* SSE4a (AMD only: EXTRQ, INSERTQ) on CPUs without it, such as every Intel CPU.
 *
 * The PS4's Jaguar CPU has SSE4a and an Unreal Engine 4 game uses INSERTQ in eight places (Unreal Engine 4 code);
 * the port runs that code natively, so an Intel CPU stopped there with an illegal instruction
 * (issue #1). At load each known site, checked byte for byte, becomes a jump to a trampoline doing
 * the same with SSE2 (PEXTRW + PINSRW through RAX, saved below the red zone; flags untouched;
 * MOVQ then clears bits 127:64 as the AMD instruction does).
 * Any other EXTRQ/INSERTQ that still runs is emulated by the fault handler. */
#include "runtime.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <cpuid.h>
#ifdef _WIN32
#include <windows.h>
#endif

/* CPUID 0x80000001 ECX bit 6. GOW3_SSE4A_EMULATE=1 uses the trampolines on any CPU (tests). */
static int sse4a_missing(void) {
    const char *force = getenv("GOW3_SSE4A_EMULATE");
    if (force && *force) return force[0] == '1';
    unsigned a, b, c, d;
    if (!__get_cpuid(0x80000001, &a, &b, &c, &d)) return 1;
    return !(c & (1u << 6));
}

/* CUSA11227 01.00 (Unreal Engine 4): INSERTQ xmmD, xmmS, 16, idx (decoded at these image offsets). */
static const struct { uint32_t offset; unsigned char bytes[7]; unsigned char size; } known[] = {
    {0x233d40e, {0xf2, 0x0f, 0x78, 0xfd, 0x10, 0x10}, 6},       /* insertq xmm7, xmm5, 16, 16 */
    {0x233d438, {0xf2, 0x44, 0x0f, 0x78, 0xcd, 0x10, 0x10}, 7}, /* insertq xmm9, xmm5, 16, 16 */
    {0x233d463, {0xf2, 0x0f, 0x78, 0xf5, 0x10, 0x10}, 6},       /* insertq xmm6, xmm5, 16, 16 */
    {0x233d48d, {0xf2, 0x0f, 0x78, 0xe5, 0x10, 0x10}, 6},       /* insertq xmm4, xmm5, 16, 16 */
    {0x3019b11, {0xf2, 0x0f, 0x78, 0xc1, 0x10, 0x10}, 6},       /* insertq xmm0, xmm1, 16, 16 */
    {0x3019bb1, {0xf2, 0x0f, 0x78, 0xc1, 0x10, 0x30}, 6},       /* insertq xmm0, xmm1, 16, 48 */
    {0x3019e44, {0xf2, 0x0f, 0x78, 0xe3, 0x10, 0x10}, 6},       /* insertq xmm4, xmm3, 16, 16 */
    {0x3019ee4, {0xf2, 0x0f, 0x78, 0xf5, 0x10, 0x30}, 6},       /* insertq xmm6, xmm5, 16, 48 */
};

/* Decoded INSERTQ/EXTRQ at `at`: 0 when not one. */
typedef struct { int insert, reg_form, dst, src, len, idx, size; } Sse4a;
static int decode(const unsigned char *at, Sse4a *out) {
    int p = 0, rex = 0;
    if (at[p] != 0x66 && at[p] != 0xf2) return 0;
    out->insert = at[p++] == 0xf2;
    if ((at[p] & 0xf0) == 0x40) rex = at[p++];
    if (at[p++] != 0x0f) return 0;
    const unsigned char op = at[p++];
    if (op != 0x78 && op != 0x79) return 0;
    const unsigned char modrm = at[p++];
    if ((modrm >> 6) != 3) return 0;
    const int reg = ((modrm >> 3) & 7) | ((rex & 4) << 1), rm = (modrm & 7) | ((rex & 1) << 3);
    out->reg_form = op == 0x79;
    if (out->insert) { out->dst = reg; out->src = rm; }
    else {
        if (!out->reg_form && reg != 0) return 0; /* EXTRQ xmm, imm, imm is /0 */
        out->dst = out->reg_form ? reg : rm; out->src = rm;
    }
    out->len = out->idx = 0;
    if (!out->reg_form) { out->len = at[p] & 63; out->idx = at[p + 1] & 63; p += 2; }
    out->size = p;
    return 1;
}

static unsigned char *trampoline(unsigned char *t, int dst, int src, int word, const unsigned char *back) {
    static const unsigned char save[] = {0x48, 0x8d, 0x64, 0x24, 0x80, 0x50};          /* lea rsp,[rsp-128]; push rax */
    static const unsigned char load[] = {0x58, 0x48, 0x8d, 0xa4, 0x24, 0x80, 0, 0, 0}; /* pop rax; lea rsp,[rsp+128] */
    memcpy(t, save, sizeof(save)); t += sizeof(save);
    *t++ = 0x66; if (src >= 8) *t++ = 0x41;                                            /* pextrw eax, xmmS, 0 */
    *t++ = 0x0f; *t++ = 0xc5; *t++ = (unsigned char)(0xc0 | (src & 7)); *t++ = 0;
    *t++ = 0x66; if (dst >= 8) *t++ = 0x44;                                            /* pinsrw xmmD, eax, word */
    *t++ = 0x0f; *t++ = 0xc4; *t++ = (unsigned char)(0xc0 | ((dst & 7) << 3)); *t++ = (unsigned char)word;
    /* movq xmmD, xmmD: INSERTQ clears bits 127:64 on AMD hardware (measured; documented undefined). */
    *t++ = 0xf3; if (dst >= 8) *t++ = 0x45;
    *t++ = 0x0f; *t++ = 0x7e; *t++ = (unsigned char)(0xc0 | ((dst & 7) << 3) | (dst & 7));
    memcpy(t, load, sizeof(load)); t += sizeof(load);
    const int32_t rel = (int32_t)(back - (t + 5));
    *t++ = 0xe9; memcpy(t, &rel, 4); t += 4;                                           /* jmp back */
    return t;
}

void runtime_sse4a_install(unsigned char *image, size_t image_size, unsigned char *stubs, size_t stubs_size) {
    if (!sse4a_missing() || !image || !stubs) return;
    unsigned char *t = stubs;
    int patched = 0;
    for (size_t i = 0; i < sizeof(known) / sizeof(known[0]); ++i) {
        unsigned char *site = image + known[i].offset;
        Sse4a op;
        if (known[i].offset + 8 > image_size || memcmp(site, known[i].bytes, known[i].size) ||
            !decode(site, &op) || op.size != known[i].size || op.len != 16 || op.idx % 16)
            continue;
        if (t + 64 > stubs + stubs_size) break;
        const int64_t distance = (int64_t)(t - (site + 5));
        if (distance != (int32_t)distance) continue; /* out of jump range: the fault handler emulates it */
        unsigned char *code = t;
        t = trampoline(t, op.dst, op.src, op.idx / 16, site + op.size);
        const int32_t rel = (int32_t)(code - (site + 5));
        site[0] = 0xe9;
        memcpy(site + 1, &rel, 4);
        memset(site + 5, 0x90, (size_t)op.size - 5);
        ++patched;
    }
    printf("SSE4a: this CPU has none; %d of %zu INSERTQ sites use SSE2 trampolines, others are emulated\n",
           patched, sizeof(known) / sizeof(known[0]));
}

#ifdef _WIN32
/* Emulates EXTRQ/INSERTQ at the faulting instruction (Windows CONTEXT XMM registers). */
int runtime_sse4a_emulate(void *context_record) {
    CONTEXT *c = context_record;
    const unsigned char *at = (const unsigned char *)(uintptr_t)c->Rip;
    Sse4a op;
    if (!decode(at, &op)) return 0;
    M128A *xmm = c->FltSave.XmmRegisters;
    uint64_t dst = xmm[op.dst].Low;
    int len = op.len, idx = op.idx;
    if (op.reg_form) {
        const uint64_t control = op.insert ? (uint64_t)xmm[op.src].High : xmm[op.src].Low;
        len = (int)(control & 63);
        idx = (int)((control >> 8) & 63);
    }
    const unsigned bits = len ? (unsigned)len : 64u;
    const uint64_t mask = bits == 64 ? ~0ull : ((1ull << bits) - 1);
    if (op.insert) {
        const uint64_t field = xmm[op.src].Low & mask;
        dst = (dst & ~(mask << idx)) | (field << idx);
    } else {
        dst = (dst >> idx) & mask;
    }
    xmm[op.dst].Low = dst;
    xmm[op.dst].High = 0; /* as AMD hardware leaves it (documented undefined) */
    c->Rip += (DWORD64)op.size;
    return 1;
}
#endif
