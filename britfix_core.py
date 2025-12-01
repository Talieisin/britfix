"""
Britfix core - spelling correction engine.
"""
import re
import json
import os
import sys
from typing import Dict, List, Tuple, Optional, Set
from collections import defaultdict


class ConfigError(Exception):
    """Raised when config.json is missing or invalid."""
    pass


def _load_config() -> Dict:
    """Load and validate config.json."""
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')

    if not os.path.exists(config_path):
        raise ConfigError(f"Config file not found: {config_path}")

    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Invalid JSON in config file: {e}")

    # Validate structure
    if 'strategies' not in config:
        raise ConfigError("Config missing 'strategies' key")

    strategies = config['strategies']
    if not isinstance(strategies, dict):
        raise ConfigError("Config 'strategies' must be an object")

    required_strategies = {'text', 'code'}
    missing = required_strategies - set(strategies.keys())
    if missing:
        raise ConfigError(f"Config missing required strategies: {missing}")

    for name, strategy in strategies.items():
        if not isinstance(strategy, dict):
            raise ConfigError(f"Strategy '{name}' must be an object")
        if 'extensions' not in strategy:
            raise ConfigError(f"Strategy '{name}' missing 'extensions' key")
        if not isinstance(strategy['extensions'], list):
            raise ConfigError(f"Strategy '{name}' extensions must be a list")
        if not strategy['extensions']:
            raise ConfigError(f"Strategy '{name}' has no extensions defined")

    return config


# Load config at module import time - fail fast if invalid
try:
    _CONFIG = _load_config()
except ConfigError as e:
    print(f"Britfix config error: {e}", file=sys.stderr)
    sys.exit(1)

class SpellingCorrector:
    """Efficient spelling corrector with precompiled regex patterns."""

    def __init__(self, dictionary: Dict[str, str]):
        self.dictionary = {k.lower(): v for k, v in dictionary.items()}
        self.pattern = self._compile_pattern()

    def _compile_pattern(self) -> Optional[re.Pattern]:
        """Compile regex pattern for all dictionary words."""
        if not self.dictionary:
            return None
        pattern = r'\b(' + '|'.join(re.escape(word) for word in self.dictionary.keys()) + r')\b'
        return re.compile(pattern, re.IGNORECASE)
    
    def detect_case(self, word: str) -> str:
        """Detect the case pattern of a word."""
        if word.isupper():
            return 'upper'
        elif word.islower():
            return 'lower'
        elif word.istitle():
            return 'title'
        else:
            return 'mixed'
    
    def apply_case(self, word: str, case_pattern: str) -> str:
        """Apply the detected case pattern to a word."""
        if case_pattern == 'upper':
            return word.upper()
        elif case_pattern == 'lower':
            return word.lower()
        elif case_pattern == 'title':
            return word.title()
        else:
            return word
    
    def find_replacements(self, text: str) -> List[Tuple[int, int, str, str]]:
        """Find all potential replacements in text."""
        if not self.pattern:
            return []
            
        replacements = []
        
        for match in self.pattern.finditer(text):
            original_word = match.group()
            case_pattern = self.detect_case(original_word)
            key = original_word.lower()
            
            if key in self.dictionary:
                british_spelling = self.dictionary[key]
                replacement = self.apply_case(british_spelling, case_pattern)
                if original_word != replacement:
                    replacements.append((match.start(), match.end(), original_word, replacement))
        
        return replacements
    
    def correct_text(self, text: str, track_changes: bool = True) -> Tuple[str, Dict[str, int]]:
        """Apply spelling corrections to text."""
        if not self.pattern:
            return text, {}
            
        change_tracker = defaultdict(int) if track_changes else None
        
        def replacement(match):
            original_word = match.group()
            case_pattern = self.detect_case(original_word)
            key = original_word.lower()
            
            if key in self.dictionary:
                british_spelling = self.dictionary[key]
                if track_changes:
                    change_tracker[key] += 1
                return self.apply_case(british_spelling, case_pattern)
            
            return original_word
        
        corrected_text = self.pattern.sub(replacement, text)
        return corrected_text, dict(change_tracker) if track_changes else {}


def load_spelling_mappings(file_path: Optional[str] = None) -> Dict[str, str]:
    """Load spelling mappings from a JSON file."""
    if not file_path:
        # Default to spelling-mapper.json in the same directory
        script_dir = os.path.dirname(os.path.realpath(__file__))
        file_path = os.path.join(script_dir, 'spelling-mapper.json')
    
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return json.load(file)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


# File processing strategies for different file types
class FileProcessingStrategy:
    """Base class for file processing strategies."""
    
    def process(self, content: str, corrector: SpellingCorrector) -> Tuple[str, Dict[str, int]]:
        """Process content and return corrected text with change tracking."""
        return corrector.correct_text(content)


class PlainTextStrategy(FileProcessingStrategy):
    """Process plain text files - just correct everything."""
    pass


class LaTeXStrategy(FileProcessingStrategy):
    """Process LaTeX files, preserving commands."""
    
    def process(self, content: str, corrector: SpellingCorrector) -> Tuple[str, Dict[str, int]]:
        # Patterns to preserve
        preserve_patterns = [
            r'\\[a-zA-Z]+\{[^}]*\}',  # LaTeX commands with arguments
            r'\\[a-zA-Z]+',            # LaTeX commands without arguments
            r'\$[^$]+\$',              # Inline math
            r'\$\$[^$]+\$\$',          # Display math
        ]
        
        # Split content into segments
        combined_pattern = '|'.join(f'({p})' for p in preserve_patterns)
        segments = re.split(combined_pattern, content)
        
        # Process only non-LaTeX segments
        corrected_segments = []
        total_changes = defaultdict(int)
        
        for i, segment in enumerate(segments):
            if segment and i % 2 == 0:  # Even indices are non-LaTeX text
                corrected, changes = corrector.correct_text(segment)
                corrected_segments.append(corrected)
                for word, count in changes.items():
                    total_changes[word] += count
            else:
                corrected_segments.append(segment or '')
                
        return ''.join(corrected_segments), dict(total_changes)


class HTMLStrategy(FileProcessingStrategy):
    """Process HTML/XML files, preserving tags."""
    
    def process(self, content: str, corrector: SpellingCorrector) -> Tuple[str, Dict[str, int]]:
        # Pattern to match HTML tags and their contents
        tag_pattern = r'<[^>]+>'
        segments = re.split(f'({tag_pattern})', content)
        
        corrected_segments = []
        total_changes = defaultdict(int)
        
        for i, segment in enumerate(segments):
            if i % 2 == 0:  # Even indices are text content
                corrected, changes = corrector.correct_text(segment)
                corrected_segments.append(corrected)
                for word, count in changes.items():
                    total_changes[word] += count
            else:  # Odd indices are tags
                corrected_segments.append(segment)
                
        return ''.join(corrected_segments), dict(total_changes)


class JSONStrategy(FileProcessingStrategy):
    """Process JSON files, only correcting string values."""
    
    def process(self, content: str, corrector: SpellingCorrector) -> Tuple[str, Dict[str, int]]:
        try:
            data = json.loads(content)
            total_changes = defaultdict(int)
            self._process_json_value(data, corrector, total_changes)
            return json.dumps(data, indent=2, ensure_ascii=False), dict(total_changes)
        except json.JSONDecodeError:
            # Fall back to plain text processing
            return corrector.correct_text(content)
    
    def _process_json_value(self, value, corrector: SpellingCorrector, change_tracker: defaultdict):
        """Recursively process JSON values."""
        if isinstance(value, dict):
            for k, v in value.items():
                if isinstance(v, str):
                    corrected, changes = corrector.correct_text(v)
                    value[k] = corrected
                    for word, count in changes.items():
                        change_tracker[word] += count
                else:
                    self._process_json_value(v, corrector, change_tracker)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, str):
                    corrected, changes = corrector.correct_text(item)
                    value[i] = corrected
                    for word, count in changes.items():
                        change_tracker[word] += count
                else:
                    self._process_json_value(item, corrector, change_tracker)


class CodeStrategy(FileProcessingStrategy):
    """
    Process code files - only convert prose in comments and docstrings.

    NEVER converts:
    - String literals (API keys, config values, etc.)
    - Text inside quotes within comments (API references)
    - Variable names, function names, etc.

    DOES convert:
    - Unquoted prose in comments (# The behavior is good)
    - Unquoted prose in docstrings
    """

    def process(self, content: str, corrector: SpellingCorrector) -> Tuple[str, Dict[str, int]]:
        total_changes = defaultdict(int)
        result = []

        # Process the content, identifying comments and docstrings
        i = 0
        while i < len(content):
            # Check for triple-quoted strings
            if content[i:i+3] in ('"""', "'''"):
                quote = content[i:i+3]
                end = content.find(quote, i + 3)
                if end == -1:
                    end = len(content)
                else:
                    end += 3

                # Check if this is a string literal (preceded by = or prefix like r/f/b)
                # vs a docstring (at start of line after def/class or at module level)
                preceding = ''.join(result).rstrip()
                is_string_literal = (
                    preceding.endswith('=') or
                    preceding.endswith('r') or preceding.endswith('f') or
                    preceding.endswith('b') or preceding.endswith('rf') or
                    preceding.endswith('fr') or preceding.endswith('br') or
                    preceding.endswith('rb')
                )

                if is_string_literal:
                    # String literal - don't convert
                    result.append(content[i:end])
                else:
                    # Docstring - convert prose
                    docstring = content[i:end]
                    corrected, changes = self._process_docstring(docstring, corrector)
                    result.append(corrected)
                    for word, count in changes.items():
                        total_changes[word] += count
                i = end
                continue

            # Check for block comments /* ... */ or /** ... */
            if content[i:i+2] == '/*':
                end = content.find('*/', i + 2)
                if end == -1:
                    end = len(content)
                else:
                    end += 2

                comment = content[i:end]
                corrected, changes = self._process_comment(comment, corrector)
                result.append(corrected)
                for word, count in changes.items():
                    total_changes[word] += count
                i = end
                continue

            # Check for line comments (# or //)
            if content[i] == '#' or content[i:i+2] == '//':
                # Find end of line
                end = content.find('\n', i)
                if end == -1:
                    end = len(content)

                comment = content[i:end]
                corrected, changes = self._process_comment(comment, corrector)
                result.append(corrected)
                for word, count in changes.items():
                    total_changes[word] += count
                i = end
                continue

            # Check for string literals - skip them entirely
            if content[i] in ('"', "'"):
                quote = content[i]
                # Handle escaped quotes
                j = i + 1
                while j < len(content):
                    if content[j] == '\\':
                        j += 2  # Skip escaped char
                        continue
                    if content[j] == quote:
                        j += 1
                        break
                    j += 1

                result.append(content[i:j])  # Keep string unchanged
                i = j
                continue

            # Regular code - keep unchanged
            result.append(content[i])
            i += 1

        return ''.join(result), dict(total_changes)

    def _process_comment(self, comment: str, corrector: SpellingCorrector) -> Tuple[str, Dict[str, int]]:
        """
        Process a comment, converting only unquoted prose.
        Preserves quoted text like 'apiFieldName' or "colorScheme".
        """
        return self._convert_unquoted_text(comment, corrector)

    def _process_docstring(self, docstring: str, corrector: SpellingCorrector) -> Tuple[str, Dict[str, int]]:
        """
        Process a docstring, converting only unquoted prose.
        Preserves quoted text and code examples.
        """
        return self._convert_unquoted_text(docstring, corrector)

    def _convert_unquoted_text(self, text: str, corrector: SpellingCorrector) -> Tuple[str, Dict[str, int]]:
        """
        Convert text but preserve anything inside quotes.
        Handles triple quotes (docstring delimiters) specially.
        """
        total_changes = defaultdict(int)
        result = []
        i = 0

        while i < len(text):
            # Check for triple quotes first (docstring delimiters) - skip them
            if text[i:i+3] in ('"""', "'''"):
                result.append(text[i:i+3])
                i += 3
                continue

            # Check for quoted text - preserve it (single 'word' or "word")
            # But handle contractions like "It's" - apostrophe between letters is not a quote
            if text[i] in ('"', "'"):
                quote = text[i]

                # Check if this is a contraction (apostrophe between letters)
                if quote == "'":
                    prev_is_letter = i > 0 and text[i-1].isalpha()
                    next_is_letter = i + 1 < len(text) and text[i+1].isalpha()
                    if prev_is_letter and next_is_letter:
                        # It's a contraction, not a quoted string - keep it as prose
                        result.append(text[i])
                        i += 1
                        continue

                # Regular quoted string
                j = i + 1
                while j < len(text) and text[j] != quote:
                    if text[j] == '\\':
                        j += 2
                        continue
                    j += 1
                if j < len(text):
                    j += 1  # Include closing quote

                result.append(text[i:j])  # Keep quoted text unchanged
                i = j
                continue

            # Check for backtick code spans - preserve them
            if text[i] == '`':
                j = i + 1
                while j < len(text) and text[j] != '`':
                    j += 1
                if j < len(text):
                    j += 1

                result.append(text[i:j])  # Keep code spans unchanged
                i = j
                continue

            # Find the next quote or end of text
            next_quote = len(text)
            for q in ('"', "'", '`'):
                pos = text.find(q, i)
                if pos != -1 and pos < next_quote:
                    next_quote = pos

            # Process unquoted segment
            segment = text[i:next_quote]
            if segment:
                corrected, changes = corrector.correct_text(segment)
                result.append(corrected)
                for word, count in changes.items():
                    total_changes[word] += count

            i = next_quote

        return ''.join(result), dict(total_changes)


# Strategy instances
_STRATEGY_INSTANCES = {
    'text': PlainTextStrategy(),
    'latex': LaTeXStrategy(),
    'html': HTMLStrategy(),
    'json': JSONStrategy(),
    'code': CodeStrategy(),
}

# Build file extension to strategy mapping from config
def _build_file_strategies() -> Dict[str, FileProcessingStrategy]:
    """Build FILE_STRATEGIES from config.json."""
    strategies = {}
    config_strategies = _CONFIG['strategies']

    for strategy_name, strategy_config in config_strategies.items():
        strategy_instance = _STRATEGY_INSTANCES.get(strategy_name)
        if strategy_instance:
            for ext in strategy_config['extensions']:
                strategies[ext.lower()] = strategy_instance

    return strategies

FILE_STRATEGIES = _build_file_strategies()

# Build CODE_EXTENSIONS set from config
def _build_code_extensions() -> Set[str]:
    """Get code extensions from config."""
    config_strategies = _CONFIG.get('strategies', {})
    code_config = config_strategies.get('code', {})
    return set(ext.lower() for ext in code_config.get('extensions', []))

CODE_EXTENSIONS = _build_code_extensions()


def get_file_strategy(file_extension: str) -> FileProcessingStrategy:
    """Get the appropriate processing strategy for a file type."""
    return FILE_STRATEGIES.get(file_extension.lower(), PlainTextStrategy())


def is_code_file(file_extension: str) -> bool:
    """Check if file extension is a code file."""
    return file_extension.lower() in CODE_EXTENSIONS