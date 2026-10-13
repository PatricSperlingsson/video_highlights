"""Run: python3 -m unittest -v test_frame_viewer. No GUI or media is opened."""

from fractions import Fraction
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import frame_viewer as viewer


def make_frame(pts):
    return Mock(pts=pts, time_base=Fraction(1, 1000), width=1920, height=1080)


class PointTests(unittest.TestCase):
    def test_preview_maps_to_original_pixels(self):
        transform = viewer.PreviewTransform(1920, 1080, 100, 50, 960, 540)
        self.assertEqual(transform.to_original(580, 320), (960, 540))
        self.assertEqual(transform.to_preview((960, 540)), (580, 320))

    def test_clicks_outside_preview_are_ignored(self):
        transform = viewer.PreviewTransform(1920, 1080, 100, 50, 960, 540)
        for point in ((99, 100), (100, 49), (1060, 100), (100, 590)):
            with self.subTest(point=point):
                self.assertIsNone(transform.to_original(*point))

    def test_original_coordinates_survive_preview_resize(self):
        point = (1300.5, 470.25)
        for size in ((960, 540), (640, 360)):
            transform = viewer.PreviewTransform(1920, 1080, 10, 100, *size)
            mapped = transform.to_original(*transform.to_preview(point))
            self.assertAlmostEqual(mapped[0], point[0])
            self.assertAlmostEqual(mapped[1], point[1])

    def test_points_are_separate_for_each_frame(self):
        first = viewer.TimedFrame.from_frame(make_frame(1), Fraction(0))
        second = viewer.TimedFrame.from_frame(make_frame(2), Fraction(0))
        first.points.ball = (20, 30)
        first.points.references.append((10, 40))
        self.assertIsNone(second.points.ball)
        self.assertEqual(second.points.references, [])

    def test_point_metadata_has_numbered_references(self):
        points = viewer.PointSelection((20, 30), [(10, 40), (50, 60)])
        self.assertEqual(points.metadata(), {
            'ball': {'x': 20, 'y': 30},
            'reference_points': [{'id': 1, 'x': 10, 'y': 40}, {'id': 2, 'x': 50, 'y': 60}],
        })

    def test_save_points_only_writes_json(self):
        frame = make_frame(75800)
        timed = viewer.TimedFrame.from_frame(frame, Fraction(0))
        timed.points.ball = (20, 30)
        with patch.object(Path, 'mkdir'), patch.object(Path, 'exists', return_value=False), \
                patch.object(Path, 'write_text') as write:
            path = viewer.save_points(timed, Path('unused-source'), Path('unused-directory'))
        self.assertTrue(path.name.endswith('_points.json'))
        self.assertIn('"x": 20', write.call_args.args[0])
        self.assertIn('"image_width": 1920', write.call_args.args[0])
        frame.to_image.assert_not_called()

    def test_empty_points_cannot_be_saved(self):
        timed = viewer.TimedFrame.from_frame(make_frame(1), Fraction(0))
        with patch.object(Path, 'mkdir') as mkdir, self.assertRaises(ValueError):
            viewer.save_points(timed, Path('unused-source'), Path('unused-directory'))
        mkdir.assert_not_called()

    def test_saved_points_are_loaded_back(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            timed = viewer.TimedFrame.from_frame(make_frame(75971), Fraction(0))
            timed.points.ball = (1352.7, 458.0)
            timed.points.references = [(904.1, 517.3)]
            viewer.save_points(timed, Path('unused-source'), Path(folder))
            reopened = viewer.TimedFrame.from_frame(make_frame(75971), Fraction(0))
            self.assertTrue(viewer.load_saved_points(reopened, Path('unused-source'), Path(folder)))
            self.assertEqual(reopened.points.ball, (1352.7, 458.0))
            self.assertEqual(reopened.points.references, [(904.1, 517.3)])
            other = viewer.TimedFrame.from_frame(make_frame(76004), Fraction(0))
            self.assertFalse(viewer.load_saved_points(other, Path('unused-source'), Path(folder)))
            self.assertIsNone(other.points.ball)

    def test_point_file_requires_explicit_overwrite(self):
        timed = viewer.TimedFrame.from_frame(make_frame(1), Fraction(0))
        timed.points.ball = (20, 30)
        with patch.object(Path, 'mkdir'), patch.object(Path, 'exists', return_value=True), \
                patch.object(Path, 'write_text') as write:
            with self.assertRaises(FileExistsError):
                viewer.save_points(timed, Path('unused-source'), Path('unused-directory'))
            write.assert_not_called()
            viewer.save_points(timed, Path('unused-source'), Path('unused-directory'), overwrite=True)
            write.assert_called_once()


class TimestampTests(unittest.TestCase):
    def test_format_timestamp(self):
        self.assertEqual(viewer.format_timestamp(Fraction(758, 10)), '01:15.800')
        self.assertEqual(viewer.format_timestamp(Fraction(599996, 10000)), '01:00.000')

    def test_uses_pts_not_frame_rate(self):
        timed = viewer.TimedFrame.from_frame(make_frame(75913), Fraction(0))
        self.assertEqual(timed.seconds, Fraction(75913, 1000))

    def test_rejects_missing_timestamp(self):
        with self.assertRaises(ValueError):
            viewer.TimedFrame.from_frame(make_frame(None), Fraction(0))

    def test_seek_skips_earlier_keyframe_and_keeps_variable_timestamps(self):
        stream = Mock(start_time=1000, time_base=Fraction(1, 1000))
        container = Mock()
        container.decode.return_value = iter([make_frame(76700), make_frame(76813), make_frame(76855)])
        frames = list(viewer.decode_from(container, stream, 75.8))
        container.seek.assert_called_once_with(76800, stream=stream, backward=True, any_frame=False)
        self.assertEqual([frame.seconds for frame in frames], [Fraction(75813, 1000), Fraction(75855, 1000)])


class NavigationTests(unittest.TestCase):
    def test_back_and_forward_reuses_history(self):
        history = viewer.FrameHistory(iter(['first', 'second', 'third']))
        self.assertTrue(history.next())
        self.assertFalse(history.previous())
        self.assertTrue(history.next())
        self.assertTrue(history.previous())
        self.assertEqual(history.current, 'first')
        self.assertTrue(history.next())
        self.assertEqual(history.current, 'second')
        self.assertTrue(history.next())
        self.assertEqual(history.current, 'third')
        self.assertFalse(history.next())
        self.assertTrue(history.previous())
        self.assertTrue(history.next())
        self.assertEqual(history.current, 'third')

    def test_history_limit_bounds_memory(self):
        history = viewer.FrameHistory(iter(range(5)), limit=2)
        for index in range(5):
            self.assertTrue(history.next())
            self.assertEqual(history.current, index)
        self.assertEqual(history.history, [3, 4])
        self.assertTrue(history.previous())
        self.assertFalse(history.previous())


class CliTests(unittest.TestCase):
    def test_help_works_without_optional_dependencies(self):
        with patch('sys.argv', ['frame_viewer.py', '--help']), patch('sys.stdout'):
            with self.assertRaises(SystemExit) as raised:
                viewer.main()
        self.assertEqual(raised.exception.code, 0)

    def test_invalid_start_is_rejected_before_accessing_source(self):
        for start in ('invalid', '-1', 'nan', 'inf'):
            with self.subTest(start=start), patch('sys.argv', ['frame_viewer.py', 'unused-source', '--start', start]), \
                    patch.object(Path, 'is_file') as check, patch('sys.stderr'):
                with self.assertRaises(SystemExit) as raised:
                    viewer.main()
                self.assertEqual(raised.exception.code, 2)
                check.assert_not_called()

    def test_missing_source_is_rejected(self):
        with patch('sys.argv', ['frame_viewer.py', 'unused-source']), \
                patch.object(Path, 'is_file', return_value=False), patch('sys.stderr'):
            with self.assertRaises(SystemExit) as raised:
                viewer.main()
        self.assertEqual(raised.exception.code, 2)


class SnapshotTests(unittest.TestCase):
    def test_metadata_preserves_exact_pts_and_time_base(self):
        timed = viewer.TimedFrame.from_frame(make_frame(76813), Fraction(1))
        metadata = timed.metadata(Path('unused-source'))
        self.assertEqual(metadata['pts'], 76813)
        self.assertEqual(metadata['time_base'], '1/1000')
        self.assertEqual(metadata['seconds'], 75.813)
        self.assertEqual(metadata['presentation_seconds'], 76.813)

    def test_save_uses_original_image_and_writes_metadata(self):
        frame = make_frame(75800)
        timed = viewer.TimedFrame.from_frame(frame, Fraction(0))
        with patch.object(Path, 'mkdir'), patch.object(Path, 'exists', return_value=False), \
                patch.object(Path, 'write_text') as write:
            path = viewer.save_snapshot(timed, Path('unused-source'), Path('unused-directory'))
        self.assertEqual(path.name, 'unused-source_01-15.800_pts-75800.png')
        frame.to_image.return_value.save.assert_called_once_with(path)
        self.assertIn('"pts": 75800', write.call_args.args[0])

    def test_save_refuses_to_overwrite(self):
        frame = make_frame(75800)
        timed = viewer.TimedFrame.from_frame(frame, Fraction(0))
        with patch.object(Path, 'mkdir'), patch.object(Path, 'exists', return_value=True):
            with self.assertRaises(FileExistsError):
                viewer.save_snapshot(timed, Path('unused-source'), Path('unused-directory'))
        frame.to_image.assert_not_called()


if __name__ == '__main__':
    unittest.main()