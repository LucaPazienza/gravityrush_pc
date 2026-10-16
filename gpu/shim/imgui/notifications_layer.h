// gow3: stand-in for shadPS4's on-screen notifications. The font library queues a single warning when
// it cannot find the PS4 system fonts; the port shows nothing.
#pragma once
#include <string>

namespace shadNotifications {
enum class position { TopLeft, TopRight, BottomLeft, BottomRight };
enum class stockIcons { shadPS4, Settings, Profiles, Input };
template <class... Rest>
inline void QueueNotification(std::string, float, position, Rest&&...) {}
} // namespace shadNotifications
