from sci_data_logger.config import Settings


def test_default_vlm_model_uses_current_qwen_vision_model(monkeypatch) -> None:
    monkeypatch.delenv("QWEN_VLM_MODEL", raising=False)

    settings = Settings(_env_file=None)

    assert settings.qwen_vlm_model == "qwen3.6-plus"
