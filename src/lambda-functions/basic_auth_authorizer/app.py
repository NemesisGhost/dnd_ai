"""
Lambda Request Authorizer for API Gateway Basic Auth.

Environment:
- SECRET_ID_BASIC_AUTH: Secrets Manager SecretId containing JSON { "username": "...", "password": "..." }

Returns IAM policy: Allow if credentials match; otherwise Deny.
"""
from __future__ import annotations

import base64
import json
import os
from typing import Any, Dict

import boto3

sm = boto3.client("secretsmanager")


def _policy(effect: str, resource: str, principal_id: str = "user") -> Dict[str, Any]:
    return {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": effect,
                    "Resource": resource,
                }
            ],
        },
        "context": {},
    }


def _get_secret() -> Dict[str, str]:
    secret_id = os.environ.get("SECRET_ID_BASIC_AUTH")
    if not secret_id:
        raise RuntimeError("SECRET_ID_BASIC_AUTH not set")
    resp = sm.get_secret_value(SecretId=secret_id)
    if "SecretString" in resp:
        data = json.loads(resp["SecretString"])
    else:
        data = json.loads(base64.b64decode(resp["SecretBinary"]).decode("utf-8"))
    return {"username": data.get("username", ""), "password": data.get("password", "")}


def handler(event, context):
    try:
        route_arn = event.get("methodArn") or "*"
        headers = event.get("headers") or {}
        auth = headers.get("Authorization") or headers.get("authorization")
        if not auth or not auth.startswith("Basic "):
            return _policy("Deny", route_arn)

        supplied = base64.b64decode(auth.split(" ", 1)[1]).decode("utf-8")
        if ":" not in supplied:
            return _policy("Deny", route_arn)
        user, pwd = supplied.split(":", 1)

        secret = _get_secret()
        if user == secret["username"] and pwd == secret["password"]:
            return _policy("Allow", route_arn, principal_id=user)
        return _policy("Deny", route_arn)
    except Exception:
        # On error, deny by default
        return _policy("Deny", event.get("methodArn", "*"))
