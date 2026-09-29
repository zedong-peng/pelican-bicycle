import unittest

from build import render_notes


class UsageNotesTests(unittest.TestCase):
    def test_empty_notes_do_not_invent_personal_experiences(self):
        markup = render_notes([])
        self.assertIn('还没有手记', markup)
        self.assertNotIn('<time', markup)

    def test_notes_are_sorted_escaped_and_keep_context(self):
        markup = render_notes([
            {'date': '2026-09-28', 'title': 'Older', 'body': 'First note'},
            {'date': '2026-09-29', 'title': '<script>not executable</script>',
             'body': 'Task\nResult <img src=x>', 'tags': ['Tool', '<model>']},
        ])
        self.assertLess(markup.index('2026-09-29'), markup.index('2026-09-28'))
        self.assertIn('&lt;script&gt;', markup)
        self.assertIn('&lt;img src=x&gt;', markup)
        self.assertIn('&lt;model&gt;', markup)
        self.assertIn('Task\nResult', markup)
        self.assertNotIn('<script>', markup)

    def test_only_https_markdown_links_become_links(self):
        markup = render_notes([{'date': '2026-09-29', 'title': 'T', 'body':
                                '[AA](https://artificialanalysis.ai/) [x](javascript:alert(1)) <b>[y](https://e.com/"q)</b>'}])
        self.assertIn('<a href="https://artificialanalysis.ai/">AA</a>', markup)
        self.assertIn('[x](javascript:alert(1))', markup)
        self.assertIn('&lt;b&gt;', markup)
        self.assertIn('[y](https://e.com/&quot;q)', markup)

    def test_invalid_notes_fail_before_build_output_is_replaced(self):
        for value in [None, {}, [None], [{'date': '2026-09-29'}],
                      [{'date': '2026-02-30', 'title': 'Title', 'body': 'Body'}],
                      [{'date': '20260929', 'title': 'Title', 'body': 'Body'}],
                      [{'date': '2026-09-29', 'title': '', 'body': 'Body'}],
                      [{'date': '2026-09-29', 'title': 'Title', 'body': 'Body', 'tags': 'Tool'}],
                      [{'date': '2026-09-29', 'title': 'Title', 'body': 'Body', 'private': 'x'}]]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                render_notes(value)


if __name__ == '__main__':
    unittest.main()
