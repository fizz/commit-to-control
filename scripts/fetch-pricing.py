#!/usr/bin/env python3
"""Fetch the price of each default model and write pricing.json.

Usage: python3 scripts/fetch-pricing.py > pricing.json

The Bedrock models are the defaults in DEFAULT_MODELS in commit-to-control, so a
new default brings its price with it. For each one the script:

  1. Finds the model in Bedrock, and skips it with a warning unless its status
     is ACTIVE. scripts/heal-models.py replaces a retired default first.
  2. Reads its on-demand input and output price in AWS_REGION (default
     us-east-1) from the AWS Price List, and stores the price per token.

A "us." or other geographic inference profile uses the standard price, and
"global." uses the global price. OpenAI has no price API, so its prices are
fixed below.

Needs bedrock:ListFoundationModels and pricing:GetProducts.
"""

import ast
import json
import os
import re
import sys
from pathlib import Path

import boto3

REPO = Path(__file__).resolve().parent.parent
REGION = os.environ.get("AWS_REGION") or "us-east-1"

# Amazon's own models have no model name in the Price List. Each one is keyed by
# its titanModel attribute.
AMAZON_PRICE_KEYS = {
    "amazon.titan-embed-text-v2:0": {"input": "TitanEmbeddingsV2-Text-input"},
}

# OpenAI publishes no price API. Source: https://openai.com/api/pricing, 2026-03-19.
OPENAI_PRICES = {
    "text-embedding-3-small": {"input": 0.00000002, "type": "embedding"},
    "text-embedding-3-large": {"input": 0.00000013, "type": "embedding"},
    "gpt-4o-mini": {"input": 0.00000015, "output": 0.0000006, "type": "chat"},
    "gpt-4o": {"input": 0.0000025, "output": 0.00001, "type": "chat"},
}

UNITS = {"1K tokens": 1_000, "1M tokens": 1_000_000}
PROFILE_PREFIXES = ("us.", "eu.", "apac.", "jp.", "au.", "ca.", "us-gov.", "global.")


def default_models() -> dict:
    """Read DEFAULT_MODELS from commit-to-control without running it."""
    tree = ast.parse((REPO / "commit-to-control").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "DEFAULT_MODELS" for t in node.targets):
            return ast.literal_eval(node.value)
    sys.exit("DEFAULT_MODELS not found in commit-to-control")


def split_profile(model_id: str) -> tuple[str, str]:
    """Return (foundation model ID, price tier) for a model or inference profile ID."""
    for prefix in PROFILE_PREFIXES:
        if model_id.startswith(prefix):
            return model_id[len(prefix):], "global_standard" if prefix == "global." else "standard"
    return model_id, "standard"


def products(pricing, service: str, **attrs) -> list[dict]:
    filters = [{"Type": "TERM_MATCH", "Field": k, "Value": v} for k, v in {"regionCode": REGION, **attrs}.items()]
    found = []
    for page in pricing.get_paginator("get_products").paginate(ServiceCode=service, Filters=filters):
        found += [json.loads(p) for p in page["PriceList"]]
    return found


def per_token(product: dict) -> float:
    (term,) = product["terms"]["OnDemand"].values()
    (dim,) = term["priceDimensions"].values()
    if dim["unit"] not in UNITS:
        sys.exit(f"Unknown price unit {dim['unit']!r} for {product['product']['attributes']['usagetype']}")
    return float(dim["pricePerUnit"]["USD"]) / UNITS[dim["unit"]]


def amazon_price(pricing, model_id: str) -> dict:
    price = {}
    for direction, key in AMAZON_PRICE_KEYS[model_id].items():
        found = [p for p in products(pricing, "AmazonBedrock", titanModel=key, feature="On-demand Inference")
                 if not p["product"]["attributes"]["usagetype"].endswith("-batch")]
        if len(found) != 1:
            sys.exit(f"Expected one {REGION} on-demand price for {key}, found {len(found)}")
        price[direction] = per_token(found[0])
    return price


def marketplace_price(pricing, model_name: str, tier: str) -> dict:
    price = {}
    for direction in ("input", "output"):
        pattern = re.compile(rf"_{direction}_tokens_{tier}-Units$")
        found = [p for p in products(pricing, "AmazonBedrockFoundationModels", model=model_name)
                 if pattern.search(p["product"]["attributes"]["usagetype"])]
        if len(found) != 1:
            sys.exit(f"Expected one {REGION} {tier} {direction} price for {model_name}, found {len(found)}")
        price[direction] = per_token(found[0])
    return price


def bedrock_prices() -> dict:
    bedrock = boto3.client("bedrock", region_name=REGION)
    pricing = boto3.client("pricing", region_name="us-east-1")  # the Price List API is in us-east-1 only
    models = {m["modelId"]: m for m in bedrock.list_foundation_models()["modelSummaries"]}

    prices = {}
    for kind, model_id in default_models()["bedrock"].items():
        base, tier = split_profile(model_id)
        model = models.get(base)
        status = (model or {}).get("modelLifecycle", {}).get("status", "not offered")
        if status != "ACTIVE":
            # scripts/heal-models.py replaces a retired judge before this runs.
            print(f"WARNING: default {kind} model {model_id} is {status} in Bedrock; no price", file=sys.stderr)
            continue

        if base in AMAZON_PRICE_KEYS:
            price = amazon_price(pricing, base)
        else:
            price = marketplace_price(pricing, model["modelName"], tier)
        prices[model_id] = {**price, "type": "embedding" if kind == "embed" else "chat"}
        print(f"{model_id}: {price}", file=sys.stderr)
    return prices


def to_json(prices: dict) -> str:
    """Write prices as fixed-point decimals, never in exponent form."""
    text = json.dumps(prices, indent=2)
    return re.sub(r"\d+(?:\.\d+)?e-\d+", lambda m: f"{float(m.group()):.12f}".rstrip("0"), text) + "\n"


def main():
    sys.stdout.write(to_json({**bedrock_prices(), **OPENAI_PRICES}))


if __name__ == "__main__":
    main()
