FROM mcr.microsoft.com/dotnet/sdk:9.0@sha256:35048e3a81e6a07c316e7bbbd80d80d2ba705fe5f23a8ed42b6638c8f4c20d30 AS build
WORKDIR /app

COPY *.csproj .
RUN dotnet restore

COPY . .
RUN dotnet publish -c Release -o out

FROM mcr.microsoft.com/dotnet/runtime:9.0@sha256:ee9e6309cef467e134056f9115b31fe3a43ef2959e5b1f42bce0cc97f1b3db3f
WORKDIR /app
COPY --from=build /app/out .

ENTRYPOINT ["dotnet", "LoggingExample.dll"] 