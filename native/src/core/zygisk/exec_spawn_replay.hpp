#pragma once

#include <cstddef>
#include <cstdint>
#include <span>

namespace zygisk {

inline constexpr std::size_t kGrapheneOsNativeForkFlagsIndex = 1;
inline constexpr std::int64_t kGrapheneOsUseZygoteSpawning = 1LL << 3;

inline bool is_grapheneos_exec_spawn_replay_contract(
        std::int64_t native_fork_flags, std::span<const int> fds_to_close) {
    return (native_fork_flags & kGrapheneOsUseZygoteSpawning) == 0 &&
           fds_to_close.size() == 2 &&
           fds_to_close[0] == -1 &&
           fds_to_close[1] == -1;
}

}
