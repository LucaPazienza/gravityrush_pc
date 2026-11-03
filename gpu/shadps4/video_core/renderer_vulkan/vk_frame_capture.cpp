// SPDX-License-Identifier: GPL-2.0-or-later
#include "video_core/renderer_vulkan/vk_frame_capture.h"

#include <algorithm>
#include <cstdlib>
#include <ctime>
#include <chrono>
#include <filesystem>
#include <format>
#include <mutex>

#include "video_core/renderer_vulkan/vk_common.h"
#include "video_core/texture_cache/image_info.h"

namespace Vulkan {

namespace {

struct Target {
    VAddr address{};
    vk::Format format{};
    u32 width{}, height{};
    bool operator==(const Target&) const = default;
};

struct Entry {
    bool compute{};
    std::vector<Target> colors;
    Target depth;
    u32 draws{};
    u64 indices{};
    std::vector<u64> shaders; ///< vs/ps pairs (graphics) or cs (compute), first few
    std::vector<std::pair<Target, bool>> sampled; ///< textures (false) and storage images (true)
    std::string note;
    std::vector<std::string> buffers; ///< dumped constants, per draw
};

// GPU thread only.
std::vector<Entry> entries;
std::vector<std::pair<Target, bool>> pending_sampled;
std::vector<std::string> pending_buffers;

void AddBuffers(Entry& entry) {
    // Constants of full-screen passes (post-processing: camera matrices) and of the first draw
    // of each geometry pass; GOW3_CAPTURE_ALL=1: of every draw (2D screens, diagnostics).
    static const bool all = std::getenv("GOW3_CAPTURE_ALL") != nullptr;
    if (entry.draws <= 4 || all) {
        for (auto& b : pending_buffers) {
            entry.buffers.push_back(std::move(b));
        }
    }
    pending_buffers.clear();
}
bool pass_open = false;
std::mutex display_mutex;
std::vector<VAddr> display_buffers;
// gow3: read on every draw; the game registers a handful of display buffers once.
std::array<std::atomic<VAddr>, 16> display_list{};
std::atomic<u32> display_count{0};

Target ToTarget(const VideoCore::ImageInfo& info) {
    return {info.guest_address, info.pixel_format, info.size.width, info.size.height};
}

std::string Describe(const Target& t) {
    if (!t.address) {
        return "-";
    }
    return std::format("{:#x} {} {}x{}", t.address, vk::to_string(t.format), t.width, t.height);
}

void AddSampled(Entry& entry) {
    for (const auto& s : pending_sampled) {
        if (entry.sampled.size() < 32 &&
            std::ranges::find(entry.sampled, s) == entry.sampled.end()) {
            entry.sampled.push_back(s);
        }
    }
    pending_sampled.clear();
}

void AddShader(Entry& entry, u64 hash) {
    if (entry.shaders.size() < 8 && std::ranges::find(entry.shaders, hash) == entry.shaders.end()) {
        entry.shaders.push_back(hash);
    }
}

std::mutex result_mutex;
std::string result; ///< for the menu (FrameCapture::LastResult)

void SetResult(std::string text) {
    std::printf("Frame capture: %s\n", text.c_str());
    std::scoped_lock lk{result_mutex};
    result = std::move(text);
}

// GOW3_CAPTURE_DIR, else <user>/captures (GOW3_GPU_USER_DIR, the saves folder).
std::filesystem::path CaptureDir() {
    if (const char* dir = std::getenv("GOW3_CAPTURE_DIR"); dir && dir[0]) {
        return dir;
    }
    const char* user = std::getenv("GOW3_GPU_USER_DIR");
    return std::filesystem::path(user && user[0] ? user : "user") / "captures";
}

void Write(VAddr presented) {
    const auto dir = CaptureDir();
    std::error_code ec;
    std::filesystem::create_directories(dir, ec);
    const std::time_t now = std::time(nullptr);
    char stamp[32];
    std::strftime(stamp, sizeof(stamp), "%Y%m%d-%H%M%S", std::localtime(&now));
    static u32 sequence = 0;
    const std::string path = (dir / std::format("frame_{}_{}.txt", stamp, ++sequence)).string();
    FILE* f = std::fopen(path.c_str(), "w");
    if (!f) {
        std::printf("Frame capture: cannot write %s\n", path.c_str());
        SetResult("Capture failed: cannot write " + path);
        return;
    }
    std::fprintf(f, "presented buffer %#llx\n", static_cast<unsigned long long>(presented));
    u32 index = 0;
    for (const auto& e : entries) {
        if (e.compute) {
            std::fprintf(f, "\n#%u COMPUTE dispatches %u, cs", index++, e.draws);
        } else {
            std::fprintf(f, "\n#%u PASS draws %u (indices %llu), vs/ps", index++, e.draws,
                         static_cast<unsigned long long>(e.indices));
        }
        for (const u64 h : e.shaders) {
            std::fprintf(f, " %016llx", static_cast<unsigned long long>(h));
        }
        std::fprintf(f, "\n");
        for (size_t i = 0; i < e.colors.size(); ++i) {
            std::fprintf(f, "  color%zu %s\n", i, Describe(e.colors[i]).c_str());
        }
        if (!e.compute) {
            std::fprintf(f, "  depth  %s\n", Describe(e.depth).c_str());
        }
        for (const auto& [t, storage] : e.sampled) {
            std::fprintf(f, "  %s %s\n", storage ? "writes " : "samples", Describe(t).c_str());
        }
        if (!e.note.empty()) {
            std::fprintf(f, "  note: %s\n", e.note.c_str());
        }
        for (const auto& b : e.buffers) {
            std::fprintf(f, "%s\n", b.c_str());
        }
    }
    std::fclose(f);
    std::printf("Frame capture: %zu passes written to %s\n", entries.size(), path.c_str());
    SetResult(std::format("Frame captured ({} passes): {}", entries.size(), path));
}

} // namespace

void FrameCapture::OnFlip(VAddr presented_address) {
    last_presented.store(presented_address, std::memory_order_relaxed);
    flips.fetch_add(1, std::memory_order_release);
    static const char* trigger = std::getenv("GOW3_CAPTURE_TRIGGER");
    if (state.load(std::memory_order_relaxed) != Idle) {
        return;
    }
    bool arm = requested.exchange(false, std::memory_order_acq_rel);
    // The trigger file is looked for 4 times a second, not at every flip.
    static auto next_check = std::chrono::steady_clock::now();
    const auto now = std::chrono::steady_clock::now();
    const bool check = !arm && trigger && now >= next_check;
    if (check) {
        next_check = now + std::chrono::milliseconds(250);
    }
    if (check && std::filesystem::exists(trigger)) {
        std::error_code ec;
        std::filesystem::remove(trigger, ec);
        arm = true;
    }
    if (arm) {
        armed_flip.store(flips.load(std::memory_order_relaxed), std::memory_order_relaxed);
        state.store(Armed, std::memory_order_release);
        std::printf("Frame capture: armed\n");
    }
}

void FrameCapture::Request() {
    SetResult("Capturing the next frame...");
    requested.store(true, std::memory_order_release);
}

std::string FrameCapture::LastResult() {
    std::scoped_lock lk{result_mutex};
    return result;
}

void FrameCapture::Poll() {}

bool FrameCapture::IsDisplayBuffer(VAddr address) {
    const u32 count = display_count.load(std::memory_order_acquire);
    for (u32 i = 0; i < count; ++i) {
        if (display_list[i].load(std::memory_order_relaxed) == address) {
            return true;
        }
    }
    if (count < display_list.size()) {
        return false;
    }
    std::scoped_lock lk{display_mutex};
    return std::ranges::find(display_buffers, address) != display_buffers.end();
}

void FrameCapture::AddDisplayBuffer(VAddr address) {
    std::scoped_lock lk{display_mutex};
    if (std::ranges::find(display_buffers, address) == display_buffers.end()) {
        display_buffers.push_back(address);
        const u32 count = display_count.load(std::memory_order_relaxed);
        if (count < display_list.size()) {
            display_list[count].store(address, std::memory_order_relaxed);
            display_count.store(count + 1, std::memory_order_release);
        }
    }
}

void FrameCapture::BeginPass(const VideoCore::ImageInfo* const* colors, u32 num_colors,
                             const VideoCore::ImageInfo* depth) {
    std::vector<Target> targets;
    bool display = false;
    {
        std::scoped_lock lk{display_mutex};
        for (u32 i = 0; i < num_colors; ++i) {
            targets.push_back(colors[i] ? ToTarget(*colors[i]) : Target{});
            display |= colors[i] && std::ranges::find(display_buffers, colors[i]->guest_address) !=
                                        display_buffers.end();
        }
    }
    // Frame boundaries in the command stream: the pass that writes a display buffer as its only
    // target. gow3: a game may also draw scene passes (two targets) into display buffers.
    display = display && targets.size() == 1;
    const bool new_pass = !(pass_open && !entries.empty() && !entries.back().compute &&
                            entries.back().colors == targets);
    (void)new_pass;
    (void)display;
    // Gravity Rush: everything the GPU draws between the second flip after the request and
    // GOW3_CAPTURE_FRAMES (default 2) flips later is recorded, wherever the passes start.
    static const u64 frames = [] {
        const char* env = std::getenv("GOW3_CAPTURE_FRAMES");
        return env ? u64(std::clamp(std::atoi(env), 1, 600)) : u64(2);
    }();
    const u64 flip = flips.load(std::memory_order_acquire);
    const u64 armed = armed_flip.load(std::memory_order_relaxed);
    if (state.load(std::memory_order_relaxed) == Armed && flip >= armed + 2) {
        entries.clear();
        pending_sampled.clear();
        pending_buffers.clear();
        pass_open = false;
        state.store(Recording, std::memory_order_release);
    }
    if (state.load(std::memory_order_relaxed) == Recording && flip >= armed + 2 + frames) {
        Write(last_presented.load(std::memory_order_relaxed));
        entries.clear();
        pending_sampled.clear();
        pending_buffers.clear();
        state.store(Idle, std::memory_order_release);
        return;
    }
    if (state.load(std::memory_order_relaxed) != Recording) {
        pending_sampled.clear();
        pending_buffers.clear();
        return;
    }
    const Target d = depth ? ToTarget(*depth) : Target{};
    if (pass_open && !entries.empty() && !entries.back().compute &&
        entries.back().colors == targets && entries.back().depth == d) {
        return;
    }
    entries.push_back({.compute = false, .colors = std::move(targets), .depth = d});
    pass_open = true;
    static u64 marked_flip = ~u64(0);  // which frame each pass belongs to (long captures)
    if (frames > 2 && flip != marked_flip) {
        marked_flip = flip;
        entries.back().note += "[flip " + std::to_string(flip - armed) + "]";
    }
}

void FrameCapture::Draw(u64 vs_hash, u64 ps_hash, u32 num_indices, u32 num_instances) {
    if (state.load(std::memory_order_relaxed) != Recording || entries.empty() ||
        entries.back().compute) {
        return;
    }
    auto& e = entries.back();
    ++e.draws;
    e.indices += u64(num_indices) * std::max(num_instances, 1u);
    static const bool all = std::getenv("GOW3_CAPTURE_ALL") != nullptr;
    if (all) {
        e.buffers.push_back(std::format("  draw {} vs {:016x} ps {:016x} indices {}", e.draws, vs_hash, ps_hash,
                                        num_indices));
    }
    AddShader(e, vs_hash);
    AddShader(e, ps_hash);
    AddSampled(e);
    AddBuffers(e);
}

void FrameCapture::Dispatch(u64 cs_hash, u32 x, u32 y, u32 z) {
    if (state.load(std::memory_order_relaxed) != Recording) {
        pending_sampled.clear();
        pending_buffers.clear();
        return;
    }
    if (!entries.empty() && entries.back().compute && !entries.back().shaders.empty() &&
        entries.back().shaders[0] == cs_hash) {
        ++entries.back().draws;
    } else {
        entries.push_back({.compute = true, .draws = 1, .shaders = {cs_hash}});
        entries.back().note = std::format("groups {}x{}x{}", x, y, z);
    }
    AddSampled(entries.back());
    AddBuffers(entries.back());
    pass_open = false;
}

void FrameCapture::Buffer(u64 stage_hash, u32 slot, VAddr address, const void* data, u64 size) {
    const u64 bytes = std::min<u64>(size, 1024) & ~u64(3);
    std::string out = std::format("  buffer stage {:016x} slot {} at {:#x} size {}:", stage_hash,
                                  slot, address, size);
    const auto* words = static_cast<const float*>(data);
    for (u64 i = 0; i < bytes / 4; ++i) {
        if (i % 8 == 0) {
            out += std::format("\n    [{:3}]", i);
        }
        out += std::format(" {:12.6g}", words[i]);
    }
    pending_buffers.push_back(std::move(out));
}

void FrameCapture::Sampled(const VideoCore::ImageInfo& info, bool storage) {
    if (pending_sampled.size() < 64) {
        pending_sampled.emplace_back(ToTarget(info), storage);
    }
}

void FrameCapture::Text(std::string line, VAddr address, u64 size, u32 pitch, u32 height) {
    pending_buffers.push_back(std::move(line));
    const auto dir = CaptureDir();
    std::error_code ec;
    std::filesystem::create_directories(dir, ec);
    const std::string path =
        (dir / std::format("text_{:x}_{}x{}.bin", address, pitch, height)).string();
    if (FILE* f = std::fopen(path.c_str(), "wb")) {
        std::fwrite(reinterpret_cast<const void*>(address), 1, size, f);
        std::fclose(f);
    }
}

void FrameCapture::Note(const char* text) {
    if (!entries.empty()) {
        entries.back().note += text;
    }
}

} // namespace Vulkan
