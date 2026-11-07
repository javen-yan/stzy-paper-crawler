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
from xml.sax.saxutils import escape
from pathlib import PurePosixPath

import zipfile
from pathlib import Path

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
FONT_ALIASES = [
    {'simsun', '宋体'}, {'kaiti', '楷体'}, {'simhei', '黑体'},
    {'microsoft yahei ui', '微软雅黑 ui'}, {'microsoft yahei', '微软雅黑'},
]
MAX_MEMBERS = 500
MAX_EXPANDED_BYTES = 512 * 1024 * 1024


def font_key(name: str) -> str:
    value = name.strip().lstrip('@').casefold()
    for group in FONT_ALIASES:
        if value in group:
            return sorted(group)[0]
    return value


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


def office_environment(work: Path) -> dict[str, str]:
    environment = os.environ.copy()
    font_dir = environment.get('STZY_WORD_FONT_DIR')
    if font_dir:
        directory = Path(font_dir).expanduser().resolve()
        if not directory.is_dir():
            raise RuntimeError('STZY_WORD_FONT_DIR 不是有效字体目录')
        config = work / 'fonts.conf'
        system = next((p for p in ('/etc/fonts/fonts.conf', '/opt/homebrew/etc/fonts/fonts.conf') if Path(p).exists()), '')
        include = f'<include ignore_missing="yes">{escape(system)}</include>' if system else ''
        config.write_text(f'<?xml version="1.0"?><fontconfig>{include}<dir>{escape(str(directory))}</dir>'
                          f'<cachedir>{escape(str(work / "font-cache"))}</cachedir></fontconfig>', encoding='utf-8')
        environment['FONTCONFIG_FILE'] = str(config)
        environment['SAL_FONTPATH'] = str(directory)
    return environment


def check_word_fonts(fonts: set[str], environment: dict[str, str]) -> None:
    executable = shutil.which('fc-list')
    if not executable:
        raise RuntimeError('Word 原样转换需要 fontconfig（fc-list）检查字体，原件已保留')
    result = subprocess.run([executable, '--format=%{family}\n'], env=environment,
                            capture_output=True, text=True, check=True, timeout=15)
    available = {font_key(name) for line in result.stdout.splitlines() for name in line.split(',')}
    missing = sorted(name for name in fonts if font_key(name) not in available)
    if missing:
        raise RuntimeError('缺少原文字体：' + '、'.join(missing) + '；请安装有授权的字体或设置 STZY_WORD_FONT_DIR，原件已保留')


def word_to_pdf(source: Path, target: Path, timeout: float, expected_pages: int = 0) -> None:
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
        check_word_fonts(fonts, environment)
        convert(local, 'pdf:writer_pdf_Export')
        output = work / 'source.pdf'
        if not output.exists():
            raise RuntimeError('LibreOffice 未生成 PDF，原件已保留')
        with pymupdf.open(output) as pdf:
            if pdf.needs_pass or not pdf.page_count:
                raise RuntimeError('Word 输出为空或加密，未发布')
            if expected_pages and pdf.page_count != expected_pages:
                raise RuntimeError(f'Word 分页与站点不一致：{pdf.page_count}/{expected_pages} 页，需核对字体和排版；未发布 PDF')
            # A necessary content check, not a proof of identical layout.
            source_chars = collections.Counter(re.sub(r'\s+', '', source_text))
            rendered_chars = collections.Counter(re.sub(r'\s+', '', ''.join(page.get_text() for page in pdf)))
            if source_chars - rendered_chars:
                raise RuntimeError('Word 转换文字覆盖校验失败，可能缺字或对象未正确渲染；未发布 PDF')
        shutil.copyfile(output, target)


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
    if kind == '.pdf':
        shutil.copyfile(source, target)
    elif kind in {'.doc', '.docx'}:
        word_to_pdf(source, target, timeout, expected_pages)
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
                        if expected and document.page_count != expected:
                            raise RuntimeError(f'{name} 页数与站点不一致，未发布 PDF')
                        first = merged.page_count + 1
                        toc.append([1, name, first])
                        merged.insert_pdf(document)
                        parts.append({'name': name, 'pages': document.page_count, 'first_page': first,
                                      'source_kind': member_report['source_kind'], 'layout': member_report['layout']})
                merged.set_toc(toc)
                merged.save(target)
    elif kind in {'.png', '.jpg', '.jpeg', '.webp'}:
        DocumentConverter.convert_originals_to_pdf([source], target)
    else:
        raise RuntimeError(f'暂不支持 {kind} 转 PDF，原件已保留')
    with pymupdf.open(target) as document:
        if document.needs_pass or not document.page_count:
            raise RuntimeError('没有生成有效 PDF 页面')
        if expected_pages and document.page_count != expected_pages:
            raise RuntimeError(f'原文转换页数不一致：{document.page_count}/{expected_pages}，未发布 PDF')
        return {'source_kind': kind, 'pages': document.page_count, 'files': parts,
                'layout': 'source_pdf_pages' if kind in {'.pdf', '.zip'} and all(p['layout'] == 'source_pdf_pages' for p in parts) else 'converted_requires_visual_review'}
