#!/usr/bin/env python3
"""Replace a default Bedrock model that Bedrock no longer offers.

Usage: python3 scripts/heal-models.py NOTES_FILE

For each Bedrock default in DEFAULT_MODELS (commit-to-control) whose model is not
ACTIVE in Bedrock:

  - Judge: the successor is the newest ACTIVE model from the same provider whose
    ID contains every word of the old ID, so a Haiku is replaced by a Haiku. It
    keeps the old inference profile prefix ("us.", "global.") when it had one.
    The script calls it once, which also starts the account's Marketplace
    subscription, and then replaces the old ID in commit-to-control and
    README.md.
  - Embedding model: no automatic replacement, because every stored vector came
    from the old model and has to be seeded again. The script reports it.

It writes one Markdown line per change or report to NOTES_FILE and exits 0.
Needs bedrock:ListFoundationModels, bedrock:ListInferenceProfiles and
bedrock:InvokeModel.
"""

import ast
import json
import os
import re
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REPO = Path(__file__).resolve().parent.parent
REGION = os.environ.get("AWS_REGION") or "us-east-1"
PROFILE_PREFIXES = ("us.", "eu.", "apac.", "jp.", "au.", "ca.", "us-gov.", "global.")
FILES = ("commit-to-control", "README.md")


def default_models() -> dict:
    tree = ast.parse((REPO / "commit-to-control").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "DEFAULT_MODELS" for t in node.targets):
            return ast.literal_eval(node.value)
    sys.exit("DEFAULT_MODELS not found in commit-to-control")


def split_profile(model_id: str) -> tuple[str, str]:
    for prefix in PROFILE_PREFIXES:
        if model_id.startswith(prefix):
            return prefix, model_id[len(prefix):]
    return "", model_id


def words(model_id: str) -> set[str]:
    """The alphabetic words of a model ID: anthropic.claude-haiku-5-5 -> {anthropic, claude, haiku}."""
    return {w for w in re.split(r"[^a-z]+", model_id.lower()) if len(w) > 1}


def version(model: dict) -> tuple[float, ...]:
    """Version numbers from the model name: "Claude Haiku 5.5" -> (5.5,)."""
    return tuple(float(n) for n in re.findall(r"\d+(?:\.\d+)?", model["modelName"]))


def system_profiles(bedrock) -> set[str]:
    ids = set()
    for page in bedrock.get_paginator("list_inference_profiles").paginate(typeEquals="SYSTEM_DEFINED"):
        ids |= {p["inferenceProfileId"] for p in page["inferenceProfileSummaries"]}
    return ids


def answers(runtime, model_id: str, tries: int = 12, wait: int = 60) -> bool:
    """Call the model once. A new Marketplace model refuses with AccessDenied until
    the subscription that the first call starts is done, so retry."""
    body = json.dumps({"anthropic_version": "bedrock-2023-05-31", "max_tokens": 50,
                       "messages": [{"role": "user", "content": "Reply with the word OK."}]})
    for attempt in range(1, tries + 1):
        try:
            result = json.loads(runtime.invoke_model(modelId=model_id, body=body)["body"].read())
            return any(b.get("type") == "text" for b in result["content"])
        except ClientError as e:
            code = e.response["Error"]["Code"]
            print(f"{model_id}: {code} (try {attempt} of {tries})", file=sys.stderr)
            if code != "AccessDeniedException" or attempt == tries:
                return False
            time.sleep(wait)
    return False


def successors(models: dict, old_id: str, prefix: str, profiles: set[str]) -> list[str]:
    _, old_base = split_profile(old_id)
    provider = old_base.split(".", 1)[0]
    found = []
    for base, m in models.items():
        if base == old_base or not base.startswith(provider + ".") or not words(old_base) <= words(base):
            continue
        if m.get("modelLifecycle", {}).get("status") != "ACTIVE" or "TEXT" not in m.get("outputModalities", []):
            continue
        new_id = prefix + base
        if prefix and new_id not in profiles:
            continue
        if not prefix and "ON_DEMAND" not in m.get("inferenceTypesSupported", []):
            continue
        found.append((version(m), new_id))
    return [new_id for _, new_id in sorted(found, reverse=True)]


def replace_everywhere(old_id: str, new_id: str) -> None:
    for name in FILES:
        path = REPO / name
        path.write_text(path.read_text().replace(old_id, new_id))


def main():
    notes_path = Path(sys.argv[1])
    bedrock = boto3.client("bedrock", region_name=REGION)
    runtime = boto3.client("bedrock-runtime", region_name=REGION)
    models = {m["modelId"]: m for m in bedrock.list_foundation_models()["modelSummaries"]}

    notes = []
    for kind, old_id in default_models()["bedrock"].items():
        prefix, base = split_profile(old_id)
        status = models.get(base, {}).get("modelLifecycle", {}).get("status", "not offered")
        if status == "ACTIVE":
            continue
        if kind == "embed":
            notes.append(f"The default embedding model `{old_id}` is {status} in Bedrock. "
                         "Choose a successor and seed the controls again.")
            continue
        for new_id in successors(models, old_id, prefix, system_profiles(bedrock) if prefix else set()):
            if answers(runtime, new_id):
                replace_everywhere(old_id, new_id)
                notes.append(f"The default judge model `{old_id}` is {status} in Bedrock. "
                             f"The default is now `{new_id}`.")
                break
        else:
            notes.append(f"The default judge model `{old_id}` is {status} in Bedrock, "
                         "and no successor answered.")

    for line in notes:
        print(line, file=sys.stderr)
    notes_path.write_text("".join(f"- {line}\n" for line in notes))


if __name__ == "__main__":
    main()
