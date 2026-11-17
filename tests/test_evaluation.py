import json

import pytest

from lexmoryn.evaluation import evaluate, load_queries, percentile, relevance_metrics


def test_metric_denominators_and_reciprocal_rank():
    relevant = [{"path": "a"}, {"path": "b"}]
    result = relevance_metrics(["x", "a", "z", "q", "r", "b"], relevant)
    assert result == {"recall_at_5": 0.5, "recall_at_10": 1, "mrr_at_10": 0.5}
    assert percentile([1, 2, 3, 4, 100], 0.95) == 100


def test_fresh_process_evaluation_records_real_counts_and_provenance(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.md").write_text("A literal evidence phrase.\n")
    queries = tmp_path / "queries.json"
    queries.write_text(
        json.dumps(
            {
                "dataset": "test",
                "judgment_provenance": "test author",
                "queries": [
                    {
                        "id": "q1",
                        "category": "content",
                        "query": "literal evidence",
                        "relevant": [{"path": "a.md", "start_line": 1, "end_line": 1}],
                    }
                ],
            }
        )
    )
    output = tmp_path / "results.json"
    evaluate(workspace, queries, output, tmp_path / "unused-model", lexical_only=True, repeats=1)
    result = json.loads(output.read_text())
    mode = result["results"][0]
    assert result["judgment_provenance"] == "test author"
    assert mode["recall_at_5"] == 1
    assert mode["source_locations_checked"] == mode["source_locations_correct"] == 1
    assert mode["judged_passage_overlaps"] == 1
    assert mode["files"] == mode["timed_searches"] == 1
    assert mode["peak_rss_mib"] > 0
    assert not (workspace / ".lexmoryn").exists()


def test_queries_require_attributed_judgments(tmp_path):
    queries = tmp_path / "queries.json"
    queries.write_text('{"queries": []}')
    with pytest.raises(ValueError, match="judgment_provenance"):
        load_queries(queries)
