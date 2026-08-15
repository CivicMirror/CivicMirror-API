import unittest

from config.python_version import UnsupportedPythonError, require_supported_python


class PythonVersionTests(unittest.TestCase):
    def test_python_313_is_supported(self):
        require_supported_python((3, 13))

    def test_python_312_is_rejected(self):
        with self.assertRaisesRegex(UnsupportedPythonError, ">=3.13,<3.14"):
            require_supported_python((3, 12))

    def test_python_314_is_rejected(self):
        with self.assertRaisesRegex(UnsupportedPythonError, ">=3.13,<3.14"):
            require_supported_python((3, 14))
