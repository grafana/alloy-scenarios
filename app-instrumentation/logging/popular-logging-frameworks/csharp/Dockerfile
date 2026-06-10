FROM mcr.microsoft.com/dotnet/sdk:9.0@sha256:ff12d25929cad887fb9c83e0be843f3cb56ef961fb90623686cd018a988c3675 AS build
WORKDIR /app

COPY *.csproj .
RUN dotnet restore

COPY . .
RUN dotnet publish -c Release -o out

FROM mcr.microsoft.com/dotnet/runtime:9.0@sha256:fa8c81841d934e6a170c2b6dc5075fd78368074bbc2646cfb181a03d5bce2785
WORKDIR /app
COPY --from=build /app/out .

ENTRYPOINT ["dotnet", "LoggingExample.dll"] 