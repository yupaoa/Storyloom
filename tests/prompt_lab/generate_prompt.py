#!/usr/bin/env python3
"""Generate prompt files from template + YAML parameter matrix.

Usage:
  python3 tests/generate_prompt.py [--config tests/prompt_lab/data/prompts/seg-test-config.yaml]
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML required: pip install pyyaml")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def render(template: str, params: dict) -> str:
    """Replace {{PLACEHOLDER}} with values from params dict (case-insensitive)."""
    import re as _re
    result = template
    keys_lower = {k.lower(): v for k, v in params.items()}
    for match in _re.finditer(r"\{\{(\w+)\}\}", result):
        placeholder = match.group(0)
        key = match.group(1).lower()
        if key in keys_lower:
            result = result.replace(placeholder, str(keys_lower[key]))
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Generate segment-test prompt files from template + config."
    )
    parser.add_argument(
        "--config", type=Path,
        default=PROJECT_ROOT / "tests" / "data" / "prompts" / "seg-test-config.yaml",
        help="Path to YAML config file.",
    )
    args = parser.parse_args()

    config_path = args.config.resolve()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    template_path = PROJECT_ROOT / config["template"]
    template_text = template_path.read_text(encoding="utf-8")

    output_dir = PROJECT_ROOT / config["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = {"tiers": [], "config": str(config_path)}

    for tier in config["tiers"]:
        rendered = render(template_text, tier)
        out_name = f"seg-{tier['label']}.txt"
        out_path = output_dir / out_name
        out_path.write_text(rendered, encoding="utf-8")

        # Verify placeholders all replaced
        remaining = [line for line in rendered.splitlines() if "{{" in line]
        if remaining:
            print(f"WARNING: Unreplaced placeholders in {out_name}:")
            for line in remaining:
                print(f"  {line.strip()}")

        entry = {
            "label": tier["label"],
            "file": str(out_path.relative_to(PROJECT_ROOT)),
            "params": tier,
        }
        manifest["tiers"].append(entry)
        print(f"Generated: {out_path.relative_to(PROJECT_ROOT)}")

    manifest_path = PROJECT_ROOT / config["manifest"]
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Manifest: {manifest_path.relative_to(PROJECT_ROOT)}")
    print(f"Done. {len(config['tiers'])} prompt files generated.")


if __name__ == "__main__":
    main()
