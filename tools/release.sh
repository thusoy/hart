#!/bin/sh

set -eu

if [ $# -ne 1 ]; then
    echo "Usage: ./tools/release <version-number>"
    echo
    echo "The version will be updated in setup.py, built and uploaded to PyPI"
    exit 1
fi

version=$1

main () {
    # clean
    # sanity_check
    # bump_version
    # patch_changelog
    # git_commit
    # build_project
    upload_to_pypi
    git_push
}

clean () {
    rm -rf dist
}

sanity_check () {
    sanity_check_changelog
    sanity_check_git_index
}

sanity_check_changelog () {
    # Ensure there are unreleased changes in the changelog
    grep --quiet 'UNRELEASED -' CHANGELOG.md \
        || (
            echo "There's no UNRELEASED section in the changelog, thus nothing to release."
            exit 1
           )
}

sanity_check_git_index () {
    set +e
    git diff-index --quiet --cached HEAD
    local has_staged_changes=$?
    git diff-files --quiet
    local has_unstaged_changes=$?
    set -e
    local untracked_files="$(git clean -n hart)"
    if [ $has_staged_changes -ne 0 ] || [ $has_unstaged_changes -ne 0 ] ; then
        write_error "You have a dirty index, please stash or commit your changes"
        write_error "before pushing to any of the environments"
        exit 1
    fi
    if [ "$untracked_files" != "" ]; then
        write_error "You have untracked files in the package that would be released:"
        echo "$untracked_files"
        exit 1
    fi
}

write_error () {
    local red=$(tput setaf 1)
    local reset=$(tput sgr0)

    echo >&2 "${red}$@${reset}"
}

bump_version () {
    echo "__version__ = '$version'" > hart/version.py
}

patch_changelog () {
    release_date=$(date -u +"%Y-%m-%d")
    temp_changelog=$(mktemp)
    sed "s/UNRELEASED -[ ]*/$version - $release_date/" \
        < CHANGELOG.md \
        > "$temp_changelog"
    mv "$temp_changelog" CHANGELOG.md
}


git_commit () {
    git add hart/version.py CHANGELOG.md
    git commit --message "Release v$version"
    git tag -m "Release v$version" "v$version"
}

build_project () {
    ./venv/bin/python setup.py sdist bdist_wheel
}

upload_to_pypi () {
    ./venv/bin/twine upload dist/*
}

git_push () {
    git push
    git push --tags
}

main
