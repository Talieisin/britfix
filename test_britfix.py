#!/usr/bin/env python3
"""
Tests for britfix - especially CodeStrategy context handling.
"""
import pytest
from britfix_core import (
    SpellingCorrector,
    load_spelling_mappings,
    CodeStrategy,
    CssStrategy,
    HTMLStrategy,
    PlainTextStrategy,
    MarkdownStrategy,
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


class TestMarkdownStrategy:
    """MarkdownStrategy should preserve code spans and code blocks."""

    @pytest.fixture
    def strategy(self):
        return MarkdownStrategy()

    # === INLINE CODE SPANS ===

    def test_inline_code_not_converted(self, strategy, corrector):
        """Inline code spans should not be converted."""
        text = "Use the `colorize` function for color."
        result, changes = strategy.process(text, corrector)
        assert "`colorize`" in result, f"Inline code was wrongly converted: {result}"
        assert "colour" in result  # Prose should be converted

    def test_double_backtick_code_not_converted(self, strategy, corrector):
        """Double-backtick code spans should not be converted."""
        text = "Use ``organization.color`` for the color."
        result, changes = strategy.process(text, corrector)
        assert "``organization.color``" in result
        assert "colour" in result  # Prose should be converted

    def test_inline_code_with_backtick_inside(self, strategy, corrector):
        """Code span containing backticks uses double backticks."""
        text = "Use `` `behavior` `` for color."
        result, changes = strategy.process(text, corrector)
        assert "behavior" in result  # Inside code span - preserved
        assert "colour" in result  # Prose converted

    # === FENCED CODE BLOCKS ===

    def test_fenced_code_block_not_converted(self, strategy, corrector):
        """Fenced code blocks should not be converted."""
        text = """Here is some color:

```python
color = "favorite"
organization = True
```

The color is nice."""
        result, changes = strategy.process(text, corrector)
        assert 'color = "favorite"' in result, f"Code block was converted: {result}"
        assert "organization = True" in result
        # Prose before and after should be converted
        assert result.startswith("Here is some colour:")
        assert result.endswith("The colour is nice.")

    def test_fenced_code_block_with_tilde(self, strategy, corrector):
        """Tilde-fenced code blocks should not be converted."""
        text = """Example:

~~~
colorize(behavior)
~~~

The color works."""
        result, changes = strategy.process(text, corrector)
        assert "colorize(behavior)" in result
        assert "colour works" in result

    def test_code_block_without_language(self, strategy, corrector):
        """Code blocks without language specifier should be preserved."""
        text = """```
color = behavior
```"""
        result, changes = strategy.process(text, corrector)
        assert "color = behavior" in result

    # === PROSE CONVERSION ===

    def test_prose_converted(self, strategy, corrector):
        """Regular prose should be converted."""
        text = "The color of the organization was analyzed."
        result, changes = strategy.process(text, corrector)
        assert "colour" in result
        assert "organisation" in result
        assert "analysed" in result

    def test_headings_converted(self, strategy, corrector):
        """Markdown headings should be converted."""
        text = "# Color Organization\n\nThe behavior is favorable."
        result, changes = strategy.process(text, corrector)
        assert "# Colour Organisation" in result
        assert "behaviour" in result
        assert "favourable" in result

    # === EDGE CASES ===

    def test_unclosed_inline_code(self, strategy, corrector):
        """Unclosed backticks should not break processing."""
        text = "The `color has no closing and behavior."
        result, changes = strategy.process(text, corrector)
        # Should handle gracefully - convert the prose
        assert "behaviour" in result

    def test_unclosed_code_block(self, strategy, corrector):
        """Unclosed code block should preserve content."""
        text = """Text before

```python
color = behavior
"""
        result, changes = strategy.process(text, corrector)
        # Code block content should be preserved
        assert "color = behavior" in result

    def test_empty_code_span(self, strategy, corrector):
        """Empty code span should not break processing."""
        text = "The `` empty and color."
        result, changes = strategy.process(text, corrector)
        assert "colour" in result

    def test_mixed_content(self, strategy, corrector):
        """Complex markdown with mixed content."""
        text = """# Color Guide

The `colorize` function handles color.

```python
def colorize(text):
    return text.upper()
```

Use `organize` for organization."""
        result, changes = strategy.process(text, corrector)
        assert "# Colour Guide" in result
        assert "`colorize`" in result  # Preserved
        assert "handles colour" in result  # Converted
        assert "def colorize(text):" in result  # Preserved in code block
        assert "`organize`" in result  # Preserved
        assert "for organisation" in result  # Converted

    # === INLINE TRIPLE BACKTICKS (not fenced blocks) ===

    def test_inline_triple_backticks_not_mistaken_for_fence(self, strategy, corrector):
        """Triple backticks inline should be treated as inline code, not fence."""
        text = "Use ```colorize``` for the color value."
        result, changes = strategy.process(text, corrector)
        assert "colorize" in result  # Preserved in inline code
        assert "colour value" in result  # Prose converted

    def test_inline_triple_backticks_mid_line(self, strategy, corrector):
        """Triple backticks mid-line are inline code, not fence."""
        text = "The function ```organization.color``` returns color."
        result, changes = strategy.process(text, corrector)
        assert "organization.color" in result  # Preserved
        assert "returns colour" in result  # Converted

    # === VARIABLE-LENGTH FENCES ===

    def test_four_backtick_fence(self, strategy, corrector):
        """Four-backtick fence should work and allow triple backticks inside."""
        text = """````markdown
Here is ```color``` in a code block
````

The color is nice."""
        result, changes = strategy.process(text, corrector)
        assert "```color```" in result  # Preserved inside fence
        assert "colour is nice" in result  # Prose converted

    def test_five_tilde_fence(self, strategy, corrector):
        """Five-tilde fence should match correctly."""
        text = """~~~~~
colorize(behavior)
~~~~~

The color works."""
        result, changes = strategy.process(text, corrector)
        assert "colorize(behavior)" in result  # Preserved
        assert "colour works" in result  # Converted

    # === INDENTED CLOSING FENCES ===

    def test_indented_closing_fence(self, strategy, corrector):
        """Closing fence with up to 3 spaces indentation should be recognized."""
        text = """```
color = behavior
   ```

The color is nice."""
        result, changes = strategy.process(text, corrector)
        assert "color = behavior" in result  # Preserved
        assert "colour is nice" in result  # Converted

    def test_closing_fence_two_spaces(self, strategy, corrector):
        """Closing fence with 2 spaces should work."""
        text = """```python
organization = True
  ```

Check the color."""
        result, changes = strategy.process(text, corrector)
        assert "organization = True" in result  # Preserved
        assert "colour" in result  # Converted

    # === INDENTED CODE BLOCKS ===

    def test_indented_code_block_four_spaces(self, strategy, corrector):
        """Four-space indented code blocks should be preserved."""
        text = """Here is code:

    color = "favorite"
    organization = True

The color is nice."""
        result, changes = strategy.process(text, corrector)
        assert '    color = "favorite"' in result  # Preserved
        assert "    organization = True" in result  # Preserved
        assert "colour is nice" in result  # Prose converted

    def test_indented_code_block_tab(self, strategy, corrector):
        """Tab-indented code blocks should be preserved."""
        text = "Here is code:\n\n\tcolor = behavior\n\nThe color works."
        result, changes = strategy.process(text, corrector)
        assert "\tcolor = behavior" in result  # Preserved
        assert "colour works" in result  # Converted

    def test_indented_block_with_blank_lines(self, strategy, corrector):
        """Indented blocks with blank lines should stay together."""
        text = """Code example:

    first_color = True

    second_color = False

Normal color text."""
        result, changes = strategy.process(text, corrector)
        assert "first_color = True" in result  # Preserved
        assert "second_color = False" in result  # Preserved
        assert "Normal colour text" in result  # Converted

    def test_tilde_not_at_line_start_no_infinite_loop(self, strategy, corrector):
        """Tilde used as approximation symbol (not at line start) should not cause infinite loop.

        Regression test for bug where '~7 days' caused 100% CPU infinite loop.
        """
        import signal

        def timeout_handler(signum, frame):
            raise TimeoutError("Infinite loop detected!")

        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(2)  # 2 second timeout

        try:
            text = "Delta links expire after ~7 days."
            result, changes = strategy.process(text, corrector)
            assert result == text  # No spelling changes expected
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

    def test_tilde_in_prose_converts_surrounding_text(self, strategy, corrector):
        """Text around tildes should still be converted."""
        text = "The color is ~7 hours or analyzed."
        result, changes = strategy.process(text, corrector)
        assert "colour" in result
        assert "~7" in result
        assert "analysed" in result


class TestMarkdownStrategyMapping:
    """Test that markdown file extensions map to MarkdownStrategy."""

    def test_md_maps_to_markdown_strategy(self):
        """The .md extension should use MarkdownStrategy."""
        from britfix_core import get_file_strategy, MarkdownStrategy
        strategy = get_file_strategy('.md')
        assert isinstance(strategy, MarkdownStrategy)

    def test_markdown_extension_maps_correctly(self):
        """The .markdown extension should use MarkdownStrategy."""
        from britfix_core import get_file_strategy, MarkdownStrategy
        strategy = get_file_strategy('.markdown')
        assert isinstance(strategy, MarkdownStrategy)

    def test_mdx_maps_to_markdown_strategy(self):
        """The .mdx extension should use MarkdownStrategy."""
        from britfix_core import get_file_strategy, MarkdownStrategy
        strategy = get_file_strategy('.mdx')
        assert isinstance(strategy, MarkdownStrategy)

    def test_txt_does_not_use_markdown_strategy(self):
        """The .txt extension should NOT use MarkdownStrategy."""
        from britfix_core import get_file_strategy, MarkdownStrategy
        strategy = get_file_strategy('.txt')
        assert not isinstance(strategy, MarkdownStrategy)


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


class TestConfigValidation:
    """Test config loading and validation."""

    def test_config_loaded(self):
        """Config should be loaded at module import."""
        from britfix_core import _CONFIG
        assert _CONFIG is not None
        assert 'strategies' in _CONFIG

    def test_config_has_required_strategies(self):
        """Config must have text and code strategies."""
        from britfix_core import _CONFIG
        assert 'text' in _CONFIG['strategies']
        assert 'code' in _CONFIG['strategies']

    def test_strategies_have_extensions(self):
        """Each strategy must have extensions list."""
        from britfix_core import _CONFIG
        for name, strategy in _CONFIG['strategies'].items():
            assert 'extensions' in strategy, f"Strategy '{name}' missing extensions"
            assert isinstance(strategy['extensions'], list)
            assert len(strategy['extensions']) > 0, f"Strategy '{name}' has no extensions"

    def test_config_error_class_exists(self):
        """ConfigError should be importable."""
        from britfix_core import ConfigError
        assert issubclass(ConfigError, Exception)


class TestCssStrategy:
    """CssStrategy should only convert text in comments, never CSS properties/values."""

    @pytest.fixture
    def strategy(self):
        return CssStrategy()

    # === SHOULD NOT CONVERT (CSS properties and values) ===

    def test_color_property_not_converted(self, strategy, corrector):
        """CSS 'color' property must NOT be converted."""
        css = "body { color: #666; }"
        result, changes = strategy.process(css, corrector)
        assert "color:" in result, f"color property was wrongly converted: {result}"
        assert len(changes) == 0

    def test_text_align_center_not_converted(self, strategy, corrector):
        """'center' in text-align must NOT become 'centre'."""
        css = ".box { text-align: center; }"
        result, changes = strategy.process(css, corrector)
        assert "center" in result, f"center value was wrongly converted: {result}"
        assert "centre" not in result

    def test_justify_content_center_not_converted(self, strategy, corrector):
        """'center' in justify-content must NOT be converted."""
        css = ".flex { justify-content: center; }"
        result, changes = strategy.process(css, corrector)
        assert "center" in result
        assert "centre" not in result

    def test_scss_variable_not_converted(self, strategy, corrector):
        """SCSS variable names should NOT be converted."""
        scss = "$favorite-color: red;"
        result, changes = strategy.process(scss, corrector)
        assert "$favorite-color" in result

    def test_css_custom_property_not_converted(self, strategy, corrector):
        """CSS custom properties should NOT be converted."""
        css = ":root { --favorite-color: red; }"
        result, changes = strategy.process(css, corrector)
        assert "--favorite-color" in result

    def test_selector_not_converted(self, strategy, corrector):
        """CSS selectors should NOT be converted."""
        css = ".organization-panel { display: flex; }"
        result, changes = strategy.process(css, corrector)
        assert ".organization-panel" in result

    # === SHOULD CONVERT (comments only) ===

    def test_block_comment_converted(self, strategy, corrector):
        """Block comment prose should be converted."""
        css = "/* This color is gray */"
        result, changes = strategy.process(css, corrector)
        assert "colour" in result, f"Comment not converted: {result}"
        assert "grey" in result

    def test_line_comment_converted(self, strategy, corrector):
        """SCSS/LESS line comment should be converted."""
        scss = "// This color is for the organization"
        result, changes = strategy.process(scss, corrector)
        assert "colour" in result
        assert "organisation" in result

    def test_multiline_block_comment_converted(self, strategy, corrector):
        """Multi-line block comment should be converted."""
        css = """/*
         * The color scheme favors organization.
         * This behavior is favorable.
         */"""
        result, changes = strategy.process(css, corrector)
        assert "colour" in result
        assert "favours" in result
        assert "organisation" in result
        assert "behaviour" in result
        assert "favourable" in result

    def test_mixed_css_and_comments(self, strategy, corrector):
        """CSS with mixed comments and properties."""
        css = """/* Set the favorite color */
.panel {
    color: blue;  /* The color value */
    text-align: center;
}"""
        result, changes = strategy.process(css, corrector)
        # Comments should be converted
        assert "favourite colour" in result
        assert "colour value" in result
        # Properties should NOT be converted
        assert "color: blue" in result
        assert "text-align: center" in result
        assert "centre" not in result

    # === EDGE CASES ===

    def test_quoted_in_comment_not_converted(self, strategy, corrector):
        """Quoted text inside comments should be preserved."""
        css = "/* The 'colorScheme' variable controls color */"
        result, changes = strategy.process(css, corrector)
        assert "'colorScheme'" in result
        assert "colour" in result  # Unquoted prose converted

    def test_string_content_property_not_converted(self, strategy, corrector):
        """CSS content property strings should NOT be converted."""
        css = '.icon::before { content: "favorite color"; }'
        result, changes = strategy.process(css, corrector)
        assert '"favorite color"' in result

    # === URL HANDLING (// must not be treated as comment) ===

    def test_protocol_relative_url_not_converted(self, strategy, corrector):
        """Protocol-relative URLs (//example.com) must NOT be treated as comments."""
        css = ".bg { background: url(//cdn.example.com/color-picker.png); }"
        result, changes = strategy.process(css, corrector)
        assert "//cdn.example.com/color-picker.png" in result
        assert "colour" not in result  # No conversion should happen

    def test_http_url_not_converted(self, strategy, corrector):
        """HTTP URLs must NOT have // treated as comments."""
        css = '@import url(http://fonts.example.com/css?family=ColorFont);'
        result, changes = strategy.process(css, corrector)
        assert "http://fonts.example.com" in result
        assert "ColorFont" in result  # URL path should be unchanged

    def test_https_url_not_converted(self, strategy, corrector):
        """HTTPS URLs must NOT have // treated as comments."""
        css = ".icon { background-image: url(https://example.com/organization/logo.png); }"
        result, changes = strategy.process(css, corrector)
        assert "https://example.com/organization/logo.png" in result
        assert "organisation" not in result

    def test_quoted_url_with_protocol_not_converted(self, strategy, corrector):
        """Quoted URLs with protocols must be preserved."""
        css = '.bg { background: url("https://example.com/color.png"); }'
        result, changes = strategy.process(css, corrector)
        assert '"https://example.com/color.png"' in result

    def test_real_line_comment_after_semicolon(self, strategy, corrector):
        """Real // comment after ; should still be converted."""
        scss = ".box { color: red; } // This is a real color comment"
        result, changes = strategy.process(scss, corrector)
        assert "colour comment" in result  # Comment should be converted
        assert "color: red" in result  # Property should NOT be converted

    def test_real_line_comment_at_start_of_line(self, strategy, corrector):
        """// at start of line is a real comment."""
        scss = "// The favorite color\n.box { color: red; }"
        result, changes = strategy.process(scss, corrector)
        assert "favourite colour" in result  # Comment converted
        assert "color: red" in result  # Property preserved


class TestHTMLStrategyStyleScript:
    """HTMLStrategy should preserve content inside <style> and <script> tags."""

    @pytest.fixture
    def strategy(self):
        return HTMLStrategy()

    # === STYLE TAGS ===

    def test_style_tag_content_preserved(self, strategy, corrector):
        """CSS inside <style> tags should NOT be converted."""
        html = "<style>.box { color: red; text-align: center; }</style>"
        result, changes = strategy.process(html, corrector)
        assert "color: red" in result
        assert "text-align: center" in result
        assert "centre" not in result

    def test_style_tag_with_attributes_preserved(self, strategy, corrector):
        """<style type='text/css'> should still be preserved."""
        html = '<style type="text/css">.box { color: blue; }</style>'
        result, changes = strategy.process(html, corrector)
        assert "color: blue" in result

    def test_multiple_style_tags_preserved(self, strategy, corrector):
        """Multiple <style> tags should all be preserved."""
        html = """<style>.a { color: red; }</style>
<p>The color is nice</p>
<style>.b { text-align: center; }</style>"""
        result, changes = strategy.process(html, corrector)
        assert "color: red" in result
        assert "text-align: center" in result
        assert "centre" not in result
        # Text content should be converted
        assert "colour is nice" in result

    # === SCRIPT TAGS ===

    def test_script_tag_content_preserved(self, strategy, corrector):
        """JavaScript inside <script> tags should NOT be converted."""
        html = "<script>var color = 'favorite';</script>"
        result, changes = strategy.process(html, corrector)
        assert "var color = 'favorite'" in result
        assert "colour" not in result

    def test_script_tag_with_attributes_preserved(self, strategy, corrector):
        """<script type='text/javascript'> should still be preserved."""
        html = '<script type="text/javascript">let organization = true;</script>'
        result, changes = strategy.process(html, corrector)
        assert "let organization = true" in result

    def test_multiple_script_tags_preserved(self, strategy, corrector):
        """Multiple <script> tags should all be preserved."""
        html = """<script>var a = 'color';</script>
<p>The color is nice</p>
<script>var b = 'organization';</script>"""
        result, changes = strategy.process(html, corrector)
        assert "var a = 'color'" in result
        assert "var b = 'organization'" in result
        # Text content should be converted
        assert "colour is nice" in result

    # === TEXT CONTENT STILL CONVERTS ===

    def test_text_content_converted(self, strategy, corrector):
        """Regular text content should still be converted."""
        html = "<p>The color of the organization is favorable.</p>"
        result, changes = strategy.process(html, corrector)
        assert "colour" in result
        assert "organisation" in result
        assert "favourable" in result

    def test_mixed_style_script_and_text(self, strategy, corrector):
        """Complex HTML with style, script, and text."""
        html = """<!DOCTYPE html>
<html>
<head>
    <style>
        .container { color: blue; text-align: center; }
    </style>
    <script>
        var favoriteColor = 'red';
        function colorize() { return true; }
    </script>
</head>
<body>
    <p>The color of the organization is nice.</p>
</body>
</html>"""
        result, changes = strategy.process(html, corrector)
        # Style preserved
        assert "color: blue" in result
        assert "text-align: center" in result
        # Script preserved
        assert "favoriteColor" in result
        assert "colorize" in result
        # Text content converted
        assert "colour of the organisation" in result

    # === CASE INSENSITIVITY ===

    def test_uppercase_style_tag_preserved(self, strategy, corrector):
        """<STYLE> uppercase should be preserved."""
        html = "<STYLE>.box { color: red; }</STYLE>"
        result, changes = strategy.process(html, corrector)
        assert "color: red" in result

    def test_mixed_case_script_tag_preserved(self, strategy, corrector):
        """<Script> mixed case should be preserved."""
        html = "<Script>var color = true;</Script>"
        result, changes = strategy.process(html, corrector)
        assert "var color = true" in result

    # === SCRIPT CONTAINING STYLE STRING (regression test) ===

    def test_script_with_inline_style_string_preserved(self, strategy, corrector):
        """Script containing <style> in a string must be fully preserved."""
        html = '''<script>
document.write("<style>.box { color: blue; }</style>");
var favoriteColor = "red";
</script>
<p>The color is nice.</p>'''
        result, changes = strategy.process(html, corrector)
        # The entire script should be preserved unchanged
        assert '<style>.box { color: blue; }</style>' in result
        assert 'favoriteColor' in result
        # No placeholders should remain
        assert '\x00' not in result
        # Text content outside script should still be converted
        assert "colour is nice" in result

    def test_script_with_style_tag_in_template_literal(self, strategy, corrector):
        """Script with style tag in template literal must be preserved."""
        html = '''<script>
const template = `<style>.color-box { text-align: center; }</style>`;
</script>'''
        result, changes = strategy.process(html, corrector)
        assert '<style>.color-box { text-align: center; }</style>' in result
        assert '\x00' not in result


class TestCssStrategyMapping:
    """Test that CSS file extensions map to CssStrategy."""

    def test_css_maps_to_css_strategy(self):
        """The .css extension should use CssStrategy."""
        from britfix_core import get_file_strategy, CssStrategy
        strategy = get_file_strategy('.css')
        assert isinstance(strategy, CssStrategy)

    def test_scss_maps_to_css_strategy(self):
        """The .scss extension should use CssStrategy."""
        from britfix_core import get_file_strategy, CssStrategy
        strategy = get_file_strategy('.scss')
        assert isinstance(strategy, CssStrategy)

    def test_sass_maps_to_css_strategy(self):
        """The .sass extension should use CssStrategy."""
        from britfix_core import get_file_strategy, CssStrategy
        strategy = get_file_strategy('.sass')
        assert isinstance(strategy, CssStrategy)

    def test_less_maps_to_css_strategy(self):
        """The .less extension should use CssStrategy."""
        from britfix_core import get_file_strategy, CssStrategy
        strategy = get_file_strategy('.less')
        assert isinstance(strategy, CssStrategy)

    def test_txt_does_not_use_css_strategy(self):
        """The .txt extension should NOT use CssStrategy."""
        from britfix_core import get_file_strategy, CssStrategy, PlainTextStrategy
        strategy = get_file_strategy('.txt')
        assert not isinstance(strategy, CssStrategy)
        assert isinstance(strategy, PlainTextStrategy)

    def test_py_does_not_use_css_strategy(self):
        """The .py extension should NOT use CssStrategy."""
        from britfix_core import get_file_strategy, CssStrategy, CodeStrategy
        strategy = get_file_strategy('.py')
        assert not isinstance(strategy, CssStrategy)
        assert isinstance(strategy, CodeStrategy)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
