#!/usr/bin/env python3
"""
British spelling fixer - corrects American spellings in files.
Refactored to use the shared spell_checker_core module.
"""
import argparse
import os
import sys
import glob
import logging
from collections import defaultdict
from pathlib import Path

try:
    from colorama import init, Fore, Back, Style
    init(autoreset=True)  # Auto-reset colours after each print
    COLORS_AVAILABLE = True
except ImportError:
    # Fallback if colorama is not available
    class _DummyColor:
        def __getattr__(self, name):
            return ""
    
    Fore = Back = Style = _DummyColor()
    COLORS_AVAILABLE = False

def get_input():
    """Get user input, handling piped stdin by using /dev/tty."""
    try:
        # When stdin is piped, read from /dev/tty for user interaction
        with open('/dev/tty', 'r') as tty:
            return tty.readline().strip().lower()
    except (OSError, IOError):
        # Fallback to regular input if /dev/tty not available
        return input().strip().lower()

def clear_screen():
    """Clear the terminal screen."""
    os.system('cls' if os.name == 'nt' else 'clear')

def move_cursor_up(lines):
    """Move cursor up by specified lines."""
    print(f'\033[{lines}A', end='')

def clear_to_end():
    """Clear from cursor to end of screen."""
    print('\033[0J', end='')

# Import our shared core module
from britfix_core import (
    SpellingCorrector,
    load_spelling_mappings,
    get_file_strategy,
)


def find_files(patterns: list, recursive: bool = False) -> list:
    """Find files matching the given patterns."""
    files = []
    
    for pattern in patterns:
        # If pattern is a directory, scan all files in it
        if os.path.isdir(pattern):
            if recursive:
                # Recursively find all files in directory and subdirectories
                for root, dirs, filenames in os.walk(pattern):
                    for filename in filenames:
                        filepath = os.path.join(root, filename)
                        # Skip hidden files/directories
                        if not any(part.startswith('.') for part in filepath.split(os.sep)[1:]):
                            files.append(filepath)
            else:
                # Just files in the directory (not subdirs)
                for filename in os.listdir(pattern):
                    filepath = os.path.join(pattern, filename)
                    if os.path.isfile(filepath):
                        files.append(filepath)
        else:
            # Pattern-based matching
            if recursive and '/' not in pattern:
                # For patterns like "*.md", search recursively
                pattern = f'**/{pattern}'
            matched = glob.glob(pattern, recursive=recursive)
            files.extend(matched)
    
    # Remove duplicates while preserving order
    seen = set()
    unique_files = []
    for f in files:
        if f not in seen and os.path.isfile(f):
            seen.add(f)
            unique_files.append(f)
            
    return unique_files


def create_backup(filepath: str) -> str:
    """Create a backup of the file."""
    base, ext = os.path.splitext(filepath)
    backup_path = f"{base}-pre-spelling-fixes{ext}.bak"
    
    # Ensure unique backup filename
    counter = 1
    while os.path.exists(backup_path):
        backup_path = f"{base}-pre-spelling-fixes-{counter}{ext}.bak"
        counter += 1
        
    with open(filepath, 'rb') as src, open(backup_path, 'wb') as dst:
        dst.write(src.read())
        
    return backup_path


def process_file_interactive(filepath: str, corrector: SpellingCorrector) -> tuple:
    """Process a file with enhanced interactive approval."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find all potential replacements
    replacements = corrector.find_replacements(content)
    if not replacements:
        return content, {}
    
    # Group replacements by word
    word_groups = list(defaultdict(list).items())
    for repl in replacements:
        found = False
        for i, (key, group) in enumerate(word_groups):
            if key == repl[2].lower():
                group.append(repl)
                found = True
                break
        if not found:
            word_groups.append((repl[2].lower(), [repl]))
    
    # Remove empty groups and convert to list
    word_groups = [(k, v) for k, v in word_groups if v]
    
    return navigate_changes_interactive(content, word_groups, filepath)


def navigate_changes_interactive(content: str, word_groups: list, filepath: str = "stdin") -> tuple:
    """Simple, reliable interactive interface."""
    if not word_groups:
        return content, {}
    
    current_index = 0
    decisions = {}  # Track user decisions
    
    print(f"\n{Style.BRIGHT}{Fore.CYAN}Spelling Corrections - {filepath}")
    print(f"Found {len(word_groups)} potential change(s)")
    print(f"{'='*50}{Style.RESET_ALL}\n")
    
    while current_index < len(word_groups):
        word_key, group = word_groups[current_index]
        original = group[0][2]
        replacement = group[0][3]
        
        # Show current change
        print(f"{Style.BRIGHT}Change {current_index + 1} of {len(word_groups)}:{Style.RESET_ALL}")
        print(f"'{Fore.RED}{original}{Style.RESET_ALL}' → '{Fore.GREEN}{replacement}{Style.RESET_ALL}' ({len(group)} occurrence(s))")
        
        # Show context
        start, end, _, _ = group[0]
        context_start = max(0, start - 30)
        context_end = min(len(content), end + 30)
        context = content[context_start:context_end]
        
        relative_start = start - context_start
        relative_end = end - context_start
        highlighted = (
            context[:relative_start] + 
            f"{Back.YELLOW}{Fore.BLACK}[{original}]{Style.RESET_ALL}" + 
            context[relative_end:]
        )
        
        print(f"Context: ...{highlighted}...")
        
        # Show current status
        if word_key in decisions:
            status = "✓ Approved" if decisions[word_key] else "✗ Rejected"
            print(f"Status: {status}")
        
        # Get user input
        print(f"\n{Fore.GREEN}[y]{Style.RESET_ALL}es  {Fore.RED}[n]{Style.RESET_ALL}o  {Fore.YELLOW}[a]{Style.RESET_ALL}ll  {Fore.BLUE}[p]{Style.RESET_ALL}rev  {Fore.BLUE}[s]{Style.RESET_ALL}kip  {Fore.CYAN}[d]{Style.RESET_ALL}one  {Fore.MAGENTA}[q]{Style.RESET_ALL}uit")
        
        try:
            choice = get_input()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{Fore.YELLOW}Interrupted, applying current decisions...{Style.RESET_ALL}")
            break
        
        if choice in ['y', 'yes']:
            decisions[word_key] = True
            current_index += 1
        elif choice in ['n', 'no']:
            decisions[word_key] = False
            current_index += 1
        elif choice in ['a', 'all']:
            # Approve all remaining
            for i in range(current_index, len(word_groups)):
                decisions[word_groups[i][0]] = True
            break
        elif choice in ['p', 'prev', 'previous']:
            if current_index > 0:
                current_index -= 1
        elif choice in ['s', 'skip']:
            current_index += 1
        elif choice in ['d', 'done']:
            break
        elif choice in ['q', 'quit']:
            print("Quitting without changes.")
            return content, {}
        elif choice in ['u', 'undo']:
            if word_key in decisions:
                del decisions[word_key]
                print("Decision undone.")
        else:
            print(f"Unknown command: '{choice}'. Try 'y', 'n', 'a', 'p', 's', 'd', or 'q'.")
        
        print()  # Add spacing
    
    # Apply approved decisions
    approved_replacements = []
    for word_key, group in word_groups:
        if decisions.get(word_key, False):
            approved_replacements.extend(group)
    
    return apply_replacements(content, approved_replacements)


def apply_replacements(text: str, replacements: list) -> tuple:
    """Apply approved replacements to text."""
    if not replacements:
        return text, {}
    
    # Apply approved changes
    change_tracker = defaultdict(int)
    offset = 0
    result = text
    
    for start, end, original, replacement in sorted(replacements):
        adjusted_start = start + offset
        adjusted_end = end + offset
        result = result[:adjusted_start] + replacement + result[adjusted_end:]
        offset += len(replacement) - len(original)
        change_tracker[original.lower()] += 1
    
    return result, dict(change_tracker)


def process_stdin_interactive(content: str, corrector: SpellingCorrector) -> tuple:
    """Process stdin content with enhanced interactive approval."""
    # Find all potential replacements
    replacements = corrector.find_replacements(content)
    if not replacements:
        return content, {}
    
    # Group replacements by word (same logic as file processing)
    word_groups = list(defaultdict(list).items())
    for repl in replacements:
        found = False
        for i, (key, group) in enumerate(word_groups):
            if key == repl[2].lower():
                group.append(repl)
                found = True
                break
        if not found:
            word_groups.append((repl[2].lower(), [repl]))
    
    # Remove empty groups
    word_groups = [(k, v) for k, v in word_groups if v]
    
    return navigate_changes_interactive(content, word_groups, "stdin")


def main():
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )
    
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description='Correct American spellings in files with support for multiple file types.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Supported file types:
  - Text: .txt, .md
  - LaTeX: .tex
  - Web: .html, .htm, .xml
  - Data: .json
  - Code: .py, .js, .java, .cpp, .c, .h, .cs, .rb, .go, .rs, .swift, .kt

Examples:
  %(prog)s --input file.md
  %(prog)s --input "*.txt" "*.md" --recursive
  %(prog)s --input document.tex --dry-run
  %(prog)s --input "src/*.py" --no-backup
  %(prog)s --input article.md --interactive
        """
    )
    
    parser.add_argument('--input', nargs='+', required=False, 
                       help='Input file(s) or pattern(s). Use quotes for wildcards. If omitted, reads from stdin.')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Preview changes without modifying files')
    parser.add_argument('--no-backup', action='store_true', 
                       help='Skip backup creation')
    parser.add_argument('--recursive', action='store_true', 
                       help='Process files recursively')
    parser.add_argument('--dictionary', 
                       help='Path to custom spelling dictionary JSON file')
    parser.add_argument('--quiet', action='store_true',
                       help='Suppress detailed output')
    parser.add_argument('--interactive', '-i', action='store_true',
                       help='Interactively approve each change')
    
    args = parser.parse_args()
    
    # Load spelling mappings
    american_to_british = load_spelling_mappings(args.dictionary)
    
    if not american_to_british:
        logging.error("No spelling dictionary found or dictionary is empty")
        sys.exit(1)
    
    # Create corrector
    corrector = SpellingCorrector(american_to_british)
    
    # Handle stdin input or file patterns
    if not args.input:
        # Check if stdin has data
        if sys.stdin.isatty():
            logging.error("No input provided. Specify --input patterns or pipe data to stdin.")
            sys.exit(1)
        
        # Process stdin (treated as plain text)
        content = sys.stdin.read()
        if args.interactive:
            corrected_content, changes = process_stdin_interactive(content, corrector)
        else:
            # Non-interactive stdin processing
            strategy = get_file_strategy('.txt')  # Default to text strategy
            corrected_content, changes = strategy.process(content, corrector)
        
        # Output result to stdout
        if not args.dry_run:
            print(corrected_content, end='')
        
        # Only show status messages if not quiet
        if not args.quiet:
            if changes:
                print(f"\n{Style.BRIGHT}{Fore.GREEN}Changes made:{Style.RESET_ALL}", file=sys.stderr)
                for word, count in sorted(changes.items()):
                    print(f"  {Fore.RED}{word}{Style.RESET_ALL} -> {Fore.GREEN}{american_to_british[word]}{Style.RESET_ALL}: {Fore.YELLOW}{count}{Style.RESET_ALL} occurrence(s)", file=sys.stderr)
            else:
                print(f"{Style.BRIGHT}{Fore.BLUE}No changes needed{Style.RESET_ALL}", file=sys.stderr)
        
        return
    
    # Find all files to process
    files = find_files(args.input, args.recursive)
    
    if not files:
        logging.error("No files found matching the specified patterns")
        sys.exit(1)
    
    # Process each file
    total_changes = defaultdict(int)
    processed_files = []
    
    for filepath in files:
        if not os.path.exists(filepath):
            logging.warning(f"File not found: {filepath}")
            continue
            
        try:
            # Get the appropriate processing strategy
            ext = os.path.splitext(filepath)[1].lower()
            strategy = get_file_strategy(ext)

            # Process the file
            if args.interactive:
                corrected_content, file_changes = process_file_interactive(filepath, corrector)
            else:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                corrected_content, file_changes = strategy.process(content, corrector)
            
            if file_changes:
                processed_files.append((filepath, file_changes))
                
                # Update total changes
                for word, count in file_changes.items():
                    total_changes[word] += count
                
                if not args.dry_run:
                    # Create backup if requested
                    backup_path = None
                    if not args.no_backup:
                        backup_path = create_backup(filepath)
                    
                    # Write corrected content
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(corrected_content)
                    
                    if not args.quiet:
                        if backup_path:
                            logging.info(f"Processed: {filepath} (backup: {backup_path})")
                        else:
                            logging.info(f"Processed: {filepath}")
            else:
                if not args.quiet:
                    logging.info(f"No changes needed: {filepath}")
                    
        except Exception as e:
            logging.error(f"Error processing {filepath}: {e}")
            continue
    
    # Print summary
    if args.dry_run:
        print("\n=== DRY RUN MODE - No files were modified ===")
    
    if processed_files:
        print(f"\n{'Would process' if args.dry_run else 'Processed'} {len(processed_files)} file(s) with changes:")
        
        if not args.quiet:
            for filepath, changes in processed_files:
                print(f"\n  {filepath}:")
                for word, count in sorted(changes.items()):
                    print(f"    {word} -> {american_to_british[word]}: {count} occurrence(s)")
        
        print(f"\nTotal changes across all files:")
        for word, count in sorted(total_changes.items(), key=lambda x: (-x[1], x[0])):
            print(f"  {word} -> {american_to_british[word]}: {count} occurrence(s)")
    else:
        print("\nNo changes were needed in any files.")


if __name__ == "__main__":
    main()