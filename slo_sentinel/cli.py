"""Command line entry point.

    slo-sentinel examples/checkout_api.yaml -o generated/
"""

import argparse
import sys
from pathlib import Path

import yaml

from .burn import assemble, parse_spec


class LiteralDumper(yaml.SafeDumper):
    pass


def _literal_str(dumper, data):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


LiteralDumper.add_representer(str, _literal_str)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="slo-sentinel",
        description="Generate multiwindow multi-burn Prometheus alerts from an SLO spec.",
    )
    ap.add_argument("specs", nargs="+", help="SLO spec YAML file(s)")
    ap.add_argument("-o", "--out", required=True, help="output directory")
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for raw in args.specs:
        path = Path(raw)
        try:
            spec = parse_spec(yaml.safe_load(path.read_text(encoding="utf-8")))
        except yaml.YAMLError as exc:
            print("FAIL %s: not valid YAML: %s" % (path, exc), file=sys.stderr)
            return 2
        except ValueError as exc:
            print("FAIL %s: %s" % (path, exc), file=sys.stderr)
            return 2
        doc = assemble(spec)
        dest = out / ("%s_slo.yaml" % spec.slug)
        dest.write_text(
            yaml.dump(doc, Dumper=LiteralDumper, sort_keys=False, width=100),
            encoding="utf-8",
        )
        written.append(dest)
        print("wrote %s  (target %s, %d recording rules, %d alerts)"
              % (dest, spec.target,
                 len(doc["groups"][0]["rules"]), len(doc["groups"][1]["rules"])))
    if not written:
        print("no specs generated", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
