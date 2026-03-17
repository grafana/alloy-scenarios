FROM mcr.microsoft.com/dotnet/sdk:9.0@sha256:13bd3b19e637289720c0ac75d08f0aefa6a4dd933b27a61c2289fd3d26330f34 AS build
WORKDIR /app

COPY *.csproj .
RUN dotnet restore

COPY . .
RUN dotnet publish -c Release -o out

FROM mcr.microsoft.com/dotnet/runtime:9.0@sha256:eebc59756707a8a5dee33786fd1b8f2a0ae0a3172e02e62799da18701e12026d
WORKDIR /app
COPY --from=build /app/out .

ENTRYPOINT ["dotnet", "LoggingExample.dll"] 