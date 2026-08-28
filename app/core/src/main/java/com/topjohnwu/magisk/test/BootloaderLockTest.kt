package com.topjohnwu.magisk.test

import androidx.annotation.Keep
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.topjohnwu.magisk.core.Info
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Info.isBootloaderLocked caches per process; test_common.sh toggles props between fresh instrumentation runs. */
@Keep
@RunWith(AndroidJUnit4::class)
class BootloaderLockTest {

    @Test
    fun lockedStateIsReported() {
        assertTrue(Info.isBootloaderLocked)
    }

    @Test
    fun unlockedStateIsReported() {
        assertFalse(Info.isBootloaderLocked)
    }
}
