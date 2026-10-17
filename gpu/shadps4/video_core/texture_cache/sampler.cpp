// SPDX-FileCopyrightText: Copyright 2024 shadPS4 Emulator Project
// SPDX-License-Identifier: GPL-2.0-or-later

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include "video_core/renderer_vulkan/liverpool_to_vk.h"
#include "video_core/renderer_vulkan/vk_instance.h"
#include "video_core/texture_cache/sampler.h"

namespace VideoCore {

Sampler::Sampler(const Vulkan::Instance& instance, const AmdGpu::Sampler& sampler,
                 const AmdGpu::BorderColorBuffer border_color_base, const bool is_depth, float extra_lod_bias,
                 int forced_anisotropy) {
    using namespace Vulkan;
    // gow3: forced anisotropic filtering, for mipmapped textures with a linear minification
    // filter only (render targets read by post effects have no mipmaps and stay as they are).
    const bool forced = forced_anisotropy > 1 && !is_depth && sampler.MaxLod() > 0.0f &&
                        sampler.mip_filter != AmdGpu::MipFilter::None &&
                        (sampler.xy_min_filter == AmdGpu::Filter::Bilinear ||
                         sampler.xy_min_filter == AmdGpu::Filter::AnisoLinear);
    const bool anisotropy_enable = instance.IsAnisotropicFilteringSupported() &&
                                   (forced || AmdGpu::IsAnisoFilter(sampler.xy_mag_filter) ||
                                    AmdGpu::IsAnisoFilter(sampler.xy_min_filter));
    const float wanted = forced ? std::max(float(forced_anisotropy), sampler.MaxAniso()) : sampler.MaxAniso();
    const float max_anisotropy =
        anisotropy_enable ? std::clamp(wanted, 1.0f, instance.MaxSamplerAnisotropy()) : 1.0f;
    static const bool trace = std::getenv("GOW3_SAMPLER_TRACE") != nullptr;
    if (trace) {
        std::printf("Sampler: min %u mag %u mip %u lod %.2f-%.2f game aniso %.0f -> %.0f%s\n",
                    u32(sampler.xy_min_filter.Value()), u32(sampler.xy_mag_filter.Value()),
                    u32(sampler.mip_filter.Value()), sampler.MinLod(), sampler.MaxLod(),
                    sampler.MaxAniso(), max_anisotropy, forced ? " (forced)" : "");
    }
    auto border_color = LiverpoolToVK::BorderColor(sampler.border_color_type);
    if (border_color == vk::BorderColor::eFloatCustomEXT &&
        !instance.IsCustomBorderColorSupported()) {
        LOG_WARNING(Render_Vulkan, "Custom border color is not supported, falling back to black");
        border_color = vk::BorderColor::eFloatOpaqueBlack;
    }

    const auto custom_color = [&]() -> std::optional<vk::SamplerCustomBorderColorCreateInfoEXT> {
        if (border_color == vk::BorderColor::eFloatCustomEXT) {
            const auto border_color_index = sampler.border_color_ptr.Value();
            const auto border_color_buffer = border_color_base.Address<std::array<float, 4>*>();
            const auto custom_border_color_array = border_color_buffer[border_color_index];

            const vk::SamplerCustomBorderColorCreateInfoEXT ret{
                .customBorderColor =
                    vk::ClearColorValue{
                        .float32 = custom_border_color_array,
                    },
                .format = vk::Format::eR32G32B32A32Sfloat,
            };
            return ret;
        } else {
            return std::nullopt;
        }
    }();

    const vk::SamplerCreateInfo sampler_ci = {
        .pNext = custom_color ? &*custom_color : nullptr,
        .magFilter = LiverpoolToVK::Filter(sampler.xy_mag_filter),
        .minFilter = LiverpoolToVK::Filter(sampler.xy_min_filter),
        .mipmapMode = LiverpoolToVK::MipFilter(sampler.mip_filter),
        .addressModeU = LiverpoolToVK::ClampMode(sampler.clamp_x),
        .addressModeV = LiverpoolToVK::ClampMode(sampler.clamp_y),
        .addressModeW = LiverpoolToVK::ClampMode(sampler.clamp_z),
        .mipLodBias = std::clamp(sampler.LodBias() + extra_lod_bias, -instance.MaxSamplerLodBias(),
                                 instance.MaxSamplerLodBias()),
        .anisotropyEnable = anisotropy_enable,
        .maxAnisotropy = max_anisotropy,
        // GCN compares per instruction; a plain read of a compare sampler is undefined in Vulkan.
        .compareEnable = is_depth,
        .compareOp = LiverpoolToVK::DepthCompare(sampler.depth_compare_func),
        .minLod = sampler.MinLod(),
        .maxLod = sampler.MaxLod(),
        .borderColor = border_color,
        .unnormalizedCoordinates = false, // Handled in shader due to Vulkan limitations.
    };
    auto [sampler_result, smplr] = instance.GetDevice().createSamplerUnique(sampler_ci);
    ASSERT_MSG(sampler_result == vk::Result::eSuccess, "Failed to create sampler: {}",
               vk::to_string(sampler_result));
    handle = std::move(smplr);
}

Sampler::~Sampler() = default;

} // namespace VideoCore
