FROM openjdk:26-slim@sha256:63814a9d8bbea6d39d5ce9c91843bec5e9d9d1d1bc2bade4bb57ba70c0839553

WORKDIR /app

# Download SLF4J API, Logback dependencies, and Jackson for JSON encoding
RUN apt-get update && apt-get install -y wget && \
    wget https://repo1.maven.org/maven2/org/slf4j/slf4j-api/2.0.9/slf4j-api-2.0.9.jar && \
    wget https://repo1.maven.org/maven2/ch/qos/logback/logback-classic/1.4.14/logback-classic-1.4.14.jar && \
    wget https://repo1.maven.org/maven2/ch/qos/logback/logback-core/1.4.14/logback-core-1.4.14.jar && \
    wget https://repo1.maven.org/maven2/com/fasterxml/jackson/core/jackson-core/2.16.1/jackson-core-2.16.1.jar && \
    wget https://repo1.maven.org/maven2/com/fasterxml/jackson/core/jackson-databind/2.16.1/jackson-databind-2.16.1.jar && \
    wget https://repo1.maven.org/maven2/com/fasterxml/jackson/core/jackson-annotations/2.16.1/jackson-annotations-2.16.1.jar && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY App.java .
COPY logback.xml .

RUN javac -cp "slf4j-api-2.0.9.jar:logback-classic-1.4.14.jar:logback-core-1.4.14.jar:jackson-core-2.16.1.jar:jackson-databind-2.16.1.jar:jackson-annotations-2.16.1.jar" App.java

CMD ["java", "-cp", ".:slf4j-api-2.0.9.jar:logback-classic-1.4.14.jar:logback-core-1.4.14.jar:jackson-core-2.16.1.jar:jackson-databind-2.16.1.jar:jackson-annotations-2.16.1.jar", "App"] 