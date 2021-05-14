#!/usr/bin/python3

# Usage: import-components.py namespace/component#ref [ ... ]

resync_cache_only = False
dry_run = True

# set if using an alternate destination namespace, None to use standard namespace
alt_ns = "temp"

import git
import logging
import os
import pyrpkg
import random
import regex
import string
import sys
import tempfile

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
    sync_repo_merge,
    sync_repo_pull,
)

# brute force configuration
c = {
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

# copy configurable values into lib/distrobaker
distrobaker.dry_run = dry_run
distrobaker.c = c

# extract default value from lib/distrobaker
retry = distrobaker.retry

repo_base = "/home/merlinm/stream-module-testing/repos/%(component)s"

logging.basicConfig(level=logging.DEBUG)

# revised sync_cache() from lib/distrobaker that allows an alternate
# destination namespace to be specified
def sync_cache(comp, sources, ns="rpms", dns=None, scacheurl=None):
    """Synchronizes lookaside cache contents for the given component.
    Expects a set of (filename, hash, hastype) tuples to synchronize, as
    returned by parse_sources().

    :param comp: The component name
    :param sources: The set of source tuples
    :param ns: The component namespace
    :param dns: An alternate destination namespace to use when uploading,
    defaults to value of 'ns'
    :param scacheurl: Optional source lookaside cache url for modular RPM
    components
    :returns: The number of files processed, or None on error
    """
    dns = dns if dns else ns
    if "main" not in c:
        logger.critical("DistroBaker is not configured, aborting.")
        return None
    if comp in c["main"]["control"]["exclude"][ns]:
        logger.critical(
            "The component %s/%s is excluded from sync, aborting.", ns, comp
        )
        return None
    logger.debug("Synchronizing %d cache file(s) for %s/%s.", len(sources), ns, comp)
    if scacheurl:
        if scacheurl != c["main"]["source"]["cache"]["url"]:
            logger.warning(
                "The custom source lookaside cache URL for %s/%s (%s) doesn't "
                "match configuration (%s), ignoring.",
                ns,
                comp,
                scacheurl,
                c["main"]["source"]["cache"]["url"],
            )
    scache = pyrpkg.lookaside.CGILookasideCache(
        "sha512",
        c["main"]["source"]["cache"]["url"],
        c["main"]["source"]["cache"]["cgi"],
    )
    scache.download_path = c["main"]["source"]["cache"]["path"]
    dcache = pyrpkg.lookaside.CGILookasideCache(
        "sha512",
        c["main"]["destination"]["cache"]["url"],
        c["main"]["destination"]["cache"]["cgi"],
    )
    dcache.download_path = c["main"]["destination"]["cache"]["path"]
    tempdir = tempfile.TemporaryDirectory(prefix="cache-{}-{}-".format(ns, comp))
    logger.debug("Temporary directory created: %s", tempdir.name)
    if comp in c["comps"][ns]:
        scname = c["comps"][ns][comp]["cache"]["source"]
        dcname = c["comps"][ns][comp]["cache"]["destination"]
    else:
        scname = c["main"]["defaults"]["cache"]["source"] % {"component": comp}
        dcname = c["main"]["defaults"]["cache"]["source"] % {"component": comp}
    for s in sources:
        # There's no API for this and .upload doesn't let us override it
        dcache.hashtype = s[2]
        for attempt in range(retry):
            try:
                if not dcache.remote_file_exists(
                    "{}/{}".format(dns, dcname), s[0], s[1]
                ):
                    logger.debug(
                        "File %s for %s/%s (%s/%s) not available in the "
                        "destination cache, downloading.",
                        s[0],
                        ns,
                        comp,
                        dns,
                        dcname,
                    )
                    scache.download(
                        "{}/{}".format(ns, scname),
                        s[0],
                        s[1],
                        os.path.join(tempdir.name, s[0]),
                        hashtype=s[2],
                    )
                    logger.debug(
                        "File %s for %s/%s (%s/%s) successfully downloaded.  "
                        "Uploading to the destination cache.",
                        s[0],
                        ns,
                        comp,
                        ns,
                        scname,
                    )
                    if not dry_run:
                        dcache.upload(
                            "{}/{}".format(dns, dcname),
                            os.path.join(tempdir.name, s[0]),
                            s[1],
                        )
                        logger.debug(
                            "File %s for %s/%s (%s/%s) )successfully uploaded "
                            "to the destination cache.",
                            s[0],
                            ns,
                            comp,
                            dns,
                            dcname,
                        )
                    else:
                        logger.debug(
                            "Running in dry run mode, not uploading %s for %s/%s (%s/%s).",
                            s[0],
                            ns,
                            comp,
                            dns,
                            dcname,
                        )
                else:
                    logger.debug(
                        "File %s for %s/%s (%s/%s) already uploaded, skipping.",
                        s[0],
                        ns,
                        comp,
                        dns,
                        dcname,
                    )
            except Exception:
                logger.warning(
                    "Failed attempt #%d/%d handling %s for %s/%s (%s/%s -> %s/%s), retrying.",
                    attempt + 1,
                    retry,
                    s[0],
                    ns,
                    comp,
                    ns,
                    scname,
                    dns,
                    dcname,
                    exc_info=True,
                )
            else:
                break
        else:
            logger.error(
                "Exhausted lookaside cache synchronization attempts for %s/%s "
                "while working on %s, skipping.",
                ns,
                comp,
                s[0],
            )
            return None
    return len(sources)


def import_component(bscm):
    ns = bscm["ns"]
    comp = bscm["comp"]
    ref = bscm["ref"]

    logger.info("Importing %s/%s#%s.", ns, comp, ref)

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
        "ref": ref,
    }
    cdst = cdst % {
        "component": cname,
        "stream": sname,
        "ref": ref,
    }
    sscm = split_scmurl("{}/{}/{}".format(c["main"]["source"]["scm"], ns, csrc))
    dscm = split_scmurl(
        "{}/{}/{}".format(c["main"]["destination"]["scm"], alt_ns if alt_ns else ns, cdst)
    )
    dscm["ref"] = dscm["ref"] if dscm["ref"] else "master"
    logger.debug("source scm = %s", sscm)
    logger.debug("destination scm = %s", dscm)

    gitdir = repo_base % {
        "component": cname,
        "stream": sname,
        "ref": ref,
    }
    logger.debug("repo directory = %s", gitdir)

    # clone desination repo
    repo = clone_destination_repo(ns, comp, dscm, gitdir)
    if repo is None:
        logger.error("Failed to clone destination repo for %s/%s, skipping.", ns, comp)
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

    if resync_cache_only:
        srcdiff = dsrc
    else:
        srcdiff = ssrc - dsrc
    if srcdiff:
        logger.debug("Source files for %s/%s differ.", ns, comp)
        if sync_cache(comp, srcdiff, ns, dns=alt_ns) is None:
            logger.error("Failed to synchronize sources for %s/%s, skipping.", ns, comp)
            return None
    else:
        logger.debug("Source files for %s/%s are up-to-date.", ns, comp)

    logger.debug("Component %s/%s successfully synchronized.", ns, comp)

    if not resync_cache_only:
        if repo_push(ns, comp, repo, dscm) is None:
            logger.error("Failed to push %s/%s, skipping.", ns, comp)
            return None
    else:
        logger.info(
            "Re-syncing cache only; not attempting to push repo for %s/%s.", ns, comp
        )

    logger.info("Successfully synchronized %s/%s.", ns, comp)


def main(argv):
    distrobaker.loglevel(logging.DEBUG)
    logger.debug("Logging configured")

    for rec in argv:
        logger.info("Processing argument %s.", rec)
        bscm = split_scmurl(rec)
        import_component(bscm)


if __name__ == "__main__":
    main(sys.argv[1:])
    pass
