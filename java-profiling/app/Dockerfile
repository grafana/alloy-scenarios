# Pinned by digest; renovate's docker manager tracks the base image.
FROM eclipse-temurin:25.0.3_9-jdk@sha256:68868d04fa9cfd5f5c6abec0b5cef86d8de2bf9c62c37c7d3e4f0f80f5cfd7ff

WORKDIR /app
COPY Main.java .
# Precompile rather than using java's source-file launcher, so the flame
# graph frames are plain Main.* methods.
RUN javac Main.java

# DebugNonSafepoints makes the JIT keep debug info outside safepoints,
# which is what gives async-profiler accurate line-level frames. The small
# heap keeps the allocation churn cheap.
CMD ["java", "-Xmx256m", "-XX:+UnlockDiagnosticVMOptions", "-XX:+DebugNonSafepoints", "Main"]
