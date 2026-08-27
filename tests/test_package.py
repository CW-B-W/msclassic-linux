import unittest

import msclassic


class PackageTests(unittest.TestCase):
    def test_public_version_is_defined(self):
        self.assertEqual(msclassic.__version__, "0.1.0")


if __name__ == "__main__":
    unittest.main()
