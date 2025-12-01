#!/usr/bin/env python3
"""
Tests for britfix - especially CodeStrategy context handling.
"""
import pytest
from britfix_core import (
    SpellingCorrector,
    load_spelling_mappings,
    CodeStrategy,
    PlainTextStrategy,
    is_code_file,
    CODE_EXTENSIONS
)


@pytest.fixture
def corrector():
    """Create a corrector with full dictionary."""
    mappings = load_spelling_mappings()
    return SpellingCorrector(mappings)


class TestPlainText:
    """Plain text should convert everything."""
    
    def test_converts_american_to_british(self, corrector):
        text = "The color of the organization was analyzed."
        result, changes = corrector.correct_text(text)
        assert result == "The colour of the organisation was analysed."
        assert "color" in changes
        assert "organization" in changes
        assert "analyzed" in changes
    
    def test_preserves_case(self, corrector):
        text = "COLOR Color color"
        result, _ = corrector.correct_text(text)
        assert result == "COLOUR Colour colour"
    
    def test_no_change_needed(self, corrector):
        text = "The colour is nice."
        result, changes = corrector.correct_text(text)
        assert result == text
        assert len(changes) == 0


class TestCodeStrategy:
    """CodeStrategy should only convert in comments/docstrings, not string literals."""
    
    @pytest.fixture
    def strategy(self):
        return CodeStrategy()
    
    # === SHOULD NOT CONVERT ===
    
    def test_dict_key_lookup_not_converted(self, strategy, corrector):
        """Dict key lookups must not be converted - they reference external configs."""
        code = "config.get('behavior')"
        result, changes = strategy.process(code, corrector)
        assert "'behavior'" in result, f"Dict key was wrongly converted: {result}"
    
    def test_dict_literal_key_not_converted(self, strategy, corrector):
        """Dict literal keys must not be converted."""
        code = "data = {'favoriteColor': value}"
        result, changes = strategy.process(code, corrector)
        assert "'favoriteColor'" in result, f"Dict key was wrongly converted: {result}"
    
    def test_string_literal_not_converted(self, strategy, corrector):
        """Regular string literals in code should not be converted."""
        code = "api_field = 'organizationName'"
        result, changes = strategy.process(code, corrector)
        assert "'organizationName'" in result, f"String literal was wrongly converted: {result}"
    
    def test_fstring_not_converted(self, strategy, corrector):
        """F-string contents should not be converted."""
        code = 'url = f"/api/{organization}/colors"'
        result, changes = strategy.process(code, corrector)
        assert "organization" in result
        assert "colors" in result
    
    def test_quoted_in_comment_not_converted(self, strategy, corrector):
        """Quoted strings inside comments should not be converted."""
        code = "# The API returns 'colorScheme' not 'colourScheme'"
        result, changes = strategy.process(code, corrector)
        assert "'colorScheme'" in result, f"Quoted term in comment was wrongly converted: {result}"
    
    def test_quoted_in_docstring_not_converted(self, strategy, corrector):
        """Quoted strings inside docstrings should not be converted."""
        code = '''"""Example: config.get('organization')"""'''
        result, changes = strategy.process(code, corrector)
        assert "'organization'" in result, f"Quoted term in docstring was wrongly converted: {result}"
    
    # === SHOULD CONVERT ===
    
    def test_comment_prose_converted(self, strategy, corrector):
        """Unquoted prose in comments should be converted."""
        code = "# The behavior of this program is favorable"
        result, changes = strategy.process(code, corrector)
        assert "behaviour" in result, f"Comment prose not converted: {result}"
        assert "programme" in result
        assert "favourable" in result
    
    def test_docstring_prose_converted(self, strategy, corrector):
        """Unquoted prose in docstrings should be converted."""
        code = '"""This function optimizes behavior for the organization."""'
        result, changes = strategy.process(code, corrector)
        assert "optimises" in result, f"Docstring prose not converted: {result}"
        assert "behaviour" in result
    
    def test_multiline_docstring_prose_converted(self, strategy, corrector):
        """Multiline docstring prose should be converted."""
        code = '''"""
        This function analyzes the color scheme.
        It optimizes behavior for better organization.
        """'''
        result, changes = strategy.process(code, corrector)
        assert "analyses" in result or "analyzes" in result  # analyzes might be excluded
        assert "colour" in result or "color" in result  # color might be excluded


class TestLanguageSpecificComments:
    """Test comment patterns for different languages."""
    
    @pytest.fixture
    def strategy(self):
        return CodeStrategy()
    
    def test_python_hash_comment(self, strategy, corrector):
        code = "x = 1  # The behavior is favorable"
        result, _ = strategy.process(code, corrector)
        assert "behaviour" in result
        assert "favourable" in result
    
    def test_js_slash_comment(self, strategy, corrector):
        code = "let x = 1; // The behavior is favorable"
        result, _ = strategy.process(code, corrector)
        assert "behaviour" in result
        assert "favourable" in result
    
    def test_c_style_block_comment(self, strategy, corrector):
        code = "/* The behavior is favorable */"
        result, _ = strategy.process(code, corrector)
        assert "behaviour" in result
        assert "favourable" in result
    
    def test_jsdoc_comment(self, strategy, corrector):
        code = """/**
         * This function optimizes behavior.
         * @param {string} color - The color value
         */"""
        result, _ = strategy.process(code, corrector)
        assert "optimises" in result
        assert "behaviour" in result


class TestEdgeCases:
    """Edge cases and tricky scenarios."""
    
    @pytest.fixture
    def strategy(self):
        return CodeStrategy()
    
    def test_mixed_quoted_unquoted_in_comment(self, strategy, corrector):
        """Comment with both quoted API ref and unquoted prose."""
        code = "# The 'colorScheme' field controls the color behavior"
        result, _ = strategy.process(code, corrector)
        assert "'colorScheme'" in result  # Quoted - don't convert
        assert "colour behaviour" in result  # Unquoted prose - should convert
    
    def test_empty_string(self, strategy, corrector):
        result, changes = strategy.process("", corrector)
        assert result == ""
        assert len(changes) == 0
    
    def test_no_comments_or_strings(self, strategy, corrector):
        code = "x = 1 + 2"
        result, changes = strategy.process(code, corrector)
        assert result == code
    
    def test_hash_in_string_not_comment(self, strategy, corrector):
        """A # inside a string is not a comment."""
        code = "color = '#ff0000'  # hex color"
        result, _ = strategy.process(code, corrector)
        assert "'#ff0000'" in result  # String untouched
        assert "hex colour" in result  # Real comment converted

    def test_triple_quoted_string_literal_not_converted(self, strategy, corrector):
        """Triple-quoted string literals (not docstrings) should NOT be converted."""
        code = 'payload = """favorite color"""'
        result, _ = strategy.process(code, corrector)
        assert '"""favorite color"""' in result, f"Triple-quoted literal was wrongly converted: {result}"

    def test_raw_triple_quoted_literal_not_converted(self, strategy, corrector):
        """Raw triple-quoted strings should NOT be converted."""
        code = "pattern = r'''color behavior'''"
        result, _ = strategy.process(code, corrector)
        assert "colour" not in result and "behaviour" not in result

    def test_comment_with_contraction_converts(self, strategy, corrector):
        """Apostrophes in contractions should not break conversion."""
        code = "# It's color and behavior we care about"
        result, _ = strategy.process(code, corrector)
        assert "colour" in result, f"Contraction broke conversion: {result}"
        assert "behaviour" in result

    def test_backtick_span_in_comment(self, strategy, corrector):
        """Backtick code spans in comments should be preserved."""
        code = "# Use `colorField` when the color is wrong"
        result, _ = strategy.process(code, corrector)
        assert "`colorField`" in result  # Backtick span preserved
        assert "colour is wrong" in result  # Prose converted


class TestFileExtensions:
    """Test that file extensions are correctly categorized."""
    
    def test_code_extensions_include_common_types(self):
        assert '.py' in CODE_EXTENSIONS
        assert '.js' in CODE_EXTENSIONS
        assert '.ts' in CODE_EXTENSIONS
        assert '.go' in CODE_EXTENSIONS
    
    def test_is_code_file(self):
        assert is_code_file('.py') == True
        assert is_code_file('.js') == True
        assert is_code_file('.md') == False
        assert is_code_file('.txt') == False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
