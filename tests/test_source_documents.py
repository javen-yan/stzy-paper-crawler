from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from stzy_app.crawler.source_documents import source_kind


class SourceDocumentsTest(unittest.TestCase):
    def test_word_and_archive_signatures_without_modification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for suffix, content in [('.doc', bytes.fromhex('d0cf11e0a1b11ae1')),
                                    ('.rar', b'Rar!\x1a\x07\x01\x00'),
                                    ('.7z', b'7z\xbc\xaf\x27\x1c')]:
                path = root / ('source' + suffix)
                path.write_bytes(content)
                self.assertEqual(source_kind(path), suffix)
                self.assertEqual(path.read_bytes(), content)
            for suffix, names in [('.docx', ['[Content_Types].xml', 'word/document.xml']),
                                  ('.zip', ['nested.zip', '../not-extracted.txt'])]:
                path = root / ('source' + suffix)
                with zipfile.ZipFile(path, 'w') as archive:
                    for name in names:
                        archive.writestr(name, b'preserve original bytes')
                original = path.read_bytes()
                self.assertEqual(source_kind(path), suffix)
                self.assertEqual(path.read_bytes(), original)
                self.assertFalse((root.parent / 'not-extracted.txt').exists())

    def test_html_empty_and_broken_files_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'source.docx'
            for data in (b'', b'<html>login</html>', b'PK\x03\x04broken'):
                path.write_bytes(data)
                with self.assertRaises(RuntimeError):
                    source_kind(path)


class ConversionFidelityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def pdf(self, name, text):
        import pymupdf
        path = self.root/name
        with pymupdf.open() as document:
            document.new_page().insert_text((30,30),text)
            document.save(path)
        return path

    def test_zip_preserves_page_pixels_and_site_order(self):
        import pymupdf
        from stzy_app.crawler.source_documents import source_to_pdf
        first = self.pdf('paper.pdf','paper')
        second = self.pdf('answers.pdf','answers')
        archive = self.root/'source.zip'
        with zipfile.ZipFile(archive,'w') as z:
            z.write(second,'answers.pdf')
            z.write(first,'paper.pdf')
        output = self.root/'result.pdf'
        report = source_to_pdf(archive,output,30,2,[{'fileName':'paper.pdf','totalPage':1},{'fileName':'answers.pdf','totalPage':1}])
        self.assertEqual(report['layout'],'source_pdf_pages')
        with pymupdf.open(output) as merged:
            for i,path in enumerate((first,second)):
                with pymupdf.open(path) as original:
                    self.assertEqual(original[0].get_pixmap().samples,merged[i].get_pixmap().samples)
            self.assertEqual([row[1] for row in merged.get_toc()],['paper.pdf','answers.pdf'])

    def test_word_only_and_mixed_archives_use_actual_file_type(self):
        import shutil
        import pymupdf
        from unittest.mock import patch
        from stzy_app.crawler.source_documents import source_to_pdf
        word = self.docx()
        pdf = self.pdf('paper.pdf', 'PDF content')
        converted = self.pdf('word-result.pdf', 'Expected text')
        for mixed in (False, True):
            archive = self.root / 'source.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                # Misleading suffix must not cause a Word to be reported as a lossless PDF.
                z.write(word, 'folder/word.pdf')
                if mixed:
                    z.write(pdf, 'paper.pdf')
            metadata = [{'fileName': 'paper.pdf', 'totalPage': 1}] if mixed else []
            metadata.append({'fileName': 'folder/word.pdf', 'totalPage': 1})
            target = self.root / 'merged.pdf'
            def convert(source, output, timeout, expected):
                self.assertEqual(source_kind(source), '.docx')
                self.assertEqual(expected, 1)
                shutil.copyfile(converted, output)
            with patch('stzy_app.crawler.source_documents.word_to_pdf', side_effect=convert) as office:
                report = source_to_pdf(archive, target, 30, 2 if mixed else 1, metadata)
            self.assertEqual(office.call_count, 1)
            self.assertEqual(report['layout'], 'converted_requires_visual_review')
            self.assertEqual(report['files'][-1]['source_kind'], '.docx')
            with pymupdf.open(target) as result:
                self.assertIn('Expected text', result[-1].get_text())
                if mixed:
                    with pymupdf.open(pdf) as original:
                        self.assertEqual(result[0].get_pixmap().samples, original[0].get_pixmap().samples)

    def test_mixed_archive_word_failure_never_publishes_partial_pdf(self):
        from unittest.mock import patch
        from stzy_app.crawler.source_documents import source_to_pdf
        pdf = self.pdf('paper.pdf', 'PDF content')
        word = self.docx()
        archive = self.root / 'source.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.write(pdf, '1.pdf')
            z.write(word, '2.docx')
        original_bytes = archive.read_bytes()
        target = self.root / 'merged.pdf'
        target.write_bytes(b'previous result')
        with patch('stzy_app.crawler.source_documents.word_to_pdf', side_effect=RuntimeError('缺少原文字体')):
            with self.assertRaisesRegex(RuntimeError, '2.docx.*缺少原文字体'):
                source_to_pdf(archive, target, 30)
        self.assertEqual(target.read_bytes(), b'previous result')
        self.assertEqual(archive.read_bytes(), original_bytes)

    def test_zip_rejects_unsafe_unsupported_and_oversized_entries(self):
        from stzy_app.crawler.source_documents import unpack_zip
        from unittest.mock import patch
        for name in ('../escape.pdf','/escape.pdf','nested.zip','notes.txt'):
            archive=self.root/'source.zip'
            with zipfile.ZipFile(archive,'w') as z:z.writestr(name,b'data')
            with self.assertRaises(RuntimeError):unpack_zip(archive,self.root,[])
        with zipfile.ZipFile(archive,'w') as z:z.writestr('paper.pdf',b'12345')
        with patch('stzy_app.crawler.source_documents.MAX_EXPANDED_BYTES',4):
            with self.assertRaises(RuntimeError):unpack_zip(archive,self.root,[])

    def test_similar_font_is_not_accepted_as_original_font(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from stzy_app.crawler.source_documents import check_word_fonts
        available = SimpleNamespace(stdout='Songti SC\n')
        fc = patch('stzy_app.crawler.source_documents.shutil.which', return_value='/bin/fc-list')
        with fc, patch('stzy_app.crawler.source_documents.subprocess.run', return_value=available), \
                patch.dict('os.environ', {'STZY_WORD_FONT_POLICY': 'strict'}):
            with self.assertRaisesRegex(RuntimeError, '宋体'):
                check_word_fonts({'宋体'}, {})
        with fc, patch('stzy_app.crawler.source_documents.subprocess.run', return_value=available), \
                patch.dict('os.environ', {'STZY_WORD_FONT_POLICY': 'substitute'}):
            plan = check_word_fonts({'宋体'}, {})
            self.assertEqual(plan['exact'], [])
            self.assertEqual(plan['substituted'], {'宋体': 'Songti SC'})
            self.assertTrue(plan['visual_review'])
        with fc, patch('stzy_app.crawler.source_documents.subprocess.run', return_value=SimpleNamespace(stdout='SimSun\n')), \
                patch.dict('os.environ', {'STZY_WORD_FONT_POLICY': 'strict'}):
            plan = check_word_fonts({'宋体'}, {})
            self.assertEqual(plan['exact'], ['宋体'])
            self.assertFalse(plan['visual_review'])

    def test_metric_compatible_latin_substitute_is_not_flagged_for_review(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from stzy_app.crawler.source_documents import check_word_fonts
        with patch('stzy_app.crawler.source_documents.shutil.which', return_value='/bin/fc-list'), \
                patch('stzy_app.crawler.source_documents.subprocess.run', return_value=SimpleNamespace(stdout='Carlito,Tinos\n')), \
                patch.dict('os.environ', {'STZY_WORD_FONT_POLICY': 'substitute'}):
            plan = check_word_fonts({'Calibri', 'Times New Roman'}, {})
        self.assertEqual(plan['substituted'], {'Calibri': 'Carlito', 'Times New Roman': 'Tinos'})
        self.assertEqual(plan['missing'], [])
        self.assertFalse(plan['visual_review'])

    def docx(self):
        path=self.root/'source.docx'
        with zipfile.ZipFile(path,'w') as z:
            z.writestr('[Content_Types].xml','<Types/>')
            z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:rPr><w:rFonts w:ascii="TestFont"/></w:rPr><w:t>Expected text</w:t></w:r></w:p></w:body></w:document>')
        return path

    def convert_with(self, pages: int, text: str, expected: int, plan: dict):
        import pymupdf
        from types import SimpleNamespace
        from unittest.mock import patch
        from stzy_app.crawler.source_documents import word_to_pdf

        source = self.docx()
        target = self.root / 'converted.pdf'
        target.unlink(missing_ok=True)

        def run(command, **kwargs):
            folder = Path(command[command.index('--outdir') + 1])
            with pymupdf.open() as document:
                for _ in range(pages):
                    document.new_page().insert_text((30, 30), text)
                document.save(folder / 'source.pdf')
            return SimpleNamespace(returncode=0)

        with patch('stzy_app.crawler.source_documents.shutil.which', return_value='/bin/soffice'), \
                patch('stzy_app.crawler.source_documents.check_word_fonts', return_value=plan), \
                patch('stzy_app.crawler.source_documents.subprocess.run', side_effect=run):
            return word_to_pdf(source, target, 30, expected), target

    def test_word_page_and_text_checks_before_publication(self):
        original = {'exact': ['TestFont'], 'substituted': {}, 'missing': [], 'visual_review': False}
        for pages, text, expected, error in [(2, 'Expected text', 1, '页数与站点预览不一致'), (1, 'Missing', 1, '文字覆盖'),
                                             (1, 'Expected text', 1, None)]:
            if error:
                with self.assertRaisesRegex(RuntimeError, error):
                    self.convert_with(pages, text, expected, dict(original))
                self.assertFalse((self.root / 'converted.pdf').exists())
            else:
                plan, target = self.convert_with(pages, text, expected, dict(original))
                self.assertTrue(target.exists())
                self.assertEqual(plan['page_check']['tolerated'], False)

    def test_substituted_fonts_publish_with_actual_page_count(self):
        plan = {'exact': [], 'substituted': {'宋体': 'Noto Serif CJK SC'}, 'missing': [], 'visual_review': True}
        report, target = self.convert_with(2, 'Expected text', 1, dict(plan))
        self.assertTrue(target.exists())
        self.assertEqual(report['page_check']['tolerated'], True)
        self.assertEqual(report['page_check']['actual'], 2)
        self.assertIn('按实际页数发布', report['page_check']['note'])

    def test_failed_conversion_does_not_replace_existing_artifacts(self):
        from unittest.mock import patch
        from stzy_app.config import AppSettings
        from stzy_app.crawler.converters import DocumentConverter
        directory=self.root/'resource';directory.mkdir()
        (directory/'练习1.png').write_bytes(b'previous')
        pdf=directory.with_suffix('.pdf');pdf.write_bytes(b'previous-pdf')
        original=directory/'源文件.docx';original.write_bytes(b'original')
        converter=DocumentConverter(AppSettings(),None)
        with patch('stzy_app.crawler.converters.run_conversion',side_effect=RuntimeError('missing font')):
            with self.assertRaises(RuntimeError):converter.convert_source_and_publish(original,directory)
        self.assertEqual(pdf.read_bytes(),b'previous-pdf')
        self.assertEqual((directory/'练习1.png').read_bytes(),b'previous')
        self.assertEqual(original.read_bytes(),b'original')


if __name__ == '__main__':
    unittest.main()
