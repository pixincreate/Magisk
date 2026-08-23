package com.topjohnwu.magisk.test

import android.os.ParcelFileDescriptor.AutoCloseInputStream
import androidx.annotation.Keep
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import org.junit.After
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Regression test for the bootloader-lock guard introduced in bf2e846:
 * "Uninstall Magisk" must disappear from home while the bootloader reads
 * as locked and return when unlocked.
 *
 * The lock state is toggled by running Environment#setupBootloaderLocked/
 * Unlocked in the app process via nested am instrument, which uses libsu
 * Shell.cmd to call resetprop -n on both ro.boot.vbmeta.device_state and
 * its ro.boot.flash.locked fallback. Because Info.isBootloaderLocked caches
 * per process, every state change is followed by an app restart.
 */
@Keep
@RunWith(AndroidJUnit4::class)
class BootloaderLockUiTest {

    companion object {
        private const val APP_PKG = "com.topjohnwu.magisk"
        private const val TEST_PKG = "$APP_PKG.test"

        private const val UNINSTALL = "Uninstall Magisk"

        // The home card action label depends on environment state
        // (Reinstall/Install/Update), so accept all of them as "home ready".
        private val ACTION_LABELS = arrayOf("Reinstall", "Install", "Update")

        private const val TIMEOUT_MS = 15_000L
    }

    private val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
    private val uiAutomation get() = InstrumentationRegistry.getInstrumentation().uiAutomation

    @After
    fun tearDown() {
        setLockStateAndRestart("unlocked")
    }

    private fun shell(cmd: String): String {
        val pfd = uiAutomation.executeShellCommand(cmd)
        return AutoCloseInputStream(pfd).reader().use { it.readText() }
    }

    // Toggle the lock state by running the corresponding Environment method
    // in the app process via nested am instrument. Environment uses libsu
    // Shell.cmd("resetprop -n ...") where resetprop is on PATH (MAGISKTMP).
    private fun setLockStateAndRestart(state: String) {
        val method = if (state == "locked") "setupBootloaderLocked" else "setupBootloaderUnlocked"
        val pfd = uiAutomation.executeShellCommand(
            "am instrument -w --user 0 -e class .Environment#$method " +
                "$TEST_PKG/${AppTestRunner::class.java.name}"
        )
        val output = AutoCloseInputStream(pfd).reader().use { it.readText() }
        assertTrue(
            "Environment#$method failed to set bootloader $state: $output",
            output.contains("OK (")
        )

        shell("am force-stop $APP_PKG")
        shell("monkey -p $APP_PKG -c android.intent.category.LAUNCHER 1")
        assertNotNull(
            "Magisk home never became ready after restart (state=$state)",
            awaitAnyOf(*ACTION_LABELS)
        )
    }

    private fun awaitAnyOf(vararg texts: String): String? {
        val deadline = System.currentTimeMillis() + TIMEOUT_MS
        while (System.currentTimeMillis() < deadline) {
            texts.firstOrNull { device.findObject(By.text(it)) != null }?.let { return it }
            Thread.sleep(250)
        }
        return null
    }

    /** True if [text] shows up within [timeout]; a false return also proves absence over the window. */
    private fun waitText(text: String, timeout: Long = TIMEOUT_MS): Boolean {
        val deadline = System.currentTimeMillis() + timeout
        while (System.currentTimeMillis() < deadline) {
            if (device.findObject(By.text(text)) != null) return true
            Thread.sleep(250)
        }
        return false
    }

    @Test
    fun testBootloaderLockHidesUninstall() {
        // Locked: the destructive action must be gone
        setLockStateAndRestart("locked")
        assertFalse(
            "$UNINSTALL must be hidden when the bootloader is locked",
            waitText(UNINSTALL)
        )

        // Unlocked: it must come back
        setLockStateAndRestart("unlocked")
        assertTrue(
            "$UNINSTALL must be visible when the bootloader is unlocked",
            waitText(UNINSTALL)
        )
    }
}

