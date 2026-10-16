"""密钥脱敏测试。"""

from packages.domain.secrets import is_sensitive_file, redact_secrets


def test_redact_api_key() -> None:
    text = "my key is sk-abc123def456 and that's it"
    result = redact_secrets(text)
    assert "sk-abc123def456" not in result
    assert "[REDACTED]" in result


def test_redact_github_token() -> None:
    text = "token: ghp_abc123def456ghi789"
    result = redact_secrets(text)
    assert "ghp_abc123def456ghi789" not in result


def test_redact_bearer_token() -> None:
    text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.test.signature"
    result = redact_secrets(text)
    assert "eyJhbGciOiJIUzI1NiJ9" not in result


def test_no_redact_normal_text() -> None:
    text = "This is a normal message about Spring Boot"
    result = redact_secrets(text)
    assert result == text


def test_sensitive_files() -> None:
    assert is_sensitive_file(".env")
    assert is_sensitive_file("config/key.pem")
    assert is_sensitive_file("id_rsa")
    assert is_sensitive_file("credentials.json")
    assert is_sensitive_file("secrets.yaml")
    assert not is_sensitive_file("src/main.py")
    assert not is_sensitive_file("README.md")
