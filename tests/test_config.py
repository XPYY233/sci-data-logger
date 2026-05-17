from sci_data_logger.config import Settings


def test_default_vlm_model_uses_real_dashscope_vision_model(monkeypatch) -> None:
    """Default model name must be a model that actually exists on DashScope.

    The previous "qwen3.6-plus" placeholder would 400 on every real call.
    qwen-vl-max-latest is the always-latest alias for the Qwen-VL max family.
    """
    monkeypatch.delenv("QWEN_VLM_MODEL", raising=False)

    settings = Settings(_env_file=None)

    assert settings.qwen_vlm_model == "qwen-vl-max-latest"
    # Sanity: ensure it's a recognized Qwen-VL family member.
    assert settings.qwen_vlm_model.startswith(("qwen-vl-", "qwen2-vl-", "qwen3-vl-"))


def test_api_key_defaults_to_none(monkeypatch) -> None:
    """When SCI_DATA_LOGGER_API_KEY is unset, auth is opt-in (None = open)."""
    monkeypatch.delenv("SCI_DATA_LOGGER_API_KEY", raising=False)

    settings = Settings(_env_file=None)

    assert settings.api_key is None
