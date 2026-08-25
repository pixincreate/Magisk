package com.topjohnwu.magisk.test

import androidx.annotation.Keep
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.topjohnwu.magisk.core.Info
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Regression test for the bootloader-lock guard introduced in bf2e846.
 *
 * Info.isBootloaderLocked is a val computed once per process from
 * ro.boot.vbmeta.device_state (falling back to ro.boot.flash.locked),
 * so test_common.sh toggles both props via Environment#setupBootloader*
 * and then runs each assertion in its own fresh instrumentation process.
 */
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
