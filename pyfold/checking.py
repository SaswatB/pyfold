"""Independent checks for human/LLM-edited representations."""
from .core import FoldError, _validate_map, digest, fingerprint, unfold
from .syntax import HEADER


def check_pair(view, sidecar, original=None):
    result = {
        'ok': False, 'pair_consistent': False,
        'original_ast_matches': None, 'exact_reconstruction': None,
        'diagnostics': [], 'view_characters': len(view),
    }
    try:
        standalone = unfold(view)
        reconstructed = unfold(view, sidecar)
        result['pair_consistent'] = fingerprint(standalone) == fingerprint(reconstructed)
        if original is not None:
            result['original_ast_matches'] = fingerprint(standalone) == fingerprint(original)
            result['exact_reconstruction'] = reconstructed == original
            result['original_characters'] = len(original)
            if not result['original_ast_matches']:
                result['diagnostics'].append('Expansion differs from the original Python AST.')
            if not result['exact_reconstruction']:
                result['diagnostics'].append('Reconstructed text differs from the original Python.')
        result['ok'] = result['pair_consistent'] and (original is None or (
            result['original_ast_matches'] and result['exact_reconstruction']))
    except (FoldError, SyntaxError, ValueError, TypeError) as exc:
        result['diagnostics'].append(str(exc))
    return result


def rebind(view, original):
    """Generate metadata for an alternate representation; never rewrite the oracle.

    A whole-module source recipe is sufficient because re-expression must retain
    exactly the original AST. Future semantic edits regenerate changed units.
    """
    canonical = unfold(view)
    if fingerprint(canonical) != fingerprint(original):
        raise FoldError('Cannot rebind: expansion differs from the original Python AST')
    compile(original, '<pyfold-original>', 'exec')
    from .syntax import lex
    tokens = [t.text for t in lex(view) if t.kind not in ('newline', 'eof')]
    version = 1 if tokens[:1] == ['fn'] or tokens[:2] == ['async', 'fn'] else 2
    body = view[len(HEADER):].lstrip('\r\n') if view.startswith(HEADER) else view
    body = body.rstrip('\r\n')
    normalized = (HEADER + '\n' if version == 2 else '') + body + '\n'
    sidecar = {'version': version, 'source_sha256': digest(original),
               'view': normalized, 'units': [{'id': 'module', 'view': body,
               'source': original, 'leading': ''}], 'trailing': ''}
    _validate_map(sidecar)
    return sidecar
