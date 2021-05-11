#!/usr/bin/python3

# Usage: import-components.py namespace/component#ref [ ... ]

import git
import logging
import os
import random
import regex
import string
import sys

# path to the lib directory of a checkout of https://github.com/fedora-eln/distrobaker
sys.path = ["/home/merlinm/github/fedora-eln/distrobaker/lib"] + sys.path
import distrobaker

from distrobaker import (
    clone_destination_repo,
    configure_repo,
    fetch_upstream_repo,
    logger,
    parse_sources,
    repo_push,
    split_module,
    split_scmurl,
    sync_cache,
    sync_repo_merge,
    sync_repo_pull,
)

logging.basicConfig(level=logging.DEBUG)

distrobaker.dry_run = False

# brute force configuration
distrobaker.c = {
    "main": {
        "source": {
            "scm": "git://pkgs.devel.redhat.com",
            "cache": {
                "url": "http://pkgs.devel.redhat.com/repo",
                "cgi": "http://pkgs.devel.redhat.com/lookaside/upload.cgi",
                "path": "%(name)s/%(filename)s/%(hashtype)s/%(hash)s/%(filename)s",
            },
        },
        "destination": {
            "scm": "ssh://git@gitlab.com/redhat/centos-stream",
            "cache": {
                "url": "https://sources.stream.rdu2.redhat.com/sources",
                "cgi": "https://sources.stream.rdu2.redhat.com/lookaside/upload.cgi",
                "path": "%(name)s/%(filename)s/%(hashtype)s/%(hash)s/%(filename)s",
            },
        },
        "git": {
            "author": "Merlin Mathesius",
            "email": "mmathesi@redhat.com",
            "message": "Component import",
        },
        "control": {
            "build": "false",
            "merge": "true",
            "exclude": {
                "rpms": {},
                "modules": {},
            },
        },
        "defaults": {
            "rpms": {
                "source": "%(component)s.git",
                "destination": "%(component)s.git",
            },
            "modules": {
                "source": "%(component)s.git#%(stream)s",
                "destination": "%(component)s.git#%(stream)s",
                "rpms": {
                    "source": "%(component)s.git",
                    "destination": "%(component)s.git#%(ref)s",
                },
            },
            "cache": {
                "source": "%(component)s",
                "destination": "%(component)s",
            },
        },
    },
    "comps": {
        "rpms": {},
        "modules": {},
    },
}

c = distrobaker.c
dry_run = distrobaker.dry_run

repo_base = "/home/merlinm/stream-module-testing/repos/%(component)s"


def main(argv):
    distrobaker.loglevel(logging.DEBUG)
    logger.debug("Logging configured")

    for rec in argv:
        bscm = split_scmurl(rec)
        ns = bscm["ns"]
        comp = bscm["comp"]

        logger.info("Importing %s.", rec)

        if ns == "modules":
            ms = split_module(comp)
            cname = ms["name"]
            sname = ms["stream"]
        else:
            cname = comp
            sname = ""

        if comp in c["comps"][ns]:
            csrc = c["comps"][ns][comp]["source"]
            cdst = c["comps"][ns][comp]["destination"]
        else:
            csrc = c["main"]["defaults"][ns]["source"]
            cdst = c["main"]["defaults"][ns]["destination"]

        # append #ref if not already present
        if "#" not in csrc:
            csrc += "#%(ref)s"
        if "#" not in cdst:
            cdst += "#%(ref)s"

        csrc = csrc % {
            "component": cname,
            "stream": sname,
            "ref": bscm["ref"],
        }
        cdst = cdst % {
            "component": cname,
            "stream": sname,
            "ref": bscm["ref"],
        }
        sscm = split_scmurl("{}/{}/{}".format(c["main"]["source"]["scm"], ns, csrc))
        dscm = split_scmurl(
            #    "{}/{}/{}".format(c["main"]["destination"]["scm"], ns, cdst)
            "{}/{}/{}".format(c["main"]["destination"]["scm"], "temp", cdst)
        )
        dscm["ref"] = dscm["ref"] if dscm["ref"] else "master"
        logger.debug("source scm = %s", sscm)
        logger.debug("destination scm = %s", dscm)

        gitdir = repo_base % {
            "component": cname,
            "stream": sname,
            "ref": bscm["ref"],
        }
        logger.debug("repo directory = %s", gitdir)

        # clone desination repo
        repo = clone_destination_repo(ns, comp, dscm, gitdir)
        if repo is None:
            logger.error(
                "Failed to clone destination repo for %s/%s, skipping.", ns, comp
            )
            return None

        if fetch_upstream_repo(ns, comp, sscm, repo) is None:
            logger.error("Failed to fetch upstream repo for %s/%s, skipping.", ns, comp)
            return None

        if configure_repo(ns, comp, repo) is None:
            logger.error(
                "Failed to configure the git repository for %s/%s, skipping.",
                ns,
                comp,
            )
            return None

        logger.debug("Gathering destination files for %s/%s.", ns, comp)

        dsrc = parse_sources(comp, ns, os.path.join(repo.working_dir, "sources"))
        if dsrc is None:
            logger.error(
                "Error processing the %s/%s destination sources file, skipping.",
                ns,
                comp,
            )
            return None

        if c["main"]["control"]["merge"]:
            if sync_repo_merge(ns, comp, repo, bscm, sscm, dscm) is None:
                logger.error("Failed to sync merge repo for %s/%s, skipping.", ns, comp)
                return None
        else:
            if sync_repo_pull(ns, comp, repo, bscm) is None:
                logger.error("Failed to sync pull repo for %s/%s, skipping.", ns, comp)
                return None

        logger.debug("Gathering source files for %s/%s.", ns, comp)
        ssrc = parse_sources(comp, ns, os.path.join(repo.working_dir, "sources"))
        if ssrc is None:
            logger.error(
                "Error processing the %s/%s source sources file, skipping.",
                ns,
                comp,
            )
            return None

        srcdiff = ssrc - dsrc
        if srcdiff:
            logger.debug("Source files for %s/%s differ.", ns, comp)
            if sync_cache(comp, srcdiff, ns) is None:
                logger.error(
                    "Failed to synchronize sources for %s/%s, skipping.", ns, comp
                )
                return None
        else:
            logger.debug("Source files for %s/%s are up-to-date.", ns, comp)

        logger.debug("Component %s/%s successfully synchronized.", ns, comp)

        if repo_push(ns, comp, repo, dscm) is None:
            logger.error("Failed to push %s/%s, skipping.", ns, comp)
            return None
        logger.info("Successfully synchronized %s/%s.", ns, comp)


if __name__ == "__main__":
    main(sys.argv[1:])
    pass
