# Contract with the shared CI (github.com/lrozewicz/.github):
#   stage "test"    - runs tests and linters; the build fails if they fail
#   stage "runtime" - the production image: listens on 8080, serves /healthz,
#                     runs as UID 10001 with a read-only root filesystem (/tmp is writable)
# Replace the Go example with your stack, keeping the stage names and the contract.

FROM golang:1.26-alpine AS build
WORKDIR /src
COPY go.mod ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/app .

FROM build AS test
RUN go vet ./... && go test ./...

FROM gcr.io/distroless/static-debian13:nonroot AS runtime
COPY --from=build /out/app /app
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["/app"]
