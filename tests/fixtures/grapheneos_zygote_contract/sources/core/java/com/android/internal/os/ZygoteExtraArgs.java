package com.android.internal.os;

public class ZygoteExtraArgs {
    public interface Flag {
        int DISABLE_HARDENED_MALLOC = 1;
        int ENABLE_COMPAT_VA_39_BIT = 1 << 1;
        int FORCIBLY_ENABLE_MEMORY_TAGGING = 1 << 2;
        int USE_ZYGOTE_SPAWNING = 1 << 3;
        int PREFER_COMPAT_ZYGOTE = 1 << 4;
        int MANUALLY_RUN_ZYGOTE_PRELOAD = 1 << 5;
    }

    private long selinuxFlags;
    private int flags;

    public boolean shouldUseExecSpawning() {
        return !hasFlag(Flag.USE_ZYGOTE_SPAWNING);
    }

    public boolean hasFlag(int flag) { return (flags & flag) == flag; }

    private static final int IDX_SELINUX_FLAGS = 0;
    private static final int IDX_FLAGS = 1;
    private static final int ARR_LEN = 2;

    public long[] makeJniLongArray() {
        long[] res = new long[ARR_LEN];
        res[IDX_SELINUX_FLAGS] = selinuxFlags;
        res[IDX_FLAGS] = flags;
        return res;
    }
}
