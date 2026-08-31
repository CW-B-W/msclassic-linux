import unittest
from urllib.parse import quote

from msclassic.protocol import ProtocolError, parse_launch_uri, parse_nexonplug_uri
from msclassic.redaction import UnsafeExportError, assert_export_safe, sanitize_text


class NexonPlugProtocolTests(unittest.TestCase):
    def test_classic_passarg_plus_and_percent_decoding(self):
        request = parse_nexonplug_uri(
            "nexonplug://?game=2982%40TW&passarg=alpha+beta%20gamma%09delta"
        )

        self.assertEqual(request.game_code, "2982")
        self.assertEqual(request.obd_tag, "TW")
        self.assertEqual(request.arguments, ("alpha", "beta", "gamma", "delta"))

    def test_shell_metacharacters_are_plain_argv_data(self):
        request = parse_nexonplug_uri(
            "nexonplug://?game=2982&passarg=%24%28touch%20%2Ftmp%2Fpwned%29"
        )

        self.assertEqual(request.arguments, ("$(touch", "/tmp/pwned)"))

    def test_non_ascii_whitespace_is_not_a_separator(self):
        request = parse_nexonplug_uri(
            "nexonplug://?game=2982&passarg=alpha%C2%A0beta+gamma"
        )

        self.assertEqual(request.arguments, ("alpha\u00a0beta", "gamma"))

    def test_rejects_wrong_scheme_or_nonclassic_game(self):
        invalid = (
            "https://example.invalid/?game=2982&passarg=a",
            "nexonplug://?game=29820&passarg=a",
            "nexonplug://?game=610074&passarg=a",
        )
        for uri in invalid:
            with self.subTest(uri=uri), self.assertRaises(ProtocolError):
                parse_nexonplug_uri(uri)


class NGMProtocolTests(unittest.TestCase):
    @staticmethod
    def uri(argument: str) -> str:
        return "ngm://launch/ " + quote(argument, safe="")

    def test_current_linux_website_format_extracts_only_classic_passarg(self):
        request = parse_launch_uri(
            self.uri(
                "-mode:launch -game:'2982@TW' -passarg:'alpha beta%literal' "
                "-token:'synthetic-token' -position:'GameWeb|https://example.invalid/' "
                "-architectureplatform:'none' -timestamp:123"
            )
        )

        self.assertEqual(request.game_code, "2982")
        self.assertEqual(request.obd_tag, "TW")
        self.assertEqual(request.arguments, ("alpha", "beta%literal"))

    def test_rejects_nonlaunch_wrong_game_duplicate_and_malformed_ngm(self):
        invalid_arguments = (
            "-mode:install -game:'2982' -passarg:'a'",
            "-mode:launch -game:'29820' -passarg:'a'",
            "-mode:launch -game:'2982' -game:'2982' -passarg:'a'",
            "-mode:launch -game:'2982' -passarg:'a' trailing",
            "-mode:launch -game:'2982' -passarg:'a",
        )
        for argument in invalid_arguments:
            with self.subTest(argument=argument), self.assertRaises(ProtocolError):
                parse_launch_uri(self.uri(argument))

        invalid_uris = (
            "ngm://install/ " + quote("-mode:launch -game:'2982' -passarg:'a'", safe=""),
            "ngm://launch/ %252Dmode%253Alaunch",
            "ngm://launch/ %ZZ",
        )
        for uri in invalid_uris:
            with self.subTest(uri=uri), self.assertRaises(ProtocolError):
                parse_launch_uri(uri)

    def test_rejects_missing_duplicate_or_empty_parameters(self):
        invalid = (
            "nexonplug://?passarg=a",
            "nexonplug://?game=2982",
            "nexonplug://?game=2982&passarg=",
            "nexonplug://?game=2982&game=2982&passarg=a",
            "nexonplug://?game=2982&passarg=a&passarg=b",
        )
        for uri in invalid:
            with self.subTest(uri=uri), self.assertRaises(ProtocolError):
                parse_nexonplug_uri(uri)

    def test_rejects_nul_fragment_and_oversized_input(self):
        invalid = (
            "nexonplug://?game=2982&passarg=alpha%00beta",
            "nexonplug://?game=2982&passarg=a#fragment",
            "nexonplug://?game=2982&passarg=" + ("a" * 65_537),
            "nexonplug://?game=2982&passarg=" + ("a" * 4_097),
            "nexonplug://?game=2982&passarg=" + "+".join(["a"] * 129),
        )
        for uri in invalid:
            with self.subTest(length=len(uri)), self.assertRaises(ProtocolError):
                parse_nexonplug_uri(uri)


class RedactionTests(unittest.TestCase):
    def test_redacts_entire_uri_and_named_secrets(self):
        raw = (
            "open nexonplug://?game=2982&passarg=SECRET "
            "OTP=1234567890 cookie=abc authorization=BearerValue"
        )

        safe = sanitize_text(raw)

        self.assertNotIn("SECRET", safe)
        self.assertNotIn("1234567890", safe)
        self.assertNotIn("cookie=abc", safe)
        self.assertNotIn("BearerValue", safe)
        self.assertIn("[REDACTED_NEXONPLUG_URI]", safe)

    def test_redacts_linux_ngm_uri_including_literal_space(self):
        raw = "open ngm://launch/ %2Dmode%3Alaunch%20%2Dpassarg%3A%27SECRET%27"

        safe = sanitize_text(raw)

        self.assertNotIn("SECRET", safe)
        self.assertIn("[REDACTED_LAUNCH_URI]", safe)

    def test_export_guard_rejects_secret_bearing_nested_values(self):
        with self.assertRaises(UnsafeExportError):
            assert_export_safe({"result": [{"passarg": "fake-secret"}]})

    def test_export_guard_accepts_allowlisted_diagnostics(self):
        assert_export_safe(
            {
                "renderer": "Virtio-GPU Venus (Intel Graphics)",
                "gate_passed": True,
                "failures": [],
            }
        )


if __name__ == "__main__":
    unittest.main()
