FROM mcr.microsoft.com/dotnet/sdk:9.0@sha256:6416205d95f47e66d4292310710f7d738a4ad8f499c8d2370cf22d29a3c7d4b3 AS build
WORKDIR /app

COPY *.csproj .
RUN dotnet restore

COPY . .
RUN dotnet publish -c Release -o out

FROM mcr.microsoft.com/dotnet/runtime:9.0@sha256:949545c232b0e78c15177f6b60f64d7d6cd835a98279fac506d9a4512a5e0151
WORKDIR /app
COPY --from=build /app/out .

ENTRYPOINT ["dotnet", "LoggingExample.dll"] 