#!/usr/bin/python

import json
import requests

dry_run = True

c = {
    "main": {
        "build": {
            "platform": "el9",
            "scratch": True,
        },
        "destination": {
            "mbs": {
                "api_url": "https://mbs.stream.rdu2.redhat.com/module-build-service/1/",
                "auth_method": "kerberos",
            },
        },
    },
}


def request_module_build(scmurl, branch):
    body = {
        "scmurl": scmurl,
        "branch": branch,
        "buildrequire_overrides": {
            "platform": [c["main"]["build"]["platform"]]
        },
        "scratch": c["main"]["build"]["scratch"],
    }

    request_url = "{}/{}/".format(c["main"]["destination"]["mbs"]["api_url"], "module-builds")

    if c["main"]["destination"]["mbs"]["auth_method"] == "kerberos":
        import requests_kerberos

        data = json.dumps(body)
        auth = requests_kerberos.HTTPKerberosAuth(
            mutual_authentication=requests_kerberos.OPTIONAL,
        )
        if not dry_run:
            resp = requests.post(request_url, data=data, auth=auth)
            if resp.status_code == 401:
                raise ValueError(
                    "MBS authentication using Kerberos failed. "
                    "Make sure you have a valid Kerberos ticket."
                )
        else:
            print("Dry mode. NOT posting build request.")
            print("  auth_method: kerberos")
            print("  request_url: {}".format(request_url))
            print("  data: {}".format(data))
            resp = requests.Response()
            resp.__setstate__({"_content": b"{}"})

    elif c["main"]["destination"]["mbs"]["auth_method"] == "oidc":
        import openidc_client

        if (
            c["main"]["destination"]["mbs"]["oidc_id_provider"] is None
            or c["main"]["destination"]["mbs"]["oidc_client_id"] is None
            or c["main"]["destination"]["mbs"]["oidc_scopes"] is None
        ):
            raise ValueError(
                "The selected authentication method was "
                '"oidc" but the OIDC configuration keyword '
                "arguments were not specified"
            )

        mapping = {"Token": "Token", "Authorization": "Authorization"}
        # Get the auth token using the OpenID client
        oidc = openidc_client.OpenIDCClient(
            "mbs_build",
            c["main"]["destination"]["mbs"]["oidc_id_provider"],
            mapping,
            c["main"]["destination"]["mbs"]["oidc_client_id"],
            c["main"]["destination"]["mbs"]["oidc_client_secret"],
        )
        if not dry_run:
            resp = oidc.send_request(
                request_url,
                http_method="POST",
                json=body,
                scopes=c["main"]["destination"]["mbs"]["oidc_scopes"],
            )
        else:
            print("Dry mode. NOT posting build request.")
            print("  auth_method: oidc")
            print("  request_url: {}".format(request_url))
            print("  json: {}".format(body))
            print(
                "  sscopes: {}".format(
                    c["main"]["destination"]["mbs"]["oidc_scopes"]
                )
            )
            resp = requests.Response()
            resp.__setstate__({"_content": b"{}"})

    else:
        raise ValueError(
            "Unknown MBS auth_method {}".format(
                c["main"]["destination"]["mbs"]["auth_method"]
            )
        )

    print("resp: {}".format(resp))
    print("resp.text: {}".format(resp.text))
    print("resp.json(): {}".format(resp.json()))


request_module_build(
    "https://gitlab.com/redhat/centos-stream/temp/container-tools.git?#5c6b8b9e1b886c0397326f68aaedb3e0e4112205",
    "3.0-rhel-9.0.0-beta",
)
