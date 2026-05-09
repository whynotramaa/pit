import argparse
import sys

def main():
  parser = argparse.ArgumentParser(
    description="PyGit - Git Reimagined"
  )
  subparsers = parser.add_subparsers(dest="command", help="Available Commands")

  # inti command
  init_parser = subparsers.add_parser("init", help="Initialize a new repository")
  init_parser = subparsers.add_parser("add", help="Adds a new repository")

  args = parser.parse_args()

  if not args.command:
    parser.print_help()
    return

  try:
    if args.command == "init":
      pass
    
  except Exception as e:
    print(f"Error -> {e}")
    sys.exit(1)

  print(args)

main()

