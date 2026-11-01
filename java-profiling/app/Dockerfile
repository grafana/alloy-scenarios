# Pinned by digest; renovate's docker manager tracks the base image.
FROM eclipse-temurin:25.0.5_8-jdk@sha256:83f4a7fc27df94dcc7b8de04d14cbbba8da14406f921e966969c3b09000aa507

WORKDIR /app
COPY Main.java .
# Precompile rather than using java's source-file launcher, so the flame
# graph frames are plain Main.* methods.
RUN javac Main.java

# DebugNonSafepoints makes the JIT keep debug info outside safepoints,
# which is what gives async-profiler accurate line-level frames. The small
# heap keeps the allocation churn cheap.
CMD ["java", "-Xmx256m", "-XX:+UnlockDiagnosticVMOptions", "-XX:+DebugNonSafepoints", "Main"]
