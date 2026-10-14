# ---- build stage: compile and shade a fat jar ----
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /app
# Resolve dependencies first so this layer caches across source changes.
COPY pom.xml .
RUN mvn -B -q dependency:go-offline
COPY src ./src
RUN mvn -B -q package

# ---- run stage: slim JRE with just the fat jar ----
FROM eclipse-temurin:25.0.4_7-jre@sha256:bb036ed6cfdc57e3da7c22634d15f1b840d2caf76183861c80e81ca4b5104abb
WORKDIR /app
COPY --from=build /app/target/app.jar app.jar
# Prometheus /metrics is served on 9100 for Alloy to scrape.
EXPOSE 9100
ENTRYPOINT ["java", "-jar", "app.jar"]
