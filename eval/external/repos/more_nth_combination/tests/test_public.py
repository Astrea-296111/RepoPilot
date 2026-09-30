from more_itertools import nth_combination_with_replacement as nth

def test_long_r():
    assert nth('ab',3,0) == ('a','a','a')
