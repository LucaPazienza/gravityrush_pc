// gow3: stand-in for shadPS4's core/file_sys/fs.h. The font library only uses it to find fonts on
// the PlayStation's system partition, which a PC port does not have: every lookup says "not found".
#pragma once
#include <filesystem>
#include <optional>
#include <string_view>
#include <vector>
#include "common/singleton.h"
#include "common/types.h"

namespace Core::FileSys {
class FileHandle {
public:
    std::optional<std::filesystem::path> GetHostPath() const { return std::nullopt; }
};
class MntPoints {
public:
    std::filesystem::path GetHostPath(std::string_view) const { return {}; }
    std::optional<std::vector<u8>> ReadFile(std::string_view) const { return std::nullopt; }
    std::optional<FileHandle> Open(std::string_view, bool) const { return std::nullopt; }
};
} // namespace Core::FileSys
