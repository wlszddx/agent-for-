import argparse
import sys

from kinetics_audit.mcp import serve
from kinetics_audit.tools import Job


def main(argv=None):
    parser = argparse.ArgumentParser(prog="kinetics-audit")
    commands = parser.add_subparsers(dest="command", required=True)
    mcp = commands.add_parser("mcp")
    mcp.add_argument("--experiment")
    mcp.add_argument("--case")
    args = parser.parse_args(argv)
    if args.command == "mcp":
        serve(Job.closed())
        return 0
    print("只接受实验报告文件，不再打开内置实验。", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
