# Pinned by digest; renovate's docker manager tracks the base image.
FROM eclipse-temurin:25.0.3_9-jdk@sha256:201fbb8886b2d273218aa3a192f0afbf7b5ff65ee8cc6ef47f5dce2171f013ea

WORKDIR /app
COPY Main.java .
# Precompile rather than using java's source-file launcher, so the flame
# graph frames are plain Main.* methods.
RUN javac Main.java

# DebugNonSafepoints makes the JIT keep debug info outside safepoints,
# which is what gives async-profiler accurate line-level frames. The small
# heap keeps the allocation churn cheap.
CMD ["java", "-Xmx256m", "-XX:+UnlockDiagnosticVMOptions", "-XX:+DebugNonSafepoints", "Main"]
