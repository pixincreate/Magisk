namespace ExtraArgsFlag {
    static const int FORCIBLY_ENABLE_MEMORY_TAGGING = 1 << 2;
}

struct ExtraArgs {
    uint64_t selinux_flags = 0;
    int flags = 0;

    ExtraArgs(JNIEnv* env, jlongArray jlongArgs) {
        const size_t num_jlong_args = 2;
        jlong jlong_arr[num_jlong_args];
        env->GetLongArrayRegion(jlongArgs, 0, num_jlong_args, (jlong *) &jlong_arr);
        selinux_flags = (uint64_t) jlong_arr[0];
        flags = (int) jlong_arr[1];
    }
};

static bool gIsExecSpawning = false;

static void DetachDescriptors(JNIEnv* env, const std::vector<int>& fds_to_close, fail_fn_t fail_fn) {
    for (int fd : fds_to_close) {
        if (fd == -1 && gIsExecSpawning) {
            continue;
        }
    }
}

static pid_t ForkCommon() {
    pid_t pid = gIsExecSpawning ? 0 : fork();
    return pid;
}

static const JNINativeMethod gMethods[] = {
        {"nativeForkAndSpecialize",
         "([JII[II[[IILjava/lang/String;Ljava/lang/String;[I[IZLjava/lang/String;Ljava/lang/"
         "String;ZZ[Ljava/lang/String;[Ljava/lang/String;ZZZ)I",
         (void*)com_android_internal_os_Zygote_nativeForkAndSpecialize},
        {"nativeForkSystemServer", "(II[II[[IJJ)I",
         (void*)com_android_internal_os_Zygote_nativeForkSystemServer},
        {"nativeSpecializeAppProcess",
         "([JII[II[[IILjava/lang/String;Ljava/lang/String;ZLjava/lang/String;Ljava/lang/"
         "String;Z[Ljava/lang/String;[Ljava/lang/String;ZZZ)V",
         (void*)com_android_internal_os_Zygote_nativeSpecializeAppProcess},
};
