#/bin/sh

set -eu

main () {
    docker build -t hart-latest .
    docker run \
        -v $(pwd)/hart:/app/hart \
        -v $(pwd)/hart.toml:/etc/hart.toml \
        -p 4505:4505 \
        -p 4506:4506 \
        -it hart-latest
}

main
