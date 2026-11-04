/* runtime_newisa.c against the real instructions (needs a CPU with BMI1, LZCNT and MOVBE).
 * Each case runs the instruction (Win64 ABI wrapper: a in rcx, b in rdx, flags out to [r8]) and
 * then emulates the very same bytes from a CONTEXT with the same inputs. */
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "runtime.h"

#define CASE(name, body)                                   \
    extern unsigned char name##_at[];                      \
    uint64_t name(uint64_t a, uint64_t b, uint64_t *flags); \
    __asm__(".text\n.globl " #name "\n" #name ":\n"       \
            "mov %rdx, %rax\n" #name "_at:\n" body "\n"    \
            "pushfq\npop %r9\nmov %r9, (%r8)\nret\n.globl " #name "_at\n");

/* rax = b on entry; result in rax. */
CASE(t_andn64, "andn %rdx, %rcx, %rax")      /* rax = ~rcx & rdx */
CASE(t_andn32, "andn %edx, %ecx, %eax")
CASE(t_andn_mem, "andn (%rdx), %rcx, %rax")  /* rax = ~rcx & [rdx] */
CASE(t_bextr64, "bextr %rcx, %rdx, %rax")    /* control rcx, source rdx */
CASE(t_bextr32, "bextr %ecx, %edx, %eax")
CASE(t_blsi64, "blsi %rcx, %rax")
CASE(t_blsi32, "blsi %ecx, %eax")
CASE(t_blsr64, "blsr %rcx, %rax")
CASE(t_blsr32, "blsr %ecx, %eax")
CASE(t_blsmsk64, "blsmsk %rcx, %rax")
CASE(t_tzcnt64, "tzcnt %rcx, %rax")
CASE(t_tzcnt32, "tzcnt %ecx, %eax")
CASE(t_tzcnt16, "tzcnt %cx, %ax")
CASE(t_lzcnt64, "lzcnt %rcx, %rax")
CASE(t_lzcnt32, "lzcnt %ecx, %eax")
CASE(t_lzcnt16, "lzcnt %cx, %ax")
CASE(t_lzcnt_r9, "mov %rcx, %r10\nlzcnt %r10, %r11\nmov %r11, %rax") /* REX.R/B; lzcnt is the 2nd line */
CASE(t_movbe_load64, "movbe 8(%rdx), %rax")
CASE(t_movbe_load32, "movbe 8(%rdx), %eax")
CASE(t_movbe_load16, "movbe 8(%rdx), %ax")
CASE(t_movbe_store64, "movbe %rcx, 8(%rdx)\nmov 8(%rdx), %rax")
CASE(t_movbe_store32, "movbe %ecx, 8(%rdx)\nmov 8(%rdx), %rax")

typedef uint64_t (*Fn)(uint64_t, uint64_t, uint64_t *);
typedef struct { const char *name; Fn fn; unsigned char *at; int mem, skip, flags_mask, after; } Case;

static uint64_t state = 0x9e3779b97f4a7c15ull;
static uint64_t rnd(void) {
    state ^= state << 13; state ^= state >> 7; state ^= state << 17;
    switch (state & 7) {
    case 0: return 0;
    case 1: return state & 0xffff;
    case 2: return 1ull << (state >> 58);
    case 3: return state & 0xffffffffull;
    default: return state;
    }
}

int main(void) {
    enum { CF = 1, ZF = 0x40, SF = 0x80, OF = 0x800 };
    const Case cases[] = {
        {"andn64", t_andn64, t_andn64_at, 0, 0, CF | ZF | SF | OF, 0},
        {"andn32", t_andn32, t_andn32_at, 0, 0, CF | ZF | SF | OF, 0},
        {"andn_mem", t_andn_mem, t_andn_mem_at, 1, 0, CF | ZF | SF | OF, 0},
        {"bextr64", t_bextr64, t_bextr64_at, 0, 0, CF | ZF | OF, 0},
        {"bextr32", t_bextr32, t_bextr32_at, 0, 0, CF | ZF | OF, 0},
        {"blsi64", t_blsi64, t_blsi64_at, 0, 0, CF | ZF | SF | OF, 0},
        {"blsi32", t_blsi32, t_blsi32_at, 0, 0, CF | ZF | SF | OF, 0},
        {"blsr64", t_blsr64, t_blsr64_at, 0, 0, CF | ZF | SF | OF, 0},
        {"blsr32", t_blsr32, t_blsr32_at, 0, 0, CF | ZF | SF | OF, 0},
        {"blsmsk64", t_blsmsk64, t_blsmsk64_at, 0, 0, CF | ZF | SF | OF, 0},
        {"tzcnt64", t_tzcnt64, t_tzcnt64_at, 0, 0, CF | ZF, 0},
        {"tzcnt32", t_tzcnt32, t_tzcnt32_at, 0, 0, CF | ZF, 0},
        {"tzcnt16", t_tzcnt16, t_tzcnt16_at, 0, 0, CF | ZF, 0},
        {"lzcnt64", t_lzcnt64, t_lzcnt64_at, 0, 0, CF | ZF, 0},
        {"lzcnt32", t_lzcnt32, t_lzcnt32_at, 0, 0, CF | ZF, 0},
        {"lzcnt16", t_lzcnt16, t_lzcnt16_at, 0, 0, CF | ZF, 0},
        {"lzcnt_r10", t_lzcnt_r9, t_lzcnt_r9_at, 0, 3, CF | ZF, 1},
        {"movbe_load64", t_movbe_load64, t_movbe_load64_at, 1, 0, 0, 0},
        {"movbe_load32", t_movbe_load32, t_movbe_load32_at, 1, 0, 0, 0},
        {"movbe_load16", t_movbe_load16, t_movbe_load16_at, 1, 0, 0, 0},
        {"movbe_store64", t_movbe_store64, t_movbe_store64_at, 1, 0, 0, 2},
        {"movbe_store32", t_movbe_store32, t_movbe_store32_at, 1, 0, 0, 2},
    };
    int failures = 0;
    for (size_t k = 0; k < sizeof(cases) / sizeof(cases[0]); ++k) {
        const Case *t = &cases[k];
        int bad = 0;
        for (int i = 0; i < 20000 && bad < 3; ++i) {
            uint64_t a = rnd(), b = rnd(), memory[2] = {rnd(), rnd()}, saved[2];
            memcpy(saved, memory, sizeof(saved));
            const uint64_t arg_b = t->mem ? (uint64_t)(uintptr_t)memory : b;
            uint64_t real_flags = 0;
            const uint64_t real = t->fn(a, arg_b, &real_flags);
            uint64_t real_mem1 = memory[1];
            memcpy(memory, saved, sizeof(saved));
            CONTEXT c;
            memset(&c, 0, sizeof(c));
            c.Rcx = a; c.Rdx = arg_b; c.Rax = arg_b; c.R10 = a; c.R11 = arg_b;
            c.EFlags = 0x202;
            c.Rip = (DWORD64)(uintptr_t)(t->at + t->skip);
            if (!runtime_newisa_emulate(&c)) { printf("%s: not decoded\n", t->name); bad = 3; break; }
            uint64_t emulated = t->after == 1 ? c.R11 : t->after == 2 ? memory[1] : c.Rax;
            if (t->after == 2) real_mem1 = real; /* the wrapper reloads the stored qword */
            const unsigned ef = (unsigned)c.EFlags & (unsigned)t->flags_mask, rf = (unsigned)real_flags & (unsigned)t->flags_mask;
            if (emulated != (t->after == 2 ? real_mem1 : real) || ef != rf) {
                printf("%s: a=%llx b=%llx real=%llx flags %x, emulated=%llx flags %x\n", t->name, (unsigned long long)a,
                       (unsigned long long)b, (unsigned long long)real, rf, (unsigned long long)emulated, ef);
                ++bad;
            }
        }
        printf("%-14s %s\n", t->name, bad ? "FAILED" : "ok");
        failures += bad != 0;
    }
    printf("%d failures\n", failures);
    return failures != 0;
}
