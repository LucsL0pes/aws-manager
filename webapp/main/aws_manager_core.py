import subprocess
import json
import hashlib
from configparser import ConfigParser
from pathlib import Path
from typing import List, Dict

import boto3

SSO_PROFILE = "IAM"
ROUTE53_SEARCH_ACCOUNT_ID = "979633380910"


def get_sso_config_value(profile_name: str, key: str) -> str | None:
    """Reads a value from the AWS config file."""
    try:
        config_path = Path.home() / ".aws" / "config"
        parser = ConfigParser()
        parser.read(config_path)

        section = f"profile {profile_name}" if profile_name else "default"
        if not parser.has_section(section):
            return None
        return parser.get(section, key, fallback=None)
    except Exception:
        return None


def get_sso_token(profile_name: str, sso_start_url: str) -> str | None:
    """Reads the SSO token from the local cache."""
    try:
        sha1 = hashlib.sha1(sso_start_url.encode()).hexdigest()
        cache_path = Path.home() / ".aws" / "sso" / "cache" / f"{sha1}.json"
        if not cache_path.exists():
            return None
        with open(cache_path) as f:
            data = json.load(f)
        return data.get("accessToken")
    except Exception:
        return None


def sso_login(profile: str = SSO_PROFILE) -> tuple[str, str] | None:
    """Performs `aws sso login` and returns the access token and region."""
    profile_arg = ["--profile", profile] if profile else []
    try:
        subprocess.run(["aws"] + profile_arg + ["sso", "login", "--no-browser"], check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    sso_start_url = get_sso_config_value(profile, "sso_start_url")
    sso_region = get_sso_config_value(profile, "sso_region")
    access_token = get_sso_token(profile, sso_start_url)
    if not all([sso_start_url, sso_region, access_token]):
        return None
    return access_token, sso_region


def cloudfront_search(access_token: str, sso_region: str, search_type: str, search_value: str) -> List[Dict]:
    """Searches CloudFront distributions across accounts and returns a list of results."""
    results: List[Dict] = []
    sso_client = boto3.client("sso", region_name=sso_region)
    paginator = sso_client.get_paginator("list_accounts")

    accounts = []
    for page in paginator.paginate(accessToken=access_token):
        accounts.extend(page.get("accountList", []))

    for account in sorted(accounts, key=lambda x: x["accountName"]):
        account_id = account["accountId"]
        account_name = account["accountName"]
        roles = sso_client.list_account_roles(accessToken=access_token, accountId=account_id).get("roleList", [])
        for role in roles:
            role_name = role["roleName"]
            try:
                creds = sso_client.get_role_credentials(roleName=role_name, accountId=account_id, accessToken=access_token).get("roleCredentials", {})
                if not creds:
                    continue
                client = boto3.client(
                    "cloudfront",
                    aws_access_key_id=creds["accessKeyId"],
                    aws_secret_access_key=creds["secretAccessKey"],
                    aws_session_token=creds["sessionToken"],
                )
                paginator_dist = client.get_paginator("list_distributions")
                for page_dist in paginator_dist.paginate():
                    distributions = page_dist.get("DistributionList", {})
                    if "Items" not in distributions:
                        continue
                    for dist in distributions.get("Items", []):
                        match = False
                        if search_type == "Id" and dist.get("Id") == search_value:
                            match = True
                        elif search_type == "DomainName" and dist.get("DomainName") == search_value:
                            match = True
                        elif search_type == "Aliases" and search_value in dist.get("Aliases", {}).get("Items", []):
                            match = True
                        if match:
                            results.append({
                                "account_name": account_name,
                                "account_id": account_id,
                                "distribution": dist,
                            })
            except Exception:
                continue
    return results


def route53_search(access_token: str, sso_region: str, search_type: str, search_value: str) -> List[Dict]:
    """Searches Route53 records in the target account and returns a list of results."""
    results: List[Dict] = []
    sso_client = boto3.client("sso", region_name=sso_region)

    accounts = sso_client.list_accounts(accessToken=access_token).get("accountList", [])
    target = next((acc for acc in accounts if acc["accountId"] == ROUTE53_SEARCH_ACCOUNT_ID), None)
    if not target:
        return results
    roles = sso_client.list_account_roles(accessToken=access_token, accountId=ROUTE53_SEARCH_ACCOUNT_ID).get("roleList", [])
    if not roles:
        return results

    role_name = roles[0]["roleName"]
    creds = sso_client.get_role_credentials(roleName=role_name, accountId=ROUTE53_SEARCH_ACCOUNT_ID, accessToken=access_token).get("roleCredentials", {})
    if not creds:
        return results

    client = boto3.client(
        "route53",
        aws_access_key_id=creds["accessKeyId"],
        aws_secret_access_key=creds["secretAccessKey"],
        aws_session_token=creds["sessionToken"],
    )

    hosted_zones = client.list_hosted_zones().get("HostedZones", [])
    for zone in hosted_zones:
        zone_id = zone["Id"]
        zone_name = zone["Name"]
        paginator = client.get_paginator("list_resource_record_sets")
        for page in paginator.paginate(HostedZoneId=zone_id):
            for record in page.get("ResourceRecordSets", []):
                match = False
                if search_type == "Name" and search_value.lower() in record.get("Name", "").lower():
                    match = True
                elif search_type == "Value":
                    for rr in record.get("ResourceRecords", []):
                        if search_value.lower() in rr.get("Value", "").lower():
                            match = True
                            break
                if match:
                    results.append({
                        "zone_name": zone_name,
                        "record": record,
                        "account_name": target["accountName"],
                    })
    return results


def cloudfront_search_creds(
    access_key: str,
    secret_key: str,
    session_token: str | None,
    search_type: str,
    search_value: str,
) -> List[Dict]:
    """Searches CloudFront distributions using provided credentials."""
    results: List[Dict] = []
    client = boto3.client(
        "cloudfront",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        aws_session_token=session_token,
    )
    paginator = client.get_paginator("list_distributions")
    for page in paginator.paginate():
        distributions = page.get("DistributionList", {})
        if "Items" not in distributions:
            continue
        for dist in distributions.get("Items", []):
            match = False
            if search_type == "Id" and dist.get("Id") == search_value:
                match = True
            elif search_type == "DomainName" and dist.get("DomainName") == search_value:
                match = True
            elif search_type == "Aliases" and search_value in dist.get("Aliases", {}).get("Items", []):
                match = True
            if match:
                results.append({"distribution": dist})
    return results


def route53_search_creds(
    access_key: str,
    secret_key: str,
    session_token: str | None,
    search_type: str,
    search_value: str,
) -> List[Dict]:
    """Searches Route53 records using provided credentials."""
    results: List[Dict] = []
    client = boto3.client(
        "route53",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        aws_session_token=session_token,
    )

    hosted_zones = client.list_hosted_zones().get("HostedZones", [])
    for zone in hosted_zones:
        zone_id = zone["Id"]
        zone_name = zone["Name"]
        paginator = client.get_paginator("list_resource_record_sets")
        for page in paginator.paginate(HostedZoneId=zone_id):
            for record in page.get("ResourceRecordSets", []):
                match = False
                if search_type == "Name" and search_value.lower() in record.get("Name", "").lower():
                    match = True
                elif search_type == "Value":
                    for rr in record.get("ResourceRecords", []):
                        if search_value.lower() in rr.get("Value", "").lower():
                            match = True
                            break
                if match:
                    results.append({"zone_name": zone_name, "record": record})
    return results
