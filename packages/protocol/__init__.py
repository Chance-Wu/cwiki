"""协议包 —— Agent Event Protocol v1 类型。"""

from packages.protocol.envelope import EventEnvelope, redact_envelope_payload

__all__ = [
    "EventEnvelope",
    "redact_envelope_payload",
]
