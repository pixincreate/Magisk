package com.android.internal.os;

class ZygoteConnection {
    Runnable processCommand(ZygoteServer zygoteServer, boolean multipleOK, ZygoteArguments command) {
        boolean isReplayingZygoteCommands = ExecSpawning.isReplayingZygoteCommands();
        int [] fdsToClose = { -1, -1 };
        if (!isReplayingZygoteCommands) {
            FileDescriptor fd = mSocket.getFileDescriptor();
            if (fd != null) { fdsToClose[0] = fd.getInt$(); }
            FileDescriptor zygoteFd = zygoteServer.getZygoteSocketFileDescriptor();
            if (zygoteFd != null) { fdsToClose[1] = zygoteFd.getInt$(); }
        }
        boolean shouldUseExecSpawning = !isReplayingZygoteCommands
                && parsedArgs.mExtraArgs.shouldUseExecSpawning();
        return null;
    }
}
