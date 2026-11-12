import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stzy_app.crawler import fonts


class FontResolutionTest(unittest.TestCase):
    def test_exact_family_wins_over_substitute(self):
        plan = fonts.resolve({'Calibri'}, {fonts.font_key('Calibri'), fonts.font_key('Carlito')})
        self.assertEqual(plan['exact'], ['Calibri'])
        self.assertEqual(plan['substituted'], {})
        self.assertFalse(plan['visual_review'])

    def test_latin_substitute_is_metric_compatible(self):
        plan = fonts.resolve({'Calibri', 'Cambria', 'Times New Roman'}, {fonts.font_key('Carlito')})
        self.assertEqual(plan['substituted'], {'Calibri': 'Carlito'})
        self.assertEqual(plan['missing'], ['Cambria', 'Times New Roman'])
        self.assertFalse(plan['visual_review'])

    def test_cjk_substitute_requests_visual_review(self):
        plan = fonts.resolve({'宋体'}, {fonts.font_key('Songti SC')})
        self.assertEqual(plan['substituted'], {'宋体': 'Songti SC'})
        self.assertTrue(plan['visual_review'])

    def test_theme_references_are_ignored(self):
        plan = fonts.resolve({'+mn-lt', ' ', 'Calibri'}, {fonts.font_key('Carlito')})
        self.assertEqual(plan['substituted'], {'Calibri': 'Carlito'})
        self.assertEqual(plan['missing'], [])

    def test_strict_mode_refuses_substitutes(self):
        plan = fonts.resolve({'宋体'}, {fonts.font_key('Songti SC')}, allow_substitutes=False)
        self.assertEqual(plan['missing'], ['宋体'])
        self.assertEqual(plan['substituted'], {})

    def test_download_targets_only_open_fonts(self):
        targets = fonts._download_targets(['Calibri', '宋体', 'Unknown Font'], set())
        self.assertEqual(targets, ['Carlito'])
        self.assertNotIn('Songti SC', targets)

    def test_alias_rules_point_declared_family_at_substitute(self):
        xml = fonts.fontconfig_xml([Path('/tmp/fonts')], Path('/tmp/cache'), '/etc/fonts/fonts.conf',
                                   {'Calibri': 'Carlito'})
        self.assertIn('<dir>/tmp/fonts</dir>', xml)
        self.assertIn('<string>Calibri</string>', xml)
        self.assertIn('mode="prepend"', xml)
        self.assertIn('<string>Carlito</string>', xml)
        self.assertIn('<include ignore_missing="yes">/etc/fonts/fonts.conf</include>', xml)


class FontProvisioningTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.env = patch.dict(os.environ, {'STZY_FONT_INSTALL_DIR': self.temporary.name,
                                           'STZY_WORD_FONT_AUTO_INSTALL': '1',
                                           'STZY_WORD_FONT_POLICY': 'substitute'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_ensure_installs_open_substitute_then_resolves(self):
        available = set()

        def families():
            return set(available)

        def install(family, directory, *, timeout=60.0):
            available.add(fonts.font_key(family))
            return []

        with patch.object(fonts, 'install_family', side_effect=install) as installer:
            plan = fonts.ensure({'Calibri'}, families)
        installer.assert_called_once_with('Carlito', Path(self.temporary.name).resolve())
        self.assertEqual(plan['installed'], ['Carlito'])
        self.assertEqual(plan['substituted'], {'Calibri': 'Carlito'})
        self.assertEqual(plan['missing'], [])

    def test_ensure_respects_auto_install_switch(self):
        with patch.dict(os.environ, {'STZY_WORD_FONT_AUTO_INSTALL': '0'}), \
                patch.object(fonts, 'install_family') as installer:
            plan = fonts.ensure({'Calibri'}, lambda: set())
        installer.assert_not_called()
        self.assertEqual(plan['missing'], ['Calibri'])

    def test_strict_policy_never_downloads(self):
        with patch.dict(os.environ, {'STZY_WORD_FONT_POLICY': 'strict'}), \
                patch.object(fonts, 'install_family') as installer:
            plan = fonts.ensure({'Calibri'}, lambda: set())
        installer.assert_not_called()
        self.assertEqual(plan['missing'], ['Calibri'])

    def test_download_failure_is_reported_not_fatal(self):
        with patch.object(fonts, '_fetch', side_effect=RuntimeError('Carlito-Regular.ttf 下载失败：超时')):
            with self.assertRaises(RuntimeError):
                fonts.install_family('Carlito', Path(self.temporary.name))
        with patch.object(fonts, 'install_family', side_effect=RuntimeError('网络不可用')):
            plan = fonts.ensure({'Calibri'}, lambda: set())
        self.assertEqual(plan['missing'], ['Calibri'])
        self.assertEqual(plan['install_failed'], ['网络不可用'])


if __name__ == '__main__':
    unittest.main()
