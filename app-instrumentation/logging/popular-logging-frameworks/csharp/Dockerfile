FROM mcr.microsoft.com/dotnet/sdk:9.0@sha256:087fc98e5c6ffcea6c3e276c135c4a6717c589d9509a09cc22e7c634830a4db8 AS build
WORKDIR /app

COPY *.csproj .
RUN dotnet restore

COPY . .
RUN dotnet publish -c Release -o out

FROM mcr.microsoft.com/dotnet/runtime:9.0@sha256:d955f883a9e648f0ff80b8bfe01e6b79874c296ef3bbcb5637c6981b64981a9a
WORKDIR /app
COPY --from=build /app/out .

ENTRYPOINT ["dotnet", "LoggingExample.dll"] 