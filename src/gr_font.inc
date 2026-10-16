/* Gravity Rush: libSceFont, step 1 = TRACE ONLY.
 * Logs the first calls of every font function (arguments in hex) and hands back fake handles.
 * It will be replaced by a real implementation once we know the font format and call order. */
#define GR_FONT_MAX_LOG 12
static uintptr_t gr_font_next_token = 0x7000;
static uintptr_t gr_font_token(void) { return (gr_font_next_token += 0x10); }

static int gr_font_ptr_ok(uint64_t p, size_t n) {
    return p >= 0x10000 && runtime_memory_is_mapped((uintptr_t)p, n);
}
static void gr_font_dump(const char *label, uint64_t addr, size_t n) {
    if (!gr_font_ptr_ok(addr, n)) return;
    const unsigned char *p = (const unsigned char *)(uintptr_t)addr;
    printf("    %s:", label);
    for (size_t i = 0; i < n; ++i) printf(" %02x", p[i]);
    printf("\n");
}
static void gr_font_give(uint64_t where) {
    if (where >= 0x10000 && where < 0x10000000000ull) *(uint64_t *)(uintptr_t)where = gr_font_token();
}
static int gr_font_log(const char *name, unsigned *count, uint64_t a, uint64_t b, uint64_t c, uint64_t d, uint64_t e, uint64_t f) {
    if (++*count > GR_FONT_MAX_LOG) return 0;
    printf("FONT %s(%llx, %llx, %llx, %llx, %llx, %llx)%s\n", name, (unsigned long long)a, (unsigned long long)b,
           (unsigned long long)c, (unsigned long long)d, (unsigned long long)e, (unsigned long long)f,
           *count == GR_FONT_MAX_LOG ? "  [last one logged]" : "");
    fflush(stdout);
    return 1;
}
#define GR_FONT_FN(NAME, ...) \
    static unsigned gr_fc_##NAME; \
    static ABI int32_t gr_font_##NAME(uint64_t a, uint64_t b, uint64_t c, uint64_t d, uint64_t e, uint64_t f) { \
        int logged = gr_font_log(#NAME, &gr_fc_##NAME, a, b, c, d, e, f); \
        (void)logged; (void)a; (void)b; (void)c; (void)d; (void)e; (void)f; \
        __VA_ARGS__ \
        return 0; \
    }

GR_FONT_FN(sceFontMemoryInit, )
GR_FONT_FN(sceFontMemoryTerm, )
GR_FONT_FN(sceFontSupportSystemFonts, )
GR_FONT_FN(sceFontSupportExternalFonts, )
GR_FONT_FN(sceFontCreateLibraryWithEdition, gr_font_give(d);)
GR_FONT_FN(sceFontCreateRendererWithEdition, gr_font_give(d);)
GR_FONT_FN(sceFontOpenFontMemory, if (logged) gr_font_dump("font data (first 16 bytes)", b, 16); gr_font_give(e);)
GR_FONT_FN(sceFontAttachDeviceCacheBuffer, )
GR_FONT_FN(sceFontBindRenderer, )
GR_FONT_FN(sceFontUnbindRenderer, )
GR_FONT_FN(sceFontCloseFont, )
GR_FONT_FN(sceFontDestroyLibrary, )
GR_FONT_FN(sceFontDestroyRenderer, )
GR_FONT_FN(sceFontGetCharGlyphMetrics, )
GR_FONT_FN(sceFontGetKerning, )
GR_FONT_FN(sceFontGetScalePixel, )
GR_FONT_FN(sceFontSetScalePixel, )
GR_FONT_FN(sceFontSetupRenderScalePixel, )
GR_FONT_FN(sceFontRenderCharGlyphImageHorizontal, )
GR_FONT_FN(sceFontRenderSurfaceInit, )

static unsigned gr_fc_select_library, gr_fc_select_renderer;
static ABI uintptr_t gr_font_sceFontSelectLibraryFt(uint64_t a) {
    gr_font_log("sceFontSelectLibraryFt", &gr_fc_select_library, a, 0, 0, 0, 0, 0);
    return gr_font_token();
}
static ABI uintptr_t gr_font_sceFontSelectRendererFt(uint64_t a) {
    gr_font_log("sceFontSelectRendererFt", &gr_fc_select_renderer, a, 0, 0, 0, 0, 0);
    return gr_font_token();
}
