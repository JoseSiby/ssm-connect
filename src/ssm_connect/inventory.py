# Copyright 2025 Siby Jose
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import sys
from typing import Optional, List, Dict
import boto3
from botocore.config import Config
from botocore.exceptions import NoCredentialsError


def make_boto3_session() -> boto3.Session:
    os.environ.setdefault("AWS_SDK_LOAD_CONFIG", "1")
    return boto3.Session()


def get_session_credentials(session: boto3.Session) -> Dict[str, str]:
    try:
        credentials = session.get_credentials()
        if not credentials:
            return {}
        frozen = credentials.get_frozen_credentials()
        env_creds = {
            "AWS_ACCESS_KEY_ID": frozen.access_key,
            "AWS_SECRET_ACCESS_KEY": frozen.secret_key,
        }
        if frozen.token:
            env_creds["AWS_SESSION_TOKEN"] = frozen.token
        return env_creds
    except NoCredentialsError:
        print("Warning: Could not resolve AWS credentials from the session.", file=sys.stderr)
        return {}


def _get_instance_name(tags: Optional[List[Dict[str, str]]]) -> str:
    if not tags:
        return "Unnamed"
    for tag in tags:
        if tag.get("Key") == "Name":
            return tag.get("Value", "Unnamed")
    return "Unnamed"


def list_running_instances(session: boto3.Session) -> List[Dict[str, str]]:
    ec2 = session.client("ec2", config=Config(retries={"max_attempts": 5}))
    paginator = ec2.get_paginator("describe_instances")
    filters = [{"Name": "instance-state-name", "Values": ["running"]}]
    instances = []
    for page in paginator.paginate(Filters=filters):
        for reservation in page.get("Reservations", []):
            for inst in reservation.get("Instances", []):
                tags = inst.get("Tags") or []
                flat_tags = {tag['Key'].lower(): (tag.get('Value') or '').lower() for tag in tags if 'Key' in tag}
                all_tag_values = ' '.join(flat_tags.values())
                instances.append({
                    "InstanceId": inst.get("InstanceId"),
                    "Name": _get_instance_name(tags),
                    "AllTagsBlob": all_tag_values
                })
    return instances


def list_rds_instances(session: boto3.Session) -> List[Dict[str, str]]:
    rds = session.client("rds", config=Config(retries={"max_attempts": 5}))
    instances = []
    try:
        paginator = rds.get_paginator("describe_db_instances")
        for page in paginator.paginate():
            for db in page.get('DBInstances', []):
                if db.get('DBInstanceStatus') == 'available':
                    endpoint = db.get('Endpoint', {})
                    instances.append({
                        "DBInstanceIdentifier": db.get("DBInstanceIdentifier", ""),
                        "Engine": db.get("Engine", ""),
                        "Endpoint": endpoint.get("Address", ""),
                        "Port": str(endpoint.get("Port", "")),
                    })
    except Exception as e:
        print(f"Error listing RDS instances: {e}", file=sys.stderr)
    return instances


def filter_instances_by_keywords(instances: List[Dict[str, str]], keywords: Optional[List[str]]) -> List[Dict[str, str]]:
    if not keywords:
        return instances
    filtered = []
    for inst in instances:
        search_blob = (
            inst.get("Name", "").lower() + " " +
            inst.get("InstanceId", "").lower() + " " +
            inst.get("AllTagsBlob", "")
        )
        if all(kw in search_blob for kw in keywords):
            filtered.append(inst)
    return filtered
