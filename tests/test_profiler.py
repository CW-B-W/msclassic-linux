import json
import stat
import tempfile
import threading
import time
import unittest
from pathlib import Path

from msclassic.paths import AppPaths
from msclassic.profiler import (
    PerformanceProfiler,
    RawCounters,
    arm_profile,
    collect_numeric_sample,
    parse_cpu_stat,
    parse_diskstats,
    parse_meminfo,
    parse_psi,
    parse_vmstat,
    profile_status,
    start_armed_profiler,
    stop_profile,
)


class ProfilerParserTests(unittest.TestCase):
    def test_proc_parsers_return_only_required_numeric_counters(self):
        self.assertEqual(
            parse_meminfo(
                "MemTotal: 8192000 kB\nMemAvailable: 4096000 kB\n"
                "SwapTotal: 524288 kB\nSwapFree: 4096 kB\n"
            ),
            (8192000, 4096000, 524288, 4096),
        )
        self.assertEqual(parse_cpu_stat("cpu  10 2 3 40 5 6 7 8\n"), 5)
        self.assertEqual(parse_vmstat("pswpin 12\npswpout 34\n"), (12, 34))
        self.assertEqual(
            parse_psi(
                "some avg10=1.00 avg60=2.00 avg300=3.00 total=123\n"
                "full avg10=0.00 avg60=0.00 avg300=0.00 total=45\n"
            ),
            (123, 45, True),
        )
        self.assertEqual(
            parse_diskstats(
                "8 0 sda 10 0 20 0 30 0 40 0 0 0 0 0 0 0 0 0\n"
                "7 0 loop0 100 0 200 0 300 0 400 0 0 0 0 0 0 0 0 0\n"
            ),
            (20 * 512, 40 * 512),
        )

    def test_malformed_or_missing_optional_proc_data_is_bounded(self):
        with self.assertRaises(ValueError):
            parse_meminfo("MemTotal: invalid\n")
        with self.assertRaises(ValueError):
            parse_cpu_stat("intr 10\n")
        self.assertEqual(parse_psi(""), (0, 0, False))
        self.assertEqual(parse_diskstats("malformed\n"), (0, 0))

    def test_sample_schema_has_only_fixed_keys_and_numeric_or_boolean_values(self):
        previous = RawCounters(10, 20, 30, 40, 50)
        current = RawCounters(13, 25, 32, 44, 58)

        sample = collect_numeric_sample(
            monotonic_ns=123456,
            meminfo=(8000, 4000, 500, 100),
            process_totals=(77, 88),
            psi=(1, 2, True, 3, 4, True, 5, 6, True),
            counters=current,
            previous=previous,
            balloon=(0, False),
        )

        self.assertEqual(sample["schema"], 1)
        self.assertEqual(sample["swap_in_pages_delta"], 3)
        self.assertEqual(sample["disk_write_bytes_delta"], 8)
        self.assertTrue(all(type(value) in {int, float, bool} for value in sample.values()))
        forbidden = {"command", "path", "title", "text", "key", "uri", "token"}
        self.assertTrue(forbidden.isdisjoint(sample))


class ProfilerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.paths = AppPaths.from_environment(
            {
                "HOME": str(self.home),
                "XDG_STATE_HOME": str(self.root / "state"),
            }
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_arm_status_start_and_stop_are_one_shot_and_private(self):
        armed = arm_profile(self.paths)
        self.assertEqual(armed.state, "armed")
        self.assertEqual(profile_status(self.paths).state, "armed")
        marker = self.paths.state / "performance-profile/armed.json"
        self.assertEqual(stat.S_IMODE(marker.stat().st_mode), 0o600)

        observed = threading.Event()

        def source(previous):
            observed.set()
            return {
                "schema": 1,
                "monotonic_ns": time.monotonic_ns(),
                "process_cpu_ticks": 0,
                "process_rss_kb": 0,
                "guest_mem_total_kb": 1,
                "guest_mem_available_kb": 1,
                "swap_total_kb": 0,
                "swap_free_kb": 0,
                "swap_in_pages_delta": 0,
                "swap_out_pages_delta": 0,
                "cpu_iowait_ticks_delta": 0,
                "psi_cpu_some_total_us": 0,
                "psi_cpu_full_total_us": 0,
                "psi_cpu_available": False,
                "psi_io_some_total_us": 0,
                "psi_io_full_total_us": 0,
                "psi_io_available": False,
                "psi_memory_some_total_us": 0,
                "psi_memory_full_total_us": 0,
                "psi_memory_available": False,
                "disk_read_bytes_delta": 0,
                "disk_write_bytes_delta": 0,
                "balloon_target_kb": 0,
                "balloon_available": False,
            }, previous

        profiler = start_armed_profiler(
            self.paths,
            sample_source=source,
            interval=0.01,
        )
        self.assertIsNotNone(profiler)
        self.assertTrue(observed.wait(1))
        self.assertEqual(profile_status(self.paths).state, "capturing")
        self.assertFalse(marker.exists())

        profiler.stop()
        self.assertEqual(profile_status(self.paths).state, "inactive")
        self.assertTrue(profiler.log_path.is_file())
        self.assertEqual(stat.S_IMODE(profiler.log_path.stat().st_mode), 0o600)
        rows = [json.loads(line) for line in profiler.log_path.read_text().splitlines()]
        self.assertGreaterEqual(len(rows), 1)
        self.assertTrue(all(type(value) in {int, float, bool} for value in rows[0].values()))

    def test_stop_disarms_without_touching_a_game(self):
        arm_profile(self.paths)

        status = stop_profile(self.paths)

        self.assertEqual(status.state, "inactive")
        self.assertFalse((self.paths.state / "performance-profile/armed.json").exists())

    def test_start_without_arm_is_a_noop(self):
        self.assertIsNone(start_armed_profiler(self.paths))


if __name__ == "__main__":
    unittest.main()
