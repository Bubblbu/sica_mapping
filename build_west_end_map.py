#!/usr/bin/env python3
from westend_map.cli import parse_args
from westend_map.build import build_map

def main():
    args = parse_args()
    build_map(args)

if __name__ == "__main__":
    main()
