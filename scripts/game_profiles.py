"""Per-game settings for the games this port runs (by title id in sce_sys/param.sfo).

modules: bundled sce_module PRX files linked into the image (link_modules.py), in order.
env:     run.py defaults for that game (the user's own environment still wins).
"""
from pathlib import Path

PROFILES = {
    'CUSA01113': {
        'name': 'Gravity Rush Remastered',
        'modules': ('libc.prx', 'libSceFios2.prx'),
        'env': {},
    },
}
PROFILES['CUSA01130'] = PROFILES['CUSA01113']  # US release: the same eboot.bin
DEFAULT = {'name': None, 'modules': ('libc.prx', 'libSceFios2.prx'), 'env': {}}


def title_id(game):
    """TITLE_ID of a game folder, or None."""
    try:
        from prepare import sfo
        return sfo((Path(game) / 'sce_sys' / 'param.sfo').read_bytes()).get('TITLE_ID')
    except (OSError, ValueError, ImportError):
        return None


def profile(game):
    """The profile of a game folder (DEFAULT for unknown games)."""
    found = PROFILES.get(title_id(game) or '')
    if not found:
        return DEFAULT
    # Only modules the dump actually ships are linked.
    modules = tuple(m for m in found['modules'] if (Path(game) / 'sce_module' / m).is_file())
    return {**found, 'modules': modules}
