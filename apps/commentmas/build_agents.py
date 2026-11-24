"""Build one locally stored Perspective Agent per supported group; no model calls."""

import argparse
from pathlib import Path

from filter_comments import write_json
from perspective_agents import build_bundle, load_grouping


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("groups", type=Path, help="Stage 2 groups.json")
    parser.add_argument("--output", type=Path, help="default: sibling 03_agents directory")
    args = parser.parse_args()
    try:
        grouped, assignments, source = load_grouping(args.groups)
        bundle = build_bundle(grouped, assignments, source)
        output = args.output or args.groups.parent.parent/"03_agents"
        write_json(output/"agents.json", bundle)
        for profile in bundle["agents"]:
            write_json(output/"profiles"/f"{profile['agent_id']}.json", profile)
        print(f"Built {len(bundle['agents'])} agents / {bundle['meta']['owned_comment_count']} owned comments -> {output/'agents.json'}")
        for a in bundle["agents"]:
            print(f"  {a['agent_id']} · {a['name']} · {len(a['comments'])} comments")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
