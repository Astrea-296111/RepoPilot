import pytest
from repopilot.tools.base import Workspace
from repopilot.tools.filesystem import ApplyPatch, WriteFile
from repopilot.context.excerpts import source_excerpt


def test_protected_writes_and_aliases(tmp_path):
    (tmp_path/'tests').mkdir()
    (tmp_path/'tests/test_a.py').write_text('assert False')
    w=Workspace(tmp_path,('tests',))
    with pytest.raises(ValueError,match='受保护'):
        ApplyPatch(w).execute({'path':'tests/../tests/test_a.py','old_text':'False','new_text':'True'})
    with pytest.raises(ValueError,match='受保护'):
        WriteFile(w).execute({'path':'tests/test_b.py','content':'pass'})
    assert (tmp_path/'tests/test_a.py').read_text()=='assert False'


def test_excerpts_find_named_symbol_beyond_prefix():
    source='"""'+('noise '*2000)+'"""\n\ndef target():\n    return 17\n\ndef unrelated():\n    return 23\n'
    excerpt=source_excerpt(source,'Fix target',500)
    assert 'return 17' in excerpt
    assert 'return 23' not in excerpt
