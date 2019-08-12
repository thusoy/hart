#/bin/sh

set -eu

main () {
    docker build -t hart-latest .
    docker run \
        -v $(pwd)/hart:/app/hart \
        -v $(pwd)/hart.toml:/etc/hart.toml \
        --net=host \
        -it hart-latest
}

main
