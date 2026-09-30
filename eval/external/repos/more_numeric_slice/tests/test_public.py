from more_itertools import numeric_range

def test_reverse_slice():
    assert list(numeric_range(0,10,2)[::-1]) == [8,6,4,2,0]
