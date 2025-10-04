#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path

parser = argparse.ArgumentParser(description="Populate AWS Secrets Manager from a local JSON config")
parser.add_argument("--env", required=True, help="Environment name, e.g. dev")
parser.add_argument("--config", required=True, help="Path to config JSON file")
parser.add_argument("--project", default="dnd-ai", help="Project name prefix")
args = parser.parse_args()

cfg_path = Path(args.config)
if not cfg_path.exists():
    print(f"Config file not found: {cfg_path}", file=sys.stderr)
    sys.exit(1)

with cfg_path.open("r", encoding="utf-8") as f:
    cfg = json.load(f)

root = f"{args.project}/{args.env}"

# helper

def run(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stderr.strip(), file=sys.stderr)
        sys.exit(res.returncode)
    return res.stdout


def upsert_secret_json(name: str, data: dict):
    payload = json.dumps(data, separators=(",", ":"))
    # check if exists
    exists = subprocess.run(["aws", "secretsmanager", "describe-secret", "--secret-id", name], capture_output=True)
    if exists.returncode == 0:
        run(["aws", "secretsmanager", "put-secret-value", "--secret-id", name, "--secret-string", payload])
        print(f"Updated secret: {name}")
    else:
        run(["aws", "secretsmanager", "create-secret", "--name", name, "--secret-string", payload])
        print(f"Created secret: {name}")

if "openai" in cfg:
    upsert_secret_json(f"{root}/openai/api-key", cfg["openai"])

if "discord" in cfg:
    upsert_secret_json(f"{root}/discord/bot-token", cfg["discord"])

print("Done.")
