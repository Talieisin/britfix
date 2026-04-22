#!/usr/bin/env python3
"""
Tests for britfix - especially CodeStrategy context handling.
"""
import os
import pytest
from pathlib import Path
from britfix_core import (
    SpellingCorrector,
    load_spelling_mappings,
    CodeStrategy,
    CssStrategy,
    HTMLStrategy,
    PlainTextStrategy,
    MarkdownStrategy,
    JSONStrategy,
    is_code_file,
    CODE_EXTENSIONS,
    parse_britfixignore,
    get_user_ignore_path,
    discover_ignore_words,
    filter_dictionary,
    get_corrector_for_strategy,
    get_file_strategy_name,
    _ignore_cache,
    _corrector_cache,
)
from britfix import apply_replacements, group_replacements_by_word


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

    # === HTML TAGS ===

    def test_html_attribute_value_preserved(self, strategy, corrector):
        """Values inside HTML attributes must not be corrected (e.g. align="center")."""
        text = '<p align="center">The center</p>'
        result, changes = strategy.process(text, corrector)
        assert 'align="center"' in result, f"Attribute value was converted: {result}"
        assert '>The centre<' in result, f"Prose inside tag was not converted: {result}"

    def test_prose_around_html_tags_still_corrected(self, strategy, corrector):
        """Prose outside HTML tags should still be converted normally."""
        text = 'Before color <span>inside color</span> after color.'
        result, changes = strategy.process(text, corrector)
        assert 'Before colour ' in result
        assert '>inside colour<' in result
        assert ' after colour.' in result

    def test_bare_angle_brackets_in_prose_not_treated_as_tag(self, strategy, corrector):
        """A bare `<` or `>` in prose should not be confused with an HTML tag."""
        text = "If 3 < 5 and color then organize."
        result, changes = strategy.process(text, corrector)
        assert "3 < 5" in result
        assert "colour" in result
        assert "organise" in result

    def test_self_closing_tag_attribute_preserved(self, strategy, corrector):
        """Self-closing tags with attributes should be preserved verbatim."""
        text = '<img alt="color" src="x.png" /> and the color is blue.'
        result, changes = strategy.process(text, corrector)
        assert '<img alt="color" src="x.png" />' in result, \
            f"Self-closing tag was modified: {result}"
        assert "the colour is blue" in result

    def test_multiline_tag_body_preserved(self, strategy, corrector):
        """HTML tags whose attributes span multiple lines should still be preserved."""
        text = '<div\n  class="color"\n  id="main"\n>inside color</div>'
        result, changes = strategy.process(text, corrector)
        assert 'class="color"' in result, f"Multi-line tag attribute was modified: {result}"
        assert 'id="main"' in result
        assert '>inside colour<' in result

    def test_markdown_autolink_preserved(self, strategy, corrector):
        """Markdown autolinks like <http://...> happen to match the tag pattern and should be preserved."""
        text = '<http://color.com> and color.'
        result, changes = strategy.process(text, corrector)
        assert '<http://color.com>' in result, \
            f"Autolink URL was converted: {result}"
        assert 'and colour.' in result

    # === BLOCKQUOTES ===

    def test_blockquote_line_preserved(self, strategy, corrector):
        """A single blockquote line should be preserved verbatim (quoted text is verbatim)."""
        text = '> "The organization analyzed its color scheme."'
        result, changes = strategy.process(text, corrector)
        assert result == text, f"Blockquote was modified: {result}"

    def test_blockquote_preserved_prose_converted(self, strategy, corrector):
        """Prose around a blockquote should be converted; blockquote itself should not."""
        text = """Before the color.

> "The organization analyzed its color scheme."

After the color."""
        result, changes = strategy.process(text, corrector)
        assert '> "The organization analyzed its color scheme."' in result
        assert "Before the colour." in result
        assert "After the colour." in result

    def test_multiline_blockquote_preserved(self, strategy, corrector):
        """Multi-line blockquotes should preserve every line."""
        text = """Prose with color.

> "First line with organization.
> Second line with behavior.
> Third line with favorite."

More color prose."""
        result, changes = strategy.process(text, corrector)
        assert "> \"First line with organization." in result
        assert "> Second line with behavior." in result
        assert "> Third line with favorite.\"" in result
        assert "with colour" in result
        assert "More colour prose." in result

    def test_blockquote_with_leading_spaces_preserved(self, strategy, corrector):
        """Blockquotes with up to 3 leading spaces should still be preserved."""
        text = """Prose color.

   > "Indented quote with organization."

More color."""
        result, changes = strategy.process(text, corrector)
        assert '   > "Indented quote with organization."' in result
        assert "Prose colour." in result
        assert "More colour." in result

    def test_four_space_indent_is_code_not_blockquote(self, strategy, corrector):
        """4+ leading spaces should be treated as indented code block, not blockquote."""
        text = """Prose color.

    > "This is indented code, not a blockquote with organization."

More color."""
        result, changes = strategy.process(text, corrector)
        # 4 spaces makes this an indented code block — preserved anyway, so organization stays
        assert "organization" in result
        assert "Prose colour." in result
        assert "More colour." in result

    def test_greater_than_in_prose_not_treated_as_blockquote(self, strategy, corrector):
        """A > mid-line should not trigger blockquote preservation."""
        text = "If color > organization, analyze the behavior."
        result, changes = strategy.process(text, corrector)
        assert "colour" in result
        assert "organisation" in result
        assert "analyse" in result
        assert "behaviour" in result

    def test_blockquote_at_start_of_file(self, strategy, corrector):
        """A blockquote as the very first line should be preserved."""
        text = '> "Opening quote with organization."\n\nFollowing color prose.'
        result, changes = strategy.process(text, corrector)
        assert '> "Opening quote with organization."' in result
        assert "Following colour prose." in result

    def test_blockquote_at_end_of_file_no_trailing_newline(self, strategy, corrector):
        """A blockquote at the very end of the file (no trailing newline) should be preserved."""
        text = 'Leading color prose.\n\n> "Closing quote with organization."'
        result, changes = strategy.process(text, corrector)
        assert '> "Closing quote with organization."' in result
        assert "Leading colour prose." in result


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


class TestGetFileStrategyName:
    """Test get_file_strategy_name returns correct strategy names."""

    def test_python_is_code(self):
        assert get_file_strategy_name('.py') == 'code'

    def test_md_is_markdown(self):
        assert get_file_strategy_name('.md') == 'markdown'

    def test_txt_is_text(self):
        assert get_file_strategy_name('.txt') == 'text'

    def test_css_is_css(self):
        assert get_file_strategy_name('.css') == 'css'

    def test_unknown_defaults_to_text(self):
        assert get_file_strategy_name('.xyz') == 'text'


class TestBritfixIgnoreParsing:
    """Test .britfixignore file parsing."""

    def test_empty_file(self):
        g, s = parse_britfixignore('')
        assert g == set()
        assert s == {}

    def test_comments_and_blank_lines(self):
        content = "# a comment\n\n# another\n"
        g, s = parse_britfixignore(content)
        assert g == set()
        assert s == {}

    def test_global_words(self):
        content = "color\nbehavior\n"
        g, s = parse_britfixignore(content)
        assert g == {'color', 'behavior'}
        assert s == {}

    def test_scoped_words(self):
        content = "code:color\nmarkdown:dialog\n"
        g, s = parse_britfixignore(content)
        assert g == set()
        assert s == {'code': {'color'}, 'markdown': {'dialog'}}

    def test_mixed_global_and_scoped(self):
        content = "color\ncode:dialog\n"
        g, s = parse_britfixignore(content)
        assert g == {'color'}
        assert s == {'code': {'dialog'}}

    def test_whitespace_handling(self):
        content = "  color  \n  code : dialog  \n"
        g, s = parse_britfixignore(content)
        assert 'color' in g
        assert 'dialog' in s.get('code', set())

    def test_case_insensitivity(self):
        content = "Color\nCode:Dialog\n"
        g, s = parse_britfixignore(content)
        assert 'color' in g
        assert 'dialog' in s.get('code', set())

    def test_unknown_strategy_warns(self, capsys):
        content = "bogus:color\n"
        g, s = parse_britfixignore(content)
        assert g == set()
        assert s == {}
        captured = capsys.readouterr()
        assert "unknown strategy 'bogus'" in captured.err

    def test_empty_word_after_colon_skipped(self):
        content = "code:\n"
        g, s = parse_britfixignore(content)
        assert g == set()
        assert s == {}

    def test_multiple_words_same_strategy(self):
        content = "code:color\ncode:dialog\ncode:center\n"
        g, s = parse_britfixignore(content)
        assert s == {'code': {'color', 'dialog', 'center'}}


class TestBritfixIgnoreDiscovery:
    """Test .britfixignore file discovery."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Clear ignore cache before each test."""
        _ignore_cache.clear()
        yield
        _ignore_cache.clear()

    def test_git_root_boundary(self, tmp_path):
        """Discovery stops at .git directory."""
        (tmp_path / '.git').mkdir()
        (tmp_path / '.britfixignore').write_text('color\n')
        (tmp_path / 'sub').mkdir()
        target = tmp_path / 'sub' / 'file.py'
        target.touch()

        g, s = discover_ignore_words(str(target))
        assert 'color' in g

    def test_nested_dirs_merge(self, tmp_path):
        """Nested .britfixignore files merge additively."""
        (tmp_path / '.git').mkdir()
        (tmp_path / '.britfixignore').write_text('color\n')
        (tmp_path / 'sub').mkdir()
        (tmp_path / 'sub' / '.britfixignore').write_text('behavior\n')
        target = tmp_path / 'sub' / 'file.py'
        target.touch()

        g, s = discover_ignore_words(str(target))
        assert 'color' in g
        assert 'behavior' in g

    def test_scoped_merge(self, tmp_path):
        """Scoped ignores from different levels merge."""
        (tmp_path / '.git').mkdir()
        (tmp_path / '.britfixignore').write_text('code:color\n')
        (tmp_path / 'sub').mkdir()
        (tmp_path / 'sub' / '.britfixignore').write_text('code:dialog\n')
        target = tmp_path / 'sub' / 'file.py'
        target.touch()

        g, s = discover_ignore_words(str(target))
        assert s.get('code') == {'color', 'dialog'}

    def test_stops_at_home_dir(self, tmp_path, monkeypatch):
        """Discovery stops at home directory."""
        fake_home = tmp_path / 'home'
        fake_home.mkdir()
        monkeypatch.setattr(Path, 'home', staticmethod(lambda: fake_home))

        # Put an ignore file ABOVE home — it should not be found
        (tmp_path / '.britfixignore').write_text('color\n')
        project = fake_home / 'project'
        project.mkdir()
        target = project / 'file.py'
        target.touch()

        g, s = discover_ignore_words(str(target))
        assert 'color' not in g

    def test_worktree_git_file(self, tmp_path):
        """A .git file (worktree) is also a valid boundary."""
        (tmp_path / '.git').write_text('gitdir: /some/other/path\n')
        (tmp_path / '.britfixignore').write_text('color\n')
        target = tmp_path / 'file.py'
        target.touch()

        g, s = discover_ignore_words(str(target))
        assert 'color' in g

    def test_user_config_merged(self, tmp_path, monkeypatch):
        """User config file is merged with project ignores."""
        (tmp_path / '.git').mkdir()
        (tmp_path / '.britfixignore').write_text('color\n')

        user_config_dir = tmp_path / 'user_config' / 'britfix'
        user_config_dir.mkdir(parents=True)
        (user_config_dir / 'ignore').write_text('behavior\n')
        monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'user_config'))

        target = tmp_path / 'file.py'
        target.touch()

        g, s = discover_ignore_words(str(target))
        assert 'color' in g
        assert 'behavior' in g

    def test_caching_by_directory(self, tmp_path):
        """Same directory should return cached result."""
        (tmp_path / '.git').mkdir()
        (tmp_path / '.britfixignore').write_text('color\n')
        f1 = tmp_path / 'a.py'
        f2 = tmp_path / 'b.py'
        f1.touch()
        f2.touch()

        r1 = discover_ignore_words(str(f1))
        r2 = discover_ignore_words(str(f2))
        # Should be the exact same object (cached)
        assert r1 is r2

    def test_no_git_outside_home_stops_at_fs_root(self, tmp_path, monkeypatch):
        """If outside home and no .git, walk up to filesystem root."""
        # Set home to something unrelated
        fake_home = tmp_path / 'fakehome'
        fake_home.mkdir()
        monkeypatch.setattr(Path, 'home', staticmethod(lambda: fake_home))

        # Create a directory outside of fake home
        project = tmp_path / 'other' / 'project'
        project.mkdir(parents=True)
        (project / '.britfixignore').write_text('color\n')
        target = project / 'file.py'
        target.touch()

        g, s = discover_ignore_words(str(target))
        assert 'color' in g

    def test_invalid_utf8_ignore_file_skipped(self, tmp_path):
        """Invalid UTF-8 in .britfixignore should be silently skipped."""
        (tmp_path / '.git').mkdir()
        # Write raw bytes that are not valid UTF-8
        (tmp_path / '.britfixignore').write_bytes(b'\xff\xfe invalid utf8\n')
        target = tmp_path / 'file.py'
        target.touch()

        # Should not raise, should return empty ignores
        g, s = discover_ignore_words(str(target))
        assert isinstance(g, set)
        assert isinstance(s, dict)

    def test_invalid_utf8_user_config_skipped(self, tmp_path, monkeypatch):
        """Invalid UTF-8 in user config should be silently skipped."""
        (tmp_path / '.git').mkdir()
        user_config_dir = tmp_path / 'user_config' / 'britfix'
        user_config_dir.mkdir(parents=True)
        (user_config_dir / 'ignore').write_bytes(b'\x80\x81\x82\n')
        monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'user_config'))

        target = tmp_path / 'file.py'
        target.touch()

        g, s = discover_ignore_words(str(target))
        assert isinstance(g, set)


class TestBritfixIgnoreParsingEdgeCases:
    """Edge cases for .britfixignore parsing."""

    def test_terminal_escape_in_strategy_name_sanitized(self, capsys):
        """Terminal escape sequences in strategy names should be escaped in warning."""
        content = "\x1b[31mevil\x1b[0m:color\n"
        parse_britfixignore(content)
        captured = capsys.readouterr()
        # The raw escape should not appear in stderr
        assert '\x1b[' not in captured.err
        assert 'unknown strategy' in captured.err


class TestFilteredCorrector:
    """Test dictionary filtering and corrector creation with ignores."""

    @pytest.fixture
    def dictionary(self):
        return load_spelling_mappings()

    def test_global_ignore(self, dictionary):
        filtered = filter_dictionary(dictionary, {'color'}, {}, 'text')
        assert 'color' not in filtered
        assert 'behavior' in filtered  # Other words unaffected

    def test_scoped_ignore(self, dictionary):
        filtered = filter_dictionary(dictionary, set(), {'code': {'color'}}, 'code')
        assert 'color' not in filtered
        assert 'behavior' in filtered

    def test_scoped_ignore_different_strategy(self, dictionary):
        """Scoped ignore for 'code' should NOT apply to 'text'."""
        filtered = filter_dictionary(dictionary, set(), {'code': {'color'}}, 'text')
        assert 'color' in filtered  # Not ignored for text strategy

    def test_cross_strategy_isolation(self, dictionary):
        """Ignoring for one strategy shouldn't affect another."""
        scoped = {'code': {'color'}, 'markdown': {'behavior'}}
        code_filtered = filter_dictionary(dictionary, set(), scoped, 'code')
        md_filtered = filter_dictionary(dictionary, set(), scoped, 'markdown')

        assert 'color' not in code_filtered
        assert 'behavior' in code_filtered
        assert 'color' in md_filtered
        assert 'behavior' not in md_filtered

    def test_case_preservation_with_ignores(self, dictionary):
        """Corrector with ignores should still preserve case for non-ignored words."""
        corrector = get_corrector_for_strategy(dictionary, {'color'}, {}, 'text')
        text = "The Color and Behavior are important."
        result, changes = corrector.correct_text(text)
        assert 'Color' in result  # Ignored, unchanged
        assert 'Behaviour' in result  # Not ignored, converted with case
        assert 'color' not in changes

    def test_empty_ignores_returns_full_dictionary(self, dictionary):
        filtered = filter_dictionary(dictionary, set(), {}, 'text')
        assert filtered == dictionary

    def test_corrector_caching(self, dictionary):
        """Same inputs should return same corrector instance."""
        from britfix_core import _corrector_cache
        _corrector_cache.clear()

        c1 = get_corrector_for_strategy(dictionary, {'color'}, {}, 'text')
        c2 = get_corrector_for_strategy(dictionary, {'color'}, {}, 'text')
        assert c1 is c2


class TestIgnoreIntegration:
    """Integration tests combining strategies with ignore support."""

    @pytest.fixture
    def dictionary(self):
        return load_spelling_mappings()

    def test_code_strategy_with_scoped_ignore(self, dictionary):
        """CodeStrategy + scoped ignore should skip specified words in comments."""
        corrector = get_corrector_for_strategy(
            dictionary, set(), {'code': {'color'}}, 'code'
        )
        strategy = CodeStrategy()
        code = "# The color and behavior are important"
        result, changes = strategy.process(code, corrector)
        assert 'color' in result  # Ignored
        assert 'behaviour' in result  # Not ignored, converted

    def test_markdown_strategy_with_global_ignore(self, dictionary):
        """MarkdownStrategy + global ignore should skip specified words."""
        corrector = get_corrector_for_strategy(
            dictionary, {'color'}, {}, 'markdown'
        )
        strategy = MarkdownStrategy()
        text = "The color and behavior are nice."
        result, changes = strategy.process(text, corrector)
        assert 'color' in result  # Ignored
        assert 'behaviour' in result  # Converted

    def test_text_strategy_scoped_code_ignore_not_applied(self, dictionary):
        """A code-scoped ignore should NOT affect text strategy."""
        corrector = get_corrector_for_strategy(
            dictionary, set(), {'code': {'color'}}, 'text'
        )
        strategy = PlainTextStrategy()
        text = "The color is nice."
        result, changes = strategy.process(text, corrector)
        assert 'colour' in result  # Not ignored for text

    def test_end_to_end_file_ignore(self, tmp_path, dictionary):
        """Full integration: .britfixignore + file processing."""
        _ignore_cache.clear()

        (tmp_path / '.git').mkdir()
        (tmp_path / '.britfixignore').write_text('code:color\n')
        py_file = tmp_path / 'test.py'
        py_file.write_text('# The color is nice\n')
        txt_file = tmp_path / 'test.txt'
        txt_file.write_text('The color is nice\n')

        # Python file: color should be ignored (code strategy)
        g, s = discover_ignore_words(str(py_file))
        py_corrector = get_corrector_for_strategy(dictionary, g, s, 'code')
        strategy = CodeStrategy()
        result, _ = strategy.process(py_file.read_text(), py_corrector)
        assert 'color' in result
        assert 'colour' not in result

        # Text file: color should NOT be ignored (text strategy)
        _ignore_cache.clear()
        g, s = discover_ignore_words(str(txt_file))
        txt_corrector = get_corrector_for_strategy(dictionary, g, s, 'text')
        strategy = PlainTextStrategy()
        result, _ = strategy.process(txt_file.read_text(), txt_corrector)
        assert 'colour' in result


class TestWildcardIgnore:
    """Test trailing * wildcard in .britfixignore entries."""

    @pytest.fixture
    def dictionary(self):
        return load_spelling_mappings()

    def test_wildcard_expands_to_inflected_forms(self, dictionary):
        """dialog* should ignore both 'dialog' and 'dialogs'."""
        filtered = filter_dictionary(dictionary, {'dialog*'}, {}, 'text')
        assert 'dialog' not in filtered
        assert 'dialogs' not in filtered
        assert 'behavior' in filtered  # Unrelated word unaffected

    def test_exact_word_does_not_expand(self, dictionary):
        """Plain 'dialog' (no *) should only ignore the exact word."""
        filtered = filter_dictionary(dictionary, {'dialog'}, {}, 'text')
        assert 'dialog' not in filtered
        assert 'dialogs' in filtered  # Plural NOT ignored

    def test_wildcard_color_family(self, dictionary):
        """color* should ignore color, colors, colored, colorful, etc."""
        filtered = filter_dictionary(dictionary, {'color*'}, {}, 'text')
        for key in list(dictionary.keys()):
            if key.lower().startswith('color'):
                assert key not in filtered, f"'{key}' should be filtered by color*"
        assert 'behavior' in filtered

    def test_wildcard_in_scoped_ignore(self, dictionary):
        """Wildcards should work in strategy-scoped ignores too."""
        filtered = filter_dictionary(dictionary, set(), {'code': {'dialog*'}}, 'code')
        assert 'dialog' not in filtered
        assert 'dialogs' not in filtered

    def test_wildcard_scoped_does_not_leak(self, dictionary):
        """Wildcard scoped to 'code' should not affect 'text'."""
        filtered = filter_dictionary(dictionary, set(), {'code': {'dialog*'}}, 'text')
        assert 'dialog' in filtered
        assert 'dialogs' in filtered

    def test_parse_preserves_wildcard(self):
        """parse_britfixignore should keep trailing * in words."""
        content = "dialog*\ncode:color*\n"
        global_ig, scoped_ig = parse_britfixignore(content)
        assert 'dialog*' in global_ig
        assert 'color*' in scoped_ig.get('code', set())

    def test_mixed_case_wildcard(self, dictionary):
        """Wildcard matching should be case-insensitive."""
        filtered = filter_dictionary(dictionary, {'Dialog*'}, {}, 'text')
        assert 'dialog' not in filtered
        assert 'dialogs' not in filtered

    def test_mixed_case_exact(self, dictionary):
        """Exact matching should be case-insensitive."""
        filtered = filter_dictionary(dictionary, {'Dialog'}, {}, 'text')
        assert 'dialog' not in filtered

    def test_bare_star_does_not_disable_all(self, dictionary):
        """A bare '*' should be silently dropped, not disable all corrections."""
        filtered = filter_dictionary(dictionary, {'*'}, {}, 'text')
        assert len(filtered) == len(dictionary)

    def test_scoped_bare_star_disables_strategy(self, dictionary):
        """A scoped 'json:*' should disable the entire strategy."""
        filtered = filter_dictionary(dictionary, set(), {'json': {'*'}}, 'json')
        assert filtered == {}

    def test_scoped_bare_star_does_not_leak_to_other_strategies(self, dictionary):
        """A scoped 'json:*' must not affect other strategies."""
        filtered = filter_dictionary(dictionary, set(), {'json': {'*'}}, 'markdown')
        assert len(filtered) == len(dictionary)

    def test_scoped_bare_star_combined_with_other_scoped_words(self, dictionary):
        """'json:*' alongside 'markdown:dialog' only zeroes out the JSON strategy."""
        scoped = {'json': {'*'}, 'markdown': {'dialog'}}
        json_filtered = filter_dictionary(dictionary, set(), scoped, 'json')
        md_filtered = filter_dictionary(dictionary, set(), scoped, 'markdown')
        assert json_filtered == {}
        # markdown still has everything except 'dialog'
        assert 'dialog' not in md_filtered
        assert 'behavior' in md_filtered

    def test_end_to_end_strategy_wildcard_skips_json(self, tmp_path, dictionary):
        """Full integration: 'json:*' in .britfixignore skips JSON corrections."""
        _ignore_cache.clear()
        _corrector_cache.clear()

        (tmp_path / '.git').mkdir()
        (tmp_path / '.britfixignore').write_text('json:*\n')
        json_file = tmp_path / 'settings.json'
        json_file.write_text('{"theme": "color", "label": "organized"}\n')

        g, s = discover_ignore_words(str(json_file))
        corrector = get_corrector_for_strategy(dictionary, g, s, 'json')
        strategy = JSONStrategy()
        result, changes = strategy.process(json_file.read_text(), corrector)
        assert 'color' in result
        assert 'organized' in result
        assert changes == {}

    def test_corrector_cache_distinguishes_global_vs_scoped_wildcard(self, dictionary):
        """A global '*' (dropped) and a scoped 'json:*' (disable) must not collide
        in the corrector cache, even though their unioned tokens are identical."""
        _corrector_cache.clear()

        # Global '*' should be dropped — corrector keeps the full dictionary.
        global_corrector = get_corrector_for_strategy(dictionary, {'*'}, {}, 'json')
        assert len(global_corrector.dictionary) == len(dictionary)

        # Scoped 'json:*' should disable the strategy — corrector is empty.
        scoped_corrector = get_corrector_for_strategy(dictionary, set(), {'json': {'*'}}, 'json')
        assert scoped_corrector.dictionary == {}

        # The two must be distinct objects, not a cached reuse.
        assert global_corrector is not scoped_corrector

    def test_end_to_end_wildcard_ignore(self, tmp_path, dictionary):
        """Full integration: wildcard in .britfixignore file."""
        _ignore_cache.clear()
        _corrector_cache.clear()

        (tmp_path / '.git').mkdir()
        (tmp_path / '.britfixignore').write_text('dialog*\n')
        md_file = tmp_path / 'test.md'
        md_file.write_text('The dialog and dialogs are shown.\n')

        g, s = discover_ignore_words(str(md_file))
        corrector = get_corrector_for_strategy(dictionary, g, s, 'markdown')
        strategy = MarkdownStrategy()
        result, changes = strategy.process(md_file.read_text(), corrector)
        assert 'dialogue' not in result
        assert 'dialogues' not in result
        assert 'dialog' in result
        assert 'dialogs' in result


class TestUserIgnorePath:
    """Test get_user_ignore_path for different platforms."""

    def test_unix_default(self, monkeypatch):
        monkeypatch.setattr(os, 'name', 'posix')
        monkeypatch.delenv('XDG_CONFIG_HOME', raising=False)
        path = get_user_ignore_path()
        assert path is not None
        assert str(path).endswith('.config/britfix/ignore')

    def test_unix_xdg(self, monkeypatch):
        monkeypatch.setattr(os, 'name', 'posix')
        monkeypatch.setenv('XDG_CONFIG_HOME', '/custom/config')
        path = get_user_ignore_path()
        assert path == Path('/custom/config/britfix/ignore')

    @pytest.mark.skipif(os.name != 'nt', reason="WindowsPath unavailable on non-Windows")
    def test_windows(self, monkeypatch):
        monkeypatch.setenv('APPDATA', 'C:\\Users\\test\\AppData\\Roaming')
        path = get_user_ignore_path()
        assert str(path).endswith('britfix\\ignore')


class TestFindSafeReplacements:
    """Test find_safe_replacements filters by strategy segmentation."""

    @pytest.fixture
    def corrector(self):
        mappings = load_spelling_mappings()
        return SpellingCorrector(mappings)

    def test_code_strategy_only_comments(self, corrector):
        """CodeStrategy: 'colour' in comment returned, in string literal not."""
        code = '# The color is nice\nname = "color"\n'
        strategy = CodeStrategy()
        safe = strategy.find_safe_replacements(code, corrector)
        originals = [r[2] for r in safe]
        assert 'color' in originals
        # Only one occurrence (the comment), not the string literal
        assert len([o for o in originals if o == 'color']) == 1

    def test_markdown_strategy_only_prose(self, corrector):
        """MarkdownStrategy: 'colour' in prose returned, in code block not."""
        md = 'The color is nice\n\n```\ncolor = value\n```\n'
        strategy = MarkdownStrategy()
        safe = strategy.find_safe_replacements(md, corrector)
        originals = [r[2] for r in safe]
        assert 'color' in originals
        assert len([o for o in originals if o == 'color']) == 1

    def test_css_strategy_only_comments(self, corrector):
        """CssStrategy: 'colour' in comment returned, in property not."""
        css = '/* The color is nice */\n.foo { color: red; }\n'
        strategy = CssStrategy()
        safe = strategy.find_safe_replacements(css, corrector)
        originals = [r[2] for r in safe]
        assert 'color' in originals
        assert len([o for o in originals if o == 'color']) == 1

    def test_html_strategy_only_text(self, corrector):
        """HTMLStrategy: 'colour' in text returned, in script not."""
        html = '<p>The color is nice</p>\n<script>var color = 1;</script>\n'
        strategy = HTMLStrategy()
        safe = strategy.find_safe_replacements(html, corrector)
        originals = [r[2] for r in safe]
        assert 'color' in originals
        assert len([o for o in originals if o == 'color']) == 1

    def test_plain_text_all_returned(self, corrector):
        """PlainTextStrategy: all occurrences returned."""
        text = 'The color is nice. Another color here.'
        strategy = PlainTextStrategy()
        safe = strategy.find_safe_replacements(text, corrector)
        originals = [r[2] for r in safe]
        assert originals.count('color') == 2

    def test_code_strategy_shorter_replacement(self, corrector):
        """CodeStrategy: shorter replacement (appall->appal) only in comment."""
        code = '# appall\nname = "appall"\n'
        strategy = CodeStrategy()
        safe = strategy.find_safe_replacements(code, corrector)
        originals = [r[2] for r in safe]
        assert originals == ['appall']
        # Verify it's from the comment (position 2), not the string literal
        assert safe[0][0] == 2

    def test_code_strategy_shorter_replacement_distill(self, corrector):
        """CodeStrategy: distill->distil only in comment, not string."""
        code = '# distill\nname = "distill"\n'
        strategy = CodeStrategy()
        safe = strategy.find_safe_replacements(code, corrector)
        assert len(safe) == 1
        assert safe[0][2] == 'distill'

    def test_code_strategy_longer_replacement_catalog(self, corrector):
        """CodeStrategy: longer replacement (catalog->catalogue) only in comment."""
        code = '# catalog\nname = "catalog"\n'
        strategy = CodeStrategy()
        safe = strategy.find_safe_replacements(code, corrector)
        originals = [r[2] for r in safe]
        assert originals == ['catalog']
        assert safe[0][0] == 2

    def test_code_strategy_longer_replacement_program(self, corrector):
        """CodeStrategy: program->programme only in comment, not string."""
        code = '# program\nname = "program"\n'
        strategy = CodeStrategy()
        safe = strategy.find_safe_replacements(code, corrector)
        assert len(safe) == 1
        assert safe[0][2] == 'program'


class TestInteractiveStrategyInvariant:
    """Approve-all via find_safe_replacements + apply_replacements should equal process()."""

    @pytest.fixture
    def corrector(self):
        mappings = load_spelling_mappings()
        return SpellingCorrector(mappings)

    @pytest.mark.parametrize("strategy,content", [
        (CodeStrategy(), '# The color and behavior\nname = "color"\n'),
        (CodeStrategy(), '# appall and distill\nname = "appall"\n'),
        (CodeStrategy(), '# catalog and program\nname = "catalog"\n'),
        (MarkdownStrategy(), 'The color is nice\n\n```\ncolor = x\n```\n'),
        (CssStrategy(), '/* color behavior */\n.x { color: red; }\n'),
        (HTMLStrategy(), '<p>color behavior</p><script>var color=1;</script>'),
        (PlainTextStrategy(), 'The color and behavior are analyzed.'),
        (PlainTextStrategy(), 'appall and distill and fulfill'),
    ])
    def test_approve_all_equals_process(self, corrector, strategy, content):
        safe = strategy.find_safe_replacements(content, corrector)
        result_interactive, _ = apply_replacements(content, safe)
        result_process, _ = strategy.process(content, corrector)
        assert result_interactive == result_process


class TestGroupReplacementsByWord:
    """Group interactive-mode replacements by their lowercased original."""

    def test_empty_input(self):
        assert group_replacements_by_word([]) == []

    def test_single_replacement(self):
        repl = (0, 5, "color", "colour")
        assert group_replacements_by_word([repl]) == [("color", [repl])]

    def test_multiple_distinct_words_preserve_insertion_order(self):
        a = (0, 5, "color", "colour")
        b = (10, 18, "behavior", "behaviour")
        c = (20, 27, "analyze", "analyse")
        result = group_replacements_by_word([a, b, c])
        assert [k for k, _ in result] == ["color", "behavior", "analyze"]
        assert result[0][1] == [a]
        assert result[1][1] == [b]
        assert result[2][1] == [c]

    def test_repeated_words_grouped_under_same_key(self):
        a = (0, 5, "color", "colour")
        b = (10, 15, "Color", "Colour")  # different case, same key
        c = (20, 28, "behavior", "behaviour")
        d = (30, 35, "color", "colour")
        result = group_replacements_by_word([a, b, c, d])
        # 'color' first (insertion order), then 'behavior'
        assert [k for k, _ in result] == ["color", "behavior"]
        # All three color-family replacements grouped together, in encounter order
        assert result[0][1] == [a, b, d]
        assert result[1][1] == [c]


class TestJsonInteractiveFallback:
    """JSON files in interactive mode fall back to non-interactive processing."""

    def test_json_not_supports_interactive(self):
        """JSONStrategy has supports_interactive=False."""
        strategy = JSONStrategy()
        assert not strategy.supports_interactive

    def test_other_strategies_support_interactive(self):
        """Non-JSON strategies have supports_interactive=True."""
        for strategy_cls in [PlainTextStrategy, MarkdownStrategy, CodeStrategy, CssStrategy, HTMLStrategy]:
            assert strategy_cls().supports_interactive


class TestJSONStrategyMalformed:
    """Malformed JSON must be left untouched, with a stderr warning."""

    def test_malformed_json_left_unchanged(self, corrector):
        # Trailing comma makes this invalid JSON; contains American spellings
        # in both keys and values that the old fallback would have rewritten.
        content = '{\n  "color": "organized",\n  "behavior": 1,\n}\n'
        strategy = JSONStrategy()
        result, changes = strategy.process(content, corrector)
        assert result == content
        assert changes == {}

    def test_malformed_json_emits_stderr_warning(self, corrector, capsys):
        content = '{ not valid json'
        strategy = JSONStrategy()
        strategy.process(content, corrector)
        captured = capsys.readouterr()
        assert "britfix: skipping malformed JSON" in captured.err

    def test_valid_json_still_processed(self, corrector):
        # Sanity check that the happy path is intact after the fallback removal.
        content = '{"description": "The color was analyzed"}'
        strategy = JSONStrategy()
        result, changes = strategy.process(content, corrector)
        assert "colour" in result
        assert "analysed" in result
        assert "color" in changes


class TestJSONStrategyHeuristic:
    """JSON values without whitespace are treated as identifiers and skipped.

    Config files store overwhelmingly programmatic strings (CSS values, paths,
    camelCase identifiers). Correcting them silently breaks downstream tools.
    """

    @pytest.fixture
    def strategy(self):
        return JSONStrategy()

    def test_single_word_values_unchanged(self, strategy, corrector):
        """Identifier-like values (no whitespace) must not be corrected."""
        content = '{"colorScheme": "dark", "textAlign": "center"}'
        result, changes = strategy.process(content, corrector)
        assert '"center"' in result
        assert '"dark"' in result
        # Keys are also untouched (existing behaviour)
        assert '"colorScheme"' in result
        assert '"textAlign"' in result
        assert changes == {}

    def test_prose_values_corrected(self, strategy, corrector):
        """Multi-word prose values still get British spellings."""
        content = '{"description": "The organization was well organized"}'
        result, changes = strategy.process(content, corrector)
        assert "organisation" in result
        assert "organised" in result
        assert "organization" in changes

    def test_single_word_prose_skipped_documents_tradeoff(self, strategy, corrector):
        """A single-word prose value is skipped — known trade-off of the heuristic."""
        content = '{"label": "organized"}'
        result, changes = strategy.process(content, corrector)
        assert '"organized"' in result
        assert changes == {}

    def test_path_like_values_unchanged(self, strategy, corrector):
        """Paths and dotted identifiers are skipped (no whitespace)."""
        content = '{"path": "src/Color.tsx", "module": "ui.color.scheme"}'
        result, changes = strategy.process(content, corrector)
        assert '"src/Color.tsx"' in result
        assert '"ui.color.scheme"' in result
        assert changes == {}

    def test_heuristic_applies_to_nested_objects(self, strategy, corrector):
        """The whitespace gate must apply at every depth."""
        content = '{"outer": {"inner": "color", "prose": "The color is nice"}}'
        result, changes = strategy.process(content, corrector)
        assert '"color"' in result  # single-word inner skipped
        assert "colour is nice" in result  # multi-word inner corrected
        assert changes.get("color") == 1

    def test_heuristic_applies_to_arrays(self, strategy, corrector):
        """The whitespace gate must apply inside arrays too."""
        content = '{"items": ["color", "behavior", "The color is nice"]}'
        result, changes = strategy.process(content, corrector)
        assert '"color"' in result
        assert '"behavior"' in result
        assert "colour is nice" in result
        assert changes.get("color") == 1
        assert "behavior" not in changes

    def test_tab_and_newline_count_as_whitespace(self, strategy, corrector):
        """Any whitespace character — not just space — qualifies a value as prose."""
        content = '{"a": "color\\tbehavior", "b": "color\\nbehavior"}'
        result, changes = strategy.process(content, corrector)
        # Both should be corrected because they contain whitespace
        assert "colour" in result
        assert "behaviour" in result

    def test_root_string_with_whitespace_corrected(self, strategy, corrector):
        """A bare string at the JSON root must still be reached by the heuristic."""
        content = '"The organization was analyzed"'
        result, changes = strategy.process(content, corrector)
        assert "organisation" in result
        assert "analysed" in result
        assert changes.get("organization") == 1

    def test_root_string_without_whitespace_skipped(self, strategy, corrector):
        """A bare identifier at the JSON root is treated as an identifier."""
        content = '"organized"'
        result, changes = strategy.process(content, corrector)
        # json.dumps re-quotes the string identically.
        assert result == '"organized"'
        assert changes == {}

    def test_root_number_unaffected(self, strategy, corrector):
        """Non-string scalar roots round-trip cleanly through the heuristic path."""
        content = '42'
        result, changes = strategy.process(content, corrector)
        assert result == '42'
        assert changes == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
