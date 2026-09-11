import json
import unittest

import script_data


class ScriptDataTest(unittest.TestCase):
    def test_hostile_text_cannot_end_the_script_element(self):
        value = {
            "answer": "</script><script>alert('stored xss')</script>",
            "comment": "<!-- & >",
            "separators": "before\u2028middle\u2029after",
        }

        encoded = script_data.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"))

        self.assertNotIn("<", encoded)
        self.assertNotIn(">", encoded)
        self.assertNotIn("&", encoded)
        self.assertNotIn("\u2028", encoded)
        self.assertNotIn("\u2029", encoded)
        self.assertEqual(value, json.loads(encoded))


if __name__ == "__main__":
    unittest.main()
