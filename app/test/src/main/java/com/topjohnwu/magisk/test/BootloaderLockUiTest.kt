package com.topjohnwu.magisk.test

import android.os.ParcelFileDescriptor.AutoCloseInputStream
import androidx.annotation.Keep
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import org.junit.After
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Regression tests for the bootloader-lock UI guard introduced in bf2e846
 * (hide direct install / uninstall when the bootloader is locked).
 *
 * Runs against the real app UI with UiAutomator. The lock state comes from
 * ro.boot.vbmeta.device_state, toggled with resetprop through Magisk's su.
 * Because Info.isBootloaderLocked caches the value per process, every state
 * change is followed by an app restart.
 */
@Keep
@RunWith(AndroidJUnit4::class)
class BootloaderLockUiTest {

    companion object {
        private const val APP_PKG = "com.topjohnwu.magisk"
        private const val LOCK_STATE_PROP = "ro.boot.vbmeta.device_state"

        private const val UNINSTALL = "Uninstall Magisk"
        private const val DIRECT_INSTALL = "Direct install (Recommended)"
        private const val PATCH_FILE = "Select and patch a file"

        // The home card action label depends on environment state
        // (Reinstall/Install/Update), so accept all of them as "home ready".
        private val ACTION_LABELS = arrayOf("Reinstall", "Install", "Update")

        private const val TIMEOUT_MS = 15_000L
        private const val GRACE_MS = 3_000L
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

    // resetprop lives in the magisk tmp dir (e.g. /debug_ramdisk on emulators),
    // not on the default PATH — same reason scripts prefix /debug_ramdisk.
    private fun resetProp(state: String) {
        val candidates = listOf(
            "su -c 'PATH=\$PATH:/debug_ramdisk resetprop $LOCK_STATE_PROP $state'",
            "su -c '/debug_ramdisk/resetprop $LOCK_STATE_PROP $state'",
            "su -c '/debug_ramdisk/magisk resetprop $LOCK_STATE_PROP $state'"
        )
        var lastOut = ""
        for (cmd in candidates) {
            lastOut = shell(cmd)
            if (shell("getprop $LOCK_STATE_PROP").trim() == state) return
        }
        throw AssertionError(
            "could not set $LOCK_STATE_PROP='$state' " +
                "(current='${shell("getprop $LOCK_STATE_PROP").trim()}', last output: ${lastOut.trim().ifEmpty { "<empty>" }})"
        )
    }

    private fun setLockStateAndRestart(state: String) {
        val suCheck = shell("su -c id")
        assertTrue(
            "su is unavailable, cannot toggle lock state: $suCheck",
            suCheck.contains("uid=0")
        )

        resetProp(state)

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

    /** True if [text] shows up within [timeout]; used both for presence and short-grace absence checks. */
    private fun waitText(text: String, timeout: Long = GRACE_MS): Boolean {
        val deadline = System.currentTimeMillis() + timeout
        while (System.currentTimeMillis() < deadline) {
            if (device.findObject(By.text(text)) != null) return true
            Thread.sleep(250)
        }
        return false
    }

    private fun openInstallSheet() {
        val action = awaitAnyOf(*ACTION_LABELS)
        assertNotNull("No install action button found on home screen", action)
        val button = action?.let { device.findObject(By.text(it)) }
        assertNotNull("Action button disappeared before it could be tapped", button)
        button!!.click()
        // Positive control: this row exists regardless of lock state,
        // so reaching it proves the sheet actually opened.
        assertTrue(
            "Install sheet did not open ($PATCH_FILE never appeared)",
            waitText(PATCH_FILE, TIMEOUT_MS)
        )
    }

    @Test
    fun testBootloaderLockTogglesInstallSurfaces() {
        // --- Locked: destructive surfaces hidden ---
        setLockStateAndRestart("locked")

        assertTrue(
            "$UNINSTALL must be hidden when the bootloader is locked",
            !waitText(UNINSTALL)
        )

        openInstallSheet()
        assertTrue(
            "$DIRECT_INSTALL must be hidden when the bootloader is locked",
            !waitText(DIRECT_INSTALL)
        )
        device.pressBack()

        // --- Unlocked: destructive surfaces restored ---
        setLockStateAndRestart("unlocked")

        assertTrue(
            "$UNINSTALL must be visible when the bootloader is unlocked",
            waitText(UNINSTALL, TIMEOUT_MS)
        )

        openInstallSheet()
        assertTrue(
            "$DIRECT_INSTALL must be visible when the bootloader is unlocked",
            waitText(DIRECT_INSTALL, TIMEOUT_MS)
        )
        device.pressBack()
    }
}
