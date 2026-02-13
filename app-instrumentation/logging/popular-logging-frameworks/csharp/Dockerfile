FROM mcr.microsoft.com/dotnet/sdk:9.0@sha256:03a7d87512a743b3d53416adae79eb89d2a7163de78bb58e7bc7b7e262e25750 AS build
WORKDIR /app

COPY *.csproj .
RUN dotnet restore

COPY . .
RUN dotnet publish -c Release -o out

FROM mcr.microsoft.com/dotnet/runtime:9.0@sha256:1cc59a29be89c6d42acf0e1191f458c20034c0ab213b2646b8af94c836c9e9bf
WORKDIR /app
COPY --from=build /app/out .

ENTRYPOINT ["dotnet", "LoggingExample.dll"] 