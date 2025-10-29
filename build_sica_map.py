#!/usr/bin/env python3
from sica_mapping.cli import parse_args
from sica_mapping.build import build_map

def main():
    args = parse_args()
    build_map(args)

if __name__ == "__main__":
    main()
