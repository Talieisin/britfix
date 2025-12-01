"""
Core spell checking functionality shared between CLI tool and Claude Code hook.
"""
import re
import json
import os
from typing import Dict, List, Tuple, Optional, Set
from collections import defaultdict

# Load programming exclusions config if available
PROGRAMMING_EXCLUSIONS: Set[str] = set()
CODE_EXTENSIONS: Set[str] = set()
_exclusions_path = os.path.join(os.path.dirname(__file__), 'programming-exclusions.json')
if os.path.exists(_exclusions_path):
    try:
        with open(_exclusions_path, 'r') as f:
            _data = json.load(f)
            PROGRAMMING_EXCLUSIONS = set(word.lower() for word in _data.get('exclusions', []))
            CODE_EXTENSIONS = set(ext.lower() for ext in _data.get('code_extensions', []))
    except:
        pass

class SpellingCorrector:
    """Efficient spelling corrector with precompiled regex patterns."""

    def __init__(self, dictionary: Dict[str, str], exclude_programming_terms: bool = False):
        self.full_dictionary = {k.lower(): v for k, v in dictionary.items()}
        self.exclude_programming_terms = exclude_programming_terms

        # Create filtered dictionary for code files
        if PROGRAMMING_EXCLUSIONS:
            self.code_dictionary = {k: v for k, v in self.full_dictionary.items()
                                   if k not in PROGRAMMING_EXCLUSIONS}
        else:
            self.code_dictionary = self.full_dictionary

        # Default to full dictionary
        self.dictionary = self.full_dictionary
        self.pattern = self._compile_pattern()

        # Also compile pattern for code dictionary
        self._code_pattern = self._compile_pattern_for_dict(self.code_dictionary)
        self._full_pattern = self.pattern

    def _compile_pattern_for_dict(self, dictionary: Dict[str, str]) -> Optional[re.Pattern]:
        """Compile regex pattern for a given dictionary."""
        if not dictionary:
            return None
        pattern = r'\b(' + '|'.join(re.escape(word) for word in dictionary.keys()) + r')\b'
        return re.compile(pattern, re.IGNORECASE)

    def use_code_mode(self, enabled: bool = True):
        """Switch between code mode (with exclusions) and normal mode."""
        if enabled:
            self.dictionary = self.code_dictionary
            self.pattern = self._code_pattern
        else:
            self.dictionary = self.full_dictionary
            self.pattern = self._full_pattern
        
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
    """Process code files, only correcting comments and strings."""
    
    def __init__(self):
        # For code files, we always want to respect programming terms
        self.enforce_programming_exclusions = True
    
    def process(self, content: str, corrector: SpellingCorrector) -> Tuple[str, Dict[str, int]]:
        lines = content.split('\n')
        corrected_lines = []
        total_changes = defaultdict(int)
        
        for line in lines:
            # Simple heuristic: correct text in comments and strings
            if '#' in line:  # Python, Ruby, etc. comments
                parts = line.split('#', 1)
                if len(parts) == 2:
                    corrected, changes = corrector.correct_text(parts[1])
                    parts[1] = corrected
                    for word, count in changes.items():
                        total_changes[word] += count
                    line = '#'.join(parts)
            elif '//' in line:  # C-style comments
                parts = line.split('//', 1)
                if len(parts) == 2:
                    corrected, changes = corrector.correct_text(parts[1])
                    parts[1] = corrected
                    for word, count in changes.items():
                        total_changes[word] += count
                    line = '//'.join(parts)
            
            # Process strings (simplified - doesn't handle all cases)
            string_pattern = r'(["\'])([^"\']*)\1'
            def replace_string(match):
                quote = match.group(1)
                content = match.group(2)
                corrected, changes = corrector.correct_text(content)
                for word, count in changes.items():
                    total_changes[word] += count
                return f'{quote}{corrected}{quote}'
            
            line = re.sub(string_pattern, replace_string, line)
            corrected_lines.append(line)
            
        return '\n'.join(corrected_lines), dict(total_changes)


# Create code strategy instance to reuse
_code_strategy = CodeStrategy()

# File type to strategy mapping
FILE_STRATEGIES = {
    '.txt': PlainTextStrategy(),
    '.md': PlainTextStrategy(),
    '.tex': LaTeXStrategy(),
    '.html': HTMLStrategy(),
    '.htm': HTMLStrategy(),
    '.xml': HTMLStrategy(),
    '.json': JSONStrategy(),
    '.py': _code_strategy,
    '.js': _code_strategy,
    '.java': _code_strategy,
    '.cpp': _code_strategy,
    '.c': _code_strategy,
    '.h': _code_strategy,
    '.hpp': _code_strategy,
    '.cs': _code_strategy,
    '.rb': _code_strategy,
    '.go': _code_strategy,
    '.rs': _code_strategy,
    '.swift': _code_strategy,
    '.kt': _code_strategy,
}


def get_file_strategy(file_extension: str) -> FileProcessingStrategy:
    """Get the appropriate processing strategy for a file type."""
    return FILE_STRATEGIES.get(file_extension.lower(), PlainTextStrategy())


def is_code_file(file_extension: str) -> bool:
    """Check if file extension is a code file that should use programming exclusions."""
    return file_extension.lower() in CODE_EXTENSIONS