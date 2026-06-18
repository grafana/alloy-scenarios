# Pinned by digest; renovate's docker manager tracks the base image.
FROM eclipse-temurin:21-jdk@sha256:949f7645022e8cd5cd65eac4b342e7505c86b721b6338f8b677c6f2edc180262

WORKDIR /app
COPY Main.java .
# Precompile rather than using java's source-file launcher, so the flame
# graph frames are plain Main.* methods.
RUN javac Main.java

# DebugNonSafepoints makes the JIT keep debug info outside safepoints,
# which is what gives async-profiler accurate line-level frames. The small
# heap keeps the allocation churn cheap.
CMD ["java", "-Xmx256m", "-XX:+UnlockDiagnosticVMOptions", "-XX:+DebugNonSafepoints", "Main"]
