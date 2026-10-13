"""Run: python3 -m unittest -v test_shot_overlay. Uses synthetic images only."""

from fractions import Fraction
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import shot_overlay as overlay


def mark(seconds, x, y, pts=None, references=(), source='video', size=(1920, 1080)):
    return {
        'source': source, 'seconds': seconds, 'pts': pts or round(seconds * 1000),
        'image_width': size[0], 'image_height': size[1],
        'ball': {'x': x, 'y': y},
        'reference_points': [{'id': i, 'x': rx, 'y': ry} for i, (rx, ry) in enumerate(references, 1)],
    }


class SpeedTests(unittest.TestCase):
    def test_estimate(self):
        self.assertAlmostEqual(overlay.estimate_speed(6.1, 75.821, 76.038), 101.198, places=2)

    def test_invalid_input(self):
        for args in ((0, 1, 2), (-1, 1, 2), (float('inf'), 1, 2), (6.1, 2, 2), (6.1, 3, 2)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                overlay.estimate_speed(*args)

    def test_decimal_comma(self):
        self.assertEqual(overlay.format_number(6.1), '6,1')
        self.assertEqual(overlay.format_number(6.0), '6')


class LoadTests(unittest.TestCase):
    def write(self, folder, name, data):
        path = Path(folder) / name
        path.write_text(json.dumps(data), encoding='utf-8')
        return path

    def test_sorted_by_time(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [self.write(folder, 'b.json', mark(2, 30, 30)), self.write(folder, 'a.json', mark(1, 10, 10))]
            self.assertEqual([m['seconds'] for m in overlay.load_marks(paths)], [1, 2])

    def test_rejects_missing_ball_mixed_sources_and_sizes(self):
        cases = [
            [{**mark(1, 0, 0), 'ball': None}],
            [mark(1, 0, 0), mark(2, 0, 0, source='other')],
            [mark(1, 0, 0), mark(2, 0, 0, size=(1280, 720))],
        ]
        for data in cases:
            with self.subTest(data=data), tempfile.TemporaryDirectory() as folder:
                paths = [self.write(folder, f'{i}.json', item) for i, item in enumerate(data)]
                with self.assertRaises(ValueError):
                    overlay.load_marks(paths)


class FrameTests(unittest.TestCase):
    def frames(self, *stamps):
        return [Mock(pts=stamp, time_base=Fraction(1, 1000)) for stamp in stamps]

    def test_finds_exact_pts(self):
        container = Mock()
        container.decode.return_value = iter(self.frames(75900, 75971, 76004))
        stream = Mock(start_time=0, time_base=Fraction(1, 1000))
        frame = overlay.find_frame(container, stream, mark(75.971, 0, 0, pts=75971))
        self.assertEqual(frame.pts, 75971)

    def test_missing_pts_raises(self):
        container = Mock()
        container.decode.return_value = iter(self.frames(75900, 76004))
        stream = Mock(start_time=0, time_base=Fraction(1, 1000))
        with self.assertRaises(ValueError):
            overlay.find_frame(container, stream, mark(75.971, 0, 0, pts=75971))


class RenderTests(unittest.TestCase):
    gray = (128, 128, 128)

    def render(self, references=(), floor_line=False):
        image = Image.new('RGB', (1920, 1080), self.gray)
        marks = [mark(1, 900, 520), mark(2, 1068, 500), mark(3, 1353, 458, references=references)]
        return overlay.render_overlay(image, marks, 101.2, 6.1, 'Uppskattad medelhastighet', floor_line)

    def test_keeps_size_and_draws_ring_trail_and_panel(self):
        result = self.render()
        self.assertEqual((result.size, result.mode), ((1920, 1080), 'RGB'))
        self.assertNotEqual(result.getpixel((1353 + 30, 458)), self.gray)
        self.assertNotEqual(result.getpixel((984, 508)), self.gray)
        self.assertNotEqual(result.getpixel((960, 60)), self.gray)
        self.assertEqual(result.getpixel((100, 1000)), self.gray)

    def test_trail_is_straight_and_skips_middle_points(self):
        image = Image.new('RGB', (1920, 1080), self.gray)
        marks = [mark(1, 900, 520), mark(2, 1100, 700), mark(3, 1353, 458)]
        result = overlay.render_overlay(image, marks, 101.2, 6.1, 'Title')
        self.assertEqual(result.getpixel((1100, 700)), self.gray)
        self.assertNotEqual(result.getpixel((1100, 493)), self.gray)

    def test_floor_line_is_opt_in_triangle(self):
        horizontal, vertical = (1170, 520), (1500, 525)
        for result in (self.render(references=[(1500, 700)]), self.render(floor_line=True)):
            self.assertEqual(result.getpixel(horizontal), self.gray)
            self.assertEqual(result.getpixel(vertical), self.gray)
        result = self.render(references=[(904, 517), (1500, 700)], floor_line=True)
        self.assertNotEqual(result.getpixel(horizontal), self.gray)
        self.assertNotEqual(result.getpixel(vertical), self.gray)
        self.assertNotEqual(result.getpixel((1360, 470)), self.gray)


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        with patch('sys.argv', ['shot_overlay.py', *args]), patch('sys.stderr'), patch('sys.stdout'):
            return overlay.main()

    def test_invalid_arguments_exit_before_reading_points(self):
        cases = [
            ('p.json', '--distance', '6.1', '--from', '1', '--to', '2', '-o', 'out.mp4'),
            ('p.json', '--distance', '0', '--from', '1', '--to', '2', '-o', 'out.png'),
            ('p.json', '--distance', '6.1', '--from', '2', '--to', '1', '-o', 'out.png'),
        ]
        for args in cases:
            with self.subTest(args=args), patch.object(overlay, 'load_marks') as load:
                with self.assertRaises(SystemExit) as raised:
                    self.run_cli(*args)
                self.assertEqual(raised.exception.code, 2)
                load.assert_not_called()

    def test_missing_video_returns_error(self):
        with patch.object(overlay, 'load_marks', return_value=[mark(1, 0, 0, source='missing-video')]), \
                patch.object(Path, 'is_file', return_value=False):
            self.assertEqual(self.run_cli('p.json', '--distance', '6.1', '--from', '1', '--to', '2',
                                          '-o', 'out.png'), 1)


if __name__ == '__main__':
    unittest.main()
