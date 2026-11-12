"""Preserve originals and publish PDFs only after conversion quality checks."""
from __future__ import annotations

import collections
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath

import zipfile
from pathlib import Path

from stzy_app.crawler import fonts as font_support
from stzy_app.crawler.fonts import FONT_ALIASES, font_key  # re-exported for older callers

SUPPORTED = {'.pdf', '.doc', '.docx', '.zip', '.rar', '.7z', '.png', '.jpg', '.jpeg', '.webp', '.svg'}


def source_kind(path: Path) -> str:
    with path.open('rb') as stream:
        head = stream.read(4096)
    if head.startswith(b'%PDF'):
        return '.pdf'
    if head.startswith(bytes.fromhex('d0cf11e0a1b11ae1')):
        return '.doc'
    if head.startswith(b'Rar!\x1a\x07'):
        return '.rar'
    if head.startswith(b'7z\xbc\xaf\x27\x1c'):
        return '.7z'
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            return '.docx' if {'[Content_Types].xml', 'word/document.xml'} <= set(archive.namelist()) else '.zip'
    if b'<html' in head.lower() or b'<!doctype html' in head.lower():
        raise RuntimeError('下载结果是 HTML 页面，不是原文文件')
    if path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.svg'}:
        return path.suffix.lower()
    raise RuntimeError('无法识别原文格式（支持 PDF、Word、ZIP、RAR、7z 和图片）')



WORD_NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
MAX_MEMBERS = 500
MAX_EXPANDED_BYTES = 512 * 1024 * 1024


def docx_content(path: Path) -> tuple[set[str], str]:
    fonts: set[str] = set()
    text = []
    with zipfile.ZipFile(path) as archive:
        if sum(info.file_size for info in archive.infolist()) > MAX_EXPANDED_BYTES:
            raise RuntimeError('Word 解压体积超过 512 MiB，原件已保留')
        for name in archive.namelist():
            if not name.startswith('word/') or not name.endswith('.xml'):
                continue
            root = ET.fromstring(archive.read(name))
            for element in root.findall('.//w:rFonts', WORD_NS):
                for key in ('ascii', 'hAnsi', 'eastAsia', 'cs'):
                    value = element.get('{%s}%s' % (WORD_NS['w'], key))
                    if value:
                        fonts.add(value)
            if name == 'word/document.xml':
                text.extend(t.text or '' for t in root.findall('.//w:t', WORD_NS))
        # Resolve theme fonts too; themes are not font names themselves.
        if 'word/theme/theme1.xml' in archive.namelist():
            root = ET.fromstring(archive.read('word/theme/theme1.xml'))
            for element in root.iter():
                if element.tag.endswith(('}latin', '}ea', '}cs')) or element.get('script') == 'Hans':
                    if element.get('typeface'):
                        fonts.add(element.get('typeface'))
    return fonts, ''.join(text)


def available_fonts(environment: dict[str, str]) -> set[str]:
    executable = shutil.which('fc-list')
    if not executable:
        raise RuntimeError('Word 原样转换需要 fontconfig（fc-list）检查字体，原件已保留')
    result = subprocess.run([executable, '--format=%{family}\n'], env=environment,
                            capture_output=True, text=True, check=True, timeout=30)
    return {font_key(name) for line in result.stdout.splitlines() for name in line.split(',') if name.strip()}


def office_environment(work: Path, aliases: dict[str, str] | None = None) -> dict[str, str]:
    """Isolated fontconfig: system fonts, licensed dir, our install dir."""
    return font_support.font_environment(work, aliases)


def check_word_fonts(fonts: set[str], environment: dict[str, str]) -> dict:
    """Resolve declared fonts, downloading open substitutes when needed.

    Returns the resolution plan. Raises only when a font is neither installed nor
    replaceable; a substitution is reported so the conversion report can say so.
    """
    executable = shutil.which('fc-list')
    if not executable:
        raise RuntimeError('Word 原样转换需要 fontconfig（fc-list）检查字体，原件已保留')
    plan = font_support.ensure(fonts, lambda: available_fonts(environment))
    if plan['missing']:
        raise RuntimeError('缺少原文字体：' + '、'.join(plan['missing'])
                           + '；请安装有授权的字体或设置 STZY_WORD_FONT_DIR，原件已保留')
    return plan


def page_check(expected: int, actual: int, tolerant: bool, label: str = '') -> dict:
    """Site page count is an oracle only while the layout uses the original fonts."""
    if not expected or actual == expected:
        return {'expected': expected, 'actual': actual, 'tolerated': False, 'note': ''}
    note = f'{label}页数与站点预览不一致：{actual}/{expected}'
    if not tolerant:
        raise RuntimeError(note + '，需核对字体和排版；未发布 PDF')
    return {'expected': expected, 'actual': actual, 'tolerated': True,
            'note': note + '；使用了替代字体，按实际页数发布'}


def word_to_pdf(source: Path, target: Path, timeout: float, expected_pages: int = 0) -> dict:
    import pymupdf

    executable = os.environ.get('STZY_SOFFICE_PATH') or shutil.which('soffice') or shutil.which('libreoffice')
    if not executable:
        candidate = Path('/Applications/LibreOffice.app/Contents/MacOS/soffice')
        executable = str(candidate) if candidate.exists() else None
    if not executable:
        raise RuntimeError('Word 转 PDF 需要 LibreOffice（STZY_SOFFICE_PATH），原件已保留')
    with tempfile.TemporaryDirectory(prefix='stzy-office-') as temporary:
        work = Path(temporary)
        environment = office_environment(work)
        profile = work / 'profile'
        (profile / 'user').mkdir(parents=True)
        (profile / 'user/registrymodifications.xcu').write_text(
            '<?xml version="1.0"?><oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
            '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item></oor:items>', encoding='utf-8')
        local = work / ('source' + source_kind(source))
        shutil.copyfile(source, local)
        deadline = time.monotonic() + timeout

        def convert(path: Path, format_name: str) -> None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError('Word 转换超时，原件已保留')
            try:
                result = subprocess.run([executable, f'-env:UserInstallation={profile.as_uri()}', '--headless', '--norestore',
                                         '--convert-to', format_name, '--outdir', str(work), str(path)],
                                        env=environment, capture_output=True, timeout=remaining, check=False)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError('Word 转换超时，原件已保留') from exc
            if result.returncode:
                raise RuntimeError('LibreOffice 转换失败，原件已保留')

        inspection = local
        if local.suffix == '.doc':
            convert(local, 'docx:Office Open XML Text')
            inspection = work / 'source.docx'
            if not inspection.exists():
                raise RuntimeError('无法检查 DOC 字体，文件可能已加密或损坏')
        fonts, source_text = docx_content(inspection)
        plan = check_word_fonts(fonts, environment)
        if plan.get('substituted'):
            # Give the substituted families to the converter's own fontconfig.
            environment = office_environment(work, plan['substituted'])
        convert(local, 'pdf:writer_pdf_Export')
        output = work / 'source.pdf'
        if not output.exists():
            raise RuntimeError('LibreOffice 未生成 PDF，原件已保留')
        with pymupdf.open(output) as pdf:
            if pdf.needs_pass or not pdf.page_count:
                raise RuntimeError('Word 输出为空或加密，未发布')
            plan['page_check'] = page_check(expected_pages, pdf.page_count, bool(plan.get('visual_review')))
            # A necessary content check, not a proof of identical layout.
            source_chars = collections.Counter(re.sub(r'\s+', '', source_text))
            rendered_chars = collections.Counter(re.sub(r'\s+', '', ''.join(page.get_text() for page in pdf)))
            if source_chars - rendered_chars:
                raise RuntimeError('Word 转换文字覆盖校验失败，可能缺字或对象未正确渲染；未发布 PDF')
        shutil.copyfile(output, target)
    return plan


def unpack_zip(source: Path, directory: Path, file_order: list[str]) -> list[tuple[str, Path]]:
    files = []
    with zipfile.ZipFile(source) as archive:
        members = archive.infolist()
        if len(members) > MAX_MEMBERS or sum(m.file_size for m in members) > MAX_EXPANDED_BYTES:
            raise RuntimeError('ZIP 超过 500 个条目或解压后 512 MiB 限制')
        order = {name: index for index, name in enumerate(file_order)}
        def key(member):
            natural = [int(part) if part.isdigit() else part.casefold() for part in re.split(r'(\d+)', member.filename)]
            return (order.get(member.filename, order.get(PurePosixPath(member.filename).name, len(order))), natural)
        for member in sorted(members, key=key):
            name = PurePosixPath(member.filename.replace('\\', '/'))
            if name.is_absolute() or '..' in name.parts or ':' in member.filename or stat.S_ISLNK(member.external_attr >> 16):
                raise RuntimeError('ZIP 包含不安全路径或符号链接')
            if member.is_dir() or '__MACOSX' in name.parts or name.name.startswith(('.', '~$')):
                continue
            if member.flag_bits & 1:
                raise RuntimeError('ZIP 已加密，原包已保留')
            suffix = name.suffix.lower()
            if suffix not in {'.pdf', '.doc', '.docx', '.png', '.jpg', '.jpeg', '.webp'}:
                raise RuntimeError(f'ZIP 中的 {name} 暂不支持转换，未跳过或标记完成')
            target = directory / f'{len(files):04d}{suffix}'
            with archive.open(member) as src, target.open('wb') as dst:
                shutil.copyfileobj(src, dst)
            files.append((str(name), target))
    if not files:
        raise RuntimeError('ZIP 中没有可转换文档')
    return files


def source_to_pdf(source: Path, target: Path, timeout: float, expected_pages: int = 0,
                  files: list[dict] | None = None) -> dict:
    import pymupdf
    from stzy_app.crawler.converters import DocumentConverter

    kind = source_kind(source)
    parts = []
    font_plan: dict = {}
    parts_tolerated = False
    if kind == '.pdf':
        shutil.copyfile(source, target)
    elif kind in {'.doc', '.docx'}:
        font_plan = word_to_pdf(source, target, timeout, expected_pages) or {}
    elif kind == '.zip':
        metadata = files or []
        with tempfile.TemporaryDirectory(prefix='stzy-zip-') as temporary:
            work = Path(temporary)
            members = unpack_zip(source, work, [f['fileName'] for f in metadata if f.get('fileName')])
            deadline = time.monotonic() + timeout
            with pymupdf.open() as merged:
                toc = []
                for name, path in members:
                    if source_kind(path) in {'.zip', '.rar', '.7z'}:
                        raise RuntimeError('暂不支持嵌套压缩包转换，原包已保留')
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RuntimeError('ZIP 转换超时，原包已保留')
                    matching = next((f for f in metadata if f.get('fileName') in {name, PurePosixPath(name).name}), {})
                    expected = int(matching.get('totalPage') or 0)
                    pdf_path = work / (path.stem + '-converted.pdf')
                    try:
                        member_report = source_to_pdf(path, pdf_path, remaining, expected)
                    except Exception as exc:
                        raise RuntimeError(f'ZIP 成员 {name} 转换失败：{exc}') from exc
                    with pymupdf.open(pdf_path) as document:
                        if document.needs_pass or not document.page_count:
                            raise RuntimeError(f'{name} 是加密或空 PDF')
                        member_check = member_report.get('page_check') or page_check(
                            expected, document.page_count, bool(member_report.get('fonts', {}).get('visual_review')),
                            label=f'{name} ')
                        if member_check.get('tolerated'):
                            parts_tolerated = True
                        first = merged.page_count + 1
                        toc.append([1, name, first])
                        merged.insert_pdf(document)
                        parts.append({'name': name, 'pages': document.page_count, 'first_page': first,
                                      'source_kind': member_report['source_kind'], 'layout': member_report['layout'],
                                      'fonts': member_report.get('fonts', {}),
                                      'page_check': member_report.get('page_check', {})})
                merged.set_toc(toc)
                merged.save(target)
    elif kind in {'.png', '.jpg', '.jpeg', '.webp'}:
        DocumentConverter.convert_originals_to_pdf([source], target)
    else:
        raise RuntimeError(f'暂不支持 {kind} 转 PDF，原件已保留')
    with pymupdf.open(target) as document:
        if document.needs_pass or not document.page_count:
            raise RuntimeError('没有生成有效 PDF 页面')
        font_plan['page_check'] = page_check(
            expected_pages, document.page_count,
            bool(font_plan.get('visual_review')) or parts_tolerated)
        return {'source_kind': kind, 'pages': document.page_count, 'files': parts,
                'fonts': font_support.describe_report(font_plan or {}),
                'page_check': font_plan.get('page_check', {}),
                'layout': 'source_pdf_pages' if kind in {'.pdf', '.zip'} and all(p['layout'] == 'source_pdf_pages' for p in parts) else 'converted_requires_visual_review'}
