FROM mcr.microsoft.com/dotnet/sdk:9.0@sha256:ca77338a19f87a7d24494a3656cb7d878a040c158621337b9cd3ab811c5eb057 AS build
WORKDIR /app

COPY *.csproj .
RUN dotnet restore

COPY . .
RUN dotnet publish -c Release -o out

FROM mcr.microsoft.com/dotnet/runtime:9.0@sha256:1ba87a6c8246f80d6fde1e83fa0bc277200879cfdd5d68df5e40933255ac1ff3
WORKDIR /app
COPY --from=build /app/out .

ENTRYPOINT ["dotnet", "LoggingExample.dll"] 