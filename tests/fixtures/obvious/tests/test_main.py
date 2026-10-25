import unittest

from main import INVOICE_DIRECTORY


class InvoiceTests(unittest.TestCase):
    def test_path_is_configured(self):
        self.assertTrue(str(INVOICE_DIRECTORY))
