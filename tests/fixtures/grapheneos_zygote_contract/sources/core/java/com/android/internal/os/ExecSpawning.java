package com.android.internal.os;

class ExecSpawning {
    static boolean isReplayingZygoteCommands() { return true; }

    static Runnable replay(ZygoteConnection pseudoConnection, ZygoteServer zygoteServer,
            ZygoteArguments cmd) {
        Runnable r = pseudoConnection.processCommand(zygoteServer, false, cmd);
        return r;
    }
}
