"""Provision Word fonts: exact family first, then a metric-compatible substitute.

The conversion gate has to answer one question per declared font: will LibreOffice
draw it with glyph metrics the original layout assumed? Two answers are acceptable:

* the exact family is installed;
* a metric-compatible substitute is installed. The Latin substitutes below are
  clones of the original: same advance widths and same vertical metrics, so line
  breaking and pagination are preserved and only glyph shapes differ. The CJK
  substitutes keep full-width advances but change line height, so the page-count
  and text-coverage checks still decide whether the PDF is publishable.

Third-party fonts are downloaded only when they are open licensed (SIL OFL /
Apache). Microsoft fonts are never fetched: install them yourself or point
STZY_WORD_FONT_DIR at a licensed copy.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

FONT_ALIASES = [
    {'simsun', '宋体'},
    {'kaiti', '楷体'},
    {'simhei', '黑体'},
    {'microsoft yahei ui', '微软雅黑 ui'},
    {'microsoft yahei', '微软雅黑'},
    {'fangsong', '仿宋'},
    {'dengxian', '等线'},
]

# Declared font (canonical key) -> ordered fallbacks.
SUBSTITUTES: dict[str, tuple[str, ...]] = {
    'calibri': ('Carlito',),
    'cambria': ('Caladea',),
    'times new roman': ('Tinos', 'Liberation Serif'),
    'arial': ('Arimo', 'Liberation Sans'),
    'courier new': ('Cousine', 'Liberation Mono'),
    'simsun': ('Songti SC', 'Noto Serif CJK SC', 'Noto Serif SC', 'Source Han Serif SC', 'AR PL UMing CN'),
    'kaiti': ('Kaiti SC', 'AR PL UKai CN', 'Noto Serif CJK SC'),
    'simhei': ('Heiti SC', 'Noto Sans CJK SC', 'Source Han Sans SC', 'WenQuanYi Zen Hei'),
    'microsoft yahei': ('PingFang SC', 'Noto Sans CJK SC', 'Source Han Sans SC'),
    'microsoft yahei ui': ('PingFang SC', 'Noto Sans CJK SC', 'Source Han Sans SC'),
    'fangsong': ('STFangsong', 'Noto Serif CJK SC', 'AR PL UMing CN'),
    'dengxian': ('PingFang SC', 'Noto Sans CJK SC'),
}

# Substitutes whose advance widths and vertical metrics equal the original, so a
# substitution alone cannot move a line or a page break.
METRIC_EQUIVALENT = {'calibri', 'cambria', 'times new roman', 'arial', 'courier new'}

_GOOGLE_FONTS = 'https://github.com/google/fonts/raw/main/ofl/{path}'

# Open-licensed families we may download: name -> ((file name, url path, sha256), ...)
OPEN_FONTS: dict[str, tuple[tuple[str, str, str], ...]] = {
    'Carlito': (
        ('Carlito-Regular.ttf', 'carlito/Carlito-Regular.ttf',
         'f6418f708baede9789daef5d458c0f53d2a888af9820e8062934e504fedc6595'),
        ('Carlito-Bold.ttf', 'carlito/Carlito-Bold.ttf',
         'bb5d20f79b82599ec72983597437373a80f2d2085fa91fc144fd74e876a594db'),
    ),
    'Caladea': (
        ('Caladea-Regular.ttf', 'caladea/Caladea-Regular.ttf',
         'f1e899278b7b4491aba5b6a8253c4b04c050cc59b21865be5c37559a775153cd'),
        ('Caladea-Bold.ttf', 'caladea/Caladea-Bold.ttf',
         'ae3cb2dcbc925809dd29d2a44e9802211cab66be541bacbfc9c08c74b27c3742'),
    ),
    'Tinos': (
        ('Tinos-Regular.ttf', 'tinos/Tinos-Regular.ttf',
         '60a0e8ef0c04dd5dd69ffe91025fa2ae5836cbd35600a82ba031977557e2cb61'),
        ('Tinos-Bold.ttf', 'tinos/Tinos-Bold.ttf',
         '393269dbab8899f938db19783eca5eac92eb431f7ae0ab45b8349ca895f1a06b'),
    ),
    'Arimo': (
        ('Arimo-Variable.ttf', 'arimo/Arimo%5Bwght%5D.ttf',
         'e43898b143ec826ac8cb4034816458a7047fbe0836558de2a1f8c6223ae3e0ca'),
    ),
    'Cousine': (
        ('Cousine-Regular.ttf', 'cousine/Cousine-Regular.ttf',
         '1da22250675fc4c42fcf3a9736c44bc0570516105331443b663fd5cfbd1412fe'),
        ('Cousine-Bold.ttf', 'cousine/Cousine-Bold.ttf',
         '17c8a7245156d2253531c9e529474937b09d9f641c5ae7695c5e33f22822eef4'),
    ),
}

OPEN_FONT_NOTICE = """下载字体说明
Carlito   SIL Open Font License 1.1  https://github.com/googlefonts/carlito
Caladea   Apache License 2.0         https://github.com/huertatipografica/Caladea
Tinos     Apache License 2.0         https://github.com/credmp/tinos
Arimo     Apache License 2.0         https://github.com/rsms/arimo
Cousine   Apache License 2.0         https://github.com/googlefonts/cousine
这些字体只用于替代缺失的 Microsoft 字体做度量一致的排版；原作者与商标权利归各自所有者。
"""


def font_key(name: str) -> str:
    value = name.strip().lstrip('@').casefold()
    for group in FONT_ALIASES:
        if value in group:
            return sorted(group)[0]
    return value


def policy() -> str:
    value = os.environ.get('STZY_WORD_FONT_POLICY', 'substitute').strip().casefold()
    return value if value in {'strict', 'substitute'} else 'substitute'


def auto_install_enabled() -> bool:
    return os.environ.get('STZY_WORD_FONT_AUTO_INSTALL', '1').strip().casefold() not in {'0', 'false', 'no', 'off'}


SYSTEM_FONTCONFIG = ('/etc/fonts/fonts.conf', '/opt/homebrew/etc/fonts/fonts.conf', '/usr/local/etc/fonts/fonts.conf')


def system_fontconfig() -> str:
    return next((path for path in SYSTEM_FONTCONFIG if Path(path).exists()), '')


def managed_font_dir() -> Path:
    override = os.environ.get('STZY_FONT_INSTALL_DIR')
    if override:
        return Path(override).expanduser().resolve()
    data_dir = os.environ.get('STZY_DATA_DIR')
    if not data_dir:
        from stzy_app.config import settings as app_settings

        data_dir = str(app_settings.data_dir)
    return (Path(data_dir).expanduser().resolve() / 'fonts')


def font_directories() -> list[Path]:
    """Licensed font directory (if configured) plus the directory we install into."""
    directories: list[Path] = []
    explicit = os.environ.get('STZY_WORD_FONT_DIR')
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_dir():
            raise RuntimeError('STZY_WORD_FONT_DIR 不是有效字体目录')
        directories.append(path)
    managed = managed_font_dir()
    try:
        managed.mkdir(parents=True, exist_ok=True)
        directories.append(managed)
    except OSError:
        pass
    return directories


def fontconfig_xml(directories: list[Path], cache_dir: Path, system_config: str,
                   aliases: dict[str, str] | None = None) -> str:
    include = f'<include ignore_missing="yes">{escape(system_config)}</include>' if system_config else ''
    body = ''.join(f'<dir>{escape(str(directory))}</dir>' for directory in directories)
    cache = f'<cachedir>{escape(str(cache_dir))}</cachedir>'
    rules = ''
    for declared, actual in sorted((aliases or {}).items()):
        # Try the substitute first, keep the declared family as a later fallback.
        rules += (f'<match target="pattern"><test name="family" qual="any"><string>{escape(declared)}</string></test>'
                  f'<edit name="family" mode="prepend" binding="same"><string>{escape(actual)}</string></edit></match>')
    return f'<?xml version="1.0"?><fontconfig>{include}{body}{cache}{rules}</fontconfig>'


def font_environment(work: Path, aliases: dict[str, str] | None = None) -> dict[str, str]:
    """Fontconfig that sees the system, the licensed dir and our install dir only."""
    environment = os.environ.copy()
    directories = font_directories()
    config = work / 'fonts.conf'
    config.write_text(fontconfig_xml(directories, work / 'font-cache', system_fontconfig(), aliases), encoding='utf-8')
    environment['FONTCONFIG_FILE'] = str(config)
    if directories:
        environment['SAL_FONTPATH'] = os.pathsep.join(str(directory) for directory in directories)
    return environment


def _fontconfig_workdir() -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory(prefix='stzy-fonts-')


def resolve(fonts: set[str], available: set[str], *, allow_substitutes: bool = True) -> dict:
    exact: list[str] = []
    substituted: dict[str, str] = {}
    missing: list[str] = []
    for name in sorted(fonts):
        key = font_key(name)
        if not key or key.startswith('+'):
            continue
        if key in available:
            exact.append(name)
            continue
        substitute = ''
        if allow_substitutes:
            substitute = next((item for item in SUBSTITUTES.get(key, ()) if font_key(item) in available), '')
        if substitute:
            substituted[name] = substitute
        else:
            missing.append(name)
    # A non-metric substitute can move line breaks, so it always needs a visual check.
    visual_review = any(font_key(name) not in METRIC_EQUIVALENT for name in substituted)
    return {'exact': exact, 'substituted': substituted, 'missing': missing, 'visual_review': visual_review}


def _download_targets(missing: list[str], available: set[str]) -> list[str]:
    targets: list[str] = []
    for name in missing:
        for candidate in SUBSTITUTES.get(font_key(name), ()):
            if font_key(candidate) in available or candidate in targets:
                continue
            if candidate in OPEN_FONTS:
                targets.append(candidate)
                break
    return targets


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            value.update(chunk)
    return value.hexdigest()


def _fetch(url: str, target: Path, expected: str, *, timeout: float, attempts: int = 3) -> None:
    """Download with digest verification; retry once on a truncated stream."""
    temporary = target.with_suffix(target.suffix + '.part')
    error = '未知错误'
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response, temporary.open('wb') as stream:
                shutil.copyfileobj(response, stream)
            digest = _digest(temporary)
            if digest != expected:
                error = f'校验失败 {digest[:12]} != {expected[:12]}'
                continue
            temporary.replace(target)
            return
        except (urllib.error.URLError, OSError) as exc:
            error = str(exc)
        time.sleep(0.5 * (attempt + 1))
    temporary.unlink(missing_ok=True)
    raise RuntimeError(f'{target.name} 下载失败：{error}')


def install_family(family: str, directory: Path, *, timeout: float = 60.0) -> list[str]:
    """Download one open-licensed family into the managed font directory."""
    directory.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for filename, path, expected in OPEN_FONTS[family]:
        target = directory / filename
        if not (target.exists() and _digest(target) == expected):
            _fetch(_GOOGLE_FONTS.format(path=path), target, expected, timeout=timeout)
        written.append(filename)
    notice = directory / 'README.txt'
    if not notice.exists():
        notice.write_text(OPEN_FONT_NOTICE, encoding='utf-8')
    _refresh_cache(directory)
    return written


def _refresh_cache(directory: Path) -> None:
    executable = shutil.which('fc-cache')
    if not executable:
        return
    try:
        subprocess.run([executable, '-f', str(directory)], capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def ensure(fonts: set[str], available_families) -> dict:
    """Resolve the declared fonts, downloading open substitutes when that is enough.

    ``available_families`` is a callable returning the canonical family names
    the current fontconfig can see, so this stays independent of fc-list details.
    """
    allow = policy() != 'strict'
    available = available_families()
    plan = resolve(fonts, available, allow_substitutes=allow)
    installed: list[str] = []
    failed: list[str] = []
    if plan['missing'] and allow and auto_install_enabled():
        for family in _download_targets(plan['missing'], available):
            try:
                install_family(family, managed_font_dir())
                installed.append(family)
            except RuntimeError as exc:
                failed.append(str(exc))
        if installed:
            available = available_families()
            plan = resolve(fonts, available, allow_substitutes=allow)
    plan.update({'installed': installed, 'install_failed': failed, 'policy': policy()})
    return plan


def describe_report(plan: dict) -> dict:
    return {
        'exact': plan.get('exact', []),
        'substituted': plan.get('substituted', {}),
        'missing': plan.get('missing', []),
        'installed': plan.get('installed', []),
        'install_failed': plan.get('install_failed', []),
        'policy': plan.get('policy', policy()),
        'visual_review': plan.get('visual_review', False),
    }


def status(families: set[str] | None = None) -> dict:
    """Environment self-check used by the settings page and the CLI."""
    directories = font_directories()
    available = _isolated_families()
    installed = sorted({family for family in OPEN_FONTS if family_installed(family, directories, available)})
    report: dict = {
        'font_config': bool(shutil.which('fc-list')),
        'libreoffice': os.environ.get('STZY_SOFFICE_PATH') or shutil.which('soffice') or shutil.which('libreoffice') or '',
        'policy': policy(),
        'auto_install': auto_install_enabled(),
        'directories': [str(directory) for directory in directories],
        'install_dir': str(managed_font_dir()),
        'open_fonts_available': sorted(OPEN_FONTS),
        'open_fonts_installed': installed,
        'open_fonts_missing': sorted(set(OPEN_FONTS) - set(installed)),
        'data_dir': str(directories[-1].parent) if directories else '',
    }
    if families:
        plan = resolve(families, available, allow_substitutes=policy() != 'strict')
        report.update({'checked': sorted(families), 'resolved': describe_report(plan)})
    return report


def available_names(environment: dict[str, str] | None = None) -> list[str]:
    executable = shutil.which('fc-list')
    if not executable:
        return []
    try:
        result = subprocess.run([executable, '--format=%{family}\n'], env=environment or os.environ,
                                capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    return [name.strip() for line in result.stdout.splitlines() for name in line.split(',') if name.strip()]


def _isolated_families() -> set[str]:
    """Families visible with the same fontconfig the converter uses."""
    with _fontconfig_workdir() as temporary:
        return {font_key(name) for name in available_names(font_environment(Path(temporary)))}


def family_installed(family: str, directories: list[Path], available: set[str] | None = None) -> bool:
    key = font_key(family)
    if available is None:
        available = _isolated_families()
    if key in available:
        return True
    for directory in directories:
        for filename, _, _ in OPEN_FONTS.get(family, ()):
            if (directory / filename).exists():
                return True
    return False


def repair(families: set[str] | None = None) -> dict:
    """Install every missing open-licensed substitute, then re-check."""
    directories = font_directories()
    available = _isolated_families()
    warnings: list[str] = []
    installed: list[str] = []
    targets = sorted(set(OPEN_FONTS))
    if families:
        targets = _download_targets(sorted(families), available)
    for family in targets:
        if family_installed(family, directories, available):
            continue
        try:
            install_family(family, managed_font_dir())
            installed.append(family)
        except RuntimeError as exc:
            warnings.append(str(exc))
    if targets and not installed and not warnings:
        warnings.append('所需开源替代字体已就绪，无需下载')
    report = status(families)
    report.update({'installed_now': installed, 'warnings': warnings, 'checked_available': len(available)})
    return report
