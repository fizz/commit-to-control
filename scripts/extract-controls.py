#!/usr/bin/env python3
"""Extract NIST 800-171 Rev 2 controls from the official XLSX and emit JSON.

Usage: python3 extract-controls.py data/sp800-171r2-security-reqs.xlsx > controls.json

Source: https://csrc.nist.gov/pubs/sp/800/171/r2/upd1/final
NIST publications are public domain (US government work).
"""

import json
import sys

import openpyxl

FAMILY_MAP = {
    "Access Control": "AC",
    "Awareness and Training": "AT",
    "Audit and Accountability": "AU",
    "Configuration Management": "CM",
    "Identification and Authentication": "IA",
    "Incident response": "IR",
    "Maintenance": "MA",
    "Media Protection": "MP",
    "Personnel Security": "PS",
    "Physical Protection": "PE",
    "Risk Assessment": "RA",
    "Security Assessment": "CA",
    "System and Communications Protection": "SC",
    "System and Information Integrity": "SI",
}

LEVEL_MAP = {"Basic": "L1", "Derived": "L2"}


def extract(path: str) -> dict:
    wb = openpyxl.load_workbook(path)
    ws = wb["SP 800-171"]
    controls = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        family, basic_derived, identifier, _sort_as, requirement, _discussion = row
        if not identifier or not requirement:
            continue
        prefix = FAMILY_MAP.get(family)
        if not prefix:
            print(f"WARNING: unmapped family '{family}'", file=sys.stderr)
            continue
        level = LEVEL_MAP.get(basic_derived, "L2")
        cmmc_id = f"{prefix}.{level}-{identifier.strip()}"
        desc = requirement.strip().replace("\n", " ")
        controls[cmmc_id] = desc
    return controls


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <xlsx-path>", file=sys.stderr)
        sys.exit(1)
    controls = extract(sys.argv[1])
    json.dump(controls, sys.stdout, indent=2)
    print()
