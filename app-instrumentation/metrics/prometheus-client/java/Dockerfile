# ---- build stage: compile and shade a fat jar ----
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /app
# Resolve dependencies first so this layer caches across source changes.
COPY pom.xml .
RUN mvn -B -q dependency:go-offline
COPY src ./src
RUN mvn -B -q package

# ---- run stage: slim JRE with just the fat jar ----
FROM eclipse-temurin:25.0.3_9-jre@sha256:d0eb1b9018b3044da1b7346f39e945f71095749853d69a3aa16b8c99dad9bb45
WORKDIR /app
COPY --from=build /app/target/app.jar app.jar
# Prometheus /metrics is served on 9100 for Alloy to scrape.
EXPOSE 9100
ENTRYPOINT ["java", "-jar", "app.jar"]
