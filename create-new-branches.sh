#!/bin/bash

# Usage: create-new-branches.sh namespace/component#ref [ ... ]

dry_run=no

scm_base="ssh://git@gitlab.com/redhat/centos-stream"

for arg in $@
do
    echo "Processing $arg"
    base="${arg%%\#*}"
    if [ "$base" == "$arg" ]
    then
        # no suffix
        ref="master"
    else
        ref="${arg#*\#}"
    fi

    comp="${base##*/}"
    if [ "$comp" == "$base" ]
    then
        ns="unknown"
    else
        ns="${base%/*}"
    fi

    # trim any trailing :stream from module component name
    comp="${comp%%\:*}"

    echo ns="$ns"
    echo comp="$comp"
    echo ref="$ref"

    tmpdir=$(mktemp -d)
    echo tmpdir="$tmpdir"

    scm="$scm_base/temp/$comp"
    echo scm="$scm"

    git clone "$scm" "$tmpdir"
    if [ $? -ne 0 ]
    then
        echo "clone failed, skipping"
        continue
    fi

    pushd "$tmpdir" >/dev/null

    git checkout --orphan "$ref"
    git rm -rf --ignore-unmatch .
    git commit --allow-empty -m "Initialize $ref branch"

    if [ "$dry_run" == "no" ]
    then
        git push --set-upstream origin $ref
    else
        git push --dry-run --set-upstream origin $ref
    fi
    
    popd >/dev/null

    rm -rf $tmpdir
done
