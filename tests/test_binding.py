from anchr_eval.binding import evidence_match


def test_same_words_on_wrong_page_do_not_verify():
    evidence={'quote':'API Key 不进入 fingerprint。','page_no':2}
    assert evidence_match(evidence,[{'segmentId':'s1','pageNo':1,'content':evidence['quote']}])==[]


def test_negation_and_numeric_difference_are_not_normalized_away():
    evidence={'quote':'最少证据 80；API Key 不参与。','page_no':1}
    assert evidence_match(evidence,[{'segmentId':'s1','pageNo':1,'content':'最少证据 60；API Key 参与。'}])==[]


def test_exact_quote_with_layout_whitespace_matches_real_id():
    evidence={'quote':'API Key 不进入 `fingerprint`。','page_no':1}
    assert evidence_match(evidence,[{'segmentId':'real-s1','anchor':{'pageNo':1},'content':'API Key 不进入\nfingerprint。'}])==['real-s1']
