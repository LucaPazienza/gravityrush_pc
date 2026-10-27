// SPDX-License-Identifier: GPL-2.0-or-later
#undef NDEBUG
#include <cassert>
#include <cstdio>
#include "../gpu/shim/window_cursor.h"

int main() {
    using Frontend::CursorVisibility;
    using Frontend::FullscreenCursorPolicy;
    for (int state = 0; state < 32; ++state) {
        const bool fullscreen = (state & 1) != 0;
        const bool focused = (state & 2) != 0;
        const bool over = (state & 4) != 0;
        const bool port_ui = (state & 8) != 0;
        const bool relative = (state & 16) != 0;
        const auto expected = relative ? CursorVisibility::Keep
            : state == 7 ? CursorVisibility::Hide : CursorVisibility::Show;
        assert(FullscreenCursorPolicy(fullscreen, focused, over, port_ui, relative) == expected);
    }
    static_assert(FullscreenCursorPolicy(false, true, true, false, false) == CursorVisibility::Show);
    static_assert(FullscreenCursorPolicy(true, false, true, false, false) == CursorVisibility::Show);
    static_assert(FullscreenCursorPolicy(true, true, false, false, false) == CursorVisibility::Show);
    static_assert(FullscreenCursorPolicy(true, true, true, true, false) == CursorVisibility::Show);
    static_assert(FullscreenCursorPolicy(true, true, true, false, false) == CursorVisibility::Hide);
    static_assert(FullscreenCursorPolicy(false, true, true, false, true) == CursorVisibility::Keep);
    std::puts("Fullscreen cursor policy: all 32 focus/hover/UI/relative-mode combinations PASS");
}
