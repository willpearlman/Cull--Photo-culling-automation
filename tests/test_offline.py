"""The engine runs offline: no stage may depend on AWS. Only agent.py talks to an LLM API."""
from cull import config, pipeline


def test_no_module_imports_aws():
    for path in (config.REPO_ROOT / "cull").glob("*.py"):
        src = path.read_text(encoding="utf-8").lower()
        assert "boto3" not in src and "bedrock" not in src and "rekognition" not in src, path.name


def test_pipeline_has_only_local_stages():
    assert pipeline.STAGE_ORDER == ["ingest", "local", "faces", "scenes", "moments", "aesthetic"]
