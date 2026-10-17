/* Gravity Rush: NGS2 created from a buffer the game provides (silent renderer, like the
 * allocator variants in runtime_extra.c). Included before the exports[] table. */
typedef struct { void *host_buffer; uint64_t host_buffer_size; void *reserved[5]; void *user_data; } GrNgs2BufferInfo;
#define GR_NGS2_ERR_OUT ((int32_t)0x804A0003)
#define GR_NGS2_BUFFER_SIZE 0x4000u

static ABI int32_t gr_ngs2_system_query(const void *option, GrNgs2BufferInfo *info) {
    (void)option;
    if (!info) return GR_NGS2_ERR_OUT;
    memset(info, 0, sizeof(*info));
    info->host_buffer_size = GR_NGS2_BUFFER_SIZE;
    return 0;
}
static ABI int32_t gr_ngs2_rack_query(uint32_t rack_id, const void *option, GrNgs2BufferInfo *info) {
    (void)rack_id; (void)option;
    if (!info) return GR_NGS2_ERR_OUT;
    memset(info, 0, sizeof(*info));
    info->host_buffer_size = GR_NGS2_BUFFER_SIZE;
    return 0;
}
static ABI int32_t gr_ngs2_system_create(const void *option, const GrNgs2BufferInfo *info, uintptr_t *out) {
    (void)option; (void)info;
    if (!out) return GR_NGS2_ERR_OUT;
    *out = ngs2_token();
    puts("Runtime: NGS2 system created from a caller buffer (silent renderer)");
    return 0;
}
static ABI int32_t gr_ngs2_rack_create(uintptr_t system, uint32_t rack_id, const void *option, const GrNgs2BufferInfo *info, uintptr_t *out) {
    (void)system; (void)option; (void)info;
    if (!out) return GR_NGS2_ERR_OUT;
    *out = ngs2_token();
    ngs2_rack_register(*out, rack_id);
    return 0;
}
