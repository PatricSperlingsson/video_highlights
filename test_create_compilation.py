"""Run from the project folder: python3 -m unittest -v test_create_compilation."""

import subprocess
import unittest
from unittest.mock import Mock, mock_open, patch

import create_compilation as app


def parse_entries(text):
    with patch('builtins.open', mock_open(read_data=text)), patch('builtins.print'):
        return app.parse_config('unused-config')


class ConfigTests(unittest.TestCase):
    def test_time_formats(self):
        for value, expected in [('26.23', 26.23), ('1:12', 72), ('1:12:30', 4350)]:
            with self.subTest(value=value):
                self.assertEqual(app.parse_time(value), expected)

    def test_invalid_time(self):
        for value in ('invalid', '1:2:3:4'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                app.parse_time(value)

    def test_comments_and_optional_fields(self):
        clips = parse_entries('# ignored\n\nsource | 3 | 5 | waveform | arrow 270 | noaudio | Goal | -0.5\n')
        self.assertEqual(len(clips), 1)
        clip = clips[0]
        self.assertEqual(clip['text'], 'Goal')
        self.assertEqual(clip['arrow'], '270')
        self.assertEqual(clip['speed'], 0.5)
        self.assertTrue(clip['reverse'])
        self.assertTrue(clip['waveform'])
        self.assertTrue(clip['noaudio'])

    def test_freeze(self):
        clip = parse_entries('source | 3 | 6 | | 0')[0]
        self.assertTrue(clip['freeze'])
        self.assertEqual(clip['end'] - clip['start'], 3)

    def test_image(self):
        clip = parse_entries('IMAGE | screenshot | 5 |')[0]
        self.assertEqual(clip, {'type': 'image', 'filename': 'screenshot', 'duration': 5, 'text': ''})

    def test_black_audio_offsets(self):
        for field, expected in [('', None), (' | 0', 0), (' | 0.7', 0.7), (' | 1:12', 72)]:
            with self.subTest(field=field):
                clip = parse_entries('BLACK | 3 | Title | sound' + field)[0]
                self.assertEqual(clip['audio_start'], expected)

    def test_invalid_video_range_is_rejected(self):
        self.assertEqual(parse_entries('source | 6 | 3\nsource | 3 | 3'), [])


class TextTests(unittest.TestCase):
    def test_explicit_newlines_and_wrapping(self):
        cases = [
            (r'And the result in\ngittools gerrit is...', 40, 'And the result in\ngittools gerrit is...'),
            (r'First\n\nLast', 40, 'First\n\nLast'),
            ('First\nSecond', 40, 'First\nSecond'),
            ('one two three four', 7, 'one two\nthree\nfour'),
            ('M\u00c5L!\\nN\u00e4sta rad', 40, 'M\u00c5L!\nN\u00e4sta rad'),
        ]
        for text, width, expected in cases:
            with self.subTest(text=text), patch.object(app.Path, 'write_text') as write:
                app.write_text_file(text, 'unused-text', width)
                write.assert_called_once_with(expected, encoding='utf-8')


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.fmt = {'width': 1454, 'height': 984, 'fps': 29, 'transfer': ''}

    def test_silent_source_never_references_source_audio(self):
        for waveform in (False, True):
            with self.subTest(waveform=waveform), patch.object(app, 'probe_has_audio', return_value=False):
                clip = parse_entries('source | 0 | 12 | | 1')[0]
                clip['waveform'] = waveform
                command = app.build_video_cmd(clip, self.fmt, 0, 'source', 'unused-output')
                graph = command[command.index('-filter_complex') + 1]
                self.assertNotIn('[0:a]', graph)
                self.assertIn('anullsrc', graph)

    def test_freeze_uses_one_frame_and_silence(self):
        clip = parse_entries('source | 3 | 6 | | 0')[0]
        with patch.object(app, 'probe_has_audio') as probe:
            command = app.build_video_cmd(clip, self.fmt, 0, 'source', 'unused-output')
        probe.assert_not_called()
        graph = command[command.index('-filter_complex') + 1]
        self.assertIn('trim=end_frame=1', graph)
        self.assertIn('tpad=stop_mode=clone:stop_duration=3.0', graph)
        self.assertNotIn('[0:a]', graph)
        self.assertEqual(command[command.index('-ss') + 1], '3.0')
        self.assertEqual(command[command.index('-t') + 1], '3.0')

    def test_image_stretches_to_master_resolution(self):
        clip = parse_entries('IMAGE | screenshot | 5 |')[0]
        command = app.build_image_cmd(clip, self.fmt, 0, 'unused-output')
        graph = command[command.index('-filter_complex') + 1]
        self.assertIn('scale=1454:984', graph)
        self.assertNotIn('force_original_aspect_ratio', graph)
        self.assertIn('anullsrc=channel_layout=stereo:sample_rate=44100', command)
        self.assertEqual(command[command.index('-t') + 1], '5.0')

    def test_explicit_black_audio_offset_does_not_probe_duration(self):
        clip = parse_entries('BLACK | 3 | | sound | 0')[0]
        with patch.object(app, 'probe_duration') as probe:
            command = app.build_black_cmd(clip, self.fmt, 0, 'unused-output')
        probe.assert_not_called()
        self.assertEqual(command[command.index('-ss') + 1], '0.0')
        self.assertEqual(command[command.index('-t') + 1], '3.0')
        self.assertIn('apad[aout]', command[command.index('-filter_complex') + 1])

    def test_default_black_audio_offset_is_centred(self):
        clip = parse_entries('BLACK | 3 | | sound')[0]
        with patch.object(app, 'probe_duration', return_value=4):
            command = app.build_black_cmd(clip, self.fmt, 0, 'unused-output')
        self.assertEqual(command[command.index('-ss') + 1], '0.5')

    def test_duration_accepts_stream_fallback(self):
        with patch.object(app.subprocess, 'run', return_value=Mock(stdout='N/A\n3.0\n')):
            self.assertEqual(app.probe_duration('unused-source'), 3)

    def test_unknown_duration_raises(self):
        with patch.object(app.subprocess, 'run', return_value=Mock(stdout='N/A\nN/A\n')):
            with self.assertRaises(ValueError):
                app.probe_duration('unused-source')


class FailureTests(unittest.TestCase):
    def test_missing_sources_abort_before_any_media_operations(self):
        for kind in ('video', 'image', 'black'):
            clip = {'type': kind, 'audio' if kind == 'black' else 'filename': 'missing-source'}
            with self.subTest(kind=kind), patch.object(app.Path, 'is_file', return_value=False), \
                    patch.object(app, 'probe_video') as probe, patch.object(app.subprocess, 'run') as run, \
                    patch.object(app.Path, 'mkdir') as mkdir, patch('builtins.print') as output:
                self.assertIsNone(app.create_compilation([clip], None))
                probe.assert_not_called()
                run.assert_not_called()
                mkdir.assert_not_called()
                self.assertIn('missing-source', output.call_args.args[0])

    def test_failed_clip_does_not_continue_or_concatenate(self):
        clips = parse_entries('source | 0 | 1\nsource | 1 | 2')
        fmt = {'width': 100, 'height': 100, 'fps': 30, 'transfer': ''}
        with patch.object(app.Path, 'is_file', return_value=True), \
                patch.object(app.Path, 'mkdir'), patch.object(app.Path, 'write_text') as write, \
                patch.object(app, 'probe_video', return_value=fmt), \
                patch.object(app, 'build_video_cmd', return_value=['ffmpeg']) as build, \
                patch.object(app.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'ffmpeg')) as run, \
                patch('builtins.print'):
            self.assertIsNone(app.create_compilation(clips, None))
            self.assertEqual(build.call_count, 1)
            self.assertEqual(run.call_count, 1)
            write.assert_not_called()


class CliTests(unittest.TestCase):
    def setUp(self):
        self.run = self.mock(app.subprocess, 'run')
        self.exists = self.mock(app.Path, 'exists', return_value=True)
        self.parse = self.mock(app, 'parse_config', return_value=[{'type': 'video'}])
        self.compile = self.mock(app, 'create_compilation', return_value={})
        self.export = self.mock(app, 'create_whatsapp_version')
        self.probe = self.mock(app, 'probe_video', return_value={})
        self.mock_print = self.mock(__import__('builtins'), 'print')

    def mock(self, target, name, **kwargs):
        patcher = patch.object(target, name, **kwargs)
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def invoke(self, *arguments):
        with patch('sys.argv', ['create_compilation.py', *arguments]):
            app.main()

    def test_default_only_builds_master(self):
        self.invoke()
        self.assertEqual(self.compile.call_args.args[1], 'compilation.mp4')
        self.export.assert_not_called()

    def test_whatsapp_is_opt_in(self):
        self.invoke('--whatsapp')
        self.export.assert_called_once_with('compilation.mp4', 'compilation_Whatsapp.mp4', {}, 185)

    def test_custom_output_and_size_target(self):
        self.invoke('custom-config', '-o', 'exports/highlights', '--whatsapp', '--whatsapp-max-mb', '50')
        self.parse.assert_called_once_with('custom-config')
        self.assertEqual(self.compile.call_args.args[1], 'exports/highlights.mp4')
        self.export.assert_called_once_with('exports/highlights.mp4', 'exports/highlights_Whatsapp.mp4', {}, 50)

    def test_whatsapp_only_does_not_read_config_or_rebuild(self):
        self.invoke('-o', 'highlights.mp4', '--whatsapp-only')
        self.parse.assert_not_called()
        self.compile.assert_not_called()
        self.export.assert_called_once_with('highlights.mp4', 'highlights_Whatsapp.mp4', {}, 185)

    def test_failure_exits_nonzero_without_whatsapp(self):
        self.compile.return_value = None
        with self.assertRaises(SystemExit) as raised:
            self.invoke('--whatsapp')
        self.assertEqual(raised.exception.code, 1)
        self.export.assert_not_called()

    def test_missing_config_exits_before_tool_checks(self):
        self.exists.return_value = False
        with self.assertRaises(SystemExit) as raised:
            self.invoke()
        self.assertEqual(raised.exception.code, 1)
        self.run.assert_not_called()

    def test_missing_existing_master_exits_nonzero(self):
        self.exists.return_value = False
        with self.assertRaises(SystemExit) as raised:
            self.invoke('--whatsapp-only')
        self.assertEqual(raised.exception.code, 1)
        self.export.assert_not_called()


if __name__ == '__main__':
    unittest.main()