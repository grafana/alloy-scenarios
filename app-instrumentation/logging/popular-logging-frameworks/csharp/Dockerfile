FROM mcr.microsoft.com/dotnet/sdk:9.0@sha256:0300d42309afd86168fa57d62db79020a34ee396d39c9634844b9c0ab285ea55 AS build
WORKDIR /app

COPY *.csproj .
RUN dotnet restore

COPY . .
RUN dotnet publish -c Release -o out

FROM mcr.microsoft.com/dotnet/runtime:9.0@sha256:7590f1b7e124fe7a4b7cffa5f6f9958f2c02a22bf5bd7a0387a84b88cddf4057
WORKDIR /app
COPY --from=build /app/out .

ENTRYPOINT ["dotnet", "LoggingExample.dll"] 