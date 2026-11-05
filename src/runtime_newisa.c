/* BMI1 (ANDN, BEXTR, BLSI, BLSMSK, BLSR, TZCNT), LZCNT and MOVBE on CPUs without them.
 *
 * The PS4's Jaguar CPU has all of them and the game's code (eboot, libc.prx, libSceFios2.prx) uses
 * them; Intel CPUs before Haswell (2013) have none. There ANDN & co. stop with an illegal
 * instruction, and LZCNT/TZCNT are worse: without the feature their encoding runs as BSR/BSF and
 * returns other values. On such a CPU every known site (gr_isa_sites.inc, image offsets from
 * scripts/gr_isa_sites.py) gets its first byte replaced by 0x06, invalid in 64-bit mode, and the
 * illegal instruction handler emulates the original instruction here. Each site is decoded before
 * it is touched, so another build of the game leaves mismatching sites alone.
 *
 * GOW3_EMULATE_NEW_ISA=1 does the same on any CPU (tests), =0 never; GOW3_NEW_ISA_STATS=1 logs
 * how many instructions were emulated every 5 s. */
#include "runtime.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#include <intrin.h>
#endif

typedef struct { uint32_t offset; uint8_t length, kind; } IsaSite;
enum { K_ANDN, K_BEXTR, K_BLSI, K_BLSMSK, K_BLSR, K_TZCNT, K_LZCNT, K_MOVBE };
static const IsaSite sites[] = {
#include "gr_isa_sites.inc"
};
enum { SITE_COUNT = sizeof(sites) / sizeof(sites[0]) };
static uint8_t original_bytes[SITE_COUNT][16];
static uint8_t site_patched[SITE_COUNT];
static unsigned char *isa_image;
static volatile long emulated_count;
/* GOW3_NEW_ISA_STATS=1: emulations per site, to find the hot ones (a trap costs microseconds). */
static int count_sites;
static volatile long site_hits[SITE_COUNT];
static uint8_t site_trap[SITE_COUNT];

/* A decoded instruction of the kinds above. */
typedef struct {
    int kind, size;          /* operand size in bytes: 2, 4 or 8 */
    int reg, vreg;           /* ModRM.reg (with REX/VEX.R) and VEX.vvvv */
    int is_mem, rm;          /* register operand when !is_mem */
    int base, index, scale;  /* memory operand: base/index -1 when absent, base -2 = RIP */
    int64_t disp;
    int length;
} Insn;

/* Decodes the instruction in `at` (its real first byte already restored). 0: not one of ours. */
static int decode(const unsigned char *at, Insn *d) {
    int p = 0, rex = 0, opsize16 = 0, rep = 0, wide = 0, rx = 0, xx = 0, bx = 0, op, map;
    memset(d, 0, sizeof(*d));
    for (;; ++p) {
        if (at[p] == 0x66) opsize16 = 1;
        else if (at[p] == 0xf3) rep = 1;
        else if (at[p] == 0xf2 || at[p] == 0x64 || at[p] == 0x65 || at[p] == 0xf0) return 0;
        else break;
    }
    if (at[p] == 0xc4) {
        const unsigned char b1 = at[p + 1], b2 = at[p + 2];
        if (rep || opsize16) return 0;
        rx = !(b1 & 0x80); xx = !(b1 & 0x40); bx = !(b1 & 0x20);
        map = b1 & 0x1f;
        wide = (b2 >> 7) & 1;
        d->vreg = (~b2 >> 3) & 15;
        if (map != 2 || (b2 & 7) != 0) return 0; /* 0F38 map, L=0, no implied prefix */
        op = at[p + 3];
        p += 4;
        if (op == 0xf2) d->kind = K_ANDN;
        else if (op == 0xf7) d->kind = K_BEXTR;
        else if (op == 0xf3) {
            const int group = (at[p] >> 3) & 7;
            if (group == 1) d->kind = K_BLSR;
            else if (group == 2) d->kind = K_BLSMSK;
            else if (group == 3) d->kind = K_BLSI;
            else return 0;
        } else return 0;
        d->size = wide ? 8 : 4;
    } else {
        if ((at[p] & 0xf0) == 0x40) { rex = at[p++]; wide = (rex >> 3) & 1; rx = (rex >> 2) & 1; xx = (rex >> 1) & 1; bx = rex & 1; }
        if (at[p++] != 0x0f) return 0;
        op = at[p++];
        if (rep && op == 0xbd) d->kind = K_LZCNT;
        else if (rep && op == 0xbc) d->kind = K_TZCNT;
        else if (!rep && op == 0x38 && (at[p] == 0xf0 || at[p] == 0xf1)) {
            d->kind = K_MOVBE;
            d->vreg = at[p++] == 0xf1; /* 1: store to memory */
        } else return 0;
        d->size = wide ? 8 : opsize16 ? 2 : 4;
    }
    const unsigned char modrm = at[p++];
    const int mod = modrm >> 6;
    d->reg = ((modrm >> 3) & 7) | (rx << 3);
    if (mod == 3) {
        if (d->kind == K_MOVBE) return 0; /* MOVBE takes memory only */
        d->rm = (modrm & 7) | (bx << 3);
    } else {
        d->is_mem = 1;
        d->base = d->index = -1;
        int rm = modrm & 7;
        if (rm == 4) {
            const unsigned char sib = at[p++];
            const int index = ((sib >> 3) & 7) | (xx << 3), base = sib & 7;
            d->scale = 1 << (sib >> 6);
            if (index != 4) d->index = index;
            if (base == 5 && mod == 0) { int32_t v; memcpy(&v, at + p, 4); d->disp = v; p += 4; }
            else d->base = base | (bx << 3);
        } else if (rm == 5 && mod == 0) {
            int32_t v; memcpy(&v, at + p, 4); d->disp = v; p += 4;
            d->base = -2;
        } else d->base = rm | (bx << 3);
        if (mod == 1) { d->disp += (int8_t)at[p]; p += 1; }
        else if (mod == 2) { int32_t v; memcpy(&v, at + p, 4); d->disp += v; p += 4; }
    }
    d->length = p;
    return 1;
}

#ifdef _WIN32
static uint64_t *gpr(uint64_t *c, int n) { return c + n; } /* rax..r15 in encoding order */

static uint64_t fit_size(uint64_t v, int size) {
    return size == 8 ? v : v & ((1ull << (size * 8)) - 1);
}
static void write_reg(uint64_t *c, int n, uint64_t v, int size) {
    uint64_t *r = gpr(c, n);
    if (size == 2) *r = (*r & ~0xffffull) | (v & 0xffff);
    else *r = fit_size(v, size); /* 32-bit results clear the upper half */
}
static uint64_t address_of(uint64_t *c, const Insn *d, uint64_t next_rip) {
    uint64_t a = (uint64_t)d->disp;
    if (d->base == -2) a += next_rip;
    else if (d->base >= 0) a += *gpr(c, d->base);
    if (d->index >= 0) a += *gpr(c, d->index) * (uint64_t)d->scale;
    return a;
}
static uint64_t load(uint64_t address, int size) {
    uint64_t v = 0;
    memcpy(&v, (const void *)(uintptr_t)address, (size_t)size);
    return v;
}
static uint64_t bswap(uint64_t v, int size) {
    if (size == 8) return _byteswap_uint64(v);
    if (size == 4) return _byteswap_ulong((unsigned long)v);
    return (uint64_t)_byteswap_ushort((unsigned short)v);
}

enum { CF = 1u << 0, PF = 1u << 2, AF = 1u << 4, ZF = 1u << 6, SF = 1u << 7, OF = 1u << 11 };

static int find_site(uint64_t offset) {
    int lo = 0, hi = SITE_COUNT - 1;
    while (lo <= hi) {
        const int mid = (lo + hi) / 2;
        if (sites[mid].offset == offset) return mid;
        if (sites[mid].offset < offset) lo = mid + 1; else hi = mid - 1;
    }
    return -1;
}

/* Emulates the instruction in `bytes` (first byte restored) found at `rip` on the registers `c`
 * (rax..r15) and `eflags`. Returns the address of the next instruction, 0 when not one of ours. */
static uint64_t emulate(uint64_t *c, uint64_t *eflags, const unsigned char *bytes, uint64_t rip) {
    Insn d;
    if (!decode(bytes, &d)) return 0;
    const uint64_t next = rip + (uint64_t)d.length;
    const int bits = d.size * 8;
    uint64_t src = d.is_mem ? 0 : fit_size(*gpr(c, d.rm), d.size);
    if (d.is_mem && !(d.kind == K_MOVBE && d.vreg)) src = load(address_of(c, &d, next), d.size);
    uint64_t result = 0;
    uint64_t flags = *eflags & ~(uint64_t)(CF | PF | AF | ZF | SF | OF);
    switch (d.kind) {
    case K_ANDN:
        result = fit_size(~*gpr(c, d.vreg), d.size) & src;
        break;
    case K_BEXTR: {
        const uint64_t control = *gpr(c, d.vreg);
        const unsigned start = control & 0xff, len = (control >> 8) & 0xff;
        result = start >= (unsigned)bits ? 0 : src >> start;
        if (len < (unsigned)bits) result &= (1ull << len) - 1;
        break;
    }
    case K_BLSI:
        result = fit_size(src & (0 - src), d.size);
        if (src) flags |= CF;
        break;
    case K_BLSMSK:
        result = fit_size(src ^ (src - 1), d.size);
        if (!src) flags |= CF;
        break;
    case K_BLSR:
        result = fit_size(src & (src - 1), d.size);
        if (!src) flags |= CF;
        break;
    case K_TZCNT:
        result = 0;
        if (!src) { result = (uint64_t)bits; flags |= CF; }
        else while (!((src >> result) & 1)) ++result;
        break;
    case K_LZCNT:
        result = 0;
        if (!src) { result = (uint64_t)bits; flags |= CF; }
        else while (!((src >> (bits - 1 - result)) & 1)) ++result;
        break;
    case K_MOVBE:
        if (d.vreg) { /* store: memory = bswap(reg) */
            const uint64_t v = bswap(*gpr(c, d.reg), d.size);
            memcpy((void *)(uintptr_t)address_of(c, &d, next), &v, (size_t)d.size);
        } else write_reg(c, d.reg, bswap(src, d.size), d.size);
        InterlockedIncrement(&emulated_count);
        return next;
    }
    result = fit_size(result, d.size);
    if (!result) flags |= ZF;
    if (d.kind != K_TZCNT && d.kind != K_LZCNT && ((result >> (bits - 1)) & 1)) flags |= SF;
    if (d.kind == K_ANDN || d.kind == K_BEXTR) flags &= ~(uint64_t)CF;
    *eflags = flags;
    /* BLSI/BLSMSK/BLSR write VEX.vvvv, the others ModRM.reg. */
    write_reg(c, d.kind == K_BLSI || d.kind == K_BLSMSK || d.kind == K_BLSR ? d.vreg : d.reg, result, d.size);
    InterlockedIncrement(&emulated_count);
    return next;
}


int runtime_newisa_emulate(void *context_record) {
    CONTEXT *c = context_record;
    const unsigned char *at = (const unsigned char *)(uintptr_t)c->Rip;
    unsigned char bytes[16];
    memcpy(bytes, at, sizeof(bytes));
    if (bytes[0] == 0x06) {
        if (!isa_image) return 0;
        const int site = find_site((uint64_t)(at - isa_image));
        if (site < 0 || !site_patched[site]) return 0;
        if (count_sites) InterlockedIncrement(&site_hits[site]);
        memcpy(bytes, original_bytes[site], sizeof(bytes));
    }
    uint64_t flags = c->EFlags;
    const uint64_t next = emulate((uint64_t *)&c->Rax, &flags, bytes, c->Rip);
    if (!next) return 0;
    c->EFlags = (DWORD)flags;
    c->Rip = next;
    return 1;
}

static DWORD WINAPI stats_thread(void *unused) {
    (void)unused;
    static long last_hits[SITE_COUNT];
    for (long last = 0;;) {
        Sleep(5000);
        const long now = emulated_count;
        long traps = 0;
        int top[5] = {-1, -1, -1, -1, -1};
        long top_n[5] = {0};
        for (int i = 0; i < SITE_COUNT; ++i) {
            const long n = site_hits[i] - last_hits[i];
            last_hits[i] += n;
            if (site_trap[i]) traps += n;
            for (int k = 0; k < 5; ++k) {
                if (n > top_n[k]) {
                    for (int j = 4; j > k; --j) { top[j] = top[j - 1]; top_n[j] = top_n[j - 1]; }
                    top[k] = i; top_n[k] = n;
                    break;
                }
            }
        }
        printf("New ISA: %ld instructions emulated in 5 s (%ld in all), %ld of them through traps; busiest:",
               now - last, now, traps);
        for (int k = 0; k < 5 && top[k] >= 0; ++k)
            printf(" 0x%x%s=%ld", sites[top[k]].offset, site_trap[top[k]] ? "(trap)" : "", top_n[k]);
        printf("\n");
        fflush(stdout);
        last = now;
    }
    return 0;
}

static int cpu_has_all(void) {
    int r[4];
    __cpuid(r, 0);
    const int max_leaf = r[0];
    __cpuid(r, 1);
    const int movbe = (r[2] >> 22) & 1;
    int bmi1 = 0;
    if (max_leaf >= 7) { __cpuidex(r, 7, 0); bmi1 = (r[1] >> 3) & 1; }
    __cpuid(r, (int)0x80000001);
    const int lzcnt = (r[2] >> 5) & 1;
    return movbe && bmi1 && lzcnt;
}

/* Sites of 5 bytes or more jump to a per-site stub instead of trapping (an exception costs
 * microseconds and loading screens run ~1M of these a second): the stub keeps the guest's red
 * zone, pushes the site index and goes to newisa_common, which saves the registers, flags and
 * xmm0-5 (the helper's volatile ones), emulates the instruction in C and returns to the next
 * guest instruction with `ret 0x80` (no register or flag touched on the way back). */
uint64_t newisa_stub_helper(uint64_t *regs, uint64_t index, uint64_t *flags);
uint64_t newisa_stub_helper(uint64_t *regs, uint64_t index, uint64_t *flags) {
    const uint64_t rip = (uint64_t)(uintptr_t)(isa_image + sites[index].offset);
    if (count_sites) InterlockedIncrement(&site_hits[index]);
    const uint64_t next = emulate(regs, flags, original_bytes[index], rip);
    if (!next) {
        fprintf(stderr, "New ISA: site 0x%x could not be emulated\n", sites[index].offset);
        fflush(NULL);
        abort();
    }
    return next;
}
__asm__(".text\n.globl newisa_common\nnewisa_common:\n"
        "pushfq\n"
        "sub $224, %rsp\n"
        "mov %rax, 0(%rsp)\nmov %rcx, 8(%rsp)\nmov %rdx, 16(%rsp)\nmov %rbx, 24(%rsp)\n"
        "mov %rbp, 40(%rsp)\nmov %rsi, 48(%rsp)\nmov %rdi, 56(%rsp)\nmov %r8, 64(%rsp)\n"
        "mov %r9, 72(%rsp)\nmov %r10, 80(%rsp)\nmov %r11, 88(%rsp)\nmov %r12, 96(%rsp)\n"
        "mov %r13, 104(%rsp)\nmov %r14, 112(%rsp)\nmov %r15, 120(%rsp)\n"
        "lea 0x170(%rsp), %rax\nmov %rax, 32(%rsp)\n" /* the guest's rsp: 224 + flags + index + red zone */
        "movdqu %xmm0, 128(%rsp)\nmovdqu %xmm1, 144(%rsp)\nmovdqu %xmm2, 160(%rsp)\n"
        "movdqu %xmm3, 176(%rsp)\nmovdqu %xmm4, 192(%rsp)\nmovdqu %xmm5, 208(%rsp)\n"
        "mov %rsp, %rcx\nmov 232(%rsp), %rdx\nlea 224(%rsp), %r8\n"
        "mov %rsp, %rbx\nand $-16, %rsp\nsub $32, %rsp\ncld\n"
        "call newisa_stub_helper\n"
        "mov %rbx, %rsp\nmov %rax, 232(%rsp)\n"
        "movdqu 128(%rsp), %xmm0\nmovdqu 144(%rsp), %xmm1\nmovdqu 160(%rsp), %xmm2\n"
        "movdqu 176(%rsp), %xmm3\nmovdqu 192(%rsp), %xmm4\nmovdqu 208(%rsp), %xmm5\n"
        "mov 8(%rsp), %rcx\nmov 16(%rsp), %rdx\nmov 24(%rsp), %rbx\nmov 40(%rsp), %rbp\n"
        "mov 48(%rsp), %rsi\nmov 56(%rsp), %rdi\nmov 64(%rsp), %r8\nmov 72(%rsp), %r9\n"
        "mov 80(%rsp), %r10\nmov 88(%rsp), %r11\nmov 96(%rsp), %r12\nmov 104(%rsp), %r13\n"
        "mov 112(%rsp), %r14\nmov 120(%rsp), %r15\nmov 0(%rsp), %rax\n"
        "add $224, %rsp\n"
        "popfq\n"
        "ret $0x80\n");
extern unsigned char newisa_common[];

/* Executable memory within 2 GB after the image for the per-site stubs (jmp rel32 from the site). */
static unsigned char *stub_memory(unsigned char *image, uint64_t image_size, size_t bytes) {
    uintptr_t at = ((uintptr_t)image + image_size + 0xffff) & ~(uintptr_t)0xffff;
    for (int i = 0; i < 16384; ++i, at += 0x10000) {
        void *p = VirtualAlloc((void *)at, bytes, MEM_RESERVE | MEM_COMMIT, PAGE_EXECUTE_READWRITE);
        if (p) return p;
    }
    return NULL;
}

/* Called once the game and its modules are mapped and relocated, while the image is writable. */
void runtime_newisa_install(unsigned char *image, uint64_t image_size) {
    const char *env = getenv("GOW3_EMULATE_NEW_ISA");
    const int force = env && env[0] == '1', never = env && env[0] == '0';
    if (never || (!force && cpu_has_all())) return;
    isa_image = image;
    const char *stub_env = getenv("GOW3_NEW_ISA_STUBS");
    enum { STUB = 32 };
    unsigned char *stubs = stub_env && stub_env[0] == '0' ? NULL : stub_memory(image, image_size, (size_t)SITE_COUNT * STUB);
    int jumps = 0, traps = 0, skipped = 0;
    for (int i = 0; i < SITE_COUNT; ++i) {
        Insn d;
        unsigned char *at = image + sites[i].offset;
        if (sites[i].offset + 16u > image_size || !decode(at, &d) ||
            d.length != sites[i].length || d.kind != sites[i].kind) {
            printf("New ISA: site 0x%x left alone (not the expected instruction)\n", sites[i].offset);
            ++skipped;
            continue;
        }
        memcpy(original_bytes[i], at, 16);
        unsigned char *stub = stubs ? stubs + (size_t)i * STUB : NULL;
        const int64_t rel = stub ? (int64_t)(stub - (at + 5)) : 0;
        if (stub && d.length >= 5 && rel == (int32_t)rel) {
            /* lea rsp,[rsp-0x80]; push i; jmp [rip+0]; dq newisa_common */
            static const unsigned char head[5] = {0x48, 0x8d, 0x64, 0x24, 0x80};
            memcpy(stub, head, 5);
            stub[5] = 0x68;
            const uint32_t index = (uint32_t)i;
            memcpy(stub + 6, &index, 4);
            stub[10] = 0xff; stub[11] = 0x25; memset(stub + 12, 0, 4);
            const uint64_t common = (uint64_t)(uintptr_t)newisa_common;
            memcpy(stub + 16, &common, 8);
            at[0] = 0xe9;
            const int32_t rel32 = (int32_t)rel;
            memcpy(at + 1, &rel32, 4);
            memset(at + 5, 0xcc, (size_t)d.length - 5); /* never reached: the stub returns past it */
            ++jumps;
        } else {
            at[0] = 0x06;
            site_trap[i] = 1;
            ++traps;
        }
        site_patched[i] = 1;
    }
    printf("New ISA: %s; %d BMI1/LZCNT/MOVBE sites emulated (%d through stubs, %d through traps), %d left alone\n",
           force ? "emulation forced (GOW3_EMULATE_NEW_ISA=1)" : "this CPU lacks BMI1, LZCNT or MOVBE",
           jumps + traps, jumps, traps, skipped);
    FlushInstructionCache(GetCurrentProcess(), NULL, 0);
    const char *stats = getenv("GOW3_NEW_ISA_STATS");
    if (stats && stats[0] == '1') {
        count_sites = 1;
        CloseHandle(CreateThread(NULL, 0, stats_thread, NULL, 0, NULL));
    }
}
#else
int runtime_newisa_emulate(void *context_record) { (void)context_record; return 0; }
void runtime_newisa_install(unsigned char *image, uint64_t image_size) { (void)image; (void)image_size; (void)decode; }
#endif
