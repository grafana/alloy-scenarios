FROM mcr.microsoft.com/dotnet/sdk:9.0@sha256:f9ddb8a31ae90f4b38d18355d82f03d76dcdd2a57d7235a2ffdf008fab11a862 AS build
WORKDIR /app

COPY *.csproj .
RUN dotnet restore

COPY . .
RUN dotnet publish -c Release -o out

FROM mcr.microsoft.com/dotnet/runtime:9.0@sha256:3373de56b087f49f8a594088206aef89e306a49c246b583e1eada6a88f0fccec
WORKDIR /app
COPY --from=build /app/out .

ENTRYPOINT ["dotnet", "LoggingExample.dll"] 