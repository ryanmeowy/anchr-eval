from anchr_eval.scoring import retrieval_scores,percentile


def test_multidocument_recall_is_not_hit_rate():
    scores=retrieval_scores([{'assetId':'a2'}],['a1','a2'])
    assert scores['recall_at_5']==.5
    assert scores['mrr_at_5']==1


def test_duplicate_docs_do_not_inflate_recall_or_rank():
    scores=retrieval_scores([{'assetId':'noise'},{'assetId':'noise'},{'assetId':'a'}],['a'])
    assert scores=={'recall_at_5':1,'mrr_at_5':.5}


def test_unanswerable_retrieval_is_not_scored_as_zero():
    assert retrieval_scores([],[])=={'recall_at_5':None,'mrr_at_5':None}


def test_small_sample_percentile_is_explicitly_interpolated():
    assert percentile([0,10],.95)==9.5
