#!/bin/sh

TEST_COMMAND='./test --exitfirst --failed-first'

forwarded_args=""
for arg in "$@"; do
    forwarded_args="$forwarded_args '$arg'"
done

if [ ! -s "$forwarded_args" ]; then
    TEST_COMMAND="$TEST_COMMAND $forwarded_args"
fi

eval $TEST_COMMAND

./venv/bin/watchmedo shell-command \
    --patterns="*.py" \
    --recursive \
    --wait \
    --drop \
    --command "$TEST_COMMAND" \
    tests/ hart/
