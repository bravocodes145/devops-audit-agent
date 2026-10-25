import unittest

from main import greeting


class GreetingTests(unittest.TestCase):
    def test_default_name(self):
        self.assertEqual(greeting(), "Hello, world!")

    def test_supplied_name(self):
        self.assertEqual(greeting("Rayyan"), "Hello, Rayyan!")
