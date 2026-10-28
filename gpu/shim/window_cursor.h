// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once

namespace Frontend {
enum class CursorVisibility { Keep, Show, Hide };

// SDL owns visibility during relative mouse-look capture. Otherwise both borderless
// and exclusive fullscreen hide the gameplay pointer, but never desktop/windowed or UI cursors.
constexpr CursorVisibility FullscreenCursorPolicy(bool fullscreen, bool focused, bool mouse_over,
                                                  bool port_ui, bool relative_mouse) {
    if (relative_mouse) {
        return CursorVisibility::Keep;
    }
    return fullscreen && focused && mouse_over && !port_ui ? CursorVisibility::Hide : CursorVisibility::Show;
}
} // namespace Frontend
