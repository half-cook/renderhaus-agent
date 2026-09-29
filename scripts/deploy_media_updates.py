#!/usr/bin/env python3
"""Update the existing ElevenLabs/Remotion Lambda code and schemas, preserving roles/auth.

Uploads a versioned renderer site. Does not create infrastructure or change IAM.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.config import load_local_env
from providers.catalog import get_provider
from providers.registry import load_committed_schemas
from scripts.deploy_gateway import build_lambda_zip, _find_gateway, GATEWAY_NAME
import boto3


def main():
    load_local_env()
    region = os.getenv("AWS_REGION", "us-east-1")
    lam = boto3.client("lambda", region_name=region)
    control = boto3.client("bedrock-agentcore-control", region_name=region)
    gateway = _find_gateway(control, GATEWAY_NAME)
    if not gateway:
        raise RuntimeError("Existing Gateway is required.")
    gateway_id = gateway.get("gatewayId") or gateway.get("gatewayIdentifier") or gateway.get("id")
    provider_names = ("elevenlabs", "remotion")
    targets_by_name = {}
    page_args = {"gatewayIdentifier": gateway_id}
    while True:
        page = control.list_gateway_targets(**page_args)
        targets_by_name.update((target["name"], target) for target in page["items"])
        if not page.get("nextToken"):
            break
        page_args["nextToken"] = page["nextToken"]
    missing = [get_provider(name).target_name for name in provider_names
               if get_provider(name).target_name not in targets_by_name]
    if missing:
        raise RuntimeError(f"Existing Gateway is missing targets: {', '.join(missing)}")
    # Read target details and schemas before uploading the site or changing Lambda code.
    target_updates = {}
    for name in provider_names:
        spec = get_provider(name)
        target = targets_by_name[spec.target_name]
        detail = control.get_gateway_target(gatewayIdentifier=gateway_id, targetId=target["targetId"])
        configuration = detail["targetConfiguration"]
        configuration["mcp"]["lambda"]["toolSchema"] = {"inlinePayload": load_committed_schemas(spec)}
        target_updates[name] = dict(gatewayIdentifier=gateway_id, targetId=target["targetId"],
                                    name=spec.target_name, targetConfiguration=configuration,
                                    credentialProviderConfigurations=detail["credentialProviderConfigurations"])
    configs = {name: lam.get_function_configuration(FunctionName=get_provider(name).function_name)
               for name in provider_names}
    env = configs["remotion"]["Environment"]["Variables"]
    child_env = {**os.environ, "REMOTION_APP_REGION": env["REMOTION_APP_REGION"],
                 "REMOTION_APP_BUCKET_NAME": env["REMOTION_APP_BUCKET_NAME"]}
    # Package before any mutation, so packaging errors leave the deployment untouched.
    package = build_lambda_zip()
    deployed = subprocess.run(["node", "scripts/deploy.mjs"], cwd=ROOT / "remotion",
                              env=child_env, text=True, capture_output=True, check=True)
    site = json.loads(deployed.stdout.strip().splitlines()[-1])
    print("Uploaded versioned Remotion composition.", flush=True)
    for name, config in configs.items():
        spec = get_provider(name)
        lam.update_function_code(FunctionName=spec.function_name, ZipFile=package,
                                 RevisionId=config["RevisionId"])
        lam.get_waiter("function_updated_v2").wait(FunctionName=spec.function_name)
        if name == "remotion":
            live = lam.get_function_configuration(FunctionName=spec.function_name)
            updated_env = {**live["Environment"]["Variables"], "REMOTION_APP_SERVE_URL": site["serveUrl"]}
            lam.update_function_configuration(FunctionName=spec.function_name,
                                              Environment={"Variables": updated_env}, RevisionId=live["RevisionId"])
            lam.get_waiter("function_updated_v2").wait(FunctionName=spec.function_name)
        control.update_gateway_target(**target_updates[name])
        print(f"Updated existing {name} Lambda and Gateway schema.", flush=True)
    output = ROOT / ".renderhaus/remotion/media-update.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"serve_url": site["serveUrl"], "previous_serve_url": env["REMOTION_APP_SERVE_URL"]}, indent=2))

if __name__ == "__main__":
    main()
