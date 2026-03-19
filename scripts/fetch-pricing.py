#!/usr/bin/env python3
"""Fetch current model pricing from providers and emit pricing.json.

Usage: python3 fetch-pricing.py > pricing.json

Sources:
  - AWS Bedrock: aws pricing get-products API
  - OpenAI: hardcoded from https://openai.com/api/pricing (no pricing API)
"""

import json
import os
import sys


def fetch_bedrock_pricing():
    """Pull Bedrock model pricing from AWS Pricing API."""
    import boto3

    # Pricing API only available in us-east-1
    client = boto3.Session(region_name="us-east-1").client("pricing")
    prices = {}

    # Embedding models
    for model_id, product_family in [
        ("amazon.titan-embed-text-v2:0", "Amazon Titan Text Embeddings V2"),
    ]:
        try:
            response = client.get_products(
                ServiceCode="AmazonBedrock",
                Filters=[
                    {"Type": "TERM_MATCH", "Field": "usagetype", "Value": "USW2-InferenceInputToken-Titan-TextEmbeddings-v2"},
                ],
                MaxResults=10,
            )
            for item in response.get("PriceList", []):
                data = json.loads(item)
                for term in data.get("terms", {}).get("OnDemand", {}).values():
                    for dim in term.get("priceDimensions", {}).values():
                        price = float(dim["pricePerUnit"]["USD"])
                        if price > 0:
                            prices[model_id] = {"input": price, "type": "embedding"}
        except Exception as e:
            print(f"WARNING: could not fetch pricing for {model_id}: {e}", file=sys.stderr)

    # Chat/judge models — fetch input and output separately
    bedrock_models = {
        "anthropic.claude-3-haiku-20240307-v1:0": {
            "input_filter": "InferenceInputToken-Anthropic-Claude3Haiku",
            "output_filter": "InferenceOutputToken-Anthropic-Claude3Haiku",
        },
        "anthropic.claude-3-5-haiku-20241022-v1:0": {
            "input_filter": "InferenceInputToken-Anthropic-Claude35Haiku",
            "output_filter": "InferenceOutputToken-Anthropic-Claude35Haiku",
        },
    }

    for model_id, filters in bedrock_models.items():
        model_price = {"type": "chat"}
        for direction, usage_filter in [("input", filters["input_filter"]), ("output", filters["output_filter"])]:
            try:
                response = client.get_products(
                    ServiceCode="AmazonBedrock",
                    Filters=[
                        {"Type": "TERM_MATCH", "Field": "usagetype", "Value": f"USW2-{usage_filter}"},
                    ],
                    MaxResults=10,
                )
                for item in response.get("PriceList", []):
                    data = json.loads(item)
                    for term in data.get("terms", {}).get("OnDemand", {}).values():
                        for dim in term.get("priceDimensions", {}).values():
                            price = float(dim["pricePerUnit"]["USD"])
                            if price > 0:
                                model_price[direction] = price
            except Exception as e:
                print(f"WARNING: could not fetch {direction} pricing for {model_id}: {e}", file=sys.stderr)

        if "input" in model_price:
            prices[model_id] = model_price

    return prices


def openai_pricing():
    """OpenAI pricing — no API, hardcoded from openai.com/api/pricing.
    Last updated: 2026-03-19.
    """
    return {
        "text-embedding-3-small": {"input": 0.00000002, "type": "embedding"},
        "text-embedding-3-large": {"input": 0.00000013, "type": "embedding"},
        "gpt-4o-mini": {"input": 0.00000015, "output": 0.0000006, "type": "chat"},
        "gpt-4o": {"input": 0.0000025, "output": 0.00001, "type": "chat"},
    }


def main():
    prices = {}

    # OpenAI (always available, no API call needed)
    prices.update(openai_pricing())

    # Bedrock (requires AWS credentials)
    try:
        bedrock = fetch_bedrock_pricing()
        prices.update(bedrock)
        print(f"Fetched {len(bedrock)} Bedrock model prices", file=sys.stderr)
    except Exception as e:
        print(f"WARNING: Bedrock pricing unavailable ({e}), using fallback", file=sys.stderr)
        # Fallback prices if AWS isn't available
        prices.update({
            "amazon.titan-embed-text-v2:0": {"input": 0.00000002, "type": "embedding"},
            "anthropic.claude-3-haiku-20240307-v1:0": {"input": 0.00000025, "output": 0.00000125, "type": "chat"},
        })

    json.dump(prices, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
