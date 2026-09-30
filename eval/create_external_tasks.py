"""Freeze public reproducers and independent edge cases BEFORE real model trials."""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent / 'external'
SPECS = [
('boltons_xfrange', 'xfrange disagrees with frange for descending ranges and inexact float boundaries. Make generator values and counts match frange, retain wrong-direction empty output and zero-step ValueError.',
'''from boltons.iterutils import xfrange, frange

def test_descending():
    assert list(xfrange(5, 0, step=-1.25)) == frange(5, 0, step=-1.25)
''',
'''import pytest
from boltons.iterutils import xfrange, frange

@pytest.mark.parametrize('start,stop,step', [(0,1,.1),(0,10,.1),(1,3,.75),(6,-2,-.5),(1,5,-1),(5,0,1),(0,0,1),(-2,2,.3)])
def test_matches(start,stop,step):
    assert list(xfrange(start,stop,step)) == frange(start,stop,step)

def test_zero():
    with pytest.raises(ValueError): list(xfrange(2,step=0))
'''),
('boltons_backoff', 'backoff/backoff_iter accepts factor=1 but crashes with an inferred count. With valid positive start==stop return one value; keep zero-stop ValueError; with start!=stop and no count raise ValueError. Keep explicit count and repeat behavior unchanged.',
'''from boltons.iterutils import backoff

def test_equal():
    assert backoff(5,5,factor=1.0) == [5.0]
''',
'''import pytest
from itertools import islice
from boltons.iterutils import backoff, backoff_iter

@pytest.mark.parametrize('start', [1,2.5,10])
def test_equal(start):
    assert backoff(start,start,factor=1) == [float(start)]

@pytest.mark.parametrize('start,stop', [(0,10),(1,8),(2,9)])
def test_cannot_grow(start,stop):
    with pytest.raises(ValueError): backoff(start,stop,factor=1)

@pytest.mark.parametrize('count', [0,1,4])
def test_count(count):
    assert backoff(2,8,count=count,factor=1) == [2.0]*count

def test_repeat_and_growth():
    assert list(islice(backoff_iter(2,8,count='repeat',factor=1),3)) == [2.0]*3
    assert backoff(1,8) == [1.0,2.0,4.0,8.0]
'''),
('boltons_split', 'split/split_iter maxsplit=0 wraps the original iterable inside the result instead of yielding the unsplit values. Return one flat group for lists and iterators. Preserve normal separator and positive maxsplit behavior.',
'''from boltons.iterutils import split

def test_zero():
    assert split([1,None,2],maxsplit=0) == [[1,None,2]]
''',
'''import pytest
from boltons.iterutils import split, split_iter

@pytest.mark.parametrize('value', [[],[1,None,2],[0,False],(1,2),'abc'])
def test_zero(value):
    assert split(value,maxsplit=0) == [list(value)]
    assert list(split_iter(iter(value),maxsplit=0)) == [list(value)]

def test_normal():
    assert split([1,None,2,None,3],maxsplit=1) == [[1],[2,None,3]]
    assert split([1,None,2]) == [[1],[2]]
'''),
('boltons_research', 'research uses remap identity caching and misses nested values reached through a second branch that points to the same tuple. Traverse every branch for acyclic shared containers, preserve query filtering and default remap caching/identity behavior.',
'''from boltons.iterutils import research

def test_shared():
    item=('hello',)
    tree={'a':item,'b':item}
    paths=[p for p,v in research(tree) if v=='hello']
    assert paths == [('a',0),('b',0)]
''',
'''from boltons.iterutils import research, remap

def test_multiple_paths():
    shared=(7,)
    tree={'left':[shared], 'right':shared}
    assert [p for p,v in research(tree,lambda p,k,v:isinstance(v,int))] == [('left',0,0),('right',0)]

def test_remap_keeps_identity():
    shared=[1,2]
    mapped=remap({'a':shared,'b':shared})
    assert mapped['a'] is mapped['b']

def test_filter_and_errors():
    assert research({'a':[1,2]}, lambda p,k,v:v==2) == [(('a',1),2)]
    assert research({'a':1},lambda p,k,v:1/0) == []
'''),
('more_numeric_slice', 'numeric_range negative-step slicing returns empty output. Make slicing follow Python range index normalization, including omitted endpoints, negative indices, out-of-bounds indices, decimal values and zero-step errors.',
'''from more_itertools import numeric_range

def test_reverse_slice():
    assert list(numeric_range(0,10,2)[::-1]) == [8,6,4,2,0]
''',
'''from decimal import Decimal
import pytest
from more_itertools import numeric_range

@pytest.mark.parametrize('params', [(0,10,2),(10,0,-2),(0,0,1),(-4,5,3)])
@pytest.mark.parametrize('sl', [slice(None,None,-1),slice(None,None,-2),slice(3,0,-1),slice(-1,-8,-2),slice(-100,100,1),slice(100,-100,-1),slice(1,4,1)])
def test_range(params,sl):
    r=numeric_range(*params)
    assert list(r[sl]) == list(range(*params))[sl]

def test_decimal():
    r=numeric_range(Decimal('0'),Decimal('1'),Decimal('.2'))
    assert list(r[::-1]) == list(r)[::-1]

def test_zero_slice():
    with pytest.raises(ValueError): numeric_range(4)[::0]
'''),
('more_predicate_sentinel', 'locate and replace leak internal padding sentinels into user predicates when window_size exceeds remaining input. Pass only actual values to variadic predicates (shorter final windows allowed), preserve None input values and replacement count semantics.',
'''from more_itertools import locate, replace

def test_no_sentinel():
    assert list(locate([1,2],lambda *xs:sum(xs)>0,window_size=3)) == [0]
    assert list(replace([1,2],lambda *xs:sum(xs)>0,[9],window_size=3)) == [9]
''',
'''import pytest
from more_itertools import locate, replace

@pytest.mark.parametrize('items,size', [([1],3),([1,2],3),([1,2,3],2),([1,2,3],1)])
def test_pred_values(items,size):
    seen=[]
    def pred(*xs):
        assert all(isinstance(x,int) for x in xs)
        seen.append(xs)
        return False
    list(locate(items,pred,window_size=size))
    assert list(replace(items,pred,[9],window_size=size)) == items

def test_none_and_limit():
    assert list(locate([None],lambda *xs:xs==(None,),window_size=2)) == [0]
    assert list(replace([1,2,3,4],lambda *xs:True,[8],count=1,window_size=2)) == [8,3,4]
    assert list(replace([1,2],lambda *xs:True,[8],count=0,window_size=3)) == [1,2]
'''),
('more_nth_combination', 'nth_combination_with_replacement incorrectly rejects r larger than input length, even though replacement allows it. Match itertools combinations_with_replacement order and negative indices; invalid index raises IndexError, negative r raises ValueError, empty pool/r=0 has one empty tuple.',
'''from more_itertools import nth_combination_with_replacement as nth

def test_long_r():
    assert nth('ab',3,0) == ('a','a','a')
''',
'''import itertools
import pytest
from more_itertools import nth_combination_with_replacement as nth

@pytest.mark.parametrize('pool,r', [('',0),('',1),('a',4),('ab',3),('abc',2),('abc',0)])
def test_indexing(pool,r):
    expected=list(itertools.combinations_with_replacement(pool,r))
    for i,value in enumerate(expected):
        assert nth(iter(pool),r,i) == value
        assert nth(pool,r,i-len(expected)) == value
    for i in [len(expected),-len(expected)-1]:
        with pytest.raises(IndexError): nth(pool,r,i)

def test_negative_r():
    with pytest.raises(ValueError): nth('ab',-1,0)
'''),
('more_nth_permutation', 'nth_permutation raises ValueError for r greater than pool length. Such a permutation set is empty, so any index must raise IndexError. Preserve negative r ValueError, r=None full length, empty permutation and positive/negative indexing order.',
'''import pytest
from more_itertools import nth_permutation

def test_empty_permutation_set():
    with pytest.raises(IndexError): nth_permutation('abc',5,0)
''',
'''import itertools
import pytest
from more_itertools import nth_permutation as nth

@pytest.mark.parametrize('pool,r', [('',0),('',1),('ab',3),('abc',2),('abc',None),('ab',0)])
def test_indexing(pool,r):
    expected=list(itertools.permutations(pool,r))
    for i,value in enumerate(expected):
        assert nth(iter(pool),r,i) == value
        assert nth(pool,r,i-len(expected)) == value
    for i in [len(expected),-len(expected)-1]:
        with pytest.raises(IndexError): nth(pool,r,i)

def test_negative_r():
    with pytest.raises(ValueError): nth('ab',-1,0)
'''),
('slugify_hex', "Modern slugify should decode both &#x and &#X hexadecimal HTML references. Legacy behavior must remain unchanged; hexadecimal=False opts out; an invalid scalar reference must not prevent a neighboring valid reference from decoding.",
'''from slugify import slugify

def test_uppercase():
    assert slugify('&#X41;',algorithm='modern') == 'a'
''',
'''import pytest
from slugify import slugify

@pytest.mark.parametrize('prefix', ['x','X'])
def test_decode(prefix):
    assert slugify(f'&#{prefix}41; &#{prefix}e9;',algorithm='modern',allow_unicode=True) == 'a-é'
    assert slugify(f'&#{prefix}41;',algorithm='modern',lowercase=False) == 'A'

def test_compatibility():
    assert slugify('&#X41;') == 'x41'
    assert slugify('&#X41;',algorithm='legacy') == 'x41'
    assert slugify('&#X41;',algorithm='modern',hexadecimal=False) == 'x41'

@pytest.mark.parametrize('bad', ['110000','D800'])
def test_invalid_neighbor(bad):
    assert slugify(f'&#X{bad}; &#X41;',algorithm='modern') == 'x'+bad.lower()+'-a'
'''),
('slugify_truncation', 'Modern slugify post-stage replacements can deliberately contain repeated or leading/trailing internal dashes. If final separator-mapped output fits max_length, preserve all replacement content for both word_boundary and save_order modes. Keep genuine truncation within final-character budget and legacy behavior unchanged.',
'''from slugify import slugify

def test_fits():
    assert slugify('x',algorithm='modern',allow_unicode=True,replacements=[('x','one--two')],replacement_stage='post',word_boundary=True,max_length=20) == 'one--two'
''',
'''import pytest
from slugify import slugify

@pytest.mark.parametrize('replacement', ['one--two','-one-two-','one---two'])
@pytest.mark.parametrize('separator', ['-','::',''])
@pytest.mark.parametrize('boundary,order', [(False,False),(False,True),(True,False),(True,True)])
def test_fitting(replacement,separator,boundary,order):
    expected=replacement.replace('-',separator)
    for limit in [len(expected),len(expected)+10]:
        assert slugify('x',algorithm='modern',allow_unicode=True,replacements=[('x',replacement)],replacement_stage='post',separator=separator,max_length=limit,word_boundary=boundary,save_order=order) == expected

def test_actual_truncation_and_legacy():
    assert slugify('a b c',algorithm='modern',separator='::',max_length=3) == 'a'
    assert slugify('Hello World') == 'hello-world'
'''),
]

provenance=json.loads((BASE/'provenance.json').read_text())
tasks=[]
for index,(ident,task,public,hidden) in enumerate(SPECS):
    repo=BASE/'repos'/ident
    (repo/'tests').mkdir(exist_ok=True)
    (repo/'tests/test_public.py').write_text(public,encoding='utf-8')
    path=BASE/'hidden'/f'{ident}.py'
    path.parent.mkdir(exist_ok=True)
    path.write_text(hidden,encoding='utf-8')
    tasks.append({**provenance[index], 'task':task, 'repo':repo.relative_to(BASE.parent.parent).as_posix(),
                  'hidden_test':path.relative_to(BASE.parent.parent).as_posix(),
                  'test_command':'python -m pytest -q -p no:cacheprovider',
                  'allowed_source_dir': 'boltons' if ident.startswith('boltons') else 'more_itertools' if ident.startswith('more') else 'slugify'})
(BASE/'tasks.json').write_text(json.dumps(tasks,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(f'Frozen {len(tasks)} independent historical tasks')
